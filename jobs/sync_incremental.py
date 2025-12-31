"""
智能增量同步系统 v2
- 检测新市场
- 移除已结算市场
- 只更新有变化的市场
- 保留历史数据
- 支持多分类（categories JSON 数组）
"""

import os
import sys
import json
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
    determine_status, filter_trades_by_time, get_band_width
)

# WebSocket 数据获取函数
def get_aggressor_stats_from_db(session, token_id: str, hours: int = 24) -> dict:
    """从 ws_trades_hourly 获取 aggressor 统计"""
    try:
        # 使用兼容的时间间隔 SQL
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
import time


def get_active_markets_from_db(session) -> dict:
    """获取数据库中的活跃市场"""
    try:
        result = session.execute(text("""
            SELECT token_id, market_id, volume_24h, current_price, updated_at, 
                   category, categories
            FROM markets
            WHERE closed = false OR closed IS NULL
            ORDER BY volume_24h DESC
        """)).fetchall()
    except Exception:
        # 回退：不带 closed 字段
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
        
        # 解析 categories JSON
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
    """检测新市场"""
    new_markets = []
    db_market_ids = set(db_markets.keys())
    
    for market in api_markets:
        if market['condition_id'] not in db_market_ids:
            new_markets.append(market)
    
    return new_markets


def detect_closed_markets(api_markets: list, db_markets: dict) -> list:
    """检测已结算的市场（在 DB 但不在 API 的活跃列表）"""
    api_market_ids = {m['condition_id'] for m in api_markets}
    closed_markets = []
    
    for market_id in db_markets.keys():
        if market_id not in api_market_ids:
            closed_markets.append(market_id)
    
    return closed_markets


def detect_changed_markets(api_markets: list, db_markets: dict, 
                           volume_change_threshold: float = 0.2,
                           price_change_threshold: float = 0.05) -> list:
    """检测有显著变化的市场"""
    changed_markets = []
    
    for market in api_markets:
        market_id = market['condition_id']
        
        if market_id not in db_markets:
            continue
        
        db_market = db_markets[market_id]
        
        # 检查交易量变化
        old_volume = db_market['volume_24h']
        new_volume = market['volume_24h']
        volume_change = abs(new_volume - old_volume) / (old_volume + 1)
        
        # 检查价格变化
        old_price = db_market['price']
        new_price = market['price']
        price_change = abs(new_price - old_price)
        
        # 检查最后更新时间
        last_updated = db_market['updated_at']
        hours_since_update = 25  # 默认值，触发更新
        
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
        
        # 判断是否需要更新
        needs_update = (
            volume_change > volume_change_threshold or
            price_change > price_change_threshold or
            hours_since_update > 24
        )
        
        if needs_update:
            changed_markets.append(market)
    
    return changed_markets


def mark_markets_as_closed(session, market_ids: list) -> int:
    """标记市场为已结算"""
    if not market_ids:
        return 0
    
    try:
        placeholders = ','.join([f':id{i}' for i in range(len(market_ids))])
        params = {f'id{i}': market_id for i, market_id in enumerate(market_ids)}
        
        result = session.execute(
            text(f"""
                UPDATE markets 
                SET closed = true, active = false 
                WHERE market_id IN ({placeholders})
            """),
            params
        )
        session.commit()
        return result.rowcount
    except Exception as e:
        print(f"  ⚠️ Could not mark as closed: {e}")
        session.rollback()
        return 0


def sync_market(session, api: PolymarketAPI, market: dict) -> bool:
    """同步单个市场"""
    try:
        condition_id = market['condition_id']
        token_id = market['token_id']
        question = market['question']
        current_price = market['price']
        volume_24h = market['volume_24h']
        category = market.get('category', 'Other')
        categories = market.get('categories', [category])
        
        # categories 转 JSON 字符串
        categories_json = json.dumps(categories) if categories else json.dumps([category])
        
        # 计算剩余天数
        days_remaining = 30
        if market.get('end_date'):
            try:
                end_date = datetime.fromisoformat(
                    market['end_date'].replace('Z', '+00:00')
                )
                days_remaining = max(1, (end_date.date() - datetime.now().date()).days)
            except:
                pass
        
        # 获取成交数据
        market_trades = api.get_trades_for_market(condition_id, limit=5000)
        
        if not market_trades:
            save_market_basic(session, token_id, condition_id, question,
                            current_price, volume_24h, category, categories_json)
            return True
        
        trades_24h = filter_trades_by_time(market_trades, hours=24)
        
        # 计算指标
        histogram_all = calculate_histogram(market_trades)
        
        if not histogram_all:
            save_market_basic(session, token_id, condition_id, question,
                            current_price, volume_24h, category, categories_json)
            return True
        
        ui = calculate_ui(histogram_all)
        band_width_now = get_band_width(histogram_all)
        
        # 从 WebSocket 数据获取 aggressor 统计来计算 CS
        cs = None
        ws_stats = get_aggressor_stats_from_db(session, token_id, hours=24)
        if ws_stats.get('has_data'):
            cs = calculate_cs(
                ws_stats['aggressive_buy'],
                ws_stats['aggressive_sell'],
                ws_stats['total_volume']
            )
        
        # 获取 7 天前的 band width（使用兼容的 SQL）
        band_width_7d_ago = None
        try:
            date_sql = get_date_7_days_ago_sql()
            result = session.execute(text(f"""
                SELECT va_high, va_low
                FROM daily_metrics 
                WHERE token_id = :token_id 
                AND date = {date_sql}
            """), {'token_id': token_id}).fetchone()
            
            if result and result[0] and result[1]:
                band_width_7d_ago = float(result[0]) - float(result[1])
        except:
            pass
        
        cer = calculate_cer(
            band_width_now,
            band_width_7d_ago,
            current_price,
            days_remaining
        ) if band_width_now and band_width_7d_ago else None
        
        status = determine_status(ui, cer, cs)
        
        # 保存到数据库
        today = datetime.now().date()
        
        # 更新 markets 表
        session.execute(text("""
            INSERT INTO markets 
            (token_id, market_id, title, current_price, volume_24h, 
             category, categories, updated_at, closed, active)
            VALUES (:tid, :mid, :title, :price, :vol, 
                    :cat, :cats, :now, false, true)
            ON CONFLICT (token_id) DO UPDATE SET
                market_id = EXCLUDED.market_id,
                title = EXCLUDED.title,
                current_price = EXCLUDED.current_price,
                volume_24h = EXCLUDED.volume_24h,
                category = EXCLUDED.category,
                categories = EXCLUDED.categories,
                updated_at = EXCLUDED.updated_at,
                closed = EXCLUDED.closed,
                active = EXCLUDED.active
        """), {
            'tid': token_id,
            'mid': condition_id,
            'title': question,
            'price': current_price,
            'vol': volume_24h,
            'cat': category,
            'cats': categories_json,
            'now': datetime.now()
        })
        
        # 计算 VA 范围
        va_high = None
        va_low = None
        if band_width_now:
            va_high = current_price * 100 + (band_width_now * 50)
            va_low = current_price * 100 - (band_width_now * 50)
        
        # 更新 daily_metrics 表
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
            'price': current_price * 100,
            'days': days_remaining,
            'vah': va_high,
            'val': va_low
        })
        
        session.commit()
        return True
        
    except Exception as e:
        session.rollback()
        print(f"  ❌ Error: {e}")
        return False


def save_market_basic(session, token_id, condition_id, question,
                      current_price, volume_24h, category, categories_json):
    """保存市场基本信息（无交易数据时）"""
    try:
        session.execute(text("""
            INSERT INTO markets 
            (token_id, market_id, title, current_price, volume_24h, 
             category, categories, updated_at, closed, active)
            VALUES (:tid, :mid, :title, :price, :vol, 
                    :cat, :cats, :now, false, true)
            ON CONFLICT (token_id) DO UPDATE SET
                market_id = EXCLUDED.market_id,
                title = EXCLUDED.title,
                current_price = EXCLUDED.current_price,
                volume_24h = EXCLUDED.volume_24h,
                category = EXCLUDED.category,
                categories = EXCLUDED.categories,
                updated_at = EXCLUDED.updated_at
        """), {
            'tid': token_id,
            'mid': condition_id,
            'title': question,
            'price': current_price,
            'vol': volume_24h,
            'cat': category,
            'cats': categories_json,
            'now': datetime.now()
        })
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"  ⚠️ Basic save error: {e}")


def incremental_sync(
    min_volume_24h: float = 100,
    volume_change_threshold: float = 0.2,
    price_change_threshold: float = 0.05,
    use_categories: bool = True
):
    """
    智能增量同步
    
    Args:
        min_volume_24h: 最小 24h 交易量
        volume_change_threshold: 交易量变化阈值（0.2 = 20%）
        price_change_threshold: 价格变化阈值（0.05 = 5%）
        use_categories: 是否按分类获取（True 更全面，False 更快）
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
        print(f"🔄 Intelligent Incremental Sync v2")
        print(f"   Database: {'PostgreSQL' if IS_POSTGRES else 'SQLite'}")
        print(f"   Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}\n")
        
        # Step 0: 确保 schema 是最新的
        print("🔧 Step 0: Ensuring database schema...")
        migrate_schema()
        
        # Step 1: 从 API 获取所有活跃市场
        print("📡 Step 1: Fetching all active markets from API...")
        
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
        
        # Step 2: 从数据库获取当前追踪的市场
        print("💾 Step 2: Loading markets from database...")
        db_markets = get_active_markets_from_db(session)
        print(f"   Database has {len(db_markets)} active markets\n")
        
        # Step 3: 检测新市场
        print("🆕 Step 3: Detecting new markets...")
        new_markets = detect_new_markets(api_markets, db_markets)
        print(f"   Found {len(new_markets)} new markets\n")
        
        # Step 4: 检测已结算市场
        print("🔚 Step 4: Detecting closed markets...")
        closed_market_ids = detect_closed_markets(api_markets, db_markets)
        print(f"   Found {len(closed_market_ids)} closed markets\n")
        
        # Step 5: 检测有变化的市场
        print("🔄 Step 5: Detecting changed markets...")
        changed_markets = detect_changed_markets(
            api_markets, db_markets,
            volume_change_threshold, price_change_threshold
        )
        print(f"   Found {len(changed_markets)} markets with significant changes\n")
        
        # Step 6: 标记已结算市场
        if closed_market_ids:
            print("📝 Step 6: Marking closed markets...")
            marked = mark_markets_as_closed(session, closed_market_ids)
            stats['closed'] = marked
            print(f"   Marked {marked} markets as closed\n")
        
        # Step 7: 同步新市场
        if new_markets:
            print(f"🆕 Step 7: Syncing {len(new_markets)} new markets...")
            for idx, market in enumerate(new_markets, 1):
                cat = market.get('category', 'Other')
                cats = market.get('categories', [])
                cats_str = f" (+{len(cats)-1})" if len(cats) > 1 else ""
                print(f"  [{idx}/{len(new_markets)}] [{cat}{cats_str}] {market['question'][:40]}...")
                
                if sync_market(session, api, market):
                    stats['new'] += 1
                    print(f"    ✅ Synced")
                else:
                    stats['failed'] += 1
                    print(f"    ❌ Failed")
                
                if idx % 10 == 0:
                    time.sleep(2)
            print()
        
        # Step 8: 更新有变化的市场
        if changed_markets:
            print(f"🔄 Step 8: Updating {len(changed_markets)} changed markets...")
            for idx, market in enumerate(changed_markets, 1):
                cat = market.get('category', 'Other')
                print(f"  [{idx}/{len(changed_markets)}] [{cat}] {market['question'][:40]}...")
                
                if sync_market(session, api, market):
                    stats['updated'] += 1
                    print(f"    ✅ Updated")
                else:
                    stats['failed'] += 1
                    print(f"    ❌ Failed")
                
                if idx % 10 == 0:
                    time.sleep(2)
            print()
        
        # Step 9: 统计
        stats['unchanged'] = max(0, len(db_markets) - len(changed_markets) - len(closed_market_ids))
        
        # 打印统计
        print(f"\n{'='*70}")
        print(f"📊 Sync Statistics:")
        print(f"{'='*70}")
        print(f"🆕 New markets added: {stats['new']}")
        print(f"🔄 Markets updated: {stats['updated']}")
        print(f"🔚 Markets closed: {stats['closed']}")
        print(f"✅ Markets unchanged: {stats['unchanged']}")
        print(f"❌ Failed: {stats['failed']}")
        print(f"{'='*70}")
        
        # 分类统计
        try:
            cat_stats = session.execute(text("""
                SELECT category, COUNT(*) as count
                FROM markets
                WHERE closed = false OR closed IS NULL
                GROUP BY category
                ORDER BY count DESC
            """)).fetchall()
            
            if cat_stats:
                print(f"\n📂 Category Distribution (primary):")
                for cat, count in cat_stats:
                    print(f"   {cat or 'Other'}: {count}")
        except:
            pass
        
        # 多分类统计
        try:
            result = session.execute(text("""
                SELECT COUNT(*) FROM markets 
                WHERE categories IS NOT NULL 
                AND categories != '[]'
                AND (closed = false OR closed IS NULL)
            """)).scalar()
            print(f"\n📊 Markets with category data: {result}")
        except:
            pass
        
        total_active = session.execute(
            text("SELECT COUNT(*) FROM markets WHERE closed = false OR closed IS NULL")
        ).scalar()
        print(f"\n📈 Total active markets in DB: {total_active}")
        print(f"⏱️  Sync completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        return stats
        
    except Exception as e:
        print(f"\n❌ Sync failed: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
        return stats
    finally:
        session.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Intelligent incremental market sync v2')
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
