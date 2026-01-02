"""
Market Sensemaking data sync (full v4).

Sources:
- Data API: trades -> Volume Profile / VAH / VAL / POC
- ws_trades_hourly: aggressor aggregates -> AR / Delta / CS
- ws_price_bins: price-bin buy/sell -> POMD

Usage:
    python jobs/sync.py --markets 100
    python jobs/sync.py --markets 500 --migrate
"""
import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from datetime import datetime, timedelta
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
import traceback
import time

from utils.db import DATABASE_URL
print("sync.py DATABASE_URL:", DATABASE_URL[:50] if DATABASE_URL else "None")
print("=" * 50)

from utils.polymarket_api import PolymarketAPI
from utils.metrics import (
    calculate_histogram,
    calculate_consensus_band,
    get_band_width,
    calculate_poc,
    calculate_pomd,
    calculate_rejected_probabilities,
    calculate_ui,
    calculate_ecr,
    calculate_acr,
    calculate_cer,
    calculate_ar,
    calculate_volume_delta,
    calculate_cs,
    determine_status,
    determine_impulse_tag,
    filter_trades_by_time,
)
from utils.db import get_session, init_db


# ============================================================================
# Database query helpers
# ============================================================================

def get_aggressor_stats_from_db(session, token_id: str, hours: int = 24) -> dict:
    """Fetch aggressor aggregates from ws_trades_hourly."""
    try:
        query = text("""
            SELECT 
                COALESCE(SUM(aggressive_buy), 0) as agg_buy,
                COALESCE(SUM(aggressive_sell), 0) as agg_sell,
                COALESCE(SUM(total_volume), 0) as total,
                COALESCE(SUM(trade_count), 0) as count
            FROM ws_trades_hourly
            WHERE token_id = :tid
            AND hour >= (NOW() - INTERVAL '24 hours')
        """)
        
        result = session.execute(query, {'tid': token_id}).fetchone()
        
        if result and result[3] > 0:
            agg_buy = float(result[0])
            agg_sell = float(result[1])
            total = float(result[2])
            delta = agg_buy - agg_sell
            directional_ar = abs(delta) / total if total > 0 else None
            
            return {
                'aggressive_buy': agg_buy,
                'aggressive_sell': agg_sell,
                'total_volume': total,
                'volume_delta': delta,
                'directional_ar': directional_ar,
                'trade_count': int(result[3]),
                'has_data': True
            }
        
    except Exception as e:
        pass
    
    return {
        'aggressive_buy': 0,
        'aggressive_sell': 0,
        'total_volume': 0,
        'volume_delta': 0,
        'directional_ar': None,
        'trade_count': 0,
        'has_data': False
    }


def get_price_bins_from_db(session, token_id: str, hours: int = 24) -> dict:
    """
    Fetch price-bin buy/sell data from ws_price_bins.

    Returns:
        {price_bin: {'buy': x, 'sell': y, 'total': z, 'min_side': w}}
    """
    try:
        query = text("""
            SELECT 
                price_bin,
                COALESCE(SUM(aggressive_buy), 0) as buy,
                COALESCE(SUM(aggressive_sell), 0) as sell,
                COALESCE(SUM(trade_count), 0) as count
            FROM ws_price_bins
            WHERE token_id = :tid
            AND hour >= (NOW() - INTERVAL '24 hours')
            GROUP BY price_bin
            ORDER BY price_bin
        """)
        
        results = session.execute(query, {'tid': token_id}).fetchall()
        
        bins = {}
        for row in results:
            price = float(row[0])
            buy = float(row[1])
            sell = float(row[2])
            bins[price] = {
                'buy': buy,
                'sell': sell,
                'total': buy + sell,
                'delta': buy - sell,
                'min_side': min(buy, sell),
                'count': int(row[3])
            }
        
        return bins
        
    except Exception as e:
        return {}


def get_band_width_7d_ago(session, token_id: str) -> float:
    """Fetch band width from 7 days ago."""
    try:
        query = text("""
            SELECT band_width, va_high, va_low
            FROM daily_metrics 
            WHERE token_id = :token_id 
            AND date = (CURRENT_DATE - INTERVAL '7 days')::date
        """)
        result = session.execute(query, {'token_id': token_id}).fetchone()
        
        if result:
            if result[0] is not None:
                return float(result[0])
            if result[1] is not None and result[2] is not None:
                return float(result[1]) - float(result[2])
        
        return None
    except Exception:
        return None


# ============================================================================
# Main sync entrypoint
# ============================================================================

def sync_markets(api: PolymarketAPI, top_n: int = 500, retry_failed: bool = True):
    """
    Sync market data (full v4).

    Flow:
    1. Data API -> trades -> Profile / VAH / VAL / POC
    2. ws_trades_hourly -> aggressor aggregates -> AR / Delta / CS
    3. ws_price_bins -> price-bin buy/sell -> POMD
    """
    session = get_session()
    
    stats = {
        'total': 0,
        'success': 0,
        'failed': 0,
        'skipped': 0,
        'with_aggressor': 0,
        'with_price_bins': 0,
        'errors': []
    }
    
    try:
        print(f"\n{'='*60}")
        print(f"Market Sensemaking - Data Sync v4")
        print(f"Data API + WebSocket Aggressor + Price Bins")
        print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
        # Step 1: fetch markets
        print("Step 1: Fetching markets...")
        
        all_markets = api.get_markets_by_categories(
            min_volume_24h=100,
            max_markets_per_category=None,
            total_limit=top_n if top_n else None
        )
        
        if not all_markets:
            print("No markets fetched")
            return stats
        
        all_markets.sort(key=lambda x: x['volume_24h'], reverse=True)
        all_markets = all_markets[:top_n]
        
        stats['total'] = len(all_markets)
        print(f"\nProcessing top {len(all_markets)} markets by volume\n")
        
        # Step 2: process markets
        print("Step 2: Analyzing markets...\n")
        
        for idx, market in enumerate(all_markets, 1):
            try:
                condition_id = market['condition_id']
                token_id = market['token_id']
                question = market['question']
                current_price = market['price']
                volume_24h = market['volume_24h']
                category = market.get('category', 'Other')
                
                progress = f"[{idx}/{stats['total']}]"
                print(f"{progress} {question[:50]}...")
                
                # Calculate days remaining.
                days_remaining = 30
                if market['end_date']:
                    try:
                        end_date = datetime.fromisoformat(
                            market['end_date'].replace('Z', '+00:00')
                        )
                        days_remaining = max(1, (end_date.date() - datetime.now().date()).days)
                    except:
                        pass
                
                # === 1. Fetch Data API trades ===
                print("  Fetching trades (Data API)...")
                market_trades = None
                for attempt in range(3):
                    try:
                        market_trades = api.get_trades_for_market(condition_id, limit=5000)
                        if market_trades:
                            break
                    except Exception as e:
                        if attempt < 2:
                            print(f"  Retry {attempt + 1}/3...")
                            time.sleep(2)
                        else:
                            raise e
                
                if not market_trades:
                    print("  No trades, skipping...\n")
                    stats['skipped'] += 1
                    continue
                
                trades_24h = filter_trades_by_time(market_trades, hours=24)
                print(f"  Trades: {len(market_trades)} total, {len(trades_24h)} in 24h")
                
                # === 2. Profile metrics (Data API) ===
                histogram = calculate_histogram(market_trades)
                
                if not histogram:
                    print("  No histogram, skipping...\n")
                    stats['skipped'] += 1
                    continue
                
                VAH, VAL, mid_prob = calculate_consensus_band(histogram)
                band_width = get_band_width(histogram)
                poc = calculate_poc(histogram)  # Max-volume price bin.
                
                # === 3. Uncertainty metrics ===
                ui_result = calculate_ui(histogram)
                # v5.3: calculate_ui returns (ui, edge_zone)
                if isinstance(ui_result, tuple):
                    ui, edge_zone = ui_result
                else:
                    ui = ui_result
                    edge_zone = False
                
                ecr = calculate_ecr(current_price, days_remaining)
                
                band_width_7d_ago = get_band_width_7d_ago(session, token_id)
                acr = calculate_acr(band_width, band_width_7d_ago)
                cer = calculate_cer(band_width, band_width_7d_ago, current_price, days_remaining)
                
                # === 4. WebSocket aggressor data ===
                agg_stats = get_aggressor_stats_from_db(session, token_id, hours=24)
                
                if agg_stats['has_data']:
                    ar = calculate_ar(
                        agg_stats['aggressive_buy'],
                        agg_stats['aggressive_sell'],
                        agg_stats['total_volume']
                    )
                    volume_delta = calculate_volume_delta(
                        agg_stats['aggressive_buy'],
                        agg_stats['aggressive_sell']
                    )
                    cs = calculate_cs(
                        agg_stats['aggressive_buy'],
                        agg_stats['aggressive_sell'],
                        agg_stats['total_volume']
                    )
                    total_vol = agg_stats['total_volume']
                    stats['with_aggressor'] += 1
                    agg_str = f"AR: {ar:.3f}" if ar else "AR: N/A"
                else:
                    ar = None
                    volume_delta = None
                    cs = None
                    total_vol = None
                    agg_str = "No WS data"
                
                # === 5. Price bins -> POMD ===
                price_bins = get_price_bins_from_db(session, token_id, hours=24)
                
                if price_bins:
                    pomd = calculate_pomd(price_bins)
                    stats['with_price_bins'] += 1
                    pomd_str = f"POMD: {pomd:.2f}" if pomd else "POMD: N/A"
                else:
                    pomd = None
                    pomd_str = "No bins"
                
                # === 6. Status (v5.3) ===
                status = determine_status(ui, cer, cs, total_vol, edge_zone)
                
                # === 7. Impulse Tag (v5.3) ===
                impulse_tag = determine_impulse_tag(ui, cer, cs, pomd, current_price)
                
                # === Display ===
                ui_str = f"{ui:.3f}" if ui is not None else "N/A"
                cer_str = f"{cer:.3f}" if cer is not None else "N/A"
                bw_str = f"{band_width:.3f}" if band_width is not None else "N/A"
                poc_str = f"{poc:.2f}" if poc is not None else "N/A"
                impulse_str = impulse_tag if impulse_tag else ""
                
                print(f"  Price: {current_price*100:.1f}% | Vol: ${volume_24h:,.0f}")
                print(f"  BW: {bw_str} | UI: {ui_str} | CER: {cer_str}")
                print(f"  POC: {poc_str} | {pomd_str}")
                print(f"  {agg_str}")
                print(f"  {category} | {status} {impulse_str}\n")
                
                # === 8. Save to database ===
                success = save_metrics(
                    session=session,
                    token_id=token_id,
                    condition_id=condition_id,
                    question=question,
                    current_price=current_price,
                    volume_24h=volume_24h,
                    category=category,
                    days_remaining=days_remaining,
                    va_high=VAH,
                    va_low=VAL,
                    band_width=band_width,
                    poc=poc,
                    pomd=pomd,
                    ui=ui,
                    ecr=ecr,
                    acr=acr,
                    cer=cer,
                    cs=cs,
                    ar=ar,
                    volume_delta=volume_delta,
                    status=status,
                    impulse_tag=impulse_tag,
                    edge_zone=edge_zone
                )
                
                if success:
                    stats['success'] += 1
                else:
                    stats['failed'] += 1
                
                # Rate limit
                if idx % 10 == 0:
                    print("  Pausing 2s...\n")
                    time.sleep(2)
                
            except Exception as e:
                print(f"  Error: {str(e)}\n")
                stats['failed'] += 1
                stats['errors'].append({
                    'market': market.get('question', 'Unknown')[:60],
                    'error': str(e)
                })
                continue
        
        # Print statistics
        print(f"\n{'='*60}")
        print("Sync Statistics")
        print(f"{'='*60}")
        print(f"Total: {stats['total']}")
        print(f"Success: {stats['success']}")
        print(f"Failed: {stats['failed']}")
        print(f"Skipped: {stats['skipped']}")
        print(f"With Aggressor: {stats['with_aggressor']}")
        print(f"With Price Bins: {stats['with_price_bins']}")
        
        if stats['total'] > 0:
            print(f"\nSuccess Rate: {stats['success']/stats['total']*100:.1f}%")
        
        print("\nMetrics Available:")
        print(f"   Profile: VAH, VAL, BW, POC")
        print(f"   Uncertainty: UI, ECR, ACR, CER")
        if stats['with_aggressor'] > 0:
            print("   Conviction: AR, Volume Delta, CS")
        if stats['with_price_bins'] > 0:
            print("   Disagreement: POMD")
        
        if stats['with_aggressor'] == 0:
            print("\nRun ws_collector.py to enable AR/CS/POMD")
        
        print(f"{'='*60}\n")
        
        return stats
        
    except Exception as e:
        print(f"\nSync failed: {e}")
        traceback.print_exc()
        session.rollback()
        return stats
    finally:
        session.close()


def save_metrics(session, token_id, condition_id, question,
                 current_price, volume_24h, category, days_remaining,
                 va_high, va_low, band_width, poc, pomd,
                 ui, ecr, acr, cer,
                 cs, ar, volume_delta,
                 status, impulse_tag=None, edge_zone=False):
    """Save all metrics to the database."""
    today = datetime.now().date()
    
    try:
        # Update markets table.
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
        
        # Update daily_metrics (v5.3 includes impulse_tag and edge_zone).
        session.execute(text("""
            INSERT INTO daily_metrics 
            (token_id, date, 
             va_high, va_low, band_width, poc, pomd,
             ui, ecr, acr, cer, 
             cs, ar, volume_delta,
             status, impulse_tag, edge_zone,
             current_price, days_to_expiry)
            VALUES 
            (:tid, :date,
             :vah, :val, :bw, :poc, :pomd,
             :ui, :ecr, :acr, :cer,
             :cs, :ar, :vdelta,
             :status, :impulse_tag, :edge_zone,
             :price, :days)
            ON CONFLICT (token_id, date) DO UPDATE SET
                va_high = EXCLUDED.va_high,
                va_low = EXCLUDED.va_low,
                band_width = EXCLUDED.band_width,
                poc = EXCLUDED.poc,
                pomd = EXCLUDED.pomd,
                ui = EXCLUDED.ui,
                ecr = EXCLUDED.ecr,
                acr = EXCLUDED.acr,
                cer = EXCLUDED.cer,
                cs = EXCLUDED.cs,
                ar = EXCLUDED.ar,
                volume_delta = EXCLUDED.volume_delta,
                status = EXCLUDED.status,
                impulse_tag = EXCLUDED.impulse_tag,
                edge_zone = EXCLUDED.edge_zone,
                current_price = EXCLUDED.current_price,
                days_to_expiry = EXCLUDED.days_to_expiry
        """), {
            'tid': token_id,
            'date': today,
            'vah': va_high,
            'val': va_low,
            'bw': band_width,
            'poc': poc,
            'pomd': pomd,
            'ui': ui,
            'ecr': ecr,
            'acr': acr,
            'cer': cer,
            'cs': cs,
            'ar': ar,
            'vdelta': volume_delta,
            'status': status,
            'impulse_tag': impulse_tag,
            'edge_zone': edge_zone,
            'price': current_price * 100,
            'days': days_remaining
        })
        
        session.commit()
        return True
        
    except SQLAlchemyError as e:
        session.rollback()
        print(f"  DB error: {e}")
        return False


def migrate_database(session):
    """Database migration: add new fields."""
    print("Migrating database schema...")
    
    new_columns = [
        ("daily_metrics", "band_width", "DECIMAL(10,6)"),
        ("daily_metrics", "poc", "DECIMAL(10,4)"),
        ("daily_metrics", "pomd", "DECIMAL(10,4)"),
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
            print(f"  Added {table}.{column}")
        except Exception as e:
            print(f"  {table}.{column}: {e}")
    
    # Create ws_trades_hourly table.
    try:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS ws_trades_hourly (
                id SERIAL PRIMARY KEY,
                token_id VARCHAR(100),
                hour TIMESTAMP,
                aggressive_buy DECIMAL(20,8) DEFAULT 0,
                aggressive_sell DECIMAL(20,8) DEFAULT 0,
                volume_delta DECIMAL(20,8) DEFAULT 0,
                total_volume DECIMAL(20,8) DEFAULT 0,
                trade_count INTEGER DEFAULT 0,
                poc DECIMAL(10,4),
                pomd DECIMAL(10,4),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(token_id, hour)
            )
        """))
        print("  Created/verified ws_trades_hourly table")
    except Exception as e:
        print(f"  ws_trades_hourly: {e}")
    
    # Create ws_price_bins table.
    try:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS ws_price_bins (
                id SERIAL PRIMARY KEY,
                token_id VARCHAR(100),
                hour TIMESTAMP,
                price_bin DECIMAL(10,4),
                aggressive_buy DECIMAL(20,8) DEFAULT 0,
                aggressive_sell DECIMAL(20,8) DEFAULT 0,
                trade_count INTEGER DEFAULT 0,
                UNIQUE(token_id, hour, price_bin)
            )
        """))
        print("  Created/verified ws_price_bins table")
    except Exception as e:
        print(f"  ws_price_bins: {e}")
    
    # Create indexes.
    try:
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ws_trades_token_hour 
            ON ws_trades_hourly(token_id, hour)
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ws_bins_token_hour 
            ON ws_price_bins(token_id, hour)
        """))
        print("  Created indexes")
    except Exception as e:
        print(f"  Index creation: {e}")
    
    session.commit()
    print("Migration complete\n")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Sync Polymarket data (v4 with POC/POMD)')
    parser.add_argument('--markets', type=int, default=5000, 
                       help='Number of markets to sync (default: 5000)')
    parser.add_argument('--migrate', action='store_true',
                       help='Run database migration first')
    parser.add_argument('--no-retry', action='store_true',
                       help='Disable retry for failed markets')
    
    args = parser.parse_args()
    
    print("Initializing database...")
    init_db()
    
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
    
    print("Next steps:")
    print(f"   1. Run 'python jobs/ws_collector.py' to collect aggressor data")
    print(f"   2. Run 'streamlit run app/Home.py' to see results!")
    
    exit_code = 0 if stats['failed'] == 0 else 1
    sys.exit(exit_code)
