"""
Sync script v2.0 - 使用 CLOB API 和新的 metrics 系统
"""
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from datetime import datetime
from sqlalchemy import text
from dotenv import load_dotenv
import time

load_dotenv()

# ✅ 导入新的模块（注意路径）
from utils.polymarket_clob_api import PolymarketCLOBClient
from utils.metrics_v2 import calculate_all_metrics, filter_trades_by_time
from utils.polymarket_api import PolymarketAPI  # ✅ 添加回来
from utils.db import get_session, init_db

def sync_markets_v2(top_n: int = 500):
    """
    使用 v2 系统同步市场数据
    """
    print("\n" + "="*70)
    print(f"Market Sensemaking v2.0 - Data Sync")
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    
    # 初始化 APIs
    gamma_api = PolymarketAPI()  # ✅ 恢复使用
    
    private_key = os.getenv("PRIVATE_KEY")
    if not private_key:
        print("❌ PRIVATE_KEY not found in .env")
        return
    
    clob_client = PolymarketCLOBClient(private_key)
    
    # 初始化 CLOB 凭证
    print("\n🔐 Initializing CLOB API...")
    if not clob_client.initialize_api_credentials():
        print("❌ Failed to initialize CLOB API")
        return
    
    print("✅ CLOB API ready")
    
    # ✅ 使用与旧 sync.py 完全相同的方法获取市场
    print(f"\n📊 Fetching top {top_n} markets...")
    markets = gamma_api.get_markets_by_categories(
        min_volume_24h=100,
        max_markets_per_category=None,
        total_limit=top_n if top_n else None
    )
    
    if not markets:
        print("❌ No markets found")
        return
    
    # 按交易量排序并取前 N 个
    markets.sort(key=lambda x: x.get('volume_24h', 0), reverse=True)
    markets = markets[:top_n]
    
    print(f"✅ Got {len(markets)} markets\n")
    
    # 处理每个市场
    session = get_session()
    stats = {'success': 0, 'failed': 0, 'skipped': 0}
    
    try:
        for idx, market in enumerate(markets, 1):
            try:
                condition_id = market['condition_id']
                token_id = market['token_id']
                question = market['question']
                current_price = market['price']
                volume_24h = market['volume_24h']
                category = market.get('category', 'Other')
                
                print(f"[{idx}/{len(markets)}] {question[:60]}...")
                
                # 计算剩余天数
                if market['end_date']:
                    try:
                        end_date = datetime.fromisoformat(
                            market['end_date'].replace('Z', '+00:00')
                        )
                        days_remaining = max(1, (end_date.date() - datetime.now().date()).days)
                    except:
                        days_remaining = 30
                else:
                    days_remaining = 30
                
                # 🆕 使用 CLOB API 获取交易（带 aggressor 信息）
                print(f"  📊 Fetching CLOB trades...")
                trades = clob_client.get_trades_for_market(
                    condition_id,
                    hours=168,  # 7天数据用于 profile
                    limit=5000
                )
                
                if not trades:
                    print(f"  ⚠️  No trades, skipping\n")
                    stats['skipped'] += 1
                    continue
                
                # 筛选 24h 交易
                trades_24h = filter_trades_by_time(trades, hours=24)
                
                print(f"  ✅ Got {len(trades)} trades (7d), {len(trades_24h)} (24h)")
                
                # 获取 7天前的 band_width
                band_width_7d_ago = get_band_width_7d_ago(session, token_id)
                
                # 🆕 使用新的 metrics 系统计算
                print(f"  🧮 Calculating v2 metrics...")
                metrics = calculate_all_metrics(
                    trades_all=trades,
                    trades_24h=trades_24h,
                    current_price=current_price,
                    days_remaining=days_remaining,
                    band_width_7d_ago=band_width_7d_ago
                )
                
                # 显示关键指标
                ui_str = f"{metrics['UI']:.3f}" if metrics['UI'] else "N/A"
                cs_str = f"{metrics['CS']:.3f}" if metrics['CS'] else "N/A"
                cer_str = f"{metrics['CER']:.3f}" if metrics['CER'] else "N/A"
                ar_str = f"{metrics['AR']:.3f}" if metrics['AR'] else "N/A"
                
                print(f"  📊 UI: {ui_str} | CS: {cs_str} | CER: {cer_str} | AR: {ar_str}")
                print(f"  {metrics['status']}\n")
                
                # 保存到数据库
                save_metrics_v2(session, token_id, condition_id, question,
                              current_price * 100, volume_24h, category,
                              days_remaining, metrics)
                
                stats['success'] += 1
                
                # 避免 rate limit
                if idx % 10 == 0:
                    time.sleep(2)
                
            except Exception as e:
                print(f"  ❌ Error: {e}\n")
                stats['failed'] += 1
                continue
        
        # 打印统计
        print("\n" + "="*70)
        print(f"📊 Sync Statistics:")
        print(f"   ✅ Success: {stats['success']}")
        print(f"   ❌ Failed: {stats['failed']}")
        print(f"   ⏭️  Skipped: {stats['skipped']}")
        print("="*70)
        
    finally:
        session.close()

def get_band_width_7d_ago(session, token_id):
    """获取 7天前的 band width"""
    try:
        query = text("""
            SELECT band_width
            FROM daily_metrics 
            WHERE token_id = :token_id 
            AND date = (CURRENT_DATE - INTERVAL '7 days')::date
        """)
        result = session.execute(query, {'token_id': token_id}).fetchone()
        return float(result[0]) if result and result[0] else None
    except:
        return None

def save_metrics_v2(session, token_id, condition_id, question,
                   current_price, volume_24h, category, days_remaining, metrics):
    """保存 v2 指标到数据库"""
    today = datetime.now().date()
    
    try:
        # 保存 markets 表
        session.execute(text("""
            INSERT INTO markets 
            (token_id, market_id, title, current_price, volume_24h, category, updated_at)
            VALUES (:tid, :mid, :title, :price, :vol, :cat, :now)
            ON CONFLICT (token_id) DO UPDATE SET
                market_id = EXCLUDED.market_id,
                title = EXCLUDED.title,
                current_price = EXCLUDED.current_price,
                volume_24h = EXCLUDED.volume_24h,
                category = EXCLUDED.category,
                updated_at = EXCLUDED.updated_at
        """), {
            'tid': token_id,
            'mid': condition_id,
            'title': question,
            'price': current_price / 100,
            'vol': volume_24h,
            'cat': category,
            'now': datetime.now()
        })
        
        # 保存 daily_metrics 表（包含新字段）
        session.execute(text("""
            INSERT INTO daily_metrics 
            (token_id, date, ui, cer, cs, ar, volume_delta, ecr, acr, 
             status, current_price, days_to_expiry, 
             vah, val, mid_probability, band_width, pomd)
            VALUES (:tid, :date, :ui, :cer, :cs, :ar, :vdelta, :ecr, :acr,
                    :status, :price, :days, 
                    :vah, :val, :mid_prob, :bw, :pomd)
            ON CONFLICT (token_id, date) DO UPDATE SET
                ui = EXCLUDED.ui,
                cer = EXCLUDED.cer,
                cs = EXCLUDED.cs,
                ar = EXCLUDED.ar,
                volume_delta = EXCLUDED.volume_delta,
                ecr = EXCLUDED.ecr,
                acr = EXCLUDED.acr,
                status = EXCLUDED.status,
                current_price = EXCLUDED.current_price,
                days_to_expiry = EXCLUDED.days_to_expiry,
                vah = EXCLUDED.vah,
                val = EXCLUDED.val,
                mid_probability = EXCLUDED.mid_probability,
                band_width = EXCLUDED.band_width,
                pomd = EXCLUDED.pomd
        """), {
            'tid': token_id,
            'date': today,
            'ui': metrics['UI'],
            'cer': metrics['CER'],
            'cs': metrics['CS'],
            'ar': metrics['AR'],
            'vdelta': metrics['volume_delta'],
            'ecr': metrics['ECR'],
            'acr': metrics['ACR'],
            'status': metrics['status'],
            'price': current_price,
            'days': days_remaining,
            'vah': metrics['VAH'],
            'val': metrics['VAL'],
            'mid_prob': metrics['mid_probability'],
            'bw': metrics['band_width'],
            'pomd': metrics['POMD']
        })
        
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"  ⚠️  DB error: {e}")
        return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Sync Polymarket data v2.0')
    parser.add_argument('--markets', type=int, default=500, 
                       help='Number of markets to sync (default: 500)')
    
    args = parser.parse_args()
    
    print("Initializing database...")
    init_db()
    
    sync_markets_v2(top_n=args.markets)