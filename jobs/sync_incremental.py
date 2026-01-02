"""
Intelligent Incremental Sync System v3

Features:
- Detect new markets
- Properly mark closed/settled markets
- Only update markets with changes
- Preserve historical data
- Support multi-category (categories JSON array)
- Write COMPLETE metrics to daily_metrics table
"""

import os
import sys
import json
import time
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from datetime import datetime, timedelta
from sqlalchemy import text
from utils.db import (
    get_session, init_db, migrate_schema,
    IS_POSTGRES, IS_SQLITE, 
    get_date_7_days_ago_sql, get_interval_hours_sql
)
from utils.polymarket_api import PolymarketAPI
from utils.metrics import (
    calculate_histogram, calculate_ui, calculate_cer, calculate_cs,
    calculate_poc, calculate_pomd, calculate_ar, calculate_volume_delta,
    calculate_ecr, calculate_acr,
    determine_status, determine_impulse_tag, filter_trades_by_time, get_band_width,
    calculate_consensus_band
)


def get_aggressor_stats_from_db(session, token_id: str, hours: int = 24) -> dict:
    """Get aggressor statistics from ws_trades_hourly table"""
    try:
        interval_sql = get_interval_hours_sql(hours)
        
        query = text(f"""
            SELECT 
                COALESCE(SUM(aggressive_buy), 0) as agg_buy,
                COALESCE(SUM(aggressive_sell), 0) as agg_sell,
                COALESCE(SUM(total_volume), 0) as total,
                COALESCE(SUM(trade_count), 0) as count
            FROM ws_trades_hourly
            WHERE token_id = :tid
            AND hour >= {interval_sql}
        """)
        
        result = session.execute(query, {'tid': token_id}).fetchone()
        
        if result and result[3] > 0:
            agg_buy = float(result[0])
            agg_sell = float(result[1])
            total = float(result[2])
            
            return {
                'aggressive_buy': agg_buy,
                'aggressive_sell': agg_sell,
                'total_volume': total,
                'trade_count': int(result[3]),
                'has_data': True
            }
    except Exception:
        pass
    
    return {'has_data': False}


def get_price_bins_from_db(session, token_id: str, hours: int = 24) -> dict:
    """Get price bin level buy/sell data from ws_price_bins table"""
    try:
        interval_sql = get_interval_hours_sql(hours)
        
        query = text(f"""
            SELECT 
                price_bin,
                COALESCE(SUM(aggressive_buy), 0) as buy,
                COALESCE(SUM(aggressive_sell), 0) as sell,
                COALESCE(SUM(trade_count), 0) as count
            FROM ws_price_bins
            WHERE token_id = :tid
            AND hour >= {interval_sql}
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
        
    except Exception:
        return {}


def get_active_markets_from_db(session) -> dict:
    """Get active markets from database"""
    try:
        result = session.execute(text("""
            SELECT token_id, market_id, volume_24h, current_price, updated_at, 
                   category, categories
            FROM markets
            WHERE closed = false OR closed IS NULL
            ORDER BY volume_24h DESC
        """)).fetchall()
    except Exception:
        # Fallback: without closed field
        result = session.execute(text("""
            SELECT token_id, market_id, volume_24h, current_price, updated_at,
                   COALESCE(category, 'Other') as category, 
                   categories
            FROM markets
            ORDER BY volume_24h DESC
        """)).fetchall()
    
    markets = {}
    for row in result:
        market_id = row[1]
        categories_raw = row[6] if len(row) > 6 else None
        
        # Parse categories JSON
        categories = []
        if categories_raw:
            try:
                categories = json.loads(categories_raw) if isinstance(categories_raw, str) else categories_raw
            except:
                categories = []
        
        markets[market_id] = {
            'token_id': row[0],
            'volume_24h': float(row[2] or 0),
            'price': float(row[3] or 0),
            'updated_at': row[4],
            'category': row[5] if len(row) > 5 else 'Other',
            'categories': categories
        }
    
    return markets


def detect_new_markets(api_markets: list, db_markets: dict) -> list:
    """Detect new markets (in API but not in DB)"""
    new_markets = []
    db_market_ids = set(db_markets.keys())
    
    for market in api_markets:
        if market['condition_id'] not in db_market_ids:
            new_markets.append(market)
    
    return new_markets


def detect_closed_markets(api_markets: list, db_markets: dict) -> list:
    """Detect closed/settled markets (in DB but not in API active list)"""
    api_market_ids = {m['condition_id'] for m in api_markets}
    closed_markets = []
    
    for market_id in db_markets.keys():
        if market_id not in api_market_ids:
            closed_markets.append(market_id)
    
    return closed_markets


def detect_changed_markets(api_markets: list, db_markets: dict, 
                           volume_change_threshold: float = 0.2,
                           price_change_threshold: float = 0.05) -> list:
    """Detect markets with significant changes"""
    changed_markets = []
    
    for market in api_markets:
        market_id = market['condition_id']
        
        if market_id not in db_markets:
            continue
        
        db_market = db_markets[market_id]
        
        # Check volume change
        old_volume = db_market['volume_24h']
        new_volume = market['volume_24h']
        volume_change = abs(new_volume - old_volume) / (old_volume + 1)
        
        # Check price change
        old_price = db_market['price']
        new_price = market['price']
        price_change = abs(new_price - old_price)
        
        # Check last update time
        last_updated = db_market['updated_at']
        hours_since_update = 25  # Default: trigger update
        
        try:
            if isinstance(last_updated, str):
                from dateutil import parser
                last_updated_dt = parser.parse(last_updated)
                if last_updated_dt.tzinfo:
                    from datetime import timezone
                    now = datetime.now(timezone.utc)
                else:
                    now = datetime.now()
                hours_since_update = (now - last_updated_dt).total_seconds() / 3600
            elif last_updated:
                if hasattr(last_updated, 'tzinfo') and last_updated.tzinfo:
                    from datetime import timezone
                    now = datetime.now(timezone.utc)
                else:
                    now = datetime.now()
                hours_since_update = (now - last_updated).total_seconds() / 3600
        except Exception:
            pass
        
        # Determine if update needed
        needs_update = (
            volume_change > volume_change_threshold or
            price_change > price_change_threshold or
            hours_since_update > 24
        )
        
        if needs_update:
            changed_markets.append(market)
    
    return changed_markets


def mark_markets_as_closed(session, market_ids: list) -> int:
    """Mark markets as closed/settled"""
    if not market_ids:
        return 0
    
    try:
        placeholders = ','.join([f':id{i}' for i in range(len(market_ids))])
        params = {f'id{i}': market_id for i, market_id in enumerate(market_ids)}
        
        result = session.execute(
            text(f"""
                UPDATE markets 
                SET closed = true, active = false, updated_at = :now
                WHERE market_id IN ({placeholders})
            """),
            {**params, 'now': datetime.now()}
        )
        session.commit()
        return result.rowcount
    except Exception as e:
        print(f"  Could not mark as closed: {e}")
        session.rollback()
        return 0


def sync_market(session, api: PolymarketAPI, market: dict) -> bool:
    """
    Sync a single market with COMPLETE metrics
    
    This function now writes ALL fields to daily_metrics table
    """
    try:
        condition_id = market['condition_id']
        token_id = market['token_id']
        question = market['question']
        current_price = market['price']
        volume_24h = market['volume_24h']
        category = market.get('category', 'Other')
        categories = market.get('categories', [category])
        event_id = market.get('event_id')
        event_title = market.get('event_title')
        
        # Categories to JSON string
        categories_json = json.dumps(categories) if categories else json.dumps([category])
        
        # Calculate days remaining
        days_remaining = 30
        if market.get('end_date'):
            try:
                end_date = datetime.fromisoformat(
                    market['end_date'].replace('Z', '+00:00')
                )
                days_remaining = max(1, (end_date.date() - datetime.now().date()).days)
            except:
                pass
        
        # Get trade data from API
        market_trades = api.get_trades_for_market(condition_id, limit=5000)
        
        if not market_trades:
            # No trades - save basic info only
            save_market_basic(session, token_id, condition_id, question,
                            current_price, volume_24h, category, categories_json,
                            event_id, event_title)
            return True
        
        trades_24h = filter_trades_by_time(market_trades, hours=24)
        
        # Calculate histogram
        histogram_all = calculate_histogram(market_trades)
        
        if not histogram_all:
            save_market_basic(session, token_id, condition_id, question,
                            current_price, volume_24h, category, categories_json,
                            event_id, event_title)
            return True
        
        # === Calculate Profile Metrics ===
        VAH, VAL, mid_prob = calculate_consensus_band(histogram_all)
        band_width = get_band_width(histogram_all)
        poc = calculate_poc(histogram_all)
        
        # === Get WebSocket Data for Conviction Metrics ===
        ws_stats = get_aggressor_stats_from_db(session, token_id, hours=24)
        price_bins = get_price_bins_from_db(session, token_id, hours=24)
        
        # Calculate POMD from price bins (requires buy/sell breakdown)
        pomd = None
        if price_bins:
            aggressor_histogram = {
                p: {'buy': d['buy'], 'sell': d['sell']} 
                for p, d in price_bins.items()
            }
            pomd = calculate_pomd(aggressor_histogram)
        
        # === Calculate Uncertainty Metrics ===
        # UI with edge_zone flag
        ui_result = calculate_ui(histogram_all)
        if isinstance(ui_result, tuple):
            ui, edge_zone = ui_result
        else:
            ui = ui_result
            edge_zone = False
        
        # Get band_width from 7 days ago for CER calculation
        band_width_7d_ago = None
        try:
            date_sql = get_date_7_days_ago_sql()
            result = session.execute(text(f"""
                SELECT band_width, va_high, va_low
                FROM daily_metrics 
                WHERE token_id = :token_id 
                AND date = {date_sql}
            """), {'token_id': token_id}).fetchone()
            
            if result:
                if result[0] is not None:
                    band_width_7d_ago = float(result[0])
                elif result[1] is not None and result[2] is not None:
                    band_width_7d_ago = float(result[1]) - float(result[2])
        except:
            pass
        
        # ECR, ACR, CER
        ecr = calculate_ecr(current_price, days_remaining) if days_remaining else None
        acr = calculate_acr(band_width, band_width_7d_ago) if band_width_7d_ago and band_width else None
        cer = calculate_cer(band_width, band_width_7d_ago, current_price, days_remaining) if band_width and band_width_7d_ago else None
        
        # === Calculate Conviction Metrics ===
        cs = None
        ar = None
        volume_delta = None
        total_volume = None
        trade_count = None
        
        if ws_stats.get('has_data'):
            agg_buy = ws_stats['aggressive_buy']
            agg_sell = ws_stats['aggressive_sell']
            total_vol = ws_stats['total_volume']
            
            cs = calculate_cs(agg_buy, agg_sell, total_vol)
            ar = calculate_ar(agg_buy, agg_sell, total_vol)
            volume_delta = calculate_volume_delta(agg_buy, agg_sell)
            total_volume = total_vol
            trade_count = ws_stats['trade_count']
        
        # === Determine Status and Impulse Tag ===
        status = determine_status(ui, cer, cs, total_volume, edge_zone)
        impulse_tag = determine_impulse_tag(ui, cer, cs, pomd, current_price)
        
        # === Save to Database ===
        today = datetime.now().date()
        
        # Update markets table (DO NOT hardcode closed/active!)
        session.execute(text("""
            INSERT INTO markets
            (token_id, market_id, title, current_price, volume_24h,
             category, categories, event_id, event_title, updated_at)
            VALUES (:tid, :mid, :title, :price, :vol,
                    :cat, :cats, :eid, :etitle, :now)
            ON CONFLICT (token_id) DO UPDATE SET
                market_id = EXCLUDED.market_id,
                title = EXCLUDED.title,
                current_price = EXCLUDED.current_price,
                volume_24h = EXCLUDED.volume_24h,
                category = EXCLUDED.category,
                categories = EXCLUDED.categories,
                event_id = EXCLUDED.event_id,
                event_title = EXCLUDED.event_title,
                updated_at = EXCLUDED.updated_at
        """), {
            'tid': token_id,
            'mid': condition_id,
            'title': question,
            'price': current_price,
            'vol': volume_24h,
            'cat': category,
            'cats': categories_json,
            'eid': event_id,
            'etitle': event_title,
            'now': datetime.now()
        })
        
        # Update daily_metrics table with COMPLETE metrics
        session.execute(text("""
            INSERT INTO daily_metrics 
            (token_id, date, 
             va_high, va_low, band_width, poc, pomd,
             ui, ecr, acr, cer, edge_zone,
             cs, ar, volume_delta, total_volume, trade_count,
             status, impulse_tag,
             current_price, days_to_expiry)
            VALUES 
            (:tid, :date,
             :vah, :val, :bw, :poc, :pomd,
             :ui, :ecr, :acr, :cer, :edge_zone,
             :cs, :ar, :vdelta, :tvol, :tcount,
             :status, :impulse_tag,
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
                edge_zone = EXCLUDED.edge_zone,
                cs = EXCLUDED.cs,
                ar = EXCLUDED.ar,
                volume_delta = EXCLUDED.volume_delta,
                total_volume = EXCLUDED.total_volume,
                trade_count = EXCLUDED.trade_count,
                status = EXCLUDED.status,
                impulse_tag = EXCLUDED.impulse_tag,
                current_price = EXCLUDED.current_price,
                days_to_expiry = EXCLUDED.days_to_expiry
        """), {
            'tid': token_id,
            'date': today,
            'vah': VAH,
            'val': VAL,
            'bw': band_width,
            'poc': poc,
            'pomd': pomd,
            'ui': ui,
            'ecr': ecr,
            'acr': acr,
            'cer': cer,
            'edge_zone': edge_zone,
            'cs': cs,
            'ar': ar,
            'vdelta': volume_delta,
            'tvol': total_volume,
            'tcount': trade_count,
            'status': status,
            'impulse_tag': impulse_tag,
            'price': current_price * 100,  # Store as percentage
            'days': days_remaining
        })
        
        session.commit()
        return True
        
    except Exception as e:
        session.rollback()
        print(f"  Error: {e}")
        return False


def save_market_basic(session, token_id, condition_id, question,
                      current_price, volume_24h, category, categories_json,
                      event_id=None, event_title=None):
    """Save basic market info (when no trade data available)"""
    try:
        session.execute(text("""
            INSERT INTO markets
            (token_id, market_id, title, current_price, volume_24h,
             category, categories, event_id, event_title, updated_at)
            VALUES (:tid, :mid, :title, :price, :vol,
                    :cat, :cats, :eid, :etitle, :now)
            ON CONFLICT (token_id) DO UPDATE SET
                market_id = EXCLUDED.market_id,
                title = EXCLUDED.title,
                current_price = EXCLUDED.current_price,
                volume_24h = EXCLUDED.volume_24h,
                category = EXCLUDED.category,
                categories = EXCLUDED.categories,
                event_id = EXCLUDED.event_id,
                event_title = EXCLUDED.event_title,
                updated_at = EXCLUDED.updated_at
        """), {
            'tid': token_id,
            'mid': condition_id,
            'title': question,
            'price': current_price,
            'vol': volume_24h,
            'cat': category,
            'cats': categories_json,
            'eid': event_id,
            'etitle': event_title,
            'now': datetime.now()
        })
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"  Basic save error: {e}")


def incremental_sync(
    min_volume_24h: float = 100,
    volume_change_threshold: float = 0.2,
    price_change_threshold: float = 0.05,
    use_categories: bool = True
):
    """
    Intelligent Incremental Sync
    
    Args:
        min_volume_24h: Minimum 24h volume threshold
        volume_change_threshold: Volume change threshold (0.2 = 20%)
        price_change_threshold: Price change threshold (0.05 = 5%)
        use_categories: Whether to fetch by category (True = more comprehensive, False = faster)
    """
    session = get_session()
    api = PolymarketAPI()
    
    stats = {
        'new': 0,
        'closed': 0,
        'updated': 0,
        'unchanged': 0,
        'failed': 0
    }
    
    try:
        print(f"\n{'='*70}")
        print("Intelligent Incremental Sync v3")
        print(f"   Database: {'PostgreSQL' if IS_POSTGRES else 'SQLite'}")
        print(f"   Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}\n")
        
        # Step 0: Ensure schema is up to date
        print("Step 0: Ensuring database schema...")
        migrate_schema()
        
        # Step 1: Fetch all active markets from API
        print("Step 1: Fetching all active markets from API...")
        
        if use_categories:
            api_markets = api.get_markets_by_categories(
                min_volume_24h=min_volume_24h,
                total_limit=None
            )
        else:
            api_markets = api.get_all_markets_from_events(
                min_volume_24h=min_volume_24h,
                max_events=None
            )
        
        print(f"   Found {len(api_markets)} active markets (volume > ${min_volume_24h})\n")
        
        # Step 2: Load markets from database
        print("Step 2: Loading markets from database...")
        db_markets = get_active_markets_from_db(session)
        print(f"   Database has {len(db_markets)} active markets\n")
        
        # Step 3: Detect new markets
        print("Step 3: Detecting new markets...")
        new_markets = detect_new_markets(api_markets, db_markets)
        print(f"   Found {len(new_markets)} new markets\n")
        
        # Step 4: Detect closed/settled markets
        print("Step 4: Detecting closed markets...")
        closed_market_ids = detect_closed_markets(api_markets, db_markets)
        print(f"   Found {len(closed_market_ids)} closed markets\n")
        
        # Step 5: Detect changed markets
        print("Step 5: Detecting changed markets...")
        changed_markets = detect_changed_markets(
            api_markets, db_markets,
            volume_change_threshold, price_change_threshold
        )
        print(f"   Found {len(changed_markets)} markets with significant changes\n")
        
        # Step 6: Mark closed markets
        if closed_market_ids:
            print("Step 6: Marking closed markets...")
            marked = mark_markets_as_closed(session, closed_market_ids)
            stats['closed'] = marked
            print(f"   Marked {marked} markets as closed\n")
        
        # Step 7: Sync new markets
        if new_markets:
            print(f"Step 7: Syncing {len(new_markets)} new markets...")
            for idx, market in enumerate(new_markets, 1):
                cat = market.get('category', 'Other')
                cats = market.get('categories', [])
                cats_str = f" (+{len(cats)-1})" if len(cats) > 1 else ""
                print(f"  [{idx}/{len(new_markets)}] [{cat}{cats_str}] {market['question'][:40]}...")
                
                if sync_market(session, api, market):
                    stats['new'] += 1
                    print("    Synced")
                else:
                    stats['failed'] += 1
                    print("    Failed")
                
                if idx % 10 == 0:
                    time.sleep(2)
            print()
        
        # Step 8: Update changed markets
        if changed_markets:
            print(f"Step 8: Updating {len(changed_markets)} changed markets...")
            for idx, market in enumerate(changed_markets, 1):
                cat = market.get('category', 'Other')
                print(f"  [{idx}/{len(changed_markets)}] [{cat}] {market['question'][:40]}...")
                
                if sync_market(session, api, market):
                    stats['updated'] += 1
                    print("    Updated")
                else:
                    stats['failed'] += 1
                    print("    Failed")
                
                if idx % 10 == 0:
                    time.sleep(2)
            print()
        
        # Step 9: Statistics
        stats['unchanged'] = max(0, len(db_markets) - len(changed_markets) - len(closed_market_ids))
        
        # Print statistics
        print(f"\n{'='*70}")
        print("Sync Statistics:")
        print(f"{'='*70}")
        print(f"New markets added: {stats['new']}")
        print(f"Markets updated: {stats['updated']}")
        print(f"Markets closed: {stats['closed']}")
        print(f"Markets unchanged: {stats['unchanged']}")
        print(f"Failed: {stats['failed']}")
        print(f"{'='*70}")
        
        # Category statistics
        try:
            cat_stats = session.execute(text("""
                SELECT category, COUNT(*) as count
                FROM markets
                WHERE closed = false OR closed IS NULL
                GROUP BY category
                ORDER BY count DESC
            """)).fetchall()
            
            if cat_stats:
                print("\nCategory Distribution (primary):")
                for cat, count in cat_stats:
                    print(f"   {cat or 'Other'}: {count}")
        except:
            pass
        
        # Multi-category statistics
        try:
            result = session.execute(text("""
                SELECT COUNT(*) FROM markets 
                WHERE categories IS NOT NULL 
                AND categories != '[]'
                AND (closed = false OR closed IS NULL)
            """)).scalar()
            print(f"\nMarkets with category data: {result}")
        except:
            pass
        
        total_active = session.execute(
            text("SELECT COUNT(*) FROM markets WHERE closed = false OR closed IS NULL")
        ).scalar()
        print(f"\nTotal active markets in DB: {total_active}")
        print(f"Sync completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        return stats
        
    except Exception as e:
        print(f"\nSync failed: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
        return stats
    finally:
        session.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Intelligent incremental market sync v3')
    parser.add_argument('--min-volume', type=float, default=100,
                       help='Minimum 24h volume (default: 100)')
    parser.add_argument('--volume-threshold', type=float, default=0.2,
                       help='Volume change threshold (default: 0.2 = 20%%)')
    parser.add_argument('--price-threshold', type=float, default=0.05,
                       help='Price change threshold (default: 0.05 = 5%%)')
    parser.add_argument('--fast', action='store_true',
                       help='Fast mode: skip category-based fetching')
    
    args = parser.parse_args()
    
    print("Initializing database...")
    init_db()
    
    stats = incremental_sync(
        min_volume_24h=args.min_volume,
        volume_change_threshold=args.volume_threshold,
        price_change_threshold=args.price_threshold,
        use_categories=not args.fast
    )
    
    exit_code = 0 if stats['failed'] == 0 else 1
    sys.exit(exit_code)
