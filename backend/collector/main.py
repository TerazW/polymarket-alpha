"""
Belief Reaction System - Collector
实时数据收集器：连接 Polymarket WebSocket，收集订单簿数据并存入数据库。

运行: python run_collector.py

直接复用老项目的 PolymarketWebSocket（已验证运行良好）
"""

import sys
import os

# 添加项目根目录到 path，以便导入 utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime
from typing import Dict, Optional
import psycopg2
from psycopg2.extras import execute_values
from utils.polymarket_ws import PolymarketWebSocket
from utils.polymarket_api import PolymarketAPI


# 数据库配置
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'belief_reaction',
    'user': 'postgres',
    'password': 'postgres'
}

# 全局数据库连接
db_conn: Optional[psycopg2.extensions.connection] = None


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


def save_book_snapshot(book: Dict):
    """保存订单簿快照到数据库"""
    try:
        conn = get_db_connection()
        ts = datetime.now()
        token_id = book.get('asset_id')

        rows = []

        # 处理 bids
        for bid in book.get('bids', []):
            price = float(bid.get('price', 0))
            size = float(bid.get('size', 0))
            if size > 0:
                rows.append((ts, token_id, 'bid', price, size))

        # 处理 asks
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


# 计数器
trade_count = 0
book_count = 0


def on_trade(trade: Dict):
    """处理成交消息"""
    global trade_count
    trade_count += 1

    # 保存到数据库
    save_trade(trade)

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
    global book_count
    book_count += 1

    # 保存到数据库（每 5 次保存一次，避免写入太频繁）
    if book_count % 5 == 0:
        save_book_snapshot(book)

    # 打印（每 20 条显示一次）
    if book_count % 20 == 0 or book_count <= 3:
        ts = datetime.now().strftime("%H:%M:%S")
        asset_id = book.get('asset_id', '')[:8]
        bids = len(book.get('bids', []))
        asks = len(book.get('asks', []))
        print(f"[{ts}] 📚 BOOK #{book_count} | {asset_id}... | {bids} bids, {asks} asks")


def get_top_markets(limit: int = 10):
    """获取热门市场"""
    print(f"正在获取前 {limit} 个热门市场...")

    api = PolymarketAPI()
    markets = api.get_all_markets_from_events(min_volume_24h=1000, max_events=20)

    # 按交易量排序，取前 limit 个
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
    print("  实时数据收集器（数据存入 TimescaleDB）")
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
    print("  数据正在写入 TimescaleDB...")
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
        print(f"  错误: {ws.stats['errors']}")
    finally:
        if db_conn:
            db_conn.close()


if __name__ == "__main__":
    main()
