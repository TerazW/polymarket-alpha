"""
Belief Reaction System - Collector
实时数据收集器：连接 Polymarket WebSocket，收集订单簿数据。

运行: python -m backend.collector.main

功能:
1. 获取热门市场的 token_ids
2. 连接 WebSocket
3. 接收 book / price_change / last_trade_price 消息
4. (未来) 写入数据库
"""

import json
import time
import threading
import httpx
from datetime import datetime
from websocket import WebSocketApp
from typing import List, Dict, Optional

# WebSocket URL
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


class Collector:
    """实时数据收集器"""

    def __init__(self, token_ids: List[str], verbose: bool = True):
        self.token_ids = token_ids
        self.verbose = verbose
        self.ws: Optional[WebSocketApp] = None
        self.is_running = False

        # 统计
        self.stats = {
            "connected_at": None,
            "books_received": 0,
            "price_changes_received": 0,
            "trades_received": 0,
            "errors": 0,
        }

    def log(self, msg: str, level: str = "INFO"):
        """打印日志"""
        if self.verbose:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] [{level}] {msg}")

    def on_open(self, ws):
        """连接成功"""
        self.stats["connected_at"] = datetime.now()
        self.is_running = True

        self.log(f"已连接到 Polymarket WebSocket")
        self.log(f"订阅 {len(self.token_ids)} 个 token...")

        # 发送订阅消息
        subscribe_msg = {
            "assets_ids": self.token_ids,
            "type": "market"
        }
        ws.send(json.dumps(subscribe_msg))

        # 启动心跳线程
        threading.Thread(target=self._ping_loop, args=(ws,), daemon=True).start()

        self.log("订阅成功，开始接收数据...")
        print()
        print("=" * 60)
        print("  实时数据流 (按 Ctrl+C 停止)")
        print("=" * 60)
        print()

    def on_message(self, ws, message: str):
        """收到消息"""
        if message == "PONG":
            return

        try:
            data = json.loads(message)
            event_type = data.get("event_type", "")

            if event_type == "book":
                self._handle_book(data)
            elif event_type == "price_change":
                self._handle_price_change(data)
            elif event_type == "last_trade_price":
                self._handle_trade(data)
            elif event_type == "tick_size_change":
                self._handle_tick_size_change(data)

        except json.JSONDecodeError:
            self.log(f"JSON 解析错误: {message[:50]}...", "ERROR")
            self.stats["errors"] += 1
        except Exception as e:
            self.log(f"处理消息错误: {e}", "ERROR")
            self.stats["errors"] += 1

    def _handle_book(self, data: dict):
        """处理 book 消息（完整订单簿快照）"""
        self.stats["books_received"] += 1
        asset_id = data.get("asset_id", "")[:8]
        bids = len(data.get("bids", []))
        asks = len(data.get("asks", []))
        self.log(f"📚 BOOK    | {asset_id}... | {bids} bids, {asks} asks")

    def _handle_price_change(self, data: dict):
        """处理 price_change 消息（增量更新）"""
        self.stats["price_changes_received"] += 1
        changes = data.get("price_changes", [])

        for c in changes[:1]:  # 只显示第一个变化
            asset_id = c.get("asset_id", "")[:8]
            price = c.get("price", "?")
            size = c.get("size", "?")
            side = c.get("side", "?")
            self.log(f"📊 CHANGE  | {asset_id}... | {side} @ {price} = {size}")

    def _handle_trade(self, data: dict):
        """处理 last_trade_price 消息（成交）"""
        self.stats["trades_received"] += 1
        asset_id = data.get("asset_id", "")[:8]
        price = data.get("price", "?")
        size = data.get("size", "?")
        side = data.get("side", "?")

        # 用颜色区分买卖
        arrow = "🟢" if side == "BUY" else "🔴"
        self.log(f"{arrow} TRADE   | {asset_id}... | {side} {size} @ {price}")

    def _handle_tick_size_change(self, data: dict):
        """处理 tick_size_change 消息"""
        asset_id = data.get("asset_id", "")[:8]
        old_tick = data.get("old_tick_size", "?")
        new_tick = data.get("new_tick_size", "?")
        self.log(f"⚙️ TICK    | {asset_id}... | {old_tick} → {new_tick}")

    def on_error(self, ws, error):
        """错误处理"""
        self.log(f"WebSocket 错误: {error}", "ERROR")
        self.stats["errors"] += 1

    def on_close(self, ws, close_status_code, close_msg):
        """连接关闭"""
        self.is_running = False
        self.log(f"连接关闭: {close_status_code} - {close_msg}")

    def _ping_loop(self, ws):
        """心跳循环"""
        while self.is_running:
            try:
                ws.send("PING")
            except:
                break
            time.sleep(10)

    def start(self):
        """启动收集器"""
        self.log("启动 Collector...")

        self.ws = WebSocketApp(
            WS_URL,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )

        self.ws.run_forever()

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            **self.stats,
            "uptime": str(datetime.now() - self.stats["connected_at"]) if self.stats["connected_at"] else None,
        }


def get_top_token_ids(limit: int = 10) -> List[str]:
    """获取热门市场的 token_ids"""
    print(f"正在获取前 {limit} 个热门市场...")

    try:
        response = httpx.get(
            "https://gamma-api.polymarket.com/markets",
            params={
                "closed": "false",
                "active": "true",
                "limit": limit,
                "order": "volume24hr",
                "ascending": "false"
            },
            timeout=10.0
        )

        if response.status_code != 200:
            print(f"API 错误: {response.status_code}")
            return []

        markets = response.json()
        token_ids = []

        for m in markets:
            tokens = m.get("clobTokenIds") or []
            question = m.get("question", "")[:40]
            if tokens:
                token_ids.extend(tokens)
                print(f"  ✓ {question}...")

        print(f"\n共获取 {len(token_ids)} 个 token_ids")
        return token_ids

    except Exception as e:
        print(f"获取市场失败: {e}")
        return []


def main():
    """主函数"""
    print()
    print("=" * 60)
    print("  Belief Reaction System - Collector")
    print("  实时数据收集器")
    print("=" * 60)
    print()

    # 获取热门市场的 token_ids
    token_ids = get_top_token_ids(limit=10)

    if not token_ids:
        print("没有获取到 token_ids，退出")
        return

    print()

    # 创建并启动 Collector
    collector = Collector(token_ids=token_ids, verbose=True)

    try:
        collector.start()
    except KeyboardInterrupt:
        print("\n\n用户中断")
        print("\n统计信息:")
        stats = collector.get_stats()
        print(f"  订单簿快照: {stats['books_received']}")
        print(f"  价格变化: {stats['price_changes_received']}")
        print(f"  成交: {stats['trades_received']}")
        print(f"  错误: {stats['errors']}")


if __name__ == "__main__":
    main()
