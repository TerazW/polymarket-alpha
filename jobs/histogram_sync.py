"""
Daily Histogram Sync Job

将每日交易数据聚合为 histogram 存入数据库
用于 Market Profile 可视化和历史对比

数据结构：
- token_id: 市场 ID
- date: 日期
- price_bin: 价格档位
- volume: 总成交量
- aggressive_buy: 主动买入量
- aggressive_sell: 主动卖出量
- trade_count: 成交笔数
"""

import sys
import os
import argparse
from datetime import datetime, timedelta
from collections import defaultdict

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db import engine, migrate_schema, IS_POSTGRES
from utils.polymarket_api import PolymarketAPI
from sqlalchemy import text


def get_active_markets(limit: int = 100) -> list:
    """获取活跃市场列表"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT token_id, market_id, title 
            FROM markets 
            WHERE active = TRUE AND closed = FALSE
            ORDER BY volume_24h DESC NULLS LAST
            LIMIT :limit
        """), {"limit": limit})
        return [{"token_id": row[0], "market_id": row[1], "title": row[2]} for row in result.fetchall()]


def aggregate_trades_to_histogram(
    trades: list, 
    tick_size: float = 0.01
) -> dict:
    """
    将交易聚合为 histogram
    
    Returns:
        {price_bin: {'volume': x, 'buy': y, 'sell': z, 'count': n}}
    """
    histogram = defaultdict(lambda: {
        'volume': 0.0,
        'aggressive_buy': 0.0,
        'aggressive_sell': 0.0,
        'trade_count': 0
    })
    
    for trade in trades:
        try:
            price = float(trade.get('price', 0))
            size = float(trade.get('size', 0))
            side = trade.get('side', '').upper()
            
            # 价格分档
            bin_price = round(price / tick_size) * tick_size
            bin_price = round(bin_price, 4)
            
            histogram[bin_price]['volume'] += size
            histogram[bin_price]['trade_count'] += 1
            
            # 区分主动买卖
            if side == 'BUY':
                histogram[bin_price]['aggressive_buy'] += size
            elif side == 'SELL':
                histogram[bin_price]['aggressive_sell'] += size
            else:
                # 如果没有 side，平均分配
                histogram[bin_price]['aggressive_buy'] += size / 2
                histogram[bin_price]['aggressive_sell'] += size / 2
                
        except (ValueError, TypeError):
            continue
    
    return dict(histogram)


def save_histogram(
    token_id: str, 
    date: datetime.date, 
    histogram: dict
):
    """保存 histogram 到数据库"""
    if not histogram:
        return 0
    
    saved = 0
    with engine.connect() as conn:
        for price_bin, data in histogram.items():
            try:
                if IS_POSTGRES:
                    # PostgreSQL: UPSERT
                    conn.execute(text("""
                        INSERT INTO daily_histogram 
                        (token_id, date, price_bin, volume, aggressive_buy, aggressive_sell, trade_count)
                        VALUES (:token_id, :date, :price_bin, :volume, :buy, :sell, :count)
                        ON CONFLICT (token_id, date, price_bin) 
                        DO UPDATE SET 
                            volume = :volume,
                            aggressive_buy = :buy,
                            aggressive_sell = :sell,
                            trade_count = :count
                    """), {
                        "token_id": token_id,
                        "date": date,
                        "price_bin": price_bin,
                        "volume": data['volume'],
                        "buy": data['aggressive_buy'],
                        "sell": data['aggressive_sell'],
                        "count": data['trade_count']
                    })
                else:
                    # SQLite: INSERT OR REPLACE
                    conn.execute(text("""
                        INSERT OR REPLACE INTO daily_histogram 
                        (token_id, date, price_bin, volume, aggressive_buy, aggressive_sell, trade_count)
                        VALUES (:token_id, :date, :price_bin, :volume, :buy, :sell, :count)
                    """), {
                        "token_id": token_id,
                        "date": date,
                        "price_bin": price_bin,
                        "volume": data['volume'],
                        "buy": data['aggressive_buy'],
                        "sell": data['aggressive_sell'],
                        "count": data['trade_count']
                    })
                saved += 1
            except Exception as e:
                print(f"    ⚠️ Error saving bin {price_bin}: {e}")
        
        conn.commit()
    
    return saved


def get_histogram_from_db(token_id: str, date: datetime.date = None) -> dict:
    """
    从数据库获取 histogram
    
    Returns:
        {price_bin: {'volume': x, 'buy': y, 'sell': z, 'count': n}}
    """
    if date is None:
        date = datetime.now().date()
    
    histogram = {}
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT price_bin, volume, aggressive_buy, aggressive_sell, trade_count
            FROM daily_histogram
            WHERE token_id = :token_id AND date = :date
            ORDER BY price_bin
        """), {"token_id": token_id, "date": date})
        
        for row in result.fetchall():
            price_bin = float(row[0])
            histogram[price_bin] = {
                'volume': float(row[1] or 0),
                'aggressive_buy': float(row[2] or 0),
                'aggressive_sell': float(row[3] or 0),
                'trade_count': int(row[4] or 0)
            }
    
    return histogram


def get_histogram_daterange(
    token_id: str, 
    start_date: datetime.date, 
    end_date: datetime.date
) -> dict:
    """
    获取日期范围内的累积 histogram
    
    用于计算多天合并的 Market Profile
    """
    histogram = defaultdict(lambda: {
        'volume': 0.0,
        'aggressive_buy': 0.0,
        'aggressive_sell': 0.0,
        'trade_count': 0
    })
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT price_bin, 
                   SUM(volume) as total_volume,
                   SUM(aggressive_buy) as total_buy,
                   SUM(aggressive_sell) as total_sell,
                   SUM(trade_count) as total_count
            FROM daily_histogram
            WHERE token_id = :token_id 
              AND date BETWEEN :start_date AND :end_date
            GROUP BY price_bin
            ORDER BY price_bin
        """), {
            "token_id": token_id, 
            "start_date": start_date,
            "end_date": end_date
        })
        
        for row in result.fetchall():
            price_bin = float(row[0])
            histogram[price_bin] = {
                'volume': float(row[1] or 0),
                'aggressive_buy': float(row[2] or 0),
                'aggressive_sell': float(row[3] or 0),
                'trade_count': int(row[4] or 0)
            }
    
    return dict(histogram)


def sync_market_histogram(
    api: PolymarketAPI,
    token_id: str,
    market_id: str = None,
    date: datetime.date = None
) -> dict:
    """
    同步单个市场的 histogram
    
    Args:
        api: PolymarketAPI 实例
        token_id: 用于存储的 token ID
        market_id: 用于 API 查询的 condition ID（如果为 None，使用 token_id）
        date: 日期
    
    Returns:
        {'bins': n, 'volume': x, 'trades': y}
    """
    if date is None:
        date = datetime.now().date()
    
    # 用于 API 查询的 ID
    query_id = market_id if market_id else token_id
    
    # 获取当天的交易
    start_ts = int(datetime.combine(date, datetime.min.time()).timestamp() * 1000)
    end_ts = int(datetime.combine(date + timedelta(days=1), datetime.min.time()).timestamp() * 1000)
    
    # 获取交易数据（使用 condition_id / market_id）
    trades = api.get_trades_for_market(query_id, limit=5000)
    
    if not trades:
        return {'bins': 0, 'volume': 0, 'trades': 0}
    
    # 过滤当天交易
    day_trades = []
    for t in trades:
        ts = t.get('timestamp', 0)
        if isinstance(ts, str):
            ts = int(ts)
        # 自适应 ms/s
        if ts < 1e12:
            ts = ts * 1000
        if start_ts <= ts < end_ts:
            day_trades.append(t)
    
    if not day_trades:
        return {'bins': 0, 'volume': 0, 'trades': 0}
    
    # 聚合为 histogram
    histogram = aggregate_trades_to_histogram(day_trades)
    
    # 保存到数据库
    bins_saved = save_histogram(token_id, date, histogram)
    
    total_volume = sum(d['volume'] for d in histogram.values())
    
    return {
        'bins': bins_saved,
        'volume': total_volume,
        'trades': len(day_trades)
    }


def main():
    parser = argparse.ArgumentParser(description='Sync daily histogram data')
    parser.add_argument('--markets', type=int, default=100, help='Number of markets to sync')
    parser.add_argument('--date', type=str, help='Date to sync (YYYY-MM-DD), default today')
    parser.add_argument('--backfill', type=int, default=0, help='Backfill N days')
    args = parser.parse_args()
    
    print("=" * 60)
    print("📊 Daily Histogram Sync")
    print("=" * 60)
    
    # 迁移数据库
    migrate_schema()
    
    # 解析日期
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
    else:
        target_date = datetime.now().date()
    
    # 确定要同步的日期范围
    dates_to_sync = [target_date]
    if args.backfill > 0:
        for i in range(1, args.backfill + 1):
            dates_to_sync.append(target_date - timedelta(days=i))
    
    print(f"\nDates to sync: {len(dates_to_sync)}")
    print(f"Markets limit: {args.markets}")
    
    # 获取活跃市场
    markets = get_active_markets(args.markets)
    print(f"Active markets found: {len(markets)}")
    
    api = PolymarketAPI()
    
    # 统计
    total_bins = 0
    total_volume = 0
    total_trades = 0
    success_count = 0
    error_count = 0
    
    for date in dates_to_sync:
        print(f"\n📅 Syncing {date}")
        print("-" * 40)
        
        for i, market in enumerate(markets):
            token_id = market['token_id']
            market_id = market.get('market_id')  # condition_id for API
            title = market['title'][:40] if market['title'] else 'Unknown'
            
            try:
                result = sync_market_histogram(api, token_id, market_id, date)
                
                if result['bins'] > 0:
                    print(f"  [{i+1}/{len(markets)}] ✅ {title}...")
                    print(f"       Bins: {result['bins']}, Volume: ${result['volume']:.0f}, Trades: {result['trades']}")
                    total_bins += result['bins']
                    total_volume += result['volume']
                    total_trades += result['trades']
                    success_count += 1
                else:
                    print(f"  [{i+1}/{len(markets)}] ⏭️ {title}... (no trades)")
                    
            except Exception as e:
                print(f"  [{i+1}/{len(markets)}] ❌ {title}... Error: {e}")
                error_count += 1
    
    # 总结
    print("\n" + "=" * 60)
    print("📊 Summary")
    print("=" * 60)
    print(f"Dates synced: {len(dates_to_sync)}")
    print(f"Markets processed: {success_count + error_count}")
    print(f"Success: {success_count}")
    print(f"Errors: {error_count}")
    print(f"Total bins saved: {total_bins}")
    print(f"Total volume: ${total_volume:,.0f}")
    print(f"Total trades: {total_trades:,}")


if __name__ == "__main__":
    main()