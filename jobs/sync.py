import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
import traceback
import time

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


def sync_markets(api: PolymarketAPI, top_n: int = 500, use_events_api: bool = True, retry_failed: bool = True):
    """
    同步市场数据
    
    Args:
        api: PolymarketAPI 实例
        top_n: 要同步的市场数量
        use_events_api: 是否使用 Events API（推荐 True，可获取所有市场）
        retry_failed: 是否重试失败的市场
    """
    session = get_session()
    
    # 追踪统计
    stats = {
        'total': 0,
        'success': 0,
        'failed': 0,
        'skipped': 0,
        'errors': []
    }
    
    try:
        print(f"\n{'='*60}")
        print(f"Market Sensemaking - Data Sync (Top {top_n})")
        print(f"Method: {'Events API (All Markets)' if use_events_api else 'Markets API (Limited)'}")
        print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
        # Step 1: 获取市场
        print(f"📊 Step 1: Fetching markets...")
        
        # ✅ 使用官方分类方法（tag_slug）
        all_markets = api.get_markets_by_categories(
            min_volume_24h=100,
            max_markets_per_category=None,  # 不限制每个分类（获取所有）
            total_limit=top_n if top_n else None  # 不限制总数（获取所有符合条件的）
        )
        
        if not all_markets:
            print("❌ No markets fetched")
            return stats
        
        # 按成交量排序，取前 N
        all_markets.sort(key=lambda x: x['volume_24h'], reverse=True)
        all_markets = all_markets[:top_n]
        
        stats['total'] = len(all_markets)
        
        print(f"\n✅ Processing top {len(all_markets)} markets by volume\n")
        
        # Step 2: 处理每个市场
        print(f"🔄 Step 2: Analyzing markets...\n")
        
        failed_markets = []
        
        for idx, market in enumerate(all_markets, 1):
            try:
                condition_id = market['condition_id']
                token_id = market['token_id']
                question = market['question']
                current_price = market['price']
                volume_24h = market['volume_24h']
                category = market.get('category', 'Other')  # ✅ 提取 category
                
                # 进度显示
                progress = f"[{idx}/{stats['total']}]"
                print(f"{progress} {question[:60]}...")
                
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
                
                # 获取成交数据（添加重试机制）
                print(f"  🔥 Fetching trades...")
                market_trades = None
                for attempt in range(3):
                    try:
                        market_trades = api.get_trades_for_market(condition_id, limit=5000)
                        if market_trades:
                            break
                    except Exception as e:
                        if attempt < 2:
                            print(f"  ⚠️  Retry {attempt + 1}/3...")
                            time.sleep(2)
                        else:
                            raise e
                
                if not market_trades:
                    print(f"  ⚠️  No trades, skipping...\n")
                    stats['skipped'] += 1
                    failed_markets.append((idx, market, "No trades"))
                    continue
                
                trades_24h = filter_trades_by_time(market_trades, hours=24)
                
                print(f"  📈 Trades: {len(market_trades)} total, {len(trades_24h)} in 24h")
                
                # 计算指标
                histogram_all = calculate_histogram(market_trades)
                histogram_24h = calculate_histogram(trades_24h)
                
                if not histogram_all:
                    print(f"  ⚠️  No histogram, skipping...\n")
                    stats['skipped'] += 1
                    failed_markets.append((idx, market, "No histogram"))
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
                print(f"  🏷️  Category: {category}")
                print(f"  {status}\n")
                
                # 保存（✅ 添加 category 参数）
                success = save_metrics(
                    session, token_id, condition_id, question,
                    current_price * 100, volume_24h,
                    ui, cer, cs, status, days_remaining, band_width_now,
                    category  # ✅ 新增参数
                )
                
                if success:
                    stats['success'] += 1
                else:
                    stats['failed'] += 1
                    failed_markets.append((idx, market, "Save failed"))
                
                # 避免 API rate limit
                if idx % 10 == 0:
                    print(f"  ⏸️  Pausing 2s to avoid rate limit...\n")
                    time.sleep(2)
                
            except Exception as e:
                error_msg = f"Error processing market: {str(e)}"
                print(f"  ❌ {error_msg}\n")
                stats['failed'] += 1
                stats['errors'].append({
                    'market': market.get('question', 'Unknown')[:60],
                    'error': str(e)
                })
                failed_markets.append((idx, market, str(e)))
                continue
        
        # 打印统计
        print(f"\n{'='*60}")
        print(f"📊 Sync Statistics:")
        print(f"{'='*60}")
        print(f"Total markets: {stats['total']}")
        print(f"✅ Success: {stats['success']}")
        print(f"❌ Failed: {stats['failed']}")
        print(f"⭕️  Skipped: {stats['skipped']}")
        print(f"Success Rate: {stats['success']/stats['total']*100:.1f}%")
        print(f"{'='*60}\n")
        
        # 显示错误详情（如果有）
        if stats['errors']:
            print(f"\n⚠️  Error Details:")
            for i, err in enumerate(stats['errors'][:5], 1):
                print(f"{i}. {err['market']}")
                print(f"   {err['error']}\n")
        
        return stats
        
    except Exception as e:
        print(f"\n❌ Sync failed: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
        return stats
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
                 days_remaining, band_width, category='Other'):  # ✅ 添加 category 参数
    """保存指标到数据库（PostgreSQL 兼容版本）"""
    today = datetime.now().date()
    
    try:
        # 使用 PostgreSQL 的 ON CONFLICT 语法
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
            'cat': category,  # ✅ 保存 category
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
        return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Sync Polymarket data')
    parser.add_argument('--markets', type=int, default=5000, 
                       help='Number of markets to sync (default: 500)')
    parser.add_argument('--no-retry', action='store_true',
                       help='Disable retry for failed markets')
    parser.add_argument('--use-markets-api', action='store_true',
                       help='Use Markets API instead of Events API (limited to 500)')
    
    args = parser.parse_args()
    
    print("Initializing database...")
    init_db()
    
    api = PolymarketAPI()
    stats = sync_markets(
        api, 
        top_n=args.markets, 
        use_events_api=not args.use_markets_api,
        retry_failed=not args.no_retry
    )
    
    print(f"\n💡 Run 'streamlit run app/Home.py' to see results!\n")
    
    # 退出码
    exit_code = 0 if stats['success'] == stats['total'] else 1
    sys.exit(exit_code)
