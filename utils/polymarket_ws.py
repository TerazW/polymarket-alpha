"""
Polymarket WebSocket 客户端 (v2 - 优化版)
用于收集实时 trades 数据（带 aggressor 方向）

优化点：
1. TradeAggregator 改成增量计数器（不存 list）
2. 支持按小时桶聚合
3. O(1) 查询统计

WebSocket Market Channel 的 `last_trade_price` 消息：
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
from typing import Dict, List, Callable, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass, field
from websocket import WebSocketApp

# WebSocket URL
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


@dataclass
class AggressorStats:
    """单个 asset 的 aggressor 统计（增量计数器）"""
    aggressive_buy: float = 0.0
    aggressive_sell: float = 0.0
    trade_count: int = 0
    last_trade_ts: int = 0  # 最后一笔 trade 的时间戳（毫秒）
    
    @property
    def total_volume(self) -> float:
        return self.aggressive_buy + self.aggressive_sell
    
    @property
    def volume_delta(self) -> float:
        return self.aggressive_buy - self.aggressive_sell
    
    @property
    def directional_ar(self) -> Optional[float]:
        """
        Directional AR = |delta| / total_volume
        
        意义：
        - 0 = 买卖对冲，方向不明
        - 1 = 完全单边，强方向性
        """
        if self.total_volume <= 0:
            return None
        return abs(self.volume_delta) / self.total_volume
    
    def add_trade(self, side: str, size: float, timestamp: int):
        """添加一笔 trade（增量更新）"""
        if side == 'BUY':
            self.aggressive_buy += size
        elif side == 'SELL':
            self.aggressive_sell += size
        
        self.trade_count += 1
        self.last_trade_ts = max(self.last_trade_ts, timestamp)
    
    def reset(self):
        """重置计数器"""
        self.aggressive_buy = 0.0
        self.aggressive_sell = 0.0
        self.trade_count = 0
        self.last_trade_ts = 0
    
    def to_dict(self) -> Dict:
        return {
            'aggressive_buy': self.aggressive_buy,
            'aggressive_sell': self.aggressive_sell,
            'total_volume': self.total_volume,
            'volume_delta': self.volume_delta,
            'directional_ar': self.directional_ar,
            'trade_count': self.trade_count,
            'last_trade_ts': self.last_trade_ts
        }


class TradeAggregator:
    """
    Trades 聚合器 (v2 - 增量计数器版)
    
    优化：
    - 不存储逐笔 trade list
    - 直接累加计数器
    - O(1) 查询
    - 支持按 (asset_id, hour) 聚合
    """
    
    def __init__(self):
        # {asset_id: AggressorStats}
        self.stats_by_asset: Dict[str, AggressorStats] = defaultdict(AggressorStats)
        
        # {(asset_id, hour_str): AggressorStats} - 按小时桶
        self.stats_by_hour: Dict[Tuple[str, str], AggressorStats] = defaultdict(AggressorStats)
        
        self.lock = threading.Lock()
        
        # 追踪上次 flush 时间
        self.last_flush_ts: int = int(datetime.now().timestamp() * 1000)
    
    def add_trade(self, trade: Dict):
        """
        添加一笔 trade（O(1) 操作）
        
        Args:
            trade: {asset_id, side, size, timestamp, ...}
        """
        asset_id = trade.get('asset_id')
        side = trade.get('side', '')
        size = float(trade.get('size', 0))
        timestamp = int(trade.get('timestamp', 0))
        
        if not asset_id or not side or size <= 0:
            return
        
        # 计算小时桶
        hour_str = self._get_hour_str(timestamp)
        
        with self.lock:
            # 更新 asset 级别统计
            self.stats_by_asset[asset_id].add_trade(side, size, timestamp)
            
            # 更新小时桶统计
            key = (asset_id, hour_str)
            self.stats_by_hour[key].add_trade(side, size, timestamp)
    
    def _get_hour_str(self, timestamp_ms: int) -> str:
        """将毫秒时间戳转换为小时字符串 (YYYY-MM-DD HH:00:00)"""
        dt = datetime.fromtimestamp(timestamp_ms / 1000)
        return dt.strftime("%Y-%m-%d %H:00:00")
    
    def get_stats(self, asset_id: str) -> Dict:
        """
        获取某个 asset 的统计（O(1)）
        
        Returns:
            统计字典
        """
        with self.lock:
            stats = self.stats_by_asset.get(asset_id)
            if stats:
                return stats.to_dict()
        
        return AggressorStats().to_dict()
    
    def get_hourly_stats(self, asset_id: str, hour_str: str) -> Dict:
        """获取某个 asset 某小时的统计"""
        with self.lock:
            key = (asset_id, hour_str)
            stats = self.stats_by_hour.get(key)
            if stats:
                return stats.to_dict()
        
        return AggressorStats().to_dict()
    
    def get_all_hourly_stats(self) -> Dict[Tuple[str, str], Dict]:
        """
        获取所有小时桶的统计（用于 flush）
        
        Returns:
            {(asset_id, hour_str): stats_dict}
        """
        with self.lock:
            return {
                key: stats.to_dict() 
                for key, stats in self.stats_by_hour.items()
                if stats.trade_count > 0
            }
    
    def get_stats_since_last_flush(self) -> Dict[str, Dict]:
        """
        获取自上次 flush 以来的统计
        
        注意：这里返回的是 asset 级别的累积统计
        flush 后应该调用 clear_and_update_flush_time()
        """
        with self.lock:
            return {
                asset_id: stats.to_dict()
                for asset_id, stats in self.stats_by_asset.items()
                if stats.trade_count > 0
            }
    
    def clear_and_update_flush_time(self):
        """清空统计并更新 flush 时间"""
        with self.lock:
            # 记录最新的 trade 时间作为下次 flush 的起点
            max_ts = self.last_flush_ts
            for stats in self.stats_by_asset.values():
                if stats.last_trade_ts > max_ts:
                    max_ts = stats.last_trade_ts
            
            self.last_flush_ts = max_ts if max_ts > self.last_flush_ts else int(datetime.now().timestamp() * 1000)
            
            # 清空
            self.stats_by_asset.clear()
            self.stats_by_hour.clear()
    
    def clear_asset(self, asset_id: str):
        """清空单个 asset 的统计"""
        with self.lock:
            if asset_id in self.stats_by_asset:
                self.stats_by_asset[asset_id].reset()
            
            # 清空相关的小时桶
            keys_to_remove = [k for k in self.stats_by_hour if k[0] == asset_id]
            for k in keys_to_remove:
                del self.stats_by_hour[k]
    
    def get_summary(self) -> Dict:
        """获取汇总信息"""
        with self.lock:
            total_trades = sum(s.trade_count for s in self.stats_by_asset.values())
            total_volume = sum(s.total_volume for s in self.stats_by_asset.values())
            
            return {
                'assets_count': len(self.stats_by_asset),
                'hourly_buckets': len(self.stats_by_hour),
                'total_trades': total_trades,
                'total_volume': total_volume,
                'last_flush_ts': self.last_flush_ts
            }


class PolymarketWebSocket:
    """
    Polymarket WebSocket 客户端
    
    功能：
    1. 订阅多个市场的实时成交
    2. 收集 last_trade_price 消息（带 aggressor side）
    3. 使用增量计数器聚合
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
        self.asset_ids = list(asset_ids)
        self.on_trade_callback = on_trade
        self.on_book_callback = on_book
        self.verbose = verbose
        
        self.ws: Optional[WebSocketApp] = None
        self.is_running = False
        self.ping_thread: Optional[threading.Thread] = None
        
        # 使用增量计数器聚合器
        self.aggregator = TradeAggregator()
        
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
            
        except json.JSONDecodeError:
            self._log(f"⚠️ Invalid JSON: {message[:100]}")
        except Exception as e:
            self._log(f"❌ Error processing message: {e}")
            self.stats['errors'] += 1
    
    def _handle_trade(self, data: Dict):
        """处理 last_trade_price 消息"""
        trade = {
            'asset_id': data.get('asset_id'),
            'market': data.get('market'),
            'price': float(data.get('price', 0)),
            'size': float(data.get('size', 0)),
            'side': data.get('side'),
            'timestamp': int(data.get('timestamp', 0)),
            'fee_rate_bps': data.get('fee_rate_bps', '0'),
        }
        
        # 增量更新聚合器
        self.aggregator.add_trade(trade)
        
        self.stats['trades_received'] += 1
        
        # 回调
        if self.on_trade_callback:
            self.on_trade_callback(trade)
        
        if self.verbose and self.stats['trades_received'] % 500 == 0:
            summary = self.aggregator.get_summary()
            self._log(f"📊 Trades: {self.stats['trades_received']} | Assets: {summary['assets_count']} | Vol: {summary['total_volume']:.0f}")
    
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
    
    def get_aggregator(self) -> TradeAggregator:
        """获取聚合器"""
        return self.aggregator
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        agg_summary = self.aggregator.get_summary()
        return {
            **self.stats,
            **agg_summary,
            'assets_subscribed': len(self.asset_ids)
        }
    
    def run(self, reconnect: bool = True):
        """启动 WebSocket（阻塞）"""
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
        """在后台线程中启动 WebSocket（非阻塞）"""
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        return thread
    
    def stop(self):
        """停止 WebSocket"""
        self.is_running = False
        if self.ws:
            self.ws.close()


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    print("🧪 Testing Polymarket WebSocket (v2 - Optimized)\n")
    print("=" * 60)
    
    # 示例 asset ID
    test_asset_ids = [
        "21742633143463906290569050155826241533067272736897614950488156847949938836455",
    ]
    
    def on_trade(trade: Dict):
        print(f"  💰 {trade['side']} {trade['size']:.2f} @ {trade['price']:.4f}")
    
    ws = PolymarketWebSocket(
        asset_ids=test_asset_ids,
        on_trade=on_trade,
        verbose=True
    )
    
    print(f"\n📡 Subscribing to {len(test_asset_ids)} assets...")
    print("Running for 30 seconds...\n")
    
    try:
        thread = ws.run_async()
        time.sleep(30)
        
        print("\n" + "=" * 60)
        print("📊 Final Statistics:")
        stats = ws.get_stats()
        for k, v in stats.items():
            print(f"  {k}: {v}")
        
        print("\n📈 Per-Asset Stats:")
        for asset_id in test_asset_ids:
            asset_stats = ws.aggregator.get_stats(asset_id)
            print(f"  {asset_id[:20]}...:")
            print(f"    Buy:   {asset_stats['aggressive_buy']:.2f}")
            print(f"    Sell:  {asset_stats['aggressive_sell']:.2f}")
            print(f"    Delta: {asset_stats['volume_delta']:.2f}")
            print(f"    AR:    {asset_stats['directional_ar']}")
        
    except KeyboardInterrupt:
        print("\n👋 Stopped")
    finally:
        ws.stop()