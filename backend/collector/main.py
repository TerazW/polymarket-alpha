"""
Belief Reaction System - Collector
实时数据收集器：连接 Polymarket WebSocket，收集订单簿数据并存入数据库。
集成 ShockDetector 实时检测价格冲击事件。

运行: python run_collector.py
"""

import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional
from collections import defaultdict
import psycopg2
from psycopg2.extras import execute_values
from utils.polymarket_ws import PolymarketWebSocket
from utils.polymarket_api import PolymarketAPI

# 导入 POC 模块
from poc.models import TradeEvent, PriceLevel, ShockEvent, ReactionEvent
from poc.shock_detector import ShockDetector
from poc.reaction_classifier import ReactionClassifier


# 数据库配置
DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 5433,
    'database': 'belief_reaction',
    'user': 'postgres',
    'password': 'postgres'
}

# 全局数据库连接
db_conn: Optional[psycopg2.extensions.connection] = None

# ShockDetector 和 ReactionClassifier 实例
shock_detector = ShockDetector()
reaction_classifier = ReactionClassifier()

# 价格层级缓存 {(token_id, price_str, side): PriceLevel}
price_levels: Dict[tuple, PriceLevel] = {}

# 最佳买卖价格缓存 {token_id: (best_bid, best_ask)}
best_prices: Dict[str, tuple] = {}


def get_db_connection():
    """获取数据库连接"""
    global db_conn
    if db_conn is None or db_conn.closed:
        db_conn = psycopg2.connect(**DB_CONFIG)
        db_conn.autocommit = True
    return db_conn


def save_trade(trade: Dict):
    """保存成交记录到数据库"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO trade_ticks (ts, token_id, price, size, side)
                VALUES (to_timestamp(%s / 1000.0), %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (
                trade.get('timestamp', int(datetime.now().timestamp() * 1000)),
                trade.get('asset_id'),
                trade.get('price'),
                trade.get('size'),
                trade.get('side')
            ))
    except Exception as e:
        print(f"[DB ERROR] 保存成交失败: {e}")


def save_shock_event(shock: ShockEvent):
    """保存 Shock 事件到数据库"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO shock_events (shock_id, ts, token_id, price, side, trade_volume, liquidity_before, trigger_type)
                VALUES (%s, to_timestamp(%s / 1000.0), %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (
                shock.shock_id,
                shock.ts_start,
                shock.token_id,
                float(shock.price),
                shock.side,
                shock.trade_volume,
                shock.liquidity_before,
                shock.trigger_type
            ))
    except Exception as e:
        print(f"[DB ERROR] 保存 Shock 失败: {e}")


def save_reaction_event(reaction: ReactionEvent):
    """保存 Reaction 事件到数据库"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO reaction_events (
                    reaction_id, shock_id, ts, token_id, price, side,
                    reaction_type, refill_ratio, time_to_refill_ms,
                    min_liquidity, price_shift, liquidity_before
                )
                VALUES (%s, %s, to_timestamp(%s / 1000.0), %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (
                reaction.reaction_id,
                reaction.shock_id,
                reaction.timestamp,
                reaction.token_id,
                float(reaction.price),
                reaction.side,
                reaction.reaction_type.value,
                reaction.refill_ratio,
                reaction.time_to_refill_ms,
                reaction.min_liquidity,
                float(reaction.price_shift),
                reaction.liquidity_before
            ))
    except Exception as e:
        print(f"[DB ERROR] 保存 Reaction 失败: {e}")


def save_book_snapshot(book: Dict):
    """保存订单簿快照到数据库"""
    try:
        conn = get_db_connection()
        ts = datetime.now()
        token_id = book.get('asset_id')

        rows = []

        for bid in book.get('bids', []):
            price = float(bid.get('price', 0))
            size = float(bid.get('size', 0))
            if size > 0:
                rows.append((ts, token_id, 'bid', price, size))

        for ask in book.get('asks', []):
            price = float(ask.get('price', 0))
            size = float(ask.get('size', 0))
            if size > 0:
                rows.append((ts, token_id, 'ask', price, size))

        if rows:
            with conn.cursor() as cur:
                execute_values(cur, """
                    INSERT INTO book_bins (ts, token_id, side, price, size)
                    VALUES %s
                    ON CONFLICT DO NOTHING
                """, rows)

    except Exception as e:
        print(f"[DB ERROR] 保存订单簿失败: {e}")


def update_price_levels(book: Dict):
    """从订单簿更新价格层级缓存"""
    token_id = book.get('asset_id')
    now = int(datetime.now().timestamp() * 1000)

    for bid in book.get('bids', []):
        price = Decimal(str(bid.get('price', 0)))
        size = float(bid.get('size', 0))
        key = (token_id, str(price), 'bid')

        if key not in price_levels:
            price_levels[key] = PriceLevel(token_id=token_id, price=price, side='bid')
        price_levels[key].update_size(size, now)

    for ask in book.get('asks', []):
        price = Decimal(str(ask.get('price', 0)))
        size = float(ask.get('size', 0))
        key = (token_id, str(price), 'ask')

        if key not in price_levels:
            price_levels[key] = PriceLevel(token_id=token_id, price=price, side='ask')
        price_levels[key].update_size(size, now)


def get_price_level(token_id: str, price: Decimal, side: str) -> Optional[PriceLevel]:
    """获取价格层级"""
    key = (token_id, str(price), side)
    return price_levels.get(key)


# 计数器
trade_count = 0
book_count = 0
shock_count = 0
reaction_count = 0


def on_trade(trade: Dict):
    """处理成交消息"""
    global trade_count, shock_count
    trade_count += 1

    # 保存到数据库
    save_trade(trade)

    # 转换为 TradeEvent
    trade_event = TradeEvent(
        token_id=trade.get('asset_id', ''),
        price=Decimal(str(trade.get('price', 0))),
        size=float(trade.get('size', 0)),
        side=trade.get('side', 'BUY').upper(),
        timestamp=int(trade.get('timestamp', 0))
    )

    # 获取对应的价格层级
    level_side = 'bid' if trade_event.side == 'SELL' else 'ask'
    level = get_price_level(trade_event.token_id, trade_event.price, level_side)

    # 检测 Shock
    shock = shock_detector.on_trade(trade_event, level)

    if shock:
        shock_count += 1
        save_shock_event(shock)
        # 启动反应观察
        reaction_classifier.start_observation(shock)
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] ⚡ SHOCK #{shock_count} | {shock.token_id[:8]}... | "
              f"price={shock.price} side={shock.side} vol={shock.trade_volume:.1f} "
              f"trigger={shock.trigger_type}")

    # 打印（每 10 条显示一次）
    if trade_count % 10 == 0 or trade_count <= 5:
        ts = datetime.now().strftime("%H:%M:%S")
        asset_id = trade.get('asset_id', '')[:8]
        price = trade.get('price', 0)
        size = trade.get('size', 0)
        side = trade.get('side', '?')
        arrow = "🟢" if side == "BUY" else "🔴"
        print(f"[{ts}] {arrow} TRADE #{trade_count} | {asset_id}... | {side} {size:.1f} @ {price:.2f}")


def on_book(book: Dict):
    """处理订单簿快照"""
    global book_count, reaction_count
    book_count += 1

    token_id = book.get('asset_id', '')
    now = int(datetime.now().timestamp() * 1000)

    # 更新价格层级缓存
    update_price_levels(book)

    # 提取最佳买卖价
    bids = book.get('bids', [])
    asks = book.get('asks', [])
    best_bid = Decimal(str(bids[0].get('price', 0))) if bids else None
    best_ask = Decimal(str(asks[0].get('price', 0))) if asks else None
    best_prices[token_id] = (best_bid, best_ask)

    # 为活跃观察记录样本
    for bid in bids:
        price = Decimal(str(bid.get('price', 0)))
        size = float(bid.get('size', 0))
        if reaction_classifier.has_active_observation(token_id, price):
            reaction_classifier.record_sample(token_id, price, now, size, best_bid, best_ask)

    for ask in asks:
        price = Decimal(str(ask.get('price', 0)))
        size = float(ask.get('size', 0))
        if reaction_classifier.has_active_observation(token_id, price):
            reaction_classifier.record_sample(token_id, price, now, size, best_bid, best_ask)

    # 检查过期的反应窗口并分类
    expired_shocks = shock_detector.get_expired_shocks(now)
    for shock in expired_shocks:
        reaction = reaction_classifier.classify(shock)
        if reaction:
            reaction_count += 1
            save_reaction_event(reaction)
            ts_str = datetime.now().strftime("%H:%M:%S")
            # 反应类型颜色
            type_colors = {
                'HOLD': '🟢', 'DELAY': '🟡', 'PULL': '🟠',
                'VACUUM': '🔴', 'CHASE': '🔵', 'FAKE': '💜'
            }
            emoji = type_colors.get(reaction.reaction_type.value, '⚪')
            print(f"[{ts_str}] {emoji} REACTION #{reaction_count} | {reaction.token_id[:8]}... | "
                  f"{reaction.reaction_type.value} refill={reaction.refill_ratio:.1%}")
        # 清理已处理的 shock
        shock_detector.complete_shock(shock.token_id, shock.price)

    # 保存到数据库（每 5 次保存一次）
    if book_count % 5 == 0:
        save_book_snapshot(book)

    # 打印（每 20 条显示一次）
    if book_count % 20 == 0 or book_count <= 3:
        ts = datetime.now().strftime("%H:%M:%S")
        asset_id = token_id[:8]
        print(f"[{ts}] 📚 BOOK #{book_count} | {asset_id}... | {len(bids)} bids, {len(asks)} asks")


def get_top_markets(limit: int = 10):
    """获取热门市场"""
    print(f"正在获取前 {limit} 个热门市场...")

    api = PolymarketAPI()
    markets = api.get_all_markets_from_events(min_volume_24h=1000, max_events=20)

    markets_sorted = sorted(markets, key=lambda x: x.get('volume_24h', 0) or 0, reverse=True)
    top_markets = markets_sorted[:limit]

    print(f"\n选取了 {len(top_markets)} 个活跃市场:")
    token_ids = []
    for m in top_markets:
        question = m.get('question', '')[:40]
        volume = m.get('volume_24h', 0) or 0
        token_id = m.get('token_id')
        if token_id:
            token_ids.append(token_id)
            print(f"  ✓ {question}... (${volume:,.0f})")

    return token_ids


def main():
    """主函数"""
    print()
    print("=" * 60)
    print("  Belief Reaction System - Collector")
    print("  实时数据收集 + Shock 检测")
    print("=" * 60)
    print()

    # 测试数据库连接
    try:
        conn = get_db_connection()
        print("✅ 数据库连接成功")
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        print("   请确保 Docker 容器正在运行: docker-compose up -d")
        return

    # 获取热门市场
    token_ids = get_top_markets(limit=10)

    if not token_ids:
        print("没有获取到市场，退出")
        return

    print()
    print("=" * 60)
    print("  实时数据流 (按 Ctrl+C 停止)")
    print("  ⚡ Shock 检测 + 反应分类已启用")
    print("=" * 60)
    print()

    # 使用老项目的 WebSocket 客户端
    ws = PolymarketWebSocket(
        asset_ids=token_ids,
        on_trade=on_trade,
        on_book=on_book,
        verbose=True
    )

    try:
        ws.run()
    except KeyboardInterrupt:
        print("\n\n用户中断")
        print("\n统计信息:")
        print(f"  成交消息: {ws.stats['trades_received']} (已存入 DB: {trade_count})")
        print(f"  订单簿: {ws.stats['books_received']} (已存入 DB: {book_count // 5})")
        print(f"  ⚡ Shock 事件: {shock_count}")
        print(f"  🎯 Reaction 事件: {reaction_count}")
        print(f"  错误: {ws.stats['errors']}")

        # 显示 ShockDetector 统计
        detector_stats = shock_detector.get_stats()
        print(f"\nShockDetector 统计:")
        print(f"  总检测数: {detector_stats['total_shocks']}")
        print(f"  活跃 Shock: {detector_stats['active_shocks']}")
        print(f"  追踪层级: {detector_stats['tracked_levels']}")

        # 显示 ReactionClassifier 统计
        classifier_stats = reaction_classifier.get_stats()
        print(f"\nReactionClassifier 统计:")
        print(f"  总分类数: {classifier_stats['total_classified']}")
        print(f"  活跃观察: {classifier_stats['active_observations']}")
        if classifier_stats['by_type']:
            print(f"  按类型:")
            for rtype, count in classifier_stats['by_type'].items():
                type_colors = {
                    'HOLD': '🟢', 'DELAY': '🟡', 'PULL': '🟠',
                    'VACUUM': '🔴', 'CHASE': '🔵', 'FAKE': '💜'
                }
                emoji = type_colors.get(rtype, '⚪')
                print(f"    {emoji} {rtype}: {count}")
    finally:
        if db_conn:
            db_conn.close()


if __name__ == "__main__":
    main()
