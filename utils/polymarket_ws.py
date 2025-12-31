"""
Polymarket WebSocket 客户端 (v3 - Price Bin 版)
用于收集实时 trades 数据（带 aggressor 方向）

新功能：
1. 按 price bin 聚合 buy/sell（用于 POMD 计算）
2. 增量计数器（内存效率）
3. 支持按小时桶聚合

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
class PriceBinStats:
    """单个 price bin 的统计"""
    aggressive_buy: float = 0.0
    aggressive_sell: float = 0.0
    trade_count: int = 0
    
    @property
    def total(self) -> float:
        return self.aggressive_buy + self.aggressive_sell
    
    @property
    def delta(self) -> float:
        return self.aggressive_buy - self.aggressive_sell
    
    @property
    def min_side(self) -> float:
        """双边最小值 = 真正的对抗量"""
        return min(self.aggressive_buy, self.aggressive_sell)
    
    def add_trade(self, side: str, size: float):
        if side == 'BUY':
            self.aggressive_buy += size
        elif side == 'SELL':
            self.aggressive_sell += size
        self.trade_count += 1
    
    def to_dict(self) -> Dict:
        return {
            'buy': self.aggressive_buy,
            'sell': self.aggressive_sell,
            'total': self.total,
            'delta': self.delta,
            'min_side': self.min_side,
            'count': self.trade_count
        }


@dataclass
class AssetStats:
    """单个 asset 的完整统计"""
    # 总体统计
    aggressive_buy: float = 0.0
    aggressive_sell: float = 0.0
    trade_count: int = 0
    last_trade_ts: int = 0
    
    # 按 price bin 的统计 {price_bin: PriceBinStats}
    price_bins: Dict[float, PriceBinStats] = field(default_factory=dict)
    
    @property
    def total_volume(self) -> float:
        return self.aggressive_buy + self.aggressive_sell
    
    @property
    def volume_delta(self) -> float:
        return self.aggressive_buy - self.aggressive_sell
    
    @property
    def directional_ar(self) -> Optional[float]:
        if self.total_volume <= 0:
            return None
        return abs(self.volume_delta) / self.total_volume
    
    def add_trade(self, side: str, size: float, price: float, timestamp: int, tick_size: float = 0.01):
        """添加一笔 trade"""
        # 更新总体统计
        if side == 'BUY':
            self.aggressive_buy += size
        elif side == 'SELL':
            self.aggressive_sell += size
        
        self.trade_count += 1
        self.last_trade_ts = max(self.last_trade_ts, timestamp)
        
        # 更新 price bin 统计
        price_bin = round(price / tick_size) * tick_size
        price_bin = round(price_bin, 4)
        
        if price_bin not in self.price_bins:
            self.price_bins[price_bin] = PriceBinStats()
        
        self.price_bins[price_bin].add_trade(side, size)
    
    def get_poc(self) -> Optional[float]:
        """POC = 成交量最大的 price bin"""
        if not self.price_bins:
            return None
        return max(self.price_bins.keys(), key=lambda p: self.price_bins[p].total)
    
    def get_pomd(self, min_threshold: float = 0) -> Optional[float]:
        """
        POMD = min(buy, sell) 最大的 price bin
        
        Args:
            min_threshold: 最小阈值，低于此值不算（避免噪音）
        """
        if not self.price_bins:
            return None
        
        # 过滤掉低于阈值的
        valid_bins = {p: s for p, s in self.price_bins.items() if s.min_side >= min_threshold}
        
        if not valid_bins:
            return None
        
        return max(valid_bins.keys(), key=lambda p: valid_bins[p].min_side)
    
    def get_fight_score(self, price_bin: float) -> float:
        """
        计算某个 price bin 的 FightScore
        FightScore = volume × (1 - |delta|/volume)
        """
        if price_bin not in self.price_bins:
            return 0
        
        stats = self.price_bins[price_bin]
        if stats.total <= 0:
            return 0
        
        balance_factor = 1 - abs(stats.delta) / (stats.total + 1e-10)
        return stats.total * balance_factor
    
    def get_pomd_by_fight_score(self) -> Optional[float]:
        """POMD (方案 A) = FightScore 最大的 price bin"""
        if not self.price_bins:
            return None
        return max(self.price_bins.keys(), key=lambda p: self.get_fight_score(p))
    
    def reset(self):
        """重置所有统计"""
        self.aggressive_buy = 0.0
        self.aggressive_sell = 0.0
        self.trade_count = 0
        self.last_trade_ts = 0
        self.price_bins.clear()
    
    def to_dict(self) -> Dict:
        return {
            'aggressive_buy': self.aggressive_buy,
            'aggressive_sell': self.aggressive_sell,
            'total_volume': self.total_volume,
            'volume_delta': self.volume_delta,
            'directional_ar': self.directional_ar,
            'trade_count': self.trade_count,
            'last_trade_ts': self.last_trade_ts,
            'poc': self.get_poc(),
            'pomd': self.get_pomd(),
            'price_bins_count': len(self.price_bins)
        }
    
    def get_price_bins_dict(self) -> Dict[float, Dict]:
        """获取所有 price bins 的详细数据"""
        return {p: s.to_dict() for p, s in self.price_bins.items()}


class TradeAggregator:
    """
    Trades 聚合器 (v3 - Price Bin 版)
    
    功能：
    - 按 asset 聚合总体 buy/sell
    - 按 asset + price bin 聚合 buy/sell（用于 POC/POMD）
    - O(1) 查询
    """
    
    def __init__(self, tick_size: float = 0.01):
        self.tick_size = tick_size
        
        # {asset_id: AssetStats}
        self.stats_by_asset: Dict[str, AssetStats] = {}
        
        self.lock = threading.Lock()
        self.last_flush_ts: int = int(datetime.now().timestamp() * 1000)
    
    def add_trade(self, trade: Dict):
        """添加一笔 trade"""
        asset_id = trade.get('asset_id')
        side = trade.get('side', '')
        size = float(trade.get('size', 0))
        price = float(trade.get('price', 0))
        timestamp = int(trade.get('timestamp', 0))
        
        if not asset_id or not side or size <= 0:
            return
        
        with self.lock:
            if asset_id not in self.stats_by_asset:
                self.stats_by_asset[asset_id] = AssetStats()
            
            self.stats_by_asset[asset_id].add_trade(
                side=side,
                size=size,
                price=price,
                timestamp=timestamp,
                tick_size=self.tick_size
            )
    
    def get_stats(self, asset_id: str) -> Dict:
        """获取某个 asset 的统计"""
        with self.lock:
            if asset_id in self.stats_by_asset:
                return self.stats_by_asset[asset_id].to_dict()
        return AssetStats().to_dict()
    
    def get_price_bins(self, asset_id: str) -> Dict[float, Dict]:
        """获取某个 asset 的所有 price bins"""
        with self.lock:
            if asset_id in self.stats_by_asset:
                return self.stats_by_asset[asset_id].get_price_bins_dict()
        return {}
    
    def get_all_stats(self) -> Dict[str, Dict]:
        """获取所有 assets 的统计"""
        with self.lock:
            return {
                asset_id: stats.to_dict()
                for asset_id, stats in self.stats_by_asset.items()
                if stats.trade_count > 0
            }
    
    def get_all_price_bins(self) -> Dict[str, Dict[float, Dict]]:
        """获取所有 assets 的所有 price bins"""
        with self.lock:
            return {
                asset_id: stats.get_price_bins_dict()
                for asset_id, stats in self.stats_by_asset.items()
                if stats.price_bins
            }
    
    def clear_and_update_flush_time(self):
        """清空并更新 flush 时间"""
        with self.lock:
            max_ts = self.last_flush_ts
            for stats in self.stats_by_asset.values():
                if stats.last_trade_ts > max_ts:
                    max_ts = stats.last_trade_ts
            
            self.last_flush_ts = max_ts if max_ts > self.last_flush_ts else int(datetime.now().timestamp() * 1000)
            self.stats_by_asset.clear()
    
    def get_summary(self) -> Dict:
        """获取汇总信息"""
        with self.lock:
            total_trades = sum(s.trade_count for s in self.stats_by_asset.values())
            total_volume = sum(s.total_volume for s in self.stats_by_asset.values())
            total_bins = sum(len(s.price_bins) for s in self.stats_by_asset.values())
            
            return {
                'assets_count': len(self.stats_by_asset),
                'total_trades': total_trades,
                'total_volume': total_volume,
                'total_price_bins': total_bins,
                'last_flush_ts': self.last_flush_ts
            }


class PolymarketWebSocket:
    """
    Polymarket WebSocket 客户端 (v3)
    """
    
    def __init__(
        self,
        asset_ids: List[str],
        on_trade: Optional[Callable[[Dict], None]] = None,
        on_book: Optional[Callable[[Dict], None]] = None,
        tick_size: float = 0.01,
        verbose: bool = True
    ):
        self.asset_ids = list(asset_ids)
        self.on_trade_callback = on_trade
        self.on_book_callback = on_book
        self.tick_size = tick_size
        self.verbose = verbose
        
        self.ws: Optional[WebSocketApp] = None
        self.is_running = False
        self.ping_thread: Optional[threading.Thread] = None
        
        # 使用 Price Bin 版聚合器
        self.aggregator = TradeAggregator(tick_size=tick_size)
        
        self.stats = {
            'connected_at': None,
            'trades_received': 0,
            'books_received': 0,
            'errors': 0,
            'reconnects': 0
        }
    
    def _log(self, message: str):
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {message}")
    
    def on_open(self, ws):
        self.stats['connected_at'] = datetime.now()
        self._log(f"✅ Connected to Polymarket WebSocket")
        self._log(f"   Subscribing to {len(self.asset_ids)} assets...")
        
        subscribe_msg = {
            "assets_ids": self.asset_ids,
            "type": "market"
        }
        ws.send(json.dumps(subscribe_msg))
        
        self.is_running = True
        self.ping_thread = threading.Thread(target=self._ping_loop, args=(ws,), daemon=True)
        self.ping_thread.start()
    
    def on_message(self, ws, message: str):
        try:
            if message == "PONG":
                return
            
            data = json.loads(message)
            event_type = data.get("event_type", "")
            
            if event_type == "last_trade_price":
                self._handle_trade(data)
            elif event_type == "book":
                self._handle_book(data)
                
        except json.JSONDecodeError:
            self._log(f"⚠️ Invalid JSON: {message[:100]}")
        except Exception as e:
            self._log(f"❌ Error processing message: {e}")
            self.stats['errors'] += 1
    
    def _handle_trade(self, data: Dict):
        trade = {
            'asset_id': data.get('asset_id'),
            'market': data.get('market'),
            'price': float(data.get('price', 0)),
            'size': float(data.get('size', 0)),
            'side': data.get('side'),
            'timestamp': int(data.get('timestamp', 0)),
        }
        
        self.aggregator.add_trade(trade)
        self.stats['trades_received'] += 1
        
        if self.on_trade_callback:
            self.on_trade_callback(trade)
        
        if self.verbose and self.stats['trades_received'] % 500 == 0:
            summary = self.aggregator.get_summary()
            self._log(f"📊 Trades: {self.stats['trades_received']} | Bins: {summary['total_price_bins']}")
    
    def _handle_book(self, data: Dict):
        self.stats['books_received'] += 1
        if self.on_book_callback:
            self.on_book_callback(data)
    
    def on_error(self, ws, error):
        self._log(f"❌ WebSocket error: {error}")
        self.stats['errors'] += 1
    
    def on_close(self, ws, close_status_code, close_msg):
        self._log(f"🔌 WebSocket closed: {close_status_code} - {close_msg}")
        self.is_running = False
    
    def _ping_loop(self, ws):
        while self.is_running:
            try:
                ws.send("PING")
                time.sleep(10)
            except Exception as e:
                self._log(f"⚠️ Ping failed: {e}")
                break
    
    def subscribe(self, asset_ids: List[str]):
        if self.ws:
            msg = {"assets_ids": asset_ids, "operation": "subscribe"}
            self.ws.send(json.dumps(msg))
            self.asset_ids.extend(asset_ids)
            self._log(f"📡 Subscribed to {len(asset_ids)} more assets")
    
    def unsubscribe(self, asset_ids: List[str]):
        if self.ws:
            msg = {"assets_ids": asset_ids, "operation": "unsubscribe"}
            self.ws.send(json.dumps(msg))
            self._log(f"📴 Unsubscribed from {len(asset_ids)} assets")
    
    def get_aggregator(self) -> TradeAggregator:
        return self.aggregator
    
    def get_stats(self) -> Dict:
        agg_summary = self.aggregator.get_summary()
        return {**self.stats, **agg_summary, 'assets_subscribed': len(self.asset_ids)}
    
    def run(self, reconnect: bool = True):
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
                self._log(f"🔄 Reconnecting in 5s... (attempt {self.stats['reconnects']})")
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
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        return thread
    
    def stop(self):
        self.is_running = False
        if self.ws:
            self.ws.close()


# ============================================================================
# 测试
# ============================================================================

if __name__ == "__main__":
    print("🧪 Testing Polymarket WebSocket v3 (Price Bin)\n")
    print("=" * 60)
    
    test_asset_ids = [
        "21742633143463906290569050155826241533067272736897614950488156847949938836455",
    ]
    
    def on_trade(trade: Dict):
        print(f"  💰 {trade['side']} {trade['size']:.2f} @ {trade['price']:.4f}")
    
    ws = PolymarketWebSocket(
        asset_ids=test_asset_ids,
        on_trade=on_trade,
        tick_size=0.01,
        verbose=True
    )
    
    print(f"\n📡 Subscribing to {len(test_asset_ids)} assets...")
    print("Running for 60 seconds...\n")
    
    try:
        thread = ws.run_async()
        time.sleep(60)
        
        print("\n" + "=" * 60)
        print("📊 Final Statistics:")
        stats = ws.get_stats()
        for k, v in stats.items():
            print(f"  {k}: {v}")
        
        print("\n📈 Per-Asset Stats:")
        for asset_id in test_asset_ids:
            asset_stats = ws.aggregator.get_stats(asset_id)
            print(f"\n  Asset: {asset_id[:20]}...")
            print(f"    Total Volume: {asset_stats['total_volume']:.2f}")
            print(f"    Delta: {asset_stats['volume_delta']:.2f}")
            print(f"    AR: {asset_stats['directional_ar']}")
            print(f"    POC: {asset_stats['poc']}")
            print(f"    POMD: {asset_stats['pomd']}")
            
            # 显示 top price bins
            bins = ws.aggregator.get_price_bins(asset_id)
            if bins:
                print(f"    Price Bins ({len(bins)}):")
                sorted_bins = sorted(bins.items(), key=lambda x: x[1]['total'], reverse=True)[:5]
                for price, data in sorted_bins:
                    print(f"      {price:.2f}: Buy={data['buy']:.0f} Sell={data['sell']:.0f} MinSide={data['min_side']:.0f}")
        
    except KeyboardInterrupt:
        print("\n👋 Stopped")
    finally:
        ws.stop()