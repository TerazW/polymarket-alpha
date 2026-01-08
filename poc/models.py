"""
Belief Reaction System - Data Models v3
Core data structures for the reaction detection system.

v2 改进:
- ShockEvent 添加 baseline_size
- ReactionMetrics 添加 drop_ratio, vacuum_duration
- ReactionEvent 添加 window_type (FAST/SLOW)
- 添加 SWEEP 反应类型
- 添加领先事件类型

v3 改进:
- 添加 NO_IMPACT 反应类型 (drop 太小不计算 refill)
- 添加 GRADUAL_THINNING 领先事件类型
- ReactionMetrics 添加 is_valid_drop 标记
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional, Literal, List
import time
import uuid


class ReactionType(Enum):
    """
    反应类型 - 系统的核心词汇表
    按优先级排序（分类时先检查优先级高的）

    这些描述的是可观察的冲击后市场行为，不是意图、预期或方向。
    """
    VACUUM = "VACUUM"       # 1. 流动性低于阈值且持续
    SWEEP = "SWEEP"         # 2. 连续成交移除多档流动性
    CHASE = "CHASE"         # 3. 流动性仅在偏移后的价位重现
    PULL = "PULL"           # 4. 冲击后流动性立即被取消（撤单）
    HOLD = "HOLD"           # 5. 流动性在限定时间窗口内补充
    DELAYED = "DELAYED"     # 6. 流动性延迟或部分补充
    NO_IMPACT = "NO_IMPACT" # 7. 观察到的变化未超过反应阈值


class LeadingEventType(Enum):
    """
    领先事件类型 - 不靠成交触发的预警信号
    这是系统"领先"于价格的核心来源
    """
    PRE_SHOCK_PULL = "PRE_SHOCK_PULL"       # 无成交撤退（信息前兆）
    DEPTH_COLLAPSE = "DEPTH_COLLAPSE"       # 多价位同步塌陷
    GRADUAL_THINNING = "GRADUAL_THINNING"   # [v3] 渐进撤退（慢慢撤离）


class WindowType(Enum):
    """
    反应窗口类型

    FAST: 即时冲击后反应检测
    SLOW: 持续性确认 / 延迟反应解决 / 冲击后稳定检查
          注意：不是"趋势确认"，系统不确认趋势
    """
    FAST = "FAST"   # 8 秒窗口 - 即时反应
    SLOW = "SLOW"   # 30 秒窗口 - 持续性确认


class BeliefState(Enum):
    """Four belief states for the state machine."""
    STABLE = "STABLE"       # Market belief is firm/consistent
    FRAGILE = "FRAGILE"     # Market belief shows weakness
    CRACKING = "CRACKING"   # Market belief actively breaking
    BROKEN = "BROKEN"       # Market belief has collapsed


# State indicators for display
STATE_INDICATORS = {
    BeliefState.STABLE: "🟢",
    BeliefState.FRAGILE: "🟡",
    BeliefState.CRACKING: "🟠",
    BeliefState.BROKEN: "🔴",
}

REACTION_INDICATORS = {
    ReactionType.VACUUM: "🔴",
    ReactionType.SWEEP: "🟣",
    ReactionType.CHASE: "🔵",
    ReactionType.PULL: "🟠",
    ReactionType.HOLD: "🟢",
    ReactionType.DELAYED: "🟡",
    ReactionType.NO_IMPACT: "⚪",  # v3: 无意义冲击
}


@dataclass
class PriceLevel:
    """
    Represents a single price level in the order book.
    This is the fundamental observation unit.
    """
    token_id: str
    price: Decimal
    side: Literal['bid', 'ask']

    # Current state
    size_now: float = 0.0
    size_peak: float = 0.0
    first_seen_ts: int = 0
    last_update_ts: int = 0

    # Size history for baseline calculation (最近 1 秒的采样)
    size_history: List[tuple] = field(default_factory=list)  # [(ts, size), ...]

    # Behavioral statistics
    hit_count: int = 0
    last_hit_ts: int = 0
    refill_count: int = 0
    cancel_count: int = 0

    def __post_init__(self):
        if self.first_seen_ts == 0:
            self.first_seen_ts = int(time.time() * 1000)
        if self.last_update_ts == 0:
            self.last_update_ts = self.first_seen_ts

    def update_size(self, new_size: float, timestamp: int) -> float:
        """Update size and return delta."""
        old_size = self.size_now
        self.size_now = new_size
        self.size_peak = max(self.size_peak, new_size)
        self.last_update_ts = timestamp

        # 记录历史（保留最近 1 秒）
        self.size_history.append((timestamp, new_size))
        cutoff = timestamp - 1000
        self.size_history = [(ts, sz) for ts, sz in self.size_history if ts > cutoff]

        return new_size - old_size

    def get_baseline_size(self, current_ts: int, window_start_ms: int = 500, window_end_ms: int = 100) -> float:
        """
        计算稳定基准深度（中位数）
        使用 [t0 - window_start_ms, t0 - window_end_ms] 范围内的样本
        """
        start_cutoff = current_ts - window_start_ms
        end_cutoff = current_ts - window_end_ms

        samples = [sz for ts, sz in self.size_history if start_cutoff <= ts <= end_cutoff]

        if not samples:
            # 退化为当前值
            return self.size_now

        # 返回中位数
        samples.sort()
        n = len(samples)
        if n % 2 == 0:
            return (samples[n // 2 - 1] + samples[n // 2]) / 2
        return samples[n // 2]


@dataclass
class TradeEvent:
    """A single trade execution."""
    token_id: str
    price: Decimal
    size: float
    side: Literal['BUY', 'SELL']
    timestamp: int  # milliseconds

    @classmethod
    def from_ws_message(cls, msg: dict) -> 'TradeEvent':
        """Create from WebSocket last_trade_price message."""
        return cls(
            token_id=msg.get('asset_id', ''),
            price=Decimal(str(msg.get('price', '0'))),
            size=float(msg.get('size', 0)),
            side=msg.get('side', 'BUY').upper(),
            timestamp=int(msg.get('timestamp', 0))
        )


@dataclass
class ShockEvent:
    """
    A shock event where a price level is significantly impacted.
    Shock = discrete event where trading activity tests a level.

    v2: 添加 baseline_size 用于更准确的反应计算
    """
    shock_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    token_id: str = ""
    price: Decimal = Decimal("0")
    side: Literal['bid', 'ask'] = 'bid'
    ts_start: int = 0
    trade_volume: float = 0.0
    liquidity_before: float = 0.0   # 冲击前的单点深度（兼容）
    baseline_size: float = 0.0      # v2: 稳定基准深度（中位数）
    trigger_type: Literal['volume', 'consecutive'] = 'volume'
    tick_size: Decimal = Decimal("0.01")  # 当时的 tick_size

    # 双窗口结束时间
    reaction_window_end: int = 0       # SLOW 窗口结束时间（兼容旧字段）
    fast_window_end: int = 0           # FAST 窗口结束时间
    slow_window_end: int = 0           # SLOW 窗口结束时间


@dataclass
class ReactionMetrics:
    """
    Metrics computed at the end of the reaction window.
    These determine the reaction classification.

    v2: 添加 drop_ratio, vacuum_duration, shift_ticks
    """
    window_type: WindowType = WindowType.FAST

    # Liquidity changes
    net_liquidity_change: float = 0.0
    min_liquidity: float = 0.0
    max_liquidity: float = 0.0
    end_size: float = 0.0

    # Drop metrics
    drop_ratio: float = 0.0           # (baseline - min) / baseline

    # Refill behavior
    refill_ratio: float = 0.0         # (max - min) / (baseline - min)
    time_to_refill_ms: Optional[int] = None

    # Vacuum detection
    vacuum_duration_ms: int = 0       # 低于 2% 的持续时间

    # Speed indicators
    cancel_speed: Literal['instant', 'fast', 'slow', 'none'] = 'none'

    # Price movement
    price_shift: Decimal = Decimal("0")
    shift_ticks: int = 0              # 偏移多少个 tick


@dataclass
class ReactionEvent:
    """
    A classified reaction after observing the reaction window.
    This is what the system outputs.

    v2: 添加 window_type, drop_ratio
    """
    reaction_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    shock_id: str = ""
    timestamp: int = 0
    token_id: str = ""
    price: Decimal = Decimal("0")
    side: Literal['bid', 'ask'] = 'bid'
    reaction_type: ReactionType = ReactionType.DELAYED
    window_type: WindowType = WindowType.FAST

    # Metrics snapshot
    baseline_size: float = 0.0        # v2: 基准深度
    refill_ratio: float = 0.0
    drop_ratio: float = 0.0           # v2
    time_to_refill_ms: Optional[int] = None
    min_liquidity: float = 0.0
    max_liquidity: float = 0.0        # v2
    vacuum_duration_ms: int = 0       # v2
    shift_ticks: int = 0              # v2
    price_shift: Decimal = Decimal("0")
    liquidity_before: float = 0.0     # For context (兼容)


@dataclass
class LeadingEvent:
    """
    领先事件 - 不靠成交触发的预警信号
    这是系统"领先"于价格的核心来源
    """
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: LeadingEventType = LeadingEventType.PRE_SHOCK_PULL
    timestamp: int = 0
    token_id: str = ""
    price: Decimal = Decimal("0")
    side: Literal['bid', 'ask'] = 'bid'

    # PRE_SHOCK_PULL 特有字段
    drop_ratio: float = 0.0           # 下降比例
    duration_ms: int = 0              # 持续时间
    trade_volume_nearby: float = 0.0  # 附近成交量
    is_anchor: bool = False           # 是否为关键价位

    # DEPTH_COLLAPSE 特有字段
    affected_levels: int = 0          # 受影响的价位数
    time_std_ms: float = 0.0          # 时间标准差

    # [v3] GRADUAL_THINNING 特有字段
    total_depth_before: float = 0.0   # 窗口开始时的总深度
    total_depth_after: float = 0.0    # 窗口结束时的总深度
    trade_driven_ratio: float = 0.0   # 成交驱动的占比


@dataclass
class BeliefStateChange:
    """Records a belief state transition."""
    timestamp: int
    token_id: str
    old_state: BeliefState
    new_state: BeliefState
    trigger_reaction_id: Optional[str] = None
    trigger_leading_event_id: Optional[str] = None  # v2
    evidence: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)  # v2: 证据回放链接


@dataclass
class AnchorLevel:
    """
    关键价位 - 用于领先事件检测
    """
    token_id: str
    price: Decimal
    side: Literal['bid', 'ask']
    peak_size: float = 0.0
    persistence_seconds: float = 0.0
    anchor_score: float = 0.0
    rank: int = 0  # 1 = 最重要
