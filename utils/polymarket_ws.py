"""
Polymarket WebSocket client (v4 - disconnect handling state machine).
Collects live trades with aggressor direction.

Features:
1. Aggregate buy/sell by price bin (for POMD)
2. Incremental counters (memory efficient)
3. Hourly bucket aggregation support
4. [v4] Connection state machine with exponential backoff
5. [v4] Order book snapshot rebuild on reconnect
6. [v4] Consistency tracking (sequence gap detection)

WebSocket Market Channel `last_trade_price` message:
{
    "asset_id": "...",
    "event_type": "last_trade_price",
    "market": "0x...",
    "price": "0.456",
    "side": "BUY",      # aggressor side
    "size": "219.217767",
    "timestamp": "1750428146322"
}

Connection States (v4):
    DISCONNECTED -> RECONNECTING -> REBUILDING -> CONNECTED
                 ^                                    |
                 |____________________________________|
"""

import json
import time
import threading
import hashlib
import requests
from datetime import datetime
from typing import Dict, List, Callable, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from websocket import WebSocketApp


# ============================================================================
# v4: Connection State Machine
# ============================================================================

class ConnectionState(Enum):
    """WebSocket connection states."""
    DISCONNECTED = "DISCONNECTED"     # Not connected
    RECONNECTING = "RECONNECTING"     # Attempting to reconnect
    REBUILDING = "REBUILDING"         # Fetching order book snapshots
    CONNECTED = "CONNECTED"           # Fully operational


# v4: Exponential backoff configuration
RECONNECT_BASE_DELAY_S = 1.0          # Initial delay: 1 second
RECONNECT_MAX_DELAY_S = 60.0          # Maximum delay: 60 seconds
RECONNECT_MULTIPLIER = 2.0            # Exponential multiplier
RECONNECT_JITTER_RATIO = 0.1          # 10% jitter to avoid thundering herd

# v4: REST API for order book snapshots
CLOB_API = "https://clob.polymarket.com"

# WebSocket URL
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


@dataclass
class PriceBinStats:
    """Stats for a single price bin."""
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
        """Two-sided minimum = true contested volume."""
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
    """Full stats for a single asset."""
    # Aggregate stats
    aggressive_buy: float = 0.0
    aggressive_sell: float = 0.0
    trade_count: int = 0
    last_trade_ts: int = 0
    
    # Price-bin stats {price_bin: PriceBinStats}
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
        """Add a trade."""
        # Update aggregate stats
        if side == 'BUY':
            self.aggressive_buy += size
        elif side == 'SELL':
            self.aggressive_sell += size
        
        self.trade_count += 1
        self.last_trade_ts = max(self.last_trade_ts, timestamp)
        
        # Update price-bin stats
        price_bin = round(price / tick_size) * tick_size
        price_bin = round(price_bin, 4)
        
        if price_bin not in self.price_bins:
            self.price_bins[price_bin] = PriceBinStats()
        
        self.price_bins[price_bin].add_trade(side, size)
    
    def get_poc(self) -> Optional[float]:
        """POC = max-volume price bin."""
        if not self.price_bins:
            return None
        return max(self.price_bins.keys(), key=lambda p: self.price_bins[p].total)
    
    def get_pomd(self, min_threshold: float = 0) -> Optional[float]:
        """
        POMD = price bin with max min(buy, sell).

        Args:
            min_threshold: minimum threshold to ignore noise
        """
        if not self.price_bins:
            return None
        
        # Filter out bins below threshold.
        valid_bins = {p: s for p, s in self.price_bins.items() if s.min_side >= min_threshold}
        
        if not valid_bins:
            return None
        
        return max(valid_bins.keys(), key=lambda p: valid_bins[p].min_side)
    
    def get_fight_score(self, price_bin: float) -> float:
        """
        Compute FightScore for a price bin.
        FightScore = volume * (1 - |delta|/volume)
        """
        if price_bin not in self.price_bins:
            return 0
        
        stats = self.price_bins[price_bin]
        if stats.total <= 0:
            return 0
        
        balance_factor = 1 - abs(stats.delta) / (stats.total + 1e-10)
        return stats.total * balance_factor
    
    def get_pomd_by_fight_score(self) -> Optional[float]:
        """POMD (option A) = max FightScore price bin."""
        if not self.price_bins:
            return None
        return max(self.price_bins.keys(), key=lambda p: self.get_fight_score(p))
    
    def reset(self):
        """Reset all stats."""
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
        """Get detailed price-bin data."""
        return {p: s.to_dict() for p, s in self.price_bins.items()}


class TradeAggregator:
    """
    Trades aggregator (v3 - price-bin).

    Features:
    - Aggregate buy/sell by asset
    - Aggregate buy/sell by asset + price bin (for POC/POMD)
    - O(1) lookups
    """
    
    def __init__(self, tick_size: float = 0.01):
        self.tick_size = tick_size
        
        # {asset_id: AssetStats}
        self.stats_by_asset: Dict[str, AssetStats] = {}
        
        self.lock = threading.Lock()
        self.last_flush_ts: int = int(datetime.now().timestamp() * 1000)
    
    def add_trade(self, trade: Dict):
        """Add a trade."""
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
        """Get stats for a single asset."""
        with self.lock:
            if asset_id in self.stats_by_asset:
                return self.stats_by_asset[asset_id].to_dict()
        return AssetStats().to_dict()
    
    def get_price_bins(self, asset_id: str) -> Dict[float, Dict]:
        """Get all price bins for an asset."""
        with self.lock:
            if asset_id in self.stats_by_asset:
                return self.stats_by_asset[asset_id].get_price_bins_dict()
        return {}
    
    def get_all_stats(self) -> Dict[str, Dict]:
        """Get stats for all assets."""
        with self.lock:
            return {
                asset_id: stats.to_dict()
                for asset_id, stats in self.stats_by_asset.items()
                if stats.trade_count > 0
            }
    
    def get_all_price_bins(self) -> Dict[str, Dict[float, Dict]]:
        """Get price bins for all assets."""
        with self.lock:
            return {
                asset_id: stats.get_price_bins_dict()
                for asset_id, stats in self.stats_by_asset.items()
                if stats.price_bins
            }
    
    def clear_and_update_flush_time(self):
        """Clear and update flush time."""
        with self.lock:
            max_ts = self.last_flush_ts
            for stats in self.stats_by_asset.values():
                if stats.last_trade_ts > max_ts:
                    max_ts = stats.last_trade_ts
            
            self.last_flush_ts = max_ts if max_ts > self.last_flush_ts else int(datetime.now().timestamp() * 1000)
            self.stats_by_asset.clear()
    
    def get_summary(self) -> Dict:
        """Get summary info."""
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


@dataclass
class OrderBookSnapshot:
    """
    v4: Order book snapshot for consistency checking.
    Used to rebuild state after disconnect.
    """
    token_id: str
    timestamp: int
    bids: Dict[str, float] = field(default_factory=dict)  # {price: size}
    asks: Dict[str, float] = field(default_factory=dict)  # {price: size}
    hash: str = ""

    def compute_hash(self) -> str:
        """Compute hash of order book state for consistency checking."""
        # Sort and serialize for deterministic hash
        sorted_bids = sorted(self.bids.items())
        sorted_asks = sorted(self.asks.items())
        data = json.dumps({
            'bids': sorted_bids,
            'asks': sorted_asks
        }, sort_keys=True)
        return hashlib.md5(data.encode()).hexdigest()[:8]

    def __post_init__(self):
        if not self.hash:
            self.hash = self.compute_hash()


class PolymarketWebSocket:
    """
    Polymarket WebSocket client (v4).

    v4 Features:
    - Connection state machine (DISCONNECTED -> RECONNECTING -> REBUILDING -> CONNECTED)
    - Exponential backoff for reconnection
    - Order book snapshot rebuild on reconnect via REST API
    - Consistency tracking with sequence numbers and hashes
    """

    def __init__(
        self,
        asset_ids: List[str],
        on_trade: Optional[Callable[[Dict], None]] = None,
        on_book: Optional[Callable[[Dict], None]] = None,
        on_state_change: Optional[Callable[['ConnectionState', 'ConnectionState'], None]] = None,
        on_snapshot_rebuild: Optional[Callable[[str, 'OrderBookSnapshot'], None]] = None,
        tick_size: float = 0.01,
        verbose: bool = True,
        rebuild_on_reconnect: bool = True
    ):
        self.asset_ids = list(asset_ids)
        self.on_trade_callback = on_trade
        self.on_book_callback = on_book
        self.on_state_change_callback = on_state_change  # v4: state change callback
        self.on_snapshot_rebuild_callback = on_snapshot_rebuild  # v4: rebuild callback
        self.tick_size = tick_size
        self.verbose = verbose
        self.rebuild_on_reconnect = rebuild_on_reconnect  # v4: auto rebuild flag

        self.ws: Optional[WebSocketApp] = None
        self.is_running = False
        self.ping_thread: Optional[threading.Thread] = None

        # Use price-bin aggregator.
        self.aggregator = TradeAggregator(tick_size=tick_size)

        # v4: Connection state machine
        self._state = ConnectionState.DISCONNECTED
        self._state_lock = threading.Lock()
        self._reconnect_attempt = 0
        self._last_disconnect_ts: Optional[int] = None

        # v4: Order book snapshots for consistency
        self._snapshots: Dict[str, OrderBookSnapshot] = {}
        self._last_book_ts: Dict[str, int] = {}  # Last book update timestamp per token
        self._sequence_gaps: List[Dict] = []  # Track sequence gaps for logging

        self.stats = {
            'connected_at': None,
            'trades_received': 0,
            'books_received': 0,
            'errors': 0,
            'reconnects': 0,
            'snapshot_rebuilds': 0,  # v4
            'sequence_gaps': 0,      # v4
            'total_disconnected_ms': 0  # v4
        }
    
    def _log(self, message: str):
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {message}")

    # =========================================================================
    # v4: State Machine Methods
    # =========================================================================

    @property
    def state(self) -> ConnectionState:
        """Get current connection state."""
        with self._state_lock:
            return self._state

    def _set_state(self, new_state: ConnectionState):
        """Transition to a new state with callback."""
        with self._state_lock:
            old_state = self._state
            if old_state == new_state:
                return
            self._state = new_state

        self._log(f"State: {old_state.value} -> {new_state.value}")

        # Track disconnect time
        now_ms = int(datetime.now().timestamp() * 1000)
        if new_state == ConnectionState.DISCONNECTED:
            self._last_disconnect_ts = now_ms
        elif old_state == ConnectionState.DISCONNECTED and self._last_disconnect_ts:
            gap_ms = now_ms - self._last_disconnect_ts
            self.stats['total_disconnected_ms'] += gap_ms
            self._log(f"   Disconnect duration: {gap_ms}ms")

        # Invoke callback
        if self.on_state_change_callback:
            try:
                self.on_state_change_callback(old_state, new_state)
            except Exception as e:
                self._log(f"State change callback error: {e}")

    def _get_reconnect_delay(self) -> float:
        """Calculate exponential backoff delay with jitter."""
        import random
        delay = RECONNECT_BASE_DELAY_S * (RECONNECT_MULTIPLIER ** self._reconnect_attempt)
        delay = min(delay, RECONNECT_MAX_DELAY_S)
        # Add jitter
        jitter = delay * RECONNECT_JITTER_RATIO * (2 * random.random() - 1)
        return delay + jitter

    # =========================================================================
    # v4: Order Book Snapshot Rebuild
    # =========================================================================

    def _fetch_order_book(self, token_id: str) -> Optional[OrderBookSnapshot]:
        """Fetch order book snapshot from REST API."""
        try:
            response = requests.get(
                f"{CLOB_API}/book",
                params={"token_id": token_id},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            now_ms = int(datetime.now().timestamp() * 1000)

            # Parse bids and asks
            bids = {}
            asks = {}

            for bid in data.get('bids', []):
                price = str(bid.get('price', '0'))
                size = float(bid.get('size', 0))
                if size > 0:
                    bids[price] = size

            for ask in data.get('asks', []):
                price = str(ask.get('price', '0'))
                size = float(ask.get('size', 0))
                if size > 0:
                    asks[price] = size

            snapshot = OrderBookSnapshot(
                token_id=token_id,
                timestamp=now_ms,
                bids=bids,
                asks=asks
            )

            return snapshot

        except requests.RequestException as e:
            self._log(f"Failed to fetch order book for {token_id[:20]}...: {e}")
            return None

    def _rebuild_order_books(self):
        """Rebuild all order books from REST API after reconnect."""
        self._set_state(ConnectionState.REBUILDING)

        rebuilt_count = 0
        failed_count = 0

        self._log(f"Rebuilding order books for {len(self.asset_ids)} assets...")

        for token_id in self.asset_ids:
            snapshot = self._fetch_order_book(token_id)

            if snapshot:
                self._snapshots[token_id] = snapshot
                self._last_book_ts[token_id] = snapshot.timestamp
                rebuilt_count += 1

                # Invoke callback to notify consumer
                if self.on_snapshot_rebuild_callback:
                    try:
                        self.on_snapshot_rebuild_callback(token_id, snapshot)
                    except Exception as e:
                        self._log(f"Snapshot rebuild callback error: {e}")

                # Also emit as book event for compatibility
                if self.on_book_callback:
                    book_event = {
                        'asset_id': token_id,
                        'event_type': 'book_snapshot',  # Mark as snapshot
                        'timestamp': snapshot.timestamp,
                        'bids': [{'price': p, 'size': s} for p, s in snapshot.bids.items()],
                        'asks': [{'price': p, 'size': s} for p, s in snapshot.asks.items()],
                        'hash': snapshot.hash,
                        'is_rebuild': True
                    }
                    try:
                        self.on_book_callback(book_event)
                    except Exception as e:
                        self._log(f"Book callback error during rebuild: {e}")
            else:
                failed_count += 1

            # Small delay to avoid rate limiting
            time.sleep(0.05)

        self.stats['snapshot_rebuilds'] += rebuilt_count
        self._log(f"   Rebuilt: {rebuilt_count}, Failed: {failed_count}")

        return rebuilt_count > 0
    
    def on_open(self, ws):
        self.stats['connected_at'] = datetime.now()
        self._log("Connected to Polymarket WebSocket")
        self._log(f"   Subscribing to {len(self.asset_ids)} assets...")

        subscribe_msg = {
            "assets_ids": self.asset_ids,
            "type": "market"
        }
        ws.send(json.dumps(subscribe_msg))

        self.is_running = True

        # v4: Rebuild order books if this is a reconnect
        if self._reconnect_attempt > 0 and self.rebuild_on_reconnect:
            self._rebuild_order_books()

        # v4: Set connected state and reset backoff
        self._set_state(ConnectionState.CONNECTED)
        self._reconnect_attempt = 0

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
            self._log(f"Invalid JSON: {message[:100]}")
        except Exception as e:
            self._log(f"Error processing message: {e}")
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
            self._log(f"Trades: {self.stats['trades_received']} | Bins: {summary['total_price_bins']}")
    
    def _handle_book(self, data: Dict):
        self.stats['books_received'] += 1

        # v4: Track sequence gaps for consistency monitoring
        token_id = data.get('asset_id', '')
        msg_ts = int(data.get('timestamp', 0))

        if token_id and msg_ts > 0:
            last_ts = self._last_book_ts.get(token_id, 0)
            if last_ts > 0:
                gap_ms = msg_ts - last_ts
                # Detect unusual gaps (> 5 seconds suggests potential data loss)
                if gap_ms > 5000:
                    self.stats['sequence_gaps'] += 1
                    gap_info = {
                        'token_id': token_id,
                        'last_ts': last_ts,
                        'current_ts': msg_ts,
                        'gap_ms': gap_ms,
                        'detected_at': int(datetime.now().timestamp() * 1000)
                    }
                    self._sequence_gaps.append(gap_info)
                    # Keep only last 100 gaps
                    if len(self._sequence_gaps) > 100:
                        self._sequence_gaps = self._sequence_gaps[-100:]
                    self._log(f"Sequence gap detected: {token_id[:20]}... gap={gap_ms}ms")
            self._last_book_ts[token_id] = msg_ts

        if self.on_book_callback:
            self.on_book_callback(data)
    
    def on_error(self, ws, error):
        self._log(f"WebSocket error: {error}")
        self.stats['errors'] += 1

    def on_close(self, ws, close_status_code, close_msg):
        self._log(f"WebSocket closed: {close_status_code} - {close_msg}")
        self.is_running = False
        # v4: Set disconnected state
        self._set_state(ConnectionState.DISCONNECTED)
    
    def _ping_loop(self, ws):
        while self.is_running:
            try:
                ws.send("PING")
                time.sleep(10)
            except Exception as e:
                self._log(f"Ping failed: {e}")
                break
    
    def subscribe(self, asset_ids: List[str]):
        if self.ws:
            msg = {"assets_ids": asset_ids, "operation": "subscribe"}
            self.ws.send(json.dumps(msg))
            self.asset_ids.extend(asset_ids)
            self._log(f"Subscribed to {len(asset_ids)} more assets")
    
    def unsubscribe(self, asset_ids: List[str]):
        if self.ws:
            msg = {"assets_ids": asset_ids, "operation": "unsubscribe"}
            self.ws.send(json.dumps(msg))
            self._log(f"Unsubscribed from {len(asset_ids)} assets")
    
    def get_aggregator(self) -> TradeAggregator:
        return self.aggregator

    def get_stats(self) -> Dict:
        agg_summary = self.aggregator.get_summary()
        return {
            **self.stats,
            **agg_summary,
            'assets_subscribed': len(self.asset_ids),
            'state': self.state.value,  # v4
            'reconnect_attempt': self._reconnect_attempt  # v4
        }

    # =========================================================================
    # v4: Consistency Monitoring Methods
    # =========================================================================

    def get_sequence_gaps(self) -> List[Dict]:
        """Get recent sequence gaps for debugging."""
        return list(self._sequence_gaps)

    def get_snapshots(self) -> Dict[str, 'OrderBookSnapshot']:
        """Get current order book snapshots."""
        return dict(self._snapshots)

    def force_rebuild(self) -> bool:
        """Force rebuild all order books from REST API."""
        self._log("Force rebuild triggered")
        return self._rebuild_order_books()
    
    def run(self, reconnect: bool = True):
        while True:
            try:
                # v4: Set reconnecting state
                if self._reconnect_attempt > 0:
                    self._set_state(ConnectionState.RECONNECTING)

                self._log(f"Connecting to {WS_URL}...")

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

                # v4: Exponential backoff for reconnection
                self._reconnect_attempt += 1
                self.stats['reconnects'] += 1
                delay = self._get_reconnect_delay()
                self._log(f"Reconnecting in {delay:.1f}s... (attempt {self._reconnect_attempt})")
                time.sleep(delay)

            except KeyboardInterrupt:
                self._log("Stopped by user")
                break
            except Exception as e:
                self._log(f"Fatal error: {e}")
                if not reconnect:
                    break
                # v4: Use backoff even for exceptions
                self._reconnect_attempt += 1
                delay = self._get_reconnect_delay()
                time.sleep(delay)
    
    def run_async(self) -> threading.Thread:
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        return thread
    
    def stop(self):
        self.is_running = False
        if self.ws:
            self.ws.close()


# ============================================================================
# Tests
# ============================================================================

if __name__ == "__main__":
    print("Testing Polymarket WebSocket v4 (Disconnect Handling)\n")
    print("=" * 60)

    test_asset_ids = [
        "21742633143463906290569050155826241533067272736897614950488156847949938836455",
    ]

    def on_trade(trade: Dict):
        print(f"  {trade['side']} {trade['size']:.2f} @ {trade['price']:.4f}")

    def on_state_change(old_state: ConnectionState, new_state: ConnectionState):
        print(f"  [STATE] {old_state.value} -> {new_state.value}")

    def on_snapshot_rebuild(token_id: str, snapshot: OrderBookSnapshot):
        print(f"  [REBUILD] {token_id[:20]}... hash={snapshot.hash} bids={len(snapshot.bids)} asks={len(snapshot.asks)}")

    ws = PolymarketWebSocket(
        asset_ids=test_asset_ids,
        on_trade=on_trade,
        on_state_change=on_state_change,
        on_snapshot_rebuild=on_snapshot_rebuild,
        tick_size=0.01,
        verbose=True,
        rebuild_on_reconnect=True
    )

    print(f"\nSubscribing to {len(test_asset_ids)} assets...")
    print("Running for 60 seconds...\n")

    try:
        thread = ws.run_async()
        time.sleep(60)

        print("\n" + "=" * 60)
        print("Final Statistics:")
        stats = ws.get_stats()
        for k, v in stats.items():
            print(f"  {k}: {v}")

        # v4: Show sequence gaps if any
        gaps = ws.get_sequence_gaps()
        if gaps:
            print(f"\nSequence Gaps ({len(gaps)}):")
            for gap in gaps[-5:]:
                print(f"  {gap['token_id'][:20]}... gap={gap['gap_ms']}ms")

        print("\nPer-Asset Stats:")
        for asset_id in test_asset_ids:
            asset_stats = ws.aggregator.get_stats(asset_id)
            print(f"\n  Asset: {asset_id[:20]}...")
            print(f"    Total Volume: {asset_stats['total_volume']:.2f}")
            print(f"    Delta: {asset_stats['volume_delta']:.2f}")
            print(f"    AR: {asset_stats['directional_ar']}")
            print(f"    POC: {asset_stats['poc']}")
            print(f"    POMD: {asset_stats['pomd']}")

            # Show top price bins.
            bins = ws.aggregator.get_price_bins(asset_id)
            if bins:
                print(f"    Price Bins ({len(bins)}):")
                sorted_bins = sorted(bins.items(), key=lambda x: x[1]['total'], reverse=True)[:5]
                for price, data in sorted_bins:
                    print(f"      {price:.2f}: Buy={data['buy']:.0f} Sell={data['sell']:.0f} MinSide={data['min_side']:.0f}")

    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        ws.stop()
