"""
Polymarket WebSocket 客户端
用于收集实时 trades 数据（带 aggressor 方向）

WebSocket Market Channel 提供 `last_trade_price` 消息：
{
    "asset_id": "...",
    "event_type": "last_trade_price",
    "market": "0x...",
    "price": "0.456",
    "side": "BUY",      ← aggressor 方向！
    "size": "219.217767",
    "timestamp": "1750428146322"
}

side = "BUY" → taker 主动买入
side = "SELL" → taker 主动卖出
"""

import json
import time
import threading
from datetime import datetime
from typing import Dict, List, Callable, Optional
from collections import defaultdict
from websocket import WebSocketApp

# WebSocket URL
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


class PolymarketWebSocket:
    """
    Polymarket WebSocket 客户端
    
    功能：
    1. 订阅多个市场的实时成交
    2. 收集 last_trade_price 消息（带 aggressor side）
    3. 支持回调函数处理数据
    4. 自动重连 + ping 保活
    """
    
    def __init__(
        self,
        asset_ids: List[str],
        on_trade: Optional[Callable[[Dict], None]] = None,
        on_book: Optional[Callable[[Dict], None]] = None,
        verbose: bool = True
    ):
        """
        初始化 WebSocket 客户端
        
        Args:
            asset_ids: 要订阅的 token IDs 列表
            on_trade: 收到 trade 时的回调函数
            on_book: 收到 orderbook 时的回调函数
            verbose: 是否打印日志
        """
        self.asset_ids = asset_ids
        self.on_trade_callback = on_trade
        self.on_book_callback = on_book
        self.verbose = verbose
        
        self.ws: Optional[WebSocketApp] = None
        self.is_running = False
        self.ping_thread: Optional[threading.Thread] = None
        
        # 数据存储
        self.trades: List[Dict] = []
        self.trades_lock = threading.Lock()
        
        # 统计
        self.stats = {
            'connected_at': None,
            'trades_received': 0,
            'books_received': 0,
            'errors': 0,
            'reconnects': 0
        }
    
    def _log(self, message: str):
        """打印日志"""
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {message}")
    
    def on_open(self, ws):
        """连接建立时"""
        self.stats['connected_at'] = datetime.now()
        self._log(f"✅ Connected to Polymarket WebSocket")
        self._log(f"   Subscribing to {len(self.asset_ids)} assets...")
        
        # 订阅 market channel
        subscribe_msg = {
            "assets_ids": self.asset_ids,
            "type": "market"
        }
        ws.send(json.dumps(subscribe_msg))
        
        # 启动 ping 线程
        self.is_running = True
        self.ping_thread = threading.Thread(target=self._ping_loop, args=(ws,), daemon=True)
        self.ping_thread.start()
    
    def on_message(self, ws, message: str):
        """收到消息时"""
        try:
            # 忽略 PONG 响应
            if message == "PONG":
                return
            
            data = json.loads(message)
            event_type = data.get("event_type", "")
            
            # last_trade_price - 成交消息（带 aggressor！）
            if event_type == "last_trade_price":
                self._handle_trade(data)
            
            # book - 订单簿快照
            elif event_type == "book":
                self._handle_book(data)
            
            # price_change - 价格变动
            elif event_type == "price_change":
                pass  # 暂不处理
            
            # tick_size_change
            elif event_type == "tick_size_change":
                pass  # 暂不处理
                
        except json.JSONDecodeError:
            self._log(f"⚠️ Invalid JSON: {message[:100]}")
        except Exception as e:
            self._log(f"❌ Error processing message: {e}")
            self.stats['errors'] += 1
    
    def _handle_trade(self, data: Dict):
        """
        处理 last_trade_price 消息
        
        关键字段：
        - asset_id: token ID
        - market: condition ID
        - price: 成交价格
        - size: 成交量
        - side: "BUY" 或 "SELL" ← 这是 TAKER 方向！
        - timestamp: 毫秒时间戳
        """
        trade = {
            'asset_id': data.get('asset_id'),
            'market': data.get('market'),
            'price': float(data.get('price', 0)),
            'size': float(data.get('size', 0)),
            'side': data.get('side'),  # BUY = taker 买, SELL = taker 卖
            'timestamp': int(data.get('timestamp', 0)),  # 毫秒
            'fee_rate_bps': data.get('fee_rate_bps', '0'),
            'received_at': datetime.now().isoformat()
        }
        
        # 存储
        with self.trades_lock:
            self.trades.append(trade)
        
        self.stats['trades_received'] += 1
        
        # 回调
        if self.on_trade_callback:
            self.on_trade_callback(trade)
        
        if self.verbose and self.stats['trades_received'] % 100 == 0:
            self._log(f"📊 Trades received: {self.stats['trades_received']}")
    
    def _handle_book(self, data: Dict):
        """处理 book 消息"""
        self.stats['books_received'] += 1
        
        if self.on_book_callback:
            self.on_book_callback(data)
    
    def on_error(self, ws, error):
        """错误处理"""
        self._log(f"❌ WebSocket error: {error}")
        self.stats['errors'] += 1
    
    def on_close(self, ws, close_status_code, close_msg):
        """连接关闭"""
        self._log(f"🔌 WebSocket closed: {close_status_code} - {close_msg}")
        self.is_running = False
    
    def _ping_loop(self, ws):
        """定期发送 ping 保持连接"""
        while self.is_running:
            try:
                ws.send("PING")
                time.sleep(10)
            except Exception as e:
                self._log(f"⚠️ Ping failed: {e}")
                break
    
    def subscribe(self, asset_ids: List[str]):
        """动态订阅更多 assets"""
        if self.ws:
            msg = {
                "assets_ids": asset_ids,
                "operation": "subscribe"
            }
            self.ws.send(json.dumps(msg))
            self.asset_ids.extend(asset_ids)
            self._log(f"📡 Subscribed to {len(asset_ids)} more assets")
    
    def unsubscribe(self, asset_ids: List[str]):
        """取消订阅"""
        if self.ws:
            msg = {
                "assets_ids": asset_ids,
                "operation": "unsubscribe"
            }
            self.ws.send(json.dumps(msg))
            self._log(f"📴 Unsubscribed from {len(asset_ids)} assets")
    
    def get_trades(self, clear: bool = False) -> List[Dict]:
        """
        获取收集到的 trades
        
        Args:
            clear: 是否清空缓存
        
        Returns:
            trades 列表
        """
        with self.trades_lock:
            trades = list(self.trades)
            if clear:
                self.trades = []
        return trades
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            **self.stats,
            'trades_in_buffer': len(self.trades),
            'assets_subscribed': len(self.asset_ids)
        }
    
    def run(self, reconnect: bool = True):
        """
        启动 WebSocket（阻塞）
        
        Args:
            reconnect: 断线后是否自动重连
        """
        while True:
            try:
                self._log(f"🔗 Connecting to {WS_URL}...")
                
                self.ws = WebSocketApp(
                    WS_URL,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close
                )
                
                self.ws.run_forever()
                
                if not reconnect:
                    break
                
                self.stats['reconnects'] += 1
                self._log(f"🔄 Reconnecting in 5 seconds... (attempt {self.stats['reconnects']})")
                time.sleep(5)
                
            except KeyboardInterrupt:
                self._log("👋 Stopped by user")
                break
            except Exception as e:
                self._log(f"❌ Fatal error: {e}")
                if not reconnect:
                    break
                time.sleep(5)
    
    def run_async(self) -> threading.Thread:
        """
        在后台线程中启动 WebSocket（非阻塞）
        
        Returns:
            后台线程对象
        """
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        return thread
    
    def stop(self):
        """停止 WebSocket"""
        self.is_running = False
        if self.ws:
            self.ws.close()


class TradeAggregator:
    """
    Trades 聚合器
    
    功能：
    - 按 market/token 聚合 trades
    - 计算 aggressive buy/sell volume
    - 计算 AR, Volume Delta
    """
    
    def __init__(self):
        # {asset_id: [trades]}
        self.trades_by_asset: Dict[str, List[Dict]] = defaultdict(list)
        self.lock = threading.Lock()
    
    def add_trade(self, trade: Dict):
        """添加一笔 trade"""
        asset_id = trade.get('asset_id')
        if asset_id:
            with self.lock:
                self.trades_by_asset[asset_id].append(trade)
    
    def get_aggressor_stats(
        self, 
        asset_id: str, 
        since_ms: Optional[int] = None
    ) -> Dict:
        """
        获取某个 asset 的 aggressor 统计
        
        Args:
            asset_id: token ID
            since_ms: 只统计这个时间戳之后的 trades（毫秒）
        
        Returns:
            {
                'aggressive_buy_volume': float,
                'aggressive_sell_volume': float,
                'total_volume': float,
                'volume_delta': float,
                'ar': float,
                'trade_count': int
            }
        """
        with self.lock:
            trades = self.trades_by_asset.get(asset_id, [])
        
        # 时间过滤
        if since_ms:
            trades = [t for t in trades if t.get('timestamp', 0) >= since_ms]
        
        if not trades:
            return {
                'aggressive_buy_volume': 0,
                'aggressive_sell_volume': 0,
                'total_volume': 0,
                'volume_delta': 0,
                'ar': None,
                'trade_count': 0
            }
        
        agg_buy = 0.0
        agg_sell = 0.0
        
        for trade in trades:
            size = trade.get('size', 0)
            side = trade.get('side', '')
            
            if side == 'BUY':
                agg_buy += size
            elif side == 'SELL':
                agg_sell += size
        
        total = agg_buy + agg_sell
        delta = agg_buy - agg_sell
        
        # AR = aggressive_volume / total_volume
        # 在预测市场，所有 trades 都是 taker 触发的，所以 AR 实际上是 |delta| / total 的概念
        # 但按照原定义，AR 应该接近 1（因为所有 volume 都来自 taker）
        ar = 1.0 if total > 0 else None
        
        return {
            'aggressive_buy_volume': agg_buy,
            'aggressive_sell_volume': agg_sell,
            'total_volume': total,
            'volume_delta': delta,
            'ar': ar,
            'trade_count': len(trades)
        }
    
    def clear(self, asset_id: Optional[str] = None):
        """清空数据"""
        with self.lock:
            if asset_id:
                self.trades_by_asset[asset_id] = []
            else:
                self.trades_by_asset.clear()


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    print("🧪 Testing Polymarket WebSocket\n")
    print("=" * 60)
    
    # 示例 asset ID（你需要替换成真实的 token ID）
    # 可以从你的数据库或 API 获取
    test_asset_ids = [
        # 添加一些活跃市场的 token IDs
        "21742633143463906290569050155826241533067272736897614950488156847949938836455",
    ]
    
    # 创建聚合器
    aggregator = TradeAggregator()
    
    def on_trade(trade: Dict):
        """收到 trade 时的回调"""
        aggregator.add_trade(trade)
        print(f"  💰 Trade: {trade['side']} {trade['size']:.2f} @ {trade['price']:.4f}")
    
    # 创建 WebSocket 客户端
    ws = PolymarketWebSocket(
        asset_ids=test_asset_ids,
        on_trade=on_trade,
        verbose=True
    )
    
    print(f"\n📡 Subscribing to {len(test_asset_ids)} assets...")
    print("Press Ctrl+C to stop\n")
    
    try:
        # 运行 30 秒测试
        thread = ws.run_async()
        time.sleep(30)
        
        # 打印统计
        print("\n" + "=" * 60)
        print("📊 Statistics:")
        stats = ws.get_stats()
        for k, v in stats.items():
            print(f"  {k}: {v}")
        
        # 打印聚合数据
        for asset_id in test_asset_ids:
            agg_stats = aggregator.get_aggressor_stats(asset_id)
            print(f"\n📈 Asset {asset_id[:20]}...:")
            print(f"  Aggressive Buy:  {agg_stats['aggressive_buy_volume']:.2f}")
            print(f"  Aggressive Sell: {agg_stats['aggressive_sell_volume']:.2f}")
            print(f"  Volume Delta:    {agg_stats['volume_delta']:.2f}")
            print(f"  Trade Count:     {agg_stats['trade_count']}")
        
    except KeyboardInterrupt:
        print("\n👋 Stopped")
    finally:
        ws.stop()