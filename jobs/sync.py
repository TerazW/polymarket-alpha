"""
Market Sensemaking - 数据同步脚本（完整版）
路线 A：Data API 版本（无 aggressor）

同步指标：
✅ Consensus Band (VAH/VAL)
✅ Band Width
✅ POMD
✅ UI / ECR / ACR / CER
🔒 CS / AR / Volume Delta = None (需要 aggressor 数据)
"""
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
    calculate_consensus_band,
    get_band_width,
    calculate_pomd,
    calculate_rejected_probabilities,
    calculate_ui,
    calculate_ecr,
    calculate_acr,
    calculate_cer,
    determine_status,
    filter_trades_by_time,
)
from utils.db import get_session, init_db


def sync_markets(api: PolymarketAPI, top_n: int = 500, use_events_api: bool = True, retry_failed: bool = True):
    """
    同步市场数据（完整版）
    
    Args:
        api: PolymarketAPI 实例
        top_n: 要同步的市场数量
        use_events_api: 是否使用 Events API
        retry_failed: 是否重试失败的市场
    """
    session = get_session()
    
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
        print(f"Route A: Data API (Complete Metrics)")
        print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
        # Step 1: 获取市场
        print(f"📊 Step 1: Fetching markets...")
        
        all_markets = api.get_markets_by_categories(
            min_volume_24h=100,
            max_markets_per_category=None,
            total_limit=top_n if top_n else None
        )
        
        if not all_markets:
            print("❌ No markets fetched")
            return stats
        
        all_markets.sort(key=lambda x: x['volume_24h'], reverse=True)
        all_markets = all_markets[:top_n]
        
        stats['total'] = len(all_markets)
        print(f"\n✅ Processing top {len(all_markets)} markets by volume\n")
        
        # Step 2: 处理每个市场
        print(f"🔄 Step 2: Analyzing markets...\n")
        
        for idx, market in enumerate(all_markets, 1):
            try:
                condition_id = market['condition_id']
                token_id = market['token_id']
                question = market['question']
                current_price = market['price']
                volume_24h = market['volume_24h']
                category = market.get('category', 'Other')
                
                progress = f"[{idx}/{stats['total']}]"
                print(f"{progress} {question[:55]}...")
                
                # 计算剩余天数
                days_remaining = 30
                if market['end_date']:
                    try:
                        end_date = datetime.fromisoformat(
                            market['end_date'].replace('Z', '+00:00')
                        )
                        days_remaining = max(1, (end_date.date() - datetime.now().date()).days)
                    except:
                        pass
                
                # 获取成交数据
                print(f"  📥 Fetching trades...")
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
                    continue
                
                # Sanity check: 验证交易数据纯度
                unique_conditions = set(t.get('conditionId', condition_id) for t in market_trades)
                if len(unique_conditions) > 1:
                    print(f"  ⚠️  Warning: Mixed market trades!")
                
                trades_24h = filter_trades_by_time(market_trades, hours=24)
                print(f"  📈 Trades: {len(market_trades)} total, {len(trades_24h)} in 24h")
                
                # === 计算所有指标 ===
                histogram = calculate_histogram(market_trades)
                
                if not histogram:
                    print(f"  ⚠️  No histogram, skipping...\n")
                    stats['skipped'] += 1
                    continue
                
                # 1. Profile 相关
                VAH, VAL, mid_prob = calculate_consensus_band(histogram)
                band_width = get_band_width(histogram)
                pomd = calculate_pomd(histogram)
                rejected_probs = calculate_rejected_probabilities(histogram)
                
                # 2. 不确定性相关
                ui = calculate_ui(histogram)
                ecr = calculate_ecr(current_price, days_remaining)
                
                # 获取 7 天前的 band_width（用于计算 ACR 和 CER）
                band_width_7d_ago = get_band_width_7d_ago(session, token_id)
                
                acr = calculate_acr(band_width, band_width_7d_ago)
                cer = calculate_cer(band_width, band_width_7d_ago, current_price, days_remaining)
                
                # 3. 信念强度（锁定）
                cs = None   # 🔒 LOCKED
                ar = None   # 🔒 LOCKED
                volume_delta = None  # 🔒 LOCKED
                
                # 4. 状态判定
                status = determine_status(ui, cer, cs)
                
                # === 显示结果 ===
                ui_str = f"{ui:.3f}" if ui is not None else "N/A"
                cer_str = f"{cer:.3f}" if cer is not None else "N/A"
                ecr_str = f"{ecr:.5f}" if ecr is not None else "N/A"
                acr_str = f"{acr:.5f}" if acr is not None else "N/A"
                bw_str = f"{band_width:.3f}" if band_width is not None else "N/A"
                vah_str = f"{VAH:.2f}" if VAH is not None else "N/A"
                val_str = f"{VAL:.2f}" if VAL is not None else "N/A"
                pomd_str = f"{pomd:.2f}" if pomd is not None else "N/A"
                
                print(f"  💰 Price: {current_price*100:.1f}% | Vol: ${volume_24h:,.0f}")
                print(f"  📊 VAH: {vah_str} | VAL: {val_str} | BW: {bw_str} | POMD: {pomd_str}")
                print(f"  📈 UI: {ui_str} | ECR: {ecr_str} | ACR: {acr_str} | CER: {cer_str}")
                print(f"  🔒 CS/AR: Locked (requires aggressor)")
                print(f"  🏷️  Category: {category} | {status}\n")
                
                # === 保存到数据库 ===
                success = save_metrics(
                    session=session,
                    token_id=token_id,
                    condition_id=condition_id,
                    question=question,
                    current_price=current_price,
                    volume_24h=volume_24h,
                    category=category,
                    days_remaining=days_remaining,
                    # Profile
                    va_high=VAH,
                    va_low=VAL,
                    band_width=band_width,
                    pomd=pomd,
                    # Uncertainty
                    ui=ui,
                    ecr=ecr,
                    acr=acr,
                    cer=cer,
                    # Conviction (locked)
                    cs=cs,
                    ar=ar,
                    volume_delta=volume_delta,
                    # Status
                    status=status
                )
                
                if success:
                    stats['success'] += 1
                else:
                    stats['failed'] += 1
                
                # Rate limit
                if idx % 10 == 0:
                    print(f"  ⏸️  Pausing 2s...\n")
                    time.sleep(2)
                
            except Exception as e:
                print(f"  ❌ Error: {str(e)}\n")
                stats['failed'] += 1
                stats['errors'].append({
                    'market': market.get('question', 'Unknown')[:60],
                    'error': str(e)
                })
                continue
        
        # 打印统计
        print(f"\n{'='*60}")
        print(f"📊 Sync Statistics")
        print(f"{'='*60}")
        print(f"Total: {stats['total']} | ✅ Success: {stats['success']} | ❌ Failed: {stats['failed']} | ⏭️ Skipped: {stats['skipped']}")
        if stats['total'] > 0:
            print(f"Success Rate: {stats['success']/stats['total']*100:.1f}%")
        print(f"\n📝 Available: VAH/VAL, BW, POMD, UI, ECR, ACR, CER")
        print(f"🔒 Locked: CS, AR, Volume Delta (require aggressor)")
        print(f"{'='*60}\n")
        
        return stats
        
    except Exception as e:
        print(f"\n❌ Sync failed: {e}")
        traceback.print_exc()
        session.rollback()
        return stats
    finally:
        session.close()


def get_band_width_7d_ago(session, token_id) -> float:
    """获取 7 天前的 band width"""
    try:
        # 尝试从 daily_metrics 获取 7 天前的数据
        query = text("""
            SELECT band_width, va_high, va_low
            FROM daily_metrics 
            WHERE token_id = :token_id 
            AND date = (CURRENT_DATE - INTERVAL '7 days')::date
        """)
        result = session.execute(query, {'token_id': token_id}).fetchone()
        
        if result:
            # 优先使用 band_width 字段
            if result[0] is not None:
                return float(result[0])
            # 否则用 va_high - va_low 计算
            if result[1] is not None and result[2] is not None:
                return float(result[1]) - float(result[2])
        
        return None
    except Exception:
        return None


def save_metrics(session, token_id, condition_id, question, 
                 current_price, volume_24h, category, days_remaining,
                 va_high, va_low, band_width, pomd,
                 ui, ecr, acr, cer,
                 cs, ar, volume_delta,
                 status):
    """
    保存所有指标到数据库
    """
    today = datetime.now().date()
    
    try:
        # 更新 markets 表
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
            'price': current_price,
            'vol': volume_24h,
            'cat': category,
            'now': datetime.now()
        })
        
        # 更新 daily_metrics 表
        # 注意：你可能需要先 ALTER TABLE 添加新字段
        session.execute(text("""
            INSERT INTO daily_metrics 
            (token_id, date, 
             va_high, va_low, band_width, pomd,
             ui, ecr, acr, cer, 
             cs, ar, volume_delta,
             status, current_price, days_to_expiry)
            VALUES 
            (:tid, :date,
             :vah, :val, :bw, :pomd,
             :ui, :ecr, :acr, :cer,
             :cs, :ar, :vdelta,
             :status, :price, :days)
            ON CONFLICT (token_id, date) DO UPDATE SET
                va_high = EXCLUDED.va_high,
                va_low = EXCLUDED.va_low,
                band_width = EXCLUDED.band_width,
                pomd = EXCLUDED.pomd,
                ui = EXCLUDED.ui,
                ecr = EXCLUDED.ecr,
                acr = EXCLUDED.acr,
                cer = EXCLUDED.cer,
                cs = EXCLUDED.cs,
                ar = EXCLUDED.ar,
                volume_delta = EXCLUDED.volume_delta,
                status = EXCLUDED.status,
                current_price = EXCLUDED.current_price,
                days_to_expiry = EXCLUDED.days_to_expiry
        """), {
            'tid': token_id,
            'date': today,
            'vah': va_high,
            'val': va_low,
            'bw': band_width,
            'pomd': pomd,
            'ui': ui,
            'ecr': ecr,
            'acr': acr,
            'cer': cer,
            'cs': cs,
            'ar': ar,
            'vdelta': volume_delta,
            'status': status,
            'price': current_price * 100,  # 存为百分比
            'days': days_remaining
        })
        
        session.commit()
        return True
        
    except SQLAlchemyError as e:
        session.rollback()
        print(f"  ⚠️  DB error: {e}")
        return False


def migrate_database(session):
    """
    迁移数据库：添加新字段
    运行一次即可
    """
    print("🔄 Migrating database schema...")
    
    new_columns = [
        ("daily_metrics", "band_width", "DECIMAL(10,6)"),
        ("daily_metrics", "pomd", "DECIMAL(10,6)"),
        ("daily_metrics", "ecr", "DECIMAL(10,6)"),
        ("daily_metrics", "acr", "DECIMAL(10,6)"),
        ("daily_metrics", "ar", "DECIMAL(10,6)"),
        ("daily_metrics", "volume_delta", "DECIMAL(20,8)"),
    ]
    
    for table, column, dtype in new_columns:
        try:
            session.execute(text(f"""
                ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {dtype}
            """))
            print(f"  ✅ Added {table}.{column}")
        except Exception as e:
            print(f"  ⚠️  {table}.{column}: {e}")
    
    session.commit()
    print("✅ Migration complete\n")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Sync Polymarket data (Complete Version)')
    parser.add_argument('--markets', type=int, default=5000, 
                       help='Number of markets to sync (default: 5000)')
    parser.add_argument('--migrate', action='store_true',
                       help='Run database migration first')
    parser.add_argument('--no-retry', action='store_true',
                       help='Disable retry for failed markets')
    
    args = parser.parse_args()
    
    print("Initializing database...")
    init_db()
    
    # 可选：运行迁移
    if args.migrate:
        session = get_session()
        migrate_database(session)
        session.close()
    
    api = PolymarketAPI()
    stats = sync_markets(
        api, 
        top_n=args.markets,
        retry_failed=not args.no_retry
    )
    
    print(f"💡 Run 'streamlit run app/Home.py' to see results!\n")
    
    exit_code = 0 if stats['failed'] == 0 else 1
    sys.exit(exit_code)