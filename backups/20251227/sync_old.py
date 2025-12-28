import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
import traceback

from utils.db import DATABASE_URL
print("🔍 sync.py DATABASE_URL:", DATABASE_URL)
print("=" * 50)

from utils.polymarket_api import PolymarketAPI
from utils.metrics import (
    calculate_histogram,
    calculate_ui,
    calculate_cs,
    calculate_cer,
    determine_status,
    filter_trades_by_time,
    get_band_width
)
from utils.db import get_session, init_db


def sync_markets(api: PolymarketAPI, top_n: int = 10):
    """同步市场数据（使用 Gamma API）"""
    session = get_session()
    
    try:
        print(f"\n{'='*60}")
        print(f"Market Sensemaking - Data Sync")
        print(f"{'='*60}\n")
        
        # Step 1: 获取开放市场
        print(f"📊 Step 1: Fetching open markets from Gamma API...")
        markets = api.get_markets(limit=200, min_volume_24h=100)
        
        if not markets:
            print("❌ No markets fetched")
            return
        
        extracted = api.extract_market_data(markets)
        
        if not extracted:
            print("❌ No markets extracted")
            return
        
        # 按成交量排序，取前 N
        extracted.sort(key=lambda x: x['volume_24h'], reverse=True)
        extracted = extracted[:top_n]
        
        print(f"✅ Processing top {len(extracted)} markets\n")
        
        # Step 2: 处理每个市场
        print(f"🔄 Step 2: Analyzing markets...\n")
        
        processed_count = 0
        
        for idx, market in enumerate(extracted, 1):
            try:
                condition_id = market['condition_id']
                token_id = market['token_id']
                question = market['question']
                current_price = market['price']
                volume_24h = market['volume_24h']
                liquidity = market['liquidity']
                
                print(f"[{idx}/{len(extracted)}] {question[:60]}...")
                
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
                
                # 获取成交数据
                print(f"  📥 Fetching trades...")
                market_trades = api.get_trades_for_market(condition_id, limit=5000)
                
                if not market_trades:
                    print(f"  ⚠️  No trades, skipping...\n")
                    continue
                
                trades_24h = filter_trades_by_time(market_trades, hours=24)
                
                print(f"  📈 Trades: {len(market_trades)} total, {len(trades_24h)} in 24h")
                
                # 计算指标
                histogram_all = calculate_histogram(market_trades)
                histogram_24h = calculate_histogram(trades_24h)
                
                if not histogram_all:
                    print(f"  ⚠️  No histogram, skipping...\n")
                    continue
                
                ui = calculate_ui(histogram_all)
                cs = calculate_cs(trades_24h) if trades_24h else None
                
                band_width_now = get_band_width(histogram_all)
                band_width_7d_ago = get_band_width_7d_ago(session, token_id)
                
                cer = calculate_cer(
                    band_width_now,
                    band_width_7d_ago,
                    current_price,
                    days_remaining
                ) if band_width_now and band_width_7d_ago else None
                
                status = determine_status(ui, cer, cs)

                ui_str = f"{ui:.3f}" if ui is not None else "N/A"
                cs_str = f"{cs:.3f}" if cs is not None else "N/A"
                cer_str = f"{cer:.3f}" if cer is not None else "N/A"
                
                print(f"  💰 Price: {current_price*100:.1f}% | Vol: ${volume_24h:,.0f}")
                print(f"  📊 UI: {ui_str} | CS: {cs_str} | CER: {cer_str}")
                print(f"  {status}\n")
                
                # 保存
                # 保存（save_metrics 内部会 commit/rollback）
                success = save_metrics(
                    session, token_id, condition_id, question,
                    current_price * 100, volume_24h,
                    ui, cer, cs, status, days_remaining, band_width_now
                )
                
                if success:
                    processed_count += 1
                
            except Exception as e:
                print(f"  ❌ Error processing market: {e}\n")
                traceback.print_exc()
                continue
        
        print(f"\n{'='*60}")
        print(f"✅ Sync completed: {processed_count} markets saved!")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"\n❌ Sync failed: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
    finally:
        session.close()

def get_band_width_7d_ago(session, token_id):
    """获取 7 天前的 band width"""
    try:
        query = text("""
            SELECT va_high, va_low
            FROM daily_metrics 
            WHERE token_id = :token_id 
            AND date = (CURRENT_DATE - INTERVAL '7 days')::date
        """)
        result = session.execute(query, {'token_id': token_id}).fetchone()
        
        if result and result[0] and result[1]:
            return float(result[0]) - float(result[1])
        return None
    except:
        return None

def save_metrics(session, token_id, condition_id, question, 
                 current_price, volume_24h, ui, cer, cs, status, 
                 days_remaining, band_width):
    """保存指标到数据库（PostgreSQL 兼容版本）"""
    today = datetime.now().date()
    
    try:
        # 使用 PostgreSQL 的 ON CONFLICT 语法
        session.execute(text("""
            INSERT INTO markets 
            (token_id, market_id, title, current_price, volume_24h, updated_at)
            VALUES (:tid, :mid, :title, :price, :vol, :now)
            ON CONFLICT (token_id) DO UPDATE SET
                market_id = EXCLUDED.market_id,
                title = EXCLUDED.title,
                current_price = EXCLUDED.current_price,
                volume_24h = EXCLUDED.volume_24h,
                updated_at = EXCLUDED.updated_at
        """), {
            'tid': token_id,
            'mid': condition_id,
            'title': question,
            'price': current_price / 100,
            'vol': volume_24h,
            'now': datetime.now()
        })
        
        if band_width:
            va_high = current_price + (band_width * 50)
            va_low = current_price - (band_width * 50)
        else:
            va_high = None
            va_low = None
        
        session.execute(text("""
            INSERT INTO daily_metrics 
            (token_id, date, ui, cer, cs, status, current_price, days_to_expiry, va_high, va_low)
            VALUES (:tid, :date, :ui, :cer, :cs, :status, :price, :days, :vah, :val)
            ON CONFLICT (token_id, date) DO UPDATE SET
                ui = EXCLUDED.ui,
                cer = EXCLUDED.cer,
                cs = EXCLUDED.cs,
                status = EXCLUDED.status,
                current_price = EXCLUDED.current_price,
                days_to_expiry = EXCLUDED.days_to_expiry,
                va_high = EXCLUDED.va_high,
                va_low = EXCLUDED.va_low
        """), {
            'tid': token_id,
            'date': today,
            'ui': ui,
            'cer': cer,
            'cs': cs,
            'status': status,
            'price': current_price,
            'days': days_remaining,
            'vah': va_high,
            'val': va_low
        })
        
        session.commit()
        return True
    except SQLAlchemyError as e:
        session.rollback()
        print(f"  ⚠️  DB error: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Initializing...")
    init_db()
    
    api = PolymarketAPI()
    sync_markets(api, top_n=10)
    
    print("\n💡 Run 'streamlit run app/Home.py' to see results!\n")