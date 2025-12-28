"""
智能增量同步系统
- 检测新市场
- 移除已结算市场
- 只更新有变化的市场
- 保留历史数据
"""

import os
import sys
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from datetime import datetime, timedelta
from sqlalchemy import text
from utils.db import get_session, init_db
from utils.polymarket_api import PolymarketAPI
from utils.metrics import (
    calculate_histogram, calculate_ui, calculate_cs, calculate_cer,
    determine_status, filter_trades_by_time, get_band_width
)
import time


def get_active_markets_from_db(session) -> dict:
    """获取数据库中的活跃市场"""
    result = session.execute(text("""
        SELECT token_id, market_id, volume_24h, current_price, updated_at
        FROM markets
        WHERE closed = false
        ORDER BY volume_24h DESC
    """)).fetchall()
    
    return {
        row[1]: {  # market_id (condition_id) 作为 key
            'token_id': row[0],
            'volume_24h': float(row[2] or 0),
            'price': float(row[3] or 0),
            'updated_at': row[4]
        }
        for row in result
    }


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
        
        # 检查最后更新时间（处理字符串和 datetime 对象）
        last_updated = db_market['updated_at']
        hours_since_update = 25  # 默认值，触发更新
        
        try:
            if isinstance(last_updated, str):
                # SQLite 返回字符串，需要解析
                from dateutil import parser
                last_updated_dt = parser.parse(last_updated)
                hours_since_update = (datetime.now() - last_updated_dt).total_seconds() / 3600
            elif last_updated:
                # PostgreSQL 返回 datetime 对象
                hours_since_update = (datetime.now() - last_updated).total_seconds() / 3600
        except Exception:
            # 解析失败，使用默认值（会触发更新）
            pass
        
        # 判断是否需要更新
        needs_update = (
            volume_change > volume_change_threshold or  # 交易量变化 > 20%
            price_change > price_change_threshold or    # 价格变化 > 5%
            hours_since_update > 24                     # 超过 24 小时未更新
        )
        
        if needs_update:
            changed_markets.append(market)
    
    return changed_markets


def mark_markets_as_closed(session, market_ids: list):
    """标记市场为已结算"""
    if not market_ids:
        return 0
    
    # 使用参数化查询
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


def sync_market(session, api: PolymarketAPI, market: dict) -> bool:
    """同步单个市场（从 sync.py 提取的逻辑）"""
    try:
        condition_id = market['condition_id']
        token_id = market['token_id']
        question = market['question']
        current_price = market['price']
        volume_24h = market['volume_24h']
        
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
        market_trades = api.get_trades_for_market(condition_id, limit=5000)
        
        if not market_trades:
            return False
        
        trades_24h = filter_trades_by_time(market_trades, hours=24)
        
        # 计算指标
        histogram_all = calculate_histogram(market_trades)
        
        if not histogram_all:
            return False
        
        ui = calculate_ui(histogram_all)
        cs = calculate_cs(trades_24h) if trades_24h else None
        
        band_width_now = get_band_width(histogram_all)
        
        # 获取 7 天前的 band width
        band_width_7d_ago = None
        try:
            result = session.execute(text("""
                SELECT va_high, va_low
                FROM daily_metrics 
                WHERE token_id = :token_id 
                AND date = (CURRENT_DATE - INTERVAL '7 days')::date
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
            (token_id, market_id, title, current_price, volume_24h, updated_at, closed, active)
            VALUES (:tid, :mid, :title, :price, :vol, :now, false, true)
            ON CONFLICT (token_id) DO UPDATE SET
                market_id = EXCLUDED.market_id,
                title = EXCLUDED.title,
                current_price = EXCLUDED.current_price,
                volume_24h = EXCLUDED.volume_24h,
                updated_at = EXCLUDED.updated_at,
                closed = EXCLUDED.closed,
                active = EXCLUDED.active
        """), {
            'tid': token_id,
            'mid': condition_id,
            'title': question,
            'price': current_price,
            'vol': volume_24h,
            'now': datetime.now()
        })
        
        # 计算 VA 范围
        if band_width_now:
            va_high = current_price * 100 + (band_width_now * 50)
            va_low = current_price * 100 - (band_width_now * 50)
        else:
            va_high = None
            va_low = None
        
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


def incremental_sync(
    min_volume_24h: float = 100,
    volume_change_threshold: float = 0.2,
    price_change_threshold: float = 0.05
):
    """
    智能增量同步
    
    Args:
        min_volume_24h: 最小 24h 交易量
        volume_change_threshold: 交易量变化阈值（0.2 = 20%）
        price_change_threshold: 价格变化阈值（0.05 = 5%）
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
        print(f"🔄 Intelligent Incremental Sync")
        print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}\n")
        
        # Step 1: 从 API 获取所有活跃市场
        print("📡 Step 1: Fetching all active markets from API...")
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
                print(f"  [{idx}/{len(new_markets)}] {market['question'][:50]}...")
                if sync_market(session, api, market):
                    stats['new'] += 1
                    print(f"    ✅ Synced")
                else:
                    stats['failed'] += 1
                    print(f"    ❌ Failed")
                
                # Rate limit protection
                if idx % 10 == 0:
                    time.sleep(2)
            print()
        
        # Step 8: 更新有变化的市场
        if changed_markets:
            print(f"🔄 Step 8: Updating {len(changed_markets)} changed markets...")
            for idx, market in enumerate(changed_markets, 1):
                print(f"  [{idx}/{len(changed_markets)}] {market['question'][:50]}...")
                if sync_market(session, api, market):
                    stats['updated'] += 1
                    print(f"    ✅ Updated")
                else:
                    stats['failed'] += 1
                    print(f"    ❌ Failed")
                
                # Rate limit protection
                if idx % 10 == 0:
                    time.sleep(2)
            print()
        
        # Step 9: 统计未变化的市场
        stats['unchanged'] = len(db_markets) - len(changed_markets) - len(closed_market_ids)
        
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
        
        total_active = session.execute(
            text("SELECT COUNT(*) FROM markets WHERE closed = false")
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
    
    parser = argparse.ArgumentParser(description='Intelligent incremental market sync')
    parser.add_argument('--min-volume', type=float, default=100,
                       help='Minimum 24h volume (default: 100)')
    parser.add_argument('--volume-threshold', type=float, default=0.2,
                       help='Volume change threshold (default: 0.2 = 20%%)')
    parser.add_argument('--price-threshold', type=float, default=0.05,
                       help='Price change threshold (default: 0.05 = 5%%)')
    
    args = parser.parse_args()
    
    print("Initializing database...")
    init_db()
    
    stats = incremental_sync(
        min_volume_24h=args.min_volume,
        volume_change_threshold=args.volume_threshold,
        price_change_threshold=args.price_threshold
    )
    
    # Exit code
    exit_code = 0 if stats['failed'] == 0 else 1
    sys.exit(exit_code)
