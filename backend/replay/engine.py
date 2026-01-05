"""
Belief Reaction System - Replay Engine v2
Re-execute raw events deterministically to reproduce system state.

Core Principles:
1. Deterministic: 使用事件时间戳而非系统时间
2. Reproducible: 同样输入必须产生同样输出
3. Auditable: 每步都有可验证的中间状态

v5.14: 集成 v5.13 确定性基础设施
- 使用 ReplayContext 强制事件时间
- 使用 EventSortKey 确保排序一致性
- 使用 deterministic_now 替代 time.time()

"同一证据包，不同机器回放结果必须相同"
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal
from enum import Enum
import json
import hashlib

from backend.evidence.bundle_hash import compute_bundle_hash
from backend.common.determinism import (
    ReplayContext,
    EventSortKey,
    get_event_clock,
    deterministic_now,
    ProcessingMode,
    sort_events,
    validate_event_order,
)


class ReplayStatus(Enum):
    """Replay execution status"""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    HASH_MATCH = "HASH_MATCH"       # Replay hash matches stored hash
    HASH_MISMATCH = "HASH_MISMATCH"  # Replay hash differs from stored
    ERROR = "ERROR"


@dataclass
class ReplayCheckpoint:
    """Checkpoint during replay for debugging"""
    event_index: int
    event_ts: int
    event_type: str
    state_hash: str  # Hash of current state at this point
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplayResult:
    """Result of replay execution"""
    status: ReplayStatus = ReplayStatus.PENDING

    # Input
    token_id: str = ""
    t0: int = 0
    events_count: int = 0

    # Computed
    computed_hash: str = ""
    expected_hash: str = ""
    hash_matches: bool = False

    # Timing
    start_ts: int = 0
    end_ts: int = 0
    duration_ms: int = 0

    # Checkpoints for debugging
    checkpoints: List[ReplayCheckpoint] = field(default_factory=list)

    # Reconstructed data
    shocks_detected: int = 0
    reactions_classified: int = 0
    state_changes: int = 0

    # Error info
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "token_id": self.token_id,
            "t0": self.t0,
            "events_count": self.events_count,
            "computed_hash": self.computed_hash,
            "expected_hash": self.expected_hash,
            "hash_matches": self.hash_matches,
            "duration_ms": self.duration_ms,
            "shocks_detected": self.shocks_detected,
            "reactions_classified": self.reactions_classified,
            "state_changes": self.state_changes,
            "checkpoints_count": len(self.checkpoints),
            "error": self.error,
        }


class DeterministicClock:
    """
    Deterministic clock that wraps EventClock for replay compatibility.

    v5.14: Now delegates to EventClock singleton for consistent time management.
    Critical for reproducible replay.
    """

    def __init__(self, start_ts: int = 0):
        self._current_ts = start_ts
        self._clock = get_event_clock()

    def advance_to(self, ts: int):
        """Advance clock to given timestamp"""
        if ts > self._current_ts:
            self._current_ts = ts
            self._clock.set_event_time(ts)

    @property
    def now(self) -> int:
        """Current timestamp (NOT system time)"""
        return self._current_ts

    def reset(self, ts: int = 0):
        self._current_ts = ts
        self._clock.clear_event_time()


class ReplayEngine:
    """
    Replays raw events to reconstruct system state deterministically.

    Usage:
        engine = ReplayEngine()
        result = engine.replay(
            raw_events=events,
            expected_hash="abc123...",
            token_id="token-xyz",
            t0=1704067200000
        )

        if result.hash_matches:
            print("Audit passed!")
        else:
            print(f"Hash mismatch: {result.computed_hash} != {result.expected_hash}")
    """

    def __init__(self, checkpoint_interval: int = 100):
        """
        Args:
            checkpoint_interval: Create checkpoint every N events
        """
        self.checkpoint_interval = checkpoint_interval
        self.clock = DeterministicClock()

        # State during replay
        self._order_book: Dict[Tuple[str, str], Dict[str, Any]] = {}  # (side, price) -> level
        self._trades: List[Dict] = []
        self._shocks: List[Dict] = []
        self._reactions: List[Dict] = []
        self._state_changes: List[Dict] = []

    def reset(self):
        """Reset engine state for new replay"""
        self.clock.reset()
        self._order_book.clear()
        self._trades.clear()
        self._shocks.clear()
        self._reactions.clear()
        self._state_changes.clear()

    def replay(
        self,
        raw_events: List[Dict],
        expected_hash: str,
        token_id: str,
        t0: int,
        window_ms: int = 60000,
        strict_order: bool = True
    ) -> ReplayResult:
        """
        Replay raw events and verify against expected hash.

        v5.14: Uses ReplayContext for strict determinism enforcement.

        Args:
            raw_events: List of raw events (trades, book updates)
            expected_hash: Expected bundle hash for verification
            token_id: Token being replayed
            t0: Center timestamp of evidence window
            window_ms: Window size (default 60s)
            strict_order: If True, raise on sort violations (default True)

        Returns:
            ReplayResult with verification status
        """
        import time as sys_time
        start = int(sys_time.time() * 1000)

        result = ReplayResult(
            status=ReplayStatus.RUNNING,
            token_id=token_id,
            t0=t0,
            expected_hash=expected_hash,
            events_count=len(raw_events),
            start_ts=start,
        )

        try:
            self.reset()

            # Sort events using EventSortKey for deterministic ordering
            def event_sort_key(e: Dict) -> EventSortKey:
                return EventSortKey(
                    token_id=e.get('token_id', token_id),
                    ts_ms=e.get('ts', 0),
                    sort_seq=e.get('seq', 0)
                )

            sorted_events = sort_events(raw_events, event_sort_key)

            # Validate sort order
            violations = validate_event_order(sorted_events, event_sort_key)
            if violations and strict_order:
                raise ValueError(f"Event order violations: {violations[:3]}")

            # Window boundaries
            window_start = t0 - (window_ms // 2)
            window_end = t0 + (window_ms // 2)

            # Process events within ReplayContext for strict determinism
            with ReplayContext(strict=strict_order) as replay_ctx:
                for i, event in enumerate(sorted_events):
                    event_ts = event.get('ts', 0)
                    event_token = event.get('token_id', token_id)
                    event_seq = event.get('seq', 0)

                    # Process event within replay context
                    with replay_ctx.process_event(event_ts, event_token, event_seq):
                        # Advance deterministic clock
                        self.clock.advance_to(event_ts)

                        # Process event
                        self._process_event(event, token_id)

                    # Checkpoint
                    if i > 0 and i % self.checkpoint_interval == 0:
                        checkpoint = self._create_checkpoint(i, event)
                        result.checkpoints.append(checkpoint)

                # Record replay context stats
                ctx_stats = replay_ctx.stats
                if ctx_stats.get('sort_violations', 0) > 0:
                    result.error = f"Sort violations: {ctx_stats['sort_violations']}"

            # Build reconstructed bundle
            bundle = self._build_bundle(token_id, t0, window_start, window_end)

            # Compute hash
            result.computed_hash = compute_bundle_hash(bundle)
            result.hash_matches = (result.computed_hash == expected_hash)

            # Fill result
            result.shocks_detected = len(self._shocks)
            result.reactions_classified = len(self._reactions)
            result.state_changes = len(self._state_changes)

            if result.hash_matches:
                result.status = ReplayStatus.HASH_MATCH
            else:
                result.status = ReplayStatus.HASH_MISMATCH

        except Exception as e:
            result.status = ReplayStatus.ERROR
            result.error = str(e)

        end = int(sys_time.time() * 1000)
        result.end_ts = end
        result.duration_ms = end - start

        return result

    def _process_event(self, event: Dict, token_id: str):
        """Process a single raw event using deterministic clock"""
        event_type = event.get('type', '')

        if event_type == 'trade':
            self._process_trade(event, token_id)
        elif event_type == 'book_snapshot':
            self._process_book_snapshot(event)
        elif event_type == 'price_change':
            self._process_price_change(event)

    def _process_trade(self, event: Dict, token_id: str):
        """Process trade event"""
        trade = {
            'ts': event.get('ts'),
            'price': event.get('price'),
            'size': event.get('size'),
            'side': event.get('side'),
            'token_id': token_id,
        }
        self._trades.append(trade)

        # Note: In full implementation, this would trigger shock detection
        # using deterministic clock (self.clock.now) not system time

    def _process_book_snapshot(self, event: Dict):
        """Process book snapshot"""
        self._order_book.clear()

        for bid in event.get('bids', []):
            key = ('bid', str(bid.get('price')))
            self._order_book[key] = {
                'price': bid.get('price'),
                'size': bid.get('size'),
                'side': 'bid',
                'ts': event.get('ts'),
            }

        for ask in event.get('asks', []):
            key = ('ask', str(ask.get('price')))
            self._order_book[key] = {
                'price': ask.get('price'),
                'size': ask.get('size'),
                'side': 'ask',
                'ts': event.get('ts'),
            }

    def _process_price_change(self, event: Dict):
        """Process price change event"""
        side = event.get('side', '').lower()
        price = str(event.get('price'))
        size = event.get('size', 0)

        key = (side, price)

        if size > 0:
            self._order_book[key] = {
                'price': event.get('price'),
                'size': size,
                'side': side,
                'ts': event.get('ts'),
            }
        else:
            self._order_book.pop(key, None)

    def _create_checkpoint(self, event_index: int, event: Dict) -> ReplayCheckpoint:
        """Create a checkpoint of current state"""
        # Hash current state
        state = {
            'book_levels': len(self._order_book),
            'trades': len(self._trades),
            'shocks': len(self._shocks),
        }
        state_json = json.dumps(state, sort_keys=True)
        state_hash = hashlib.sha256(state_json.encode()).hexdigest()[:16]

        return ReplayCheckpoint(
            event_index=event_index,
            event_ts=event.get('ts', 0),
            event_type=event.get('type', ''),
            state_hash=state_hash,
            metrics={
                'book_levels': len(self._order_book),
                'trades_count': len(self._trades),
            }
        )

    def _build_bundle(
        self,
        token_id: str,
        t0: int,
        window_start: int,
        window_end: int
    ) -> Dict:
        """Build evidence bundle from replayed state"""
        # Filter trades in window
        trades_in_window = [
            t for t in self._trades
            if window_start <= t.get('ts', 0) <= window_end
        ]

        # Get book state at t0 (simplified - in reality need historical reconstruction)
        book_at_t0 = {
            'bids': [v for k, v in self._order_book.items() if k[0] == 'bid'],
            'asks': [v for k, v in self._order_book.items() if k[0] == 'ask'],
        }

        bundle = {
            'token_id': token_id,
            't0': t0,
            'window': {
                'from_ts': window_start,
                'to_ts': window_end,
            },
            'trades': trades_in_window,
            'book_snapshot': book_at_t0,
            'shocks': self._shocks,
            'reactions': self._reactions,
            'belief_states': self._state_changes,
        }

        return bundle

    def get_diff(self, expected_bundle: Dict, replayed_bundle: Dict) -> List[str]:
        """
        Get differences between expected and replayed bundle.
        Useful for debugging hash mismatches.
        """
        diffs = []

        # Compare trade counts
        expected_trades = len(expected_bundle.get('trades', []))
        replayed_trades = len(replayed_bundle.get('trades', []))
        if expected_trades != replayed_trades:
            diffs.append(f"Trade count: expected {expected_trades}, got {replayed_trades}")

        # Compare shock counts
        expected_shocks = len(expected_bundle.get('shocks', []))
        replayed_shocks = len(replayed_bundle.get('shocks', []))
        if expected_shocks != replayed_shocks:
            diffs.append(f"Shock count: expected {expected_shocks}, got {replayed_shocks}")

        # Compare reaction counts
        expected_reactions = len(expected_bundle.get('reactions', []))
        replayed_reactions = len(replayed_bundle.get('reactions', []))
        if expected_reactions != replayed_reactions:
            diffs.append(f"Reaction count: expected {expected_reactions}, got {replayed_reactions}")

        return diffs
