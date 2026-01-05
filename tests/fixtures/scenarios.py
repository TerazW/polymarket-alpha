"""
Adversarial Test Fixtures Library (v5.21)

Fixed raw_events fixtures for reproducible adversarial testing.

Scenarios:
- VACUUM: Sudden depth evacuation at anchor level
- PULL: Cancel-driven depth removal
- SWEEP: Trade-driven depth removal
- SPOOF: Fake liquidity that cancels
- FLASH_CRASH: Rapid cascade then recovery
- LAYERING: Multi-level coordinated withdrawal
- WASH_TRADE: Self-trade patterns
- QUOTE_STUFFING: Rapid update noise

"每一个反例都有故事"
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from decimal import Decimal
import hashlib
import json


# =============================================================================
# Base timestamp for all fixtures (fixed for reproducibility)
# =============================================================================
BASE_TS = 1700000000000  # 2023-11-14 22:13:20 UTC (fixed)


# =============================================================================
# Event Type Constants
# =============================================================================
class EventType:
    TRADE = "trade"
    PRICE_CHANGE = "price_change"
    ORDER_PLACED = "order_placed"
    ORDER_CANCELLED = "order_cancelled"
    BOOK_SNAPSHOT = "book_snapshot"


# =============================================================================
# Scenario Definition
# =============================================================================
@dataclass
class AdversarialScenario:
    """A fixed, reproducible test scenario"""
    name: str
    description: str
    description_cn: str
    token_id: str
    t0: int                             # Center timestamp
    window_ms: int                      # Window size
    raw_events: List[Dict[str, Any]]    # The actual events
    expected_outcomes: Dict[str, Any]   # What we expect to detect
    tags: List[str] = field(default_factory=list)
    version: str = "1.0"

    def __post_init__(self):
        # Ensure events are sorted by timestamp
        self.raw_events = sorted(self.raw_events, key=lambda e: (e.get('ts', 0), e.get('seq', 0)))

    @property
    def scenario_hash(self) -> str:
        """Deterministic hash of the scenario for verification"""
        content = json.dumps({
            'name': self.name,
            'token_id': self.token_id,
            't0': self.t0,
            'events': self.raw_events,
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'description': self.description,
            'description_cn': self.description_cn,
            'token_id': self.token_id,
            't0': self.t0,
            'window_ms': self.window_ms,
            'raw_events': self.raw_events,
            'expected_outcomes': self.expected_outcomes,
            'tags': self.tags,
            'version': self.version,
            'scenario_hash': self.scenario_hash,
        }


# =============================================================================
# Helper Functions for Building Events
# =============================================================================

def trade_event(ts: int, price: float, size: float, side: str, seq: int = 0) -> Dict[str, Any]:
    """Create a trade event"""
    return {
        'ts': ts,
        'seq': seq,
        'type': EventType.TRADE,
        'price': price,
        'size': size,
        'side': side,
    }


def price_change_event(ts: int, price: float, size: float, side: str, seq: int = 0) -> Dict[str, Any]:
    """Create a price level change event (book update)"""
    return {
        'ts': ts,
        'seq': seq,
        'type': EventType.PRICE_CHANGE,
        'price': price,
        'size': size,
        'side': side,
    }


def order_cancelled_event(ts: int, price: float, size: float, side: str, seq: int = 0) -> Dict[str, Any]:
    """Create an order cancellation event"""
    return {
        'ts': ts,
        'seq': seq,
        'type': EventType.ORDER_CANCELLED,
        'price': price,
        'size': size,
        'side': side,
    }


def book_snapshot_event(ts: int, bids: List[tuple], asks: List[tuple], seq: int = 0) -> Dict[str, Any]:
    """Create a book snapshot event"""
    return {
        'ts': ts,
        'seq': seq,
        'type': EventType.BOOK_SNAPSHOT,
        'bids': [{'price': p, 'size': s} for p, s in bids],
        'asks': [{'price': p, 'size': s} for p, s in asks],
    }


# =============================================================================
# SCENARIO 1: VACUUM at Anchor Level
# =============================================================================

VACUUM_AT_ANCHOR = AdversarialScenario(
    name="vacuum_at_anchor",
    description="Large trade sweeps anchor level, depth doesn't recover for 5 seconds",
    description_cn="大单扫掉锚点位深度，5秒内未恢复 → VACUUM",
    token_id="fixture-vacuum-001",
    t0=BASE_TS + 5000,
    window_ms=10000,
    tags=["vacuum", "trade_driven", "anchor"],
    raw_events=[
        # Initial book state - anchor at 0.72 with 500 depth
        book_snapshot_event(BASE_TS,
            bids=[(0.72, 500), (0.71, 300), (0.70, 200)],
            asks=[(0.73, 400), (0.74, 300), (0.75, 200)]),

        # Pre-shock steady state
        price_change_event(BASE_TS + 1000, 0.72, 500, 'bid', seq=1),
        price_change_event(BASE_TS + 2000, 0.72, 500, 'bid', seq=2),

        # SHOCK: Large trade at 0.72 (sweeps the anchor)
        trade_event(BASE_TS + 3000, 0.72, 480, 'buy', seq=3),

        # Depth evacuates to 20 (96% drop)
        price_change_event(BASE_TS + 3100, 0.72, 20, 'bid', seq=4),

        # Stays evacuated for 5 seconds (VACUUM duration)
        price_change_event(BASE_TS + 4000, 0.72, 25, 'bid', seq=5),
        price_change_event(BASE_TS + 5000, 0.72, 30, 'bid', seq=6),
        price_change_event(BASE_TS + 6000, 0.72, 35, 'bid', seq=7),
        price_change_event(BASE_TS + 7000, 0.72, 40, 'bid', seq=8),
        price_change_event(BASE_TS + 8000, 0.72, 50, 'bid', seq=9),

        # Eventual recovery
        price_change_event(BASE_TS + 9000, 0.72, 200, 'bid', seq=10),
    ],
    expected_outcomes={
        'shock_detected': True,
        'shock_price': 0.72,
        'reaction_type': 'VACUUM',
        'drop_ratio': 0.96,
        'vacuum_duration_ms': 5900,  # 3100 to 9000
        'attribution_type': 'TRADE_DRIVEN',
        'trade_driven_ratio': 0.96,  # 480/500
    }
)


# =============================================================================
# SCENARIO 2: PULL - Cancel-Driven Depth Removal
# =============================================================================

PULL_CANCEL_DRIVEN = AdversarialScenario(
    name="pull_cancel_driven",
    description="Depth removed by cancellations, not trades",
    description_cn="深度被撤单移除，非成交 → PULL",
    token_id="fixture-pull-001",
    t0=BASE_TS + 5000,
    window_ms=10000,
    tags=["pull", "cancel_driven"],
    raw_events=[
        # Initial book state
        book_snapshot_event(BASE_TS,
            bids=[(0.72, 500), (0.71, 300), (0.70, 200)],
            asks=[(0.73, 400), (0.74, 300), (0.75, 200)]),

        # Steady state
        price_change_event(BASE_TS + 1000, 0.72, 500, 'bid', seq=1),
        price_change_event(BASE_TS + 2000, 0.72, 500, 'bid', seq=2),

        # Small trade (not enough to explain depth drop)
        trade_event(BASE_TS + 3000, 0.72, 50, 'buy', seq=3),

        # Depth drops dramatically (cancellation)
        price_change_event(BASE_TS + 3100, 0.72, 100, 'bid', seq=4),  # 400 cancelled

        # Cancel event recorded
        order_cancelled_event(BASE_TS + 3100, 0.72, 350, 'bid', seq=5),

        # Depth stays low
        price_change_event(BASE_TS + 4000, 0.72, 90, 'bid', seq=6),
        price_change_event(BASE_TS + 5000, 0.72, 80, 'bid', seq=7),
        price_change_event(BASE_TS + 6000, 0.72, 85, 'bid', seq=8),

        # Partial recovery
        price_change_event(BASE_TS + 8000, 0.72, 150, 'bid', seq=9),
    ],
    expected_outcomes={
        'shock_detected': True,
        'reaction_type': 'PULL',
        'drop_ratio': 0.80,  # 500 -> 100
        'attribution_type': 'CANCEL_DRIVEN',
        'trade_driven_ratio': 0.125,  # 50/400 removed
        'cancel_driven_ratio': 0.875,  # 350/400 removed
    }
)


# =============================================================================
# SCENARIO 3: SWEEP - Trade-Driven but Recovers
# =============================================================================

SWEEP_WITH_RECOVERY = AdversarialScenario(
    name="sweep_with_recovery",
    description="Large trade sweeps depth, but quick recovery (not VACUUM)",
    description_cn="大单扫单但快速恢复 → SWEEP 非 VACUUM",
    token_id="fixture-sweep-001",
    t0=BASE_TS + 5000,
    window_ms=10000,
    tags=["sweep", "trade_driven", "recovery"],
    raw_events=[
        # Initial book state
        book_snapshot_event(BASE_TS,
            bids=[(0.72, 500), (0.71, 300), (0.70, 200)],
            asks=[(0.73, 400), (0.74, 300), (0.75, 200)]),

        # Steady state
        price_change_event(BASE_TS + 1000, 0.72, 500, 'bid', seq=1),

        # SHOCK: Large trade
        trade_event(BASE_TS + 3000, 0.72, 450, 'buy', seq=2),

        # Depth drops
        price_change_event(BASE_TS + 3100, 0.72, 50, 'bid', seq=3),

        # Quick recovery within 1 second
        price_change_event(BASE_TS + 3300, 0.72, 150, 'bid', seq=4),
        price_change_event(BASE_TS + 3500, 0.72, 300, 'bid', seq=5),
        price_change_event(BASE_TS + 3800, 0.72, 450, 'bid', seq=6),

        # Sustained recovery
        price_change_event(BASE_TS + 5000, 0.72, 480, 'bid', seq=7),
        price_change_event(BASE_TS + 7000, 0.72, 500, 'bid', seq=8),
    ],
    expected_outcomes={
        'shock_detected': True,
        'reaction_type': 'SWEEP',  # Not VACUUM due to recovery
        'drop_ratio': 0.90,
        'refill_ratio': 0.90,  # 450/500 recovered
        'time_to_refill_ms': 800,  # 3100 to 3800
        'attribution_type': 'TRADE_DRIVEN',
    }
)


# =============================================================================
# SCENARIO 4: SPOOF - Fake Liquidity Cancelled
# =============================================================================

SPOOF_ORDER_CANCEL = AdversarialScenario(
    name="spoof_order_cancel",
    description="Large order appears then cancels before any trades - spoof pattern",
    description_cn="大单出现后立即撤销，无成交 → 疑似幌骗",
    token_id="fixture-spoof-001",
    t0=BASE_TS + 5000,
    window_ms=10000,
    tags=["spoof", "manipulation", "cancel"],
    raw_events=[
        # Initial book state
        book_snapshot_event(BASE_TS,
            bids=[(0.72, 200), (0.71, 150), (0.70, 100)],
            asks=[(0.73, 200), (0.74, 150), (0.75, 100)]),

        # Large order appears (potential spoof)
        price_change_event(BASE_TS + 1000, 0.72, 1500, 'bid', seq=1),  # 7.5x increase

        # Stays briefly
        price_change_event(BASE_TS + 1500, 0.72, 1500, 'bid', seq=2),

        # Cancelled before any trades (spoof signature)
        order_cancelled_event(BASE_TS + 2000, 0.72, 1300, 'bid', seq=3),
        price_change_event(BASE_TS + 2000, 0.72, 200, 'bid', seq=4),

        # Pattern repeats (3 cycles = flagged)
        price_change_event(BASE_TS + 3000, 0.72, 1200, 'bid', seq=5),
        order_cancelled_event(BASE_TS + 3800, 0.72, 1000, 'bid', seq=6),
        price_change_event(BASE_TS + 3800, 0.72, 200, 'bid', seq=7),

        price_change_event(BASE_TS + 5000, 0.72, 1100, 'bid', seq=8),
        order_cancelled_event(BASE_TS + 5700, 0.72, 900, 'bid', seq=9),
        price_change_event(BASE_TS + 5700, 0.72, 200, 'bid', seq=10),
    ],
    expected_outcomes={
        'spoof_cycles_detected': 3,
        'anchor_should_not_include': 0.72,  # Spoof orders not anchors
        'total_cancelled_volume': 3200,
        'total_traded_volume': 0,
    }
)


# =============================================================================
# SCENARIO 5: FLASH_CRASH with Recovery
# =============================================================================

FLASH_CRASH_RECOVERY = AdversarialScenario(
    name="flash_crash_recovery",
    description="Rapid cascade across multiple levels, then full recovery within 30s",
    description_cn="多价位快速连锁下跌后30秒内完全恢复 → 闪崩恢复",
    token_id="fixture-flash-001",
    t0=BASE_TS + 15000,
    window_ms=40000,
    tags=["flash_crash", "cascade", "recovery"],
    raw_events=[
        # Initial healthy book
        book_snapshot_event(BASE_TS,
            bids=[(0.72, 500), (0.71, 400), (0.70, 300), (0.69, 200)],
            asks=[(0.73, 500), (0.74, 400), (0.75, 300), (0.76, 200)]),

        # Stable before crash
        price_change_event(BASE_TS + 5000, 0.72, 500, 'bid', seq=1),

        # CASCADE begins - rapid trades eating through levels
        trade_event(BASE_TS + 10000, 0.72, 480, 'buy', seq=2),
        price_change_event(BASE_TS + 10100, 0.72, 20, 'bid', seq=3),

        trade_event(BASE_TS + 10200, 0.71, 380, 'buy', seq=4),
        price_change_event(BASE_TS + 10300, 0.71, 20, 'bid', seq=5),

        trade_event(BASE_TS + 10400, 0.70, 280, 'buy', seq=6),
        price_change_event(BASE_TS + 10500, 0.70, 20, 'bid', seq=7),

        trade_event(BASE_TS + 10600, 0.69, 180, 'buy', seq=8),
        price_change_event(BASE_TS + 10700, 0.69, 20, 'bid', seq=9),

        # Bottom - all levels evacuated
        price_change_event(BASE_TS + 12000, 0.72, 10, 'bid', seq=10),
        price_change_event(BASE_TS + 12000, 0.71, 10, 'bid', seq=11),
        price_change_event(BASE_TS + 12000, 0.70, 10, 'bid', seq=12),
        price_change_event(BASE_TS + 12000, 0.69, 10, 'bid', seq=13),

        # Recovery begins - gradual refill
        price_change_event(BASE_TS + 20000, 0.69, 100, 'bid', seq=14),
        price_change_event(BASE_TS + 22000, 0.70, 150, 'bid', seq=15),
        price_change_event(BASE_TS + 24000, 0.71, 200, 'bid', seq=16),
        price_change_event(BASE_TS + 26000, 0.72, 250, 'bid', seq=17),

        # Full recovery by 30s
        price_change_event(BASE_TS + 35000, 0.72, 480, 'bid', seq=18),
        price_change_event(BASE_TS + 35000, 0.71, 380, 'bid', seq=19),
        price_change_event(BASE_TS + 35000, 0.70, 280, 'bid', seq=20),
        price_change_event(BASE_TS + 35000, 0.69, 180, 'bid', seq=21),
    ],
    expected_outcomes={
        'cascade_detected': True,
        'levels_affected': 4,
        'cascade_duration_ms': 700,  # 10000 to 10700
        'recovery_time_ms': 25000,   # 10000 to 35000
        'final_state': 'STABLE',     # Recovered, not BROKEN
        'alert_auto_resolved': True,
    }
)


# =============================================================================
# SCENARIO 6: LAYERING - Multi-level Coordinated Withdrawal
# =============================================================================

LAYERING_WITHDRAWAL = AdversarialScenario(
    name="layering_withdrawal",
    description="Multiple levels withdraw simultaneously (coordinated)",
    description_cn="多价位同时撤单，时间标准差<500ms → 分层撤单",
    token_id="fixture-layer-001",
    t0=BASE_TS + 5000,
    window_ms=10000,
    tags=["layering", "manipulation", "coordinated"],
    raw_events=[
        # Initial layered book
        book_snapshot_event(BASE_TS,
            bids=[(0.72, 300), (0.71, 300), (0.70, 300), (0.69, 300), (0.68, 300)],
            asks=[(0.73, 400), (0.74, 300), (0.75, 200)]),

        # Stable
        price_change_event(BASE_TS + 2000, 0.72, 300, 'bid', seq=1),

        # COORDINATED WITHDRAWAL - all levels within 200ms
        # (time_std < 500ms = DEPTH_COLLAPSE)
        price_change_event(BASE_TS + 3000, 0.72, 50, 'bid', seq=2),
        price_change_event(BASE_TS + 3050, 0.71, 50, 'bid', seq=3),
        price_change_event(BASE_TS + 3100, 0.70, 50, 'bid', seq=4),
        price_change_event(BASE_TS + 3150, 0.69, 50, 'bid', seq=5),
        price_change_event(BASE_TS + 3200, 0.68, 50, 'bid', seq=6),

        # Corresponding cancellations
        order_cancelled_event(BASE_TS + 3000, 0.72, 250, 'bid', seq=7),
        order_cancelled_event(BASE_TS + 3050, 0.71, 250, 'bid', seq=8),
        order_cancelled_event(BASE_TS + 3100, 0.70, 250, 'bid', seq=9),
        order_cancelled_event(BASE_TS + 3150, 0.69, 250, 'bid', seq=10),
        order_cancelled_event(BASE_TS + 3200, 0.68, 250, 'bid', seq=11),

        # Stays withdrawn
        price_change_event(BASE_TS + 5000, 0.72, 60, 'bid', seq=12),
        price_change_event(BASE_TS + 7000, 0.72, 80, 'bid', seq=13),
    ],
    expected_outcomes={
        'leading_event_type': 'DEPTH_COLLAPSE',
        'levels_affected': 5,
        'time_std_ms': 70,  # Very coordinated
        'total_cancelled': 1250,  # 250 * 5
        'attribution_type': 'CANCEL_DRIVEN',
    }
)


# =============================================================================
# SCENARIO 7: WASH_TRADE - Self-trade Pattern
# =============================================================================

WASH_TRADE_PATTERN = AdversarialScenario(
    name="wash_trade_pattern",
    description="High volume trades with no price impact - wash trade signature",
    description_cn="高成交量但价格无变化 → 疑似对敲",
    token_id="fixture-wash-001",
    t0=BASE_TS + 5000,
    window_ms=10000,
    tags=["wash_trade", "manipulation", "suspicious"],
    raw_events=[
        # Initial book
        book_snapshot_event(BASE_TS,
            bids=[(0.72, 200), (0.71, 150)],
            asks=[(0.73, 200), (0.74, 150)]),

        # High volume trades at same price - no movement
        trade_event(BASE_TS + 1000, 0.725, 500, 'buy', seq=1),   # Mid-price
        trade_event(BASE_TS + 1100, 0.725, 500, 'sell', seq=2),  # Immediate reversal

        price_change_event(BASE_TS + 1200, 0.72, 200, 'bid', seq=3),  # No change
        price_change_event(BASE_TS + 1200, 0.73, 200, 'ask', seq=4),  # No change

        # More wash trades
        trade_event(BASE_TS + 2000, 0.725, 800, 'buy', seq=5),
        trade_event(BASE_TS + 2050, 0.725, 800, 'sell', seq=6),

        trade_event(BASE_TS + 3000, 0.725, 600, 'buy', seq=7),
        trade_event(BASE_TS + 3030, 0.725, 600, 'sell', seq=8),

        # Book remains unchanged
        price_change_event(BASE_TS + 5000, 0.72, 200, 'bid', seq=9),
        price_change_event(BASE_TS + 5000, 0.73, 200, 'ask', seq=10),
    ],
    expected_outcomes={
        'total_volume': 3800,  # 500+500+800+800+600+600
        'net_price_change': 0,
        'wash_trade_suspected': True,
        'shock_should_not_trigger': True,  # High volume but suspicious
    }
)


# =============================================================================
# SCENARIO 8: QUOTE_STUFFING - Rapid Updates Noise
# =============================================================================

QUOTE_STUFFING_NOISE = AdversarialScenario(
    name="quote_stuffing_noise",
    description="100 updates in 250ms, net-zero change - noise to filter",
    description_cn="250ms内100次更新，净变化为零 → 高频噪音",
    token_id="fixture-stuff-001",
    t0=BASE_TS + 500,
    window_ms=2000,
    tags=["quote_stuffing", "noise", "filter"],
    raw_events=[
        # Initial state
        book_snapshot_event(BASE_TS,
            bids=[(0.72, 200)],
            asks=[(0.73, 200)]),

        # 100 rapid updates in 250ms (oscillating)
        *[
            price_change_event(
                BASE_TS + 300 + (i * 2),  # 2ms apart
                0.72,
                200 + (50 if i % 2 == 0 else -50),  # Oscillate 150-250
                'bid',
                seq=i+1
            )
            for i in range(100)
        ],

        # Final state - same as start
        price_change_event(BASE_TS + 1000, 0.72, 200, 'bid', seq=101),
    ],
    expected_outcomes={
        'raw_event_count': 102,
        'filtered_bucket_count': 2,  # Should reduce to ~2 buckets
        'net_change': 0,
        'should_not_be_signal': True,  # Oscillation = noise
    }
)


# =============================================================================
# SCENARIO 9: PRE_SHOCK_PULL - Information Leakage
# =============================================================================

PRE_SHOCK_PULL = AdversarialScenario(
    name="pre_shock_pull",
    description="Depth pulled just before large trade - potential info leakage",
    description_cn="大单成交前深度先被撤走 → 可能存在信息泄露",
    token_id="fixture-preshock-001",
    t0=BASE_TS + 5000,
    window_ms=10000,
    tags=["pre_shock_pull", "leading_event", "info_leakage"],
    raw_events=[
        # Initial book
        book_snapshot_event(BASE_TS,
            bids=[(0.72, 500), (0.71, 300)],
            asks=[(0.73, 400), (0.74, 300)]),

        # Stable
        price_change_event(BASE_TS + 1000, 0.72, 500, 'bid', seq=1),

        # PRE-SHOCK: Depth pulled 500ms before the trade
        price_change_event(BASE_TS + 2500, 0.72, 100, 'bid', seq=2),  # 80% pulled
        order_cancelled_event(BASE_TS + 2500, 0.72, 400, 'bid', seq=3),

        # SHOCK: Large trade arrives (but less depth to hit)
        trade_event(BASE_TS + 3000, 0.72, 95, 'buy', seq=4),  # Hits remaining
        price_change_event(BASE_TS + 3100, 0.72, 5, 'bid', seq=5),

        # Stays low
        price_change_event(BASE_TS + 5000, 0.72, 10, 'bid', seq=6),
        price_change_event(BASE_TS + 7000, 0.72, 50, 'bid', seq=7),
    ],
    expected_outcomes={
        'leading_event_detected': True,
        'leading_event_type': 'PRE_SHOCK_PULL',
        'lead_time_ms': 500,  # 2500 to 3000
        'pre_pull_volume': 400,
        'shock_volume': 95,
        'attribution_type': 'MIXED',  # Both cancel and trade involved
    }
)


# =============================================================================
# SCENARIO 10: GRADUAL_THINNING - Slow Depth Erosion
# =============================================================================

GRADUAL_THINNING = AdversarialScenario(
    name="gradual_thinning",
    description="Depth slowly erodes over time without obvious trigger",
    description_cn="深度缓慢流失，无明显触发事件 → 逐渐稀薄",
    token_id="fixture-thin-001",
    t0=BASE_TS + 30000,
    window_ms=60000,
    tags=["gradual_thinning", "leading_event", "slow"],
    raw_events=[
        # Initial healthy book
        book_snapshot_event(BASE_TS,
            bids=[(0.72, 500), (0.71, 400), (0.70, 300)],
            asks=[(0.73, 400)]),

        # Gradual decline over 60 seconds
        price_change_event(BASE_TS + 5000, 0.72, 450, 'bid', seq=1),
        price_change_event(BASE_TS + 10000, 0.72, 400, 'bid', seq=2),
        price_change_event(BASE_TS + 15000, 0.72, 350, 'bid', seq=3),
        price_change_event(BASE_TS + 20000, 0.72, 300, 'bid', seq=4),
        price_change_event(BASE_TS + 25000, 0.72, 250, 'bid', seq=5),
        price_change_event(BASE_TS + 30000, 0.72, 200, 'bid', seq=6),
        price_change_event(BASE_TS + 35000, 0.72, 150, 'bid', seq=7),
        price_change_event(BASE_TS + 40000, 0.72, 100, 'bid', seq=8),
        price_change_event(BASE_TS + 45000, 0.72, 80, 'bid', seq=9),
        price_change_event(BASE_TS + 50000, 0.72, 60, 'bid', seq=10),
        price_change_event(BASE_TS + 55000, 0.72, 50, 'bid', seq=11),

        # Small trades scattered throughout
        trade_event(BASE_TS + 8000, 0.72, 20, 'buy', seq=12),
        trade_event(BASE_TS + 22000, 0.72, 15, 'buy', seq=13),
        trade_event(BASE_TS + 38000, 0.72, 25, 'buy', seq=14),
    ],
    expected_outcomes={
        'leading_event_detected': True,
        'leading_event_type': 'GRADUAL_THINNING',
        'total_depth_lost': 450,  # 500 -> 50
        'total_traded': 60,
        'thinning_rate_per_min': 9.0,  # 450 / 50s * 60
        'attribution_type': 'CANCEL_DRIVEN',  # 390/450 = 87% cancelled
    }
)


# =============================================================================
# Scenario Registry
# =============================================================================

SCENARIOS: Dict[str, AdversarialScenario] = {
    'vacuum_at_anchor': VACUUM_AT_ANCHOR,
    'pull_cancel_driven': PULL_CANCEL_DRIVEN,
    'sweep_with_recovery': SWEEP_WITH_RECOVERY,
    'spoof_order_cancel': SPOOF_ORDER_CANCEL,
    'flash_crash_recovery': FLASH_CRASH_RECOVERY,
    'layering_withdrawal': LAYERING_WITHDRAWAL,
    'wash_trade_pattern': WASH_TRADE_PATTERN,
    'quote_stuffing_noise': QUOTE_STUFFING_NOISE,
    'pre_shock_pull': PRE_SHOCK_PULL,
    'gradual_thinning': GRADUAL_THINNING,
}


def get_scenario(name: str) -> Optional[AdversarialScenario]:
    """Get a scenario by name"""
    return SCENARIOS.get(name)


def list_scenarios(tags: Optional[List[str]] = None) -> List[str]:
    """List scenario names, optionally filtered by tags"""
    if tags is None:
        return list(SCENARIOS.keys())
    return [
        name for name, scenario in SCENARIOS.items()
        if any(tag in scenario.tags for tag in tags)
    ]


def get_scenarios_by_tag(tag: str) -> List[AdversarialScenario]:
    """Get all scenarios with a specific tag"""
    return [s for s in SCENARIOS.values() if tag in s.tags]
