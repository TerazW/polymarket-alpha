import os
import sys
from datetime import datetime, timedelta
from sqlalchemy import text

# 添加项目根目录到 path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.polymarket_api import PolymarketAPI
from utils.metrics import *
from utils.db import get_session, init_db

def sync_markets(api: PolymarketAPI, top_n: int = 50):
    """
    同步市场数据
    1. 获取市场列表
    2. 对每个市场：拉取成交、计算指标、存储
    """
    session = get_session()
    
    try:
        # 1. 获取市场列表
        print(f"Fetching top {top_n} markets...")
        markets = api.get_markets(limit=200)
        
        # 按 24h 成交量排序（如果有的话）
        # 这里简化处理，实际需要从 API 获取 volume
        markets = markets[:top_n]
        
        print(f"Processing {len(markets)} markets...")
        
        for idx, market in enumerate(markets, 1):
            try:
                # 提取信息（根据实际 API 返回调整）
                token_id = market.get('tokens', [{}])[0].get('token_id') if market.get('tokens') else None
                if not token_id:
                    continue
                
                market_id = market.get('condition_id', '')
                title = market.get('question', 'Unknown')
                
                print(f"\n[{idx}/{len(markets)}] {title[:50]}...")
                
                # 2. 获取成交数据
                trades_7d = api.get_trades(token_id, limit=5000)
                if not trades_7d:
                    print("  ⚠️  No trades data")
                    continue
                
                # 3. 计算直方图
                histogram_7d = calculate_histogram(trades_7d)
                histogram_24h = calculate_histogram(
                    [t for t in trades_7d if is_within_24h(t)]
                )
                
                # 4. 计算指标
                ui = calculate_ui(histogram_7d)
                
                # CER 需要历史数据，这里简化处理
                # 实际应该从数据库读取 7 天前的数据
                cer = None  # 暂时设为 None
                
                current_price = get_current_price(trades_7d)
                cs = calculate_cs_simple(histogram_24h, current_price)
                
                # 5. 判定状态
                status = determine_status(ui, cer, cs)
                
                print(f"  UI: {ui:.4f if ui else 'N/A'}")
                print(f"  CS: {cs:.4f if cs else 'N/A'}")
                print(f"  Status: {status}")
                
                # 6. 存储到数据库
                save_daily_metrics(
                    session=session,
                    token_id=token_id,
                    ui=ui,
                    cer=cer,
                    cs=cs,
                    status=status,
                    current_price=current_price
                )
                
            except Exception as e:
                print(f"  ❌ Error processing market: {e}")
                continue
        
        session.commit()
        print(f"\n✅ Sync completed: {len(markets)} markets")
        
    except Exception as e:
        print(f"❌ Sync failed: {e}")
        session.rollback()
    finally:
        session.close()

def is_within_24h(trade: dict) -> bool:
    """判断成交是否在 24 小时内"""
    try:
        timestamp = trade.get('timestamp') or trade.get('created_at')
        if not timestamp:
            return False
        
        # 解析时间（根据实际格式调整）
        trade_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        return datetime.now() - trade_time < timedelta(hours=24)
    except:
        return False

def get_current_price(trades: list) -> float:
    """获取最新价格"""
    if not trades:
        return 0.5
    
    # 假设最新的在前面
    return float(trades[0].get('price', 0.5))

def save_daily_metrics(session, token_id, ui, cer, cs, status, current_price):
    """保存每日指标"""
    today = datetime.now().date()
    
    # 插入或更新
    query = text("""
        INSERT INTO daily_metrics 
        (token_id, date, ui, cer, cs, status, current_price)
        VALUES 
        (:token_id, :date, :ui, :cer, :cs, :status, :current_price)
        ON CONFLICT(token_id, date) DO UPDATE SET
            ui = :ui,
            cer = :cer,
            cs = :cs,
            status = :status,
            current_price = :current_price
    """)
    
    session.execute(query, {
        'token_id': token_id,
        'date': today,
        'ui': ui,
        'cer': cer,
        'cs': cs,
        'status': status,
        'current_price': current_price
    })

# 主函数
if __name__ == "__main__":
    # 确保数据库已初始化
    init_db()
    
    # 创建 API 实例
    api = PolymarketAPI()
    
    # 同步数据（先测试 5 个市场）
    sync_markets(api, top_n=5)