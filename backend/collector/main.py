"""
Belief Reaction System - Collector
实时数据收集器：连接 Polymarket WebSocket，收集订单簿数据。

运行: python run_collector.py

直接复用老项目的 PolymarketWebSocket（已验证运行良好）
"""

import sys
import os

# 添加项目根目录到 path，以便导入 utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime
from typing import Dict
from utils.polymarket_ws import PolymarketWebSocket
from utils.polymarket_api import PolymarketAPI


def on_trade(trade: Dict):
    """处理成交消息"""
    ts = datetime.now().strftime("%H:%M:%S")
    asset_id = trade.get('asset_id', '')[:8]
    price = trade.get('price', 0)
    size = trade.get('size', 0)
    side = trade.get('side', '?')

    # 用颜色区分买卖
    arrow = "🟢" if side == "BUY" else "🔴"
    print(f"[{ts}] {arrow} TRADE | {asset_id}... | {side} {size:.1f} @ {price:.2f}")


def on_book(book: Dict):
    """处理订单簿快照"""
    ts = datetime.now().strftime("%H:%M:%S")
    asset_id = book.get('asset_id', '')[:8]
    bids = len(book.get('bids', []))
    asks = len(book.get('asks', []))
    print(f"[{ts}] 📚 BOOK  | {asset_id}... | {bids} bids, {asks} asks")


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
        token_id = m.get('token_id')  # 老项目用的是 token_id
        if token_id:
            token_ids.append(token_id)
            print(f"  ✓ {question}... (${volume:,.0f})")

    return token_ids


def main():
    """主函数"""
    print()
    print("=" * 60)
    print("  Belief Reaction System - Collector")
    print("  实时数据收集器（复用老项目 WebSocket）")
    print("=" * 60)
    print()

    # 获取热门市场
    token_ids = get_top_markets(limit=10)

    if not token_ids:
        print("没有获取到市场，退出")
        return

    print()
    print("=" * 60)
    print("  实时数据流 (按 Ctrl+C 停止)")
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
        print(f"  成交消息: {ws.stats['trades_received']}")
        print(f"  订单簿: {ws.stats['books_received']}")
        print(f"  错误: {ws.stats['errors']}")


if __name__ == "__main__":
    main()
