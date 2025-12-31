"""
Lifecycle Phases 同步脚本

功能：
1. 回填历史 phases（用 Data API）
2. 更新当前 phase（用 WebSocket 数据如果有）

运行方式：
    python jobs/lifecycle_sync.py --markets 100
    python jobs/lifecycle_sync.py --markets 100 --backfill
"""

import os
import sys
import time
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from sqlalchemy import text
from utils.db import get_session, init_db, DATABASE_URL
from utils.polymarket_api import PolymarketAPI
from utils.lifecycle import (
    PHASES,
    calculate_phase_dates,
    get_current_phase,
    filter_trades_by_phase,
    calculate_phase_metrics,
    save_phase_metrics,
    get_phase_metrics,
    create_lifecycle_table,
)


def get_price_bins_for_phase(
    session,
    token_id: str,
    phase_start: datetime,
    phase_end: datetime
) -> Dict[float, Dict]:
    """
    从 ws_price_bins 获取某个 phase 时间段内的 price bins
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
            AND hour >= :start
            AND hour < :end
            GROUP BY price_bin
        """)
        
        results = session.execute(query, {
            'tid': token_id,
            'start': phase_start,
            'end': phase_end
        }).fetchall()
        
        bins = {}
        for row in results:
            price = float(row[0])
            buy = float(row[1])
            sell = float(row[2])
            bins[price] = {
                'buy': buy,
                'sell': sell,
                'total': buy + sell,
                'min_side': min(buy, sell),
                'count': int(row[3])
            }
        
        return bins
        
    except Exception:
        return {}


def get_aggressor_stats_for_phase(
    session,
    token_id: str,
    phase_start: datetime,
    phase_end: datetime
) -> Dict:
    """
    从 ws_trades_hourly 获取某个 phase 时间段内的 aggressor 统计
    """
    try:
        query = text("""
            SELECT 
                COALESCE(SUM(aggressive_buy), 0) as buy,
                COALESCE(SUM(aggressive_sell), 0) as sell,
                COALESCE(SUM(trade_count), 0) as count
            FROM ws_trades_hourly
            WHERE token_id = :tid
            AND hour >= :start
            AND hour < :end
        """)
        
        result = session.execute(query, {
            'tid': token_id,
            'start': phase_start,
            'end': phase_end
        }).fetchone()
        
        if result and result[2] > 0:
            return {
                'aggressive_buy': float(result[0]),
                'aggressive_sell': float(result[1]),
                'trade_count': int(result[2]),
                'has_data': True
            }
        
    except Exception:
        pass
    
    return {'has_data': False}


def sync_market_lifecycle(
    session,
    api: PolymarketAPI,
    market: Dict,
    backfill: bool = True,
    verbose: bool = True
) -> Dict:
    """
    同步单个市场的 lifecycle phases
    
    Args:
        session: 数据库会话
        api: Polymarket API
        market: 市场信息
        backfill: 是否回填历史 phases
        verbose: 是否打印详细日志
    
    Returns:
        {'phases_synced': int, 'success': bool}
    """
    token_id = market['token_id']
    condition_id = market['condition_id']
    question = market['question']
    
    # 获取市场时间范围
    # 注意：需要从 API 获取 created_at
    created_at_str = market.get('created_at')
    end_date_str = market.get('end_date')
    
    if not end_date_str:
        if verbose:
            print(f"  ⚠️ No end_date, skipping")
        return {'phases_synced': 0, 'success': False}
    
    try:
        end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).replace(tzinfo=None)
    except:
        if verbose:
            print(f"  ⚠️ Invalid end_date, skipping")
        return {'phases_synced': 0, 'success': False}
    
    # created_at：如果没有，估算为 end_date - 90 天
    if created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00')).replace(tzinfo=None)
        except:
            created_at = end_date - timedelta(days=90)
    else:
        created_at = end_date - timedelta(days=90)
    
    # 确保 created_at < end_date
    if created_at >= end_date:
        created_at = end_date - timedelta(days=30)
    
    # 计算 phases
    phases = calculate_phase_dates(created_at, end_date)
    
    if verbose:
        duration = (end_date - created_at).days
        print(f"  📅 Lifecycle: {duration} days ({created_at.date()} → {end_date.date()})")
    
    # 获取当前时间和当前 phase
    now = datetime.now()
    current_phase = get_current_phase(created_at, end_date, now)
    
    # 获取所有 trades（用于历史回填）
    all_trades = []
    if backfill:
        if verbose:
            print(f"  📥 Fetching all trades...")
        all_trades = api.get_trades_for_market(condition_id, limit=10000)
        if verbose:
            print(f"  📈 Got {len(all_trades)} trades")
    
    phases_synced = 0
    previous_band_width = None
    
    for phase_num, phase_start, phase_end in phases:
        # 判断这个 phase 是否已完成
        phase_completed = now >= phase_end
        phase_in_progress = phase_start <= now < phase_end
        phase_future = now < phase_start
        
        if phase_future:
            # 未来的 phase，跳过
            continue
        
        # 检查是否已经有数据
        existing = get_phase_metrics(session, token_id, phase_num)
        if existing and phase_completed and not backfill:
            # 已完成的 phase 有数据了，跳过
            previous_band_width = existing.get('band_width')
            continue
        
        if verbose:
            status_str = "✅" if phase_completed else "🔄" if phase_in_progress else "⏳"
            print(f"  {status_str} Phase {phase_num}: {phase_start.date()} → {phase_end.date()}")
        
        # 筛选这个 phase 的 trades
        phase_trades = filter_trades_by_phase(all_trades, phase_start, phase_end)
        
        if not phase_trades:
            if verbose:
                print(f"     No trades in this phase")
            continue
        
        # 获取该 phase 结束时的价格（取最后一笔 trade 的价格）
        phase_trades_sorted = sorted(phase_trades, key=lambda x: x.get('timestamp', 0))
        price_at_end = float(phase_trades_sorted[-1].get('price', 0.5))
        
        # 计算剩余天数（该 phase 结束时）
        days_remaining = max(1, (end_date - phase_end).days)
        
        # 获取 WebSocket 数据（如果有）
        aggressor_histogram = None
        aggressive_buy = None
        aggressive_sell = None
        
        # 只有完成的 phase 或当前 phase 才查 WebSocket 数据
        if phase_completed or phase_in_progress:
            price_bins = get_price_bins_for_phase(session, token_id, phase_start, phase_end)
            if price_bins:
                aggressor_histogram = price_bins
            
            agg_stats = get_aggressor_stats_for_phase(session, token_id, phase_start, phase_end)
            if agg_stats.get('has_data'):
                aggressive_buy = agg_stats['aggressive_buy']
                aggressive_sell = agg_stats['aggressive_sell']
        
        # 计算指标
        metrics = calculate_phase_metrics(
            trades=phase_trades,
            current_price=price_at_end,
            days_remaining=days_remaining,
            previous_band_width=previous_band_width,
            aggressor_histogram=aggressor_histogram,
            aggressive_buy=aggressive_buy,
            aggressive_sell=aggressive_sell,
        )
        
        if metrics.get('has_data'):
            # 保存
            success = save_phase_metrics(
                session=session,
                token_id=token_id,
                phase_number=phase_num,
                phase_start=phase_start,
                phase_end=phase_end,
                metrics=metrics
            )
            
            if success:
                phases_synced += 1
                if verbose:
                    bw = metrics.get('band_width')
                    ui = metrics.get('ui')
                    bw_str = f"{bw:.3f}" if bw else "N/A"
                    ui_str = f"{ui:.3f}" if ui else "N/A"
                    has_ws = "✅" if aggressor_histogram else "❌"
                    print(f"     BW: {bw_str} | UI: {ui_str} | WS: {has_ws} | Trades: {metrics['trade_count']}")
            
            # 更新 previous_band_width
            previous_band_width = metrics.get('band_width')
    
    return {'phases_synced': phases_synced, 'success': True}


def sync_all_lifecycles(
    api: PolymarketAPI,
    top_n: int = 100,
    backfill: bool = True,
    verbose: bool = True
):
    """
    同步所有市场的 lifecycle phases
    """
    session = get_session()
    
    stats = {
        'total': 0,
        'success': 0,
        'failed': 0,
        'total_phases': 0,
    }
    
    try:
        print(f"\n{'='*60}")
        print(f"Lifecycle Phases Sync")
        print(f"Backfill: {backfill}")
        print(f"{'='*60}\n")
        
        # 确保表存在
        create_lifecycle_table(session)
        
        # 获取市场
        print(f"📊 Fetching markets...")
        markets = api.get_markets_by_categories(
            min_volume_24h=100,
            total_limit=top_n
        )
        
        if not markets:
            print("❌ No markets")
            return stats
        
        markets.sort(key=lambda x: x['volume_24h'], reverse=True)
        stats['total'] = len(markets)
        
        print(f"✅ Processing {len(markets)} markets\n")
        
        for idx, market in enumerate(markets, 1):
            question = market['question']
            print(f"[{idx}/{stats['total']}] {question[:50]}...")
            
            try:
                result = sync_market_lifecycle(
                    session=session,
                    api=api,
                    market=market,
                    backfill=backfill,
                    verbose=verbose
                )
                
                if result['success']:
                    stats['success'] += 1
                    stats['total_phases'] += result['phases_synced']
                else:
                    stats['failed'] += 1
                
            except Exception as e:
                print(f"  ❌ Error: {e}")
                stats['failed'] += 1
            
            # Rate limit
            if idx % 5 == 0:
                time.sleep(1)
        
        # 统计
        print(f"\n{'='*60}")
        print(f"📊 Sync Statistics")
        print(f"{'='*60}")
        print(f"Total markets: {stats['total']}")
        print(f"Success: {stats['success']}")
        print(f"Failed: {stats['failed']}")
        print(f"Total phases synced: {stats['total_phases']}")
        
        return stats
        
    except Exception as e:
        print(f"❌ Sync failed: {e}")
        return stats
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Sync lifecycle phases')
    parser.add_argument('--markets', type=int, default=100,
                       help='Number of markets (default: 100)')
    parser.add_argument('--backfill', action='store_true',
                       help='Backfill historical phases')
    parser.add_argument('--quiet', action='store_true',
                       help='Reduce logging')
    
    args = parser.parse_args()
    
    print("Initializing...")
    init_db()
    
    api = PolymarketAPI()
    
    sync_all_lifecycles(
        api=api,
        top_n=args.markets,
        backfill=args.backfill,
        verbose=not args.quiet
    )
