"""
Belief Reaction System - Leading Events Detector v3
检测不靠成交触发的领先预警信号。

这是系统从"成交驱动"升级为"行为领先"的核心模块。

三种领先事件:
1. PRE_SHOCK_PULL: 无成交撤退（信息前兆）
2. DEPTH_COLLAPSE: 多价位同步塌陷（恐慌信号）
3. [v3] GRADUAL_THINNING: 渐进撤退（慢慢撤离）

关键价位选择 (Anchor Levels):
- 基于 peak_size 和 persistence 评分
- 只在 Anchor 价位上检测 PRE_SHOCK_PULL
"""

from collections import defaultdict
from decimal import Decimal
from typing import Optional, Dict, List, Tuple, Set
from dataclasses import dataclass, field
import time
import math

# v5.13: Determinism infrastructure
from backend.common.determinism import deterministic_now

from .models import (
    LeadingEvent, LeadingEventType, AnchorLevel, PriceLevel
)
from .config import (
    # PRE_SHOCK_PULL
    PRE_SHOCK_PULL_WINDOW_MS,
    PRE_SHOCK_PULL_DROP_FROM,
    PRE_SHOCK_PULL_DROP_TO,
    PRE_SHOCK_SMALL_TRADE_RATIO,
    PRE_SHOCK_SMALL_TRADE_ABS,
    # DEPTH_COLLAPSE
    DEPTH_COLLAPSE_WINDOW_MS,
    DEPTH_COLLAPSE_TICKS,
    DEPTH_COLLAPSE_MIN_LEVELS,
    DEPTH_COLLAPSE_DROP_RATIO,
    DEPTH_COLLAPSE_TIME_STD_MS,
    # [v3] GRADUAL_THINNING
    GRADUAL_THINNING_WINDOW_MS,
    GRADUAL_THINNING_TICKS,
    GRADUAL_THINNING_DROP_RATIO,
    GRADUAL_THINNING_TRADE_RATIO,
    # ANCHOR
    ANCHOR_LOOKBACK_HOURS,
    ANCHOR_PERSISTENCE_THETA,
    ANCHOR_WEIGHT_PEAK,
    ANCHOR_WEIGHT_PERSISTENCE,
    ANCHOR_TOP_K
)


@dataclass
class LevelSnapshot:
    """价位快照，用于检测变化"""
    timestamp: int
    size: float
    baseline: float  # 基准深度


class AnchorLevelTracker:
    """
    关键价位追踪器

    选择标准 (Spec 2):
    - peak_size: 历史最大深度
    - persistence: 保持在 50% peak 以上的时间
    - anchor_score = w1 * log(1+peak) + w2 * log(1+persistence_seconds)
    """

    def __init__(self):
        # 每个 token 的价位统计
        # {token_id: {(price_str, side): {'peak': float, 'persistence_ms': int, 'above_threshold_since': int}}}
        self.level_stats: Dict[str, Dict[Tuple[str, str], dict]] = defaultdict(dict)

        # 当前 anchor 集合
        # {token_id: [AnchorLevel, ...]}
        self.anchors: Dict[str, List[AnchorLevel]] = {}

        # 上次更新时间
        self.last_anchor_update: Dict[str, int] = {}

    def update_level(self, level: PriceLevel, timestamp: int):
        """更新价位统计"""
        token_id = level.token_id
        key = (str(level.price), level.side)

        if key not in self.level_stats[token_id]:
            self.level_stats[token_id][key] = {
                'peak': 0.0,
                'persistence_ms': 0,
                'above_threshold_since': None,
                'price': level.price,
                'side': level.side
            }

        stats = self.level_stats[token_id][key]

        # 更新 peak
        if level.size_now > stats['peak']:
            stats['peak'] = level.size_now

        # 更新 persistence
        threshold = ANCHOR_PERSISTENCE_THETA * stats['peak']

        if level.size_now >= threshold:
            if stats['above_threshold_since'] is None:
                stats['above_threshold_since'] = timestamp
        else:
            if stats['above_threshold_since'] is not None:
                stats['persistence_ms'] += timestamp - stats['above_threshold_since']
                stats['above_threshold_since'] = None

    def compute_anchors(self, token_id: str, current_time: int) -> List[AnchorLevel]:
        """计算关键价位"""
        if token_id not in self.level_stats:
            return []

        # 计算每个价位的分数
        scored_levels = []

        for key, stats in self.level_stats[token_id].items():
            # 如果当前仍在 threshold 以上，累加时间
            if stats['above_threshold_since'] is not None:
                persistence_ms = stats['persistence_ms'] + (current_time - stats['above_threshold_since'])
            else:
                persistence_ms = stats['persistence_ms']

            persistence_seconds = persistence_ms / 1000.0

            # 计算分数
            score = (
                ANCHOR_WEIGHT_PEAK * math.log(1 + stats['peak']) +
                ANCHOR_WEIGHT_PERSISTENCE * math.log(1 + persistence_seconds)
            )

            scored_levels.append({
                'price': stats['price'],
                'side': stats['side'],
                'peak': stats['peak'],
                'persistence_seconds': persistence_seconds,
                'score': score
            })

        # 按分数排序，取 top K
        scored_levels.sort(key=lambda x: x['score'], reverse=True)
        top_levels = scored_levels[:ANCHOR_TOP_K]

        anchors = []
        for i, level in enumerate(top_levels):
            anchors.append(AnchorLevel(
                token_id=token_id,
                price=level['price'],
                side=level['side'],
                peak_size=level['peak'],
                persistence_seconds=level['persistence_seconds'],
                anchor_score=level['score'],
                rank=i + 1
            ))

        self.anchors[token_id] = anchors
        self.last_anchor_update[token_id] = current_time

        return anchors

    def get_anchors(self, token_id: str) -> List[AnchorLevel]:
        """获取当前 anchor 列表"""
        return self.anchors.get(token_id, [])

    def is_anchor(self, token_id: str, price: Decimal, side: str) -> bool:
        """检查是否为关键价位"""
        anchors = self.anchors.get(token_id, [])
        for anchor in anchors:
            if anchor.price == price and anchor.side == side:
                return True
        return False

    def get_anchor_rank(self, token_id: str, price: Decimal, side: str) -> int:
        """获取 anchor 排名 (0 = 不是 anchor)"""
        anchors = self.anchors.get(token_id, [])
        for anchor in anchors:
            if anchor.price == price and anchor.side == side:
                return anchor.rank
        return 0


class PreShockPullDetector:
    """
    PRE_SHOCK_PULL 检测器

    触发条件 (Spec 1):
    - 在 3s 内从 >= 80% baseline 降到 <= 20% baseline
    - 同时成交量很小 (< 5% baseline 或 < 50)
    - 且发生在关键价位 (Anchor)
    """

    def __init__(self, anchor_tracker: AnchorLevelTracker):
        self.anchor_tracker = anchor_tracker

        # 价位快照历史 {(token_id, price_str, side): [LevelSnapshot, ...]}
        self.level_history: Dict[Tuple[str, str, str], List[LevelSnapshot]] = defaultdict(list)

        # 附近成交量 {(token_id, price_str): [(timestamp, size), ...]}
        self.nearby_trades: Dict[Tuple[str, str], List[Tuple[int, float]]] = defaultdict(list)

        # 已检测的事件 (避免重复)
        self.detected_events: Set[Tuple[str, str, str, int]] = set()

        # 统计
        self.total_detected = 0

    def record_level_snapshot(
        self,
        token_id: str,
        price: Decimal,
        side: str,
        size: float,
        baseline: float,
        timestamp: int
    ):
        """记录价位快照"""
        key = (token_id, str(price), side)
        snapshot = LevelSnapshot(timestamp=timestamp, size=size, baseline=baseline)

        self.level_history[key].append(snapshot)

        # 清理旧数据 (保留 5s)
        cutoff = timestamp - 5000
        self.level_history[key] = [
            s for s in self.level_history[key] if s.timestamp > cutoff
        ]

    def record_trade(self, token_id: str, price: Decimal, size: float, timestamp: int):
        """记录成交"""
        key = (token_id, str(price))
        self.nearby_trades[key].append((timestamp, size))

        # 清理旧数据 (保留 5s)
        cutoff = timestamp - 5000
        self.nearby_trades[key] = [
            (ts, sz) for ts, sz in self.nearby_trades[key] if ts > cutoff
        ]

    def check_pre_shock_pull(
        self,
        token_id: str,
        price: Decimal,
        side: str,
        current_time: int
    ) -> Optional[LeadingEvent]:
        """检查是否触发 PRE_SHOCK_PULL"""
        key = (token_id, str(price), side)
        history = self.level_history.get(key, [])

        if len(history) < 2:
            return None

        # 检查是否为 anchor
        is_anchor = self.anchor_tracker.is_anchor(token_id, price, side)

        # 获取最新快照
        latest = history[-1]
        baseline = latest.baseline

        if baseline <= 0:
            return None

        current_ratio = latest.size / baseline

        # 只在当前低于阈值时检查
        if current_ratio > PRE_SHOCK_PULL_DROP_TO:
            return None

        # 寻找窗口内从高位下降的点
        window_start = current_time - PRE_SHOCK_PULL_WINDOW_MS

        high_point = None
        for snapshot in history:
            if snapshot.timestamp < window_start:
                continue
            ratio = snapshot.size / baseline
            if ratio >= PRE_SHOCK_PULL_DROP_FROM:
                high_point = snapshot
                break

        if high_point is None:
            return None

        # 计算持续时间
        duration_ms = current_time - high_point.timestamp

        # 检查附近成交量
        trade_key = (token_id, str(price))
        trades_in_window = [
            (ts, sz) for ts, sz in self.nearby_trades.get(trade_key, [])
            if high_point.timestamp <= ts <= current_time
        ]
        total_trade_volume = sum(sz for _, sz in trades_in_window)

        # 成交量阈值
        small_trade_threshold = max(
            PRE_SHOCK_SMALL_TRADE_RATIO * baseline,
            PRE_SHOCK_SMALL_TRADE_ABS
        )

        if total_trade_volume >= small_trade_threshold:
            return None  # 成交量太大，不是无成交撤退

        # 避免重复检测
        event_key = (token_id, str(price), side, high_point.timestamp // 1000)  # 秒级去重
        if event_key in self.detected_events:
            return None

        self.detected_events.add(event_key)
        self.total_detected += 1

        # 计算 drop_ratio
        drop_ratio = (high_point.size - latest.size) / high_point.size

        return LeadingEvent(
            event_type=LeadingEventType.PRE_SHOCK_PULL,
            timestamp=current_time,
            token_id=token_id,
            price=price,
            side=side,
            drop_ratio=drop_ratio,
            duration_ms=duration_ms,
            trade_volume_nearby=total_trade_volume,
            is_anchor=is_anchor
        )

    def get_stats(self) -> dict:
        return {
            "total_detected": self.total_detected,
            "tracked_levels": len(self.level_history)
        }


class DepthCollapseDetector:
    """
    DEPTH_COLLAPSE 检测器

    触发条件 (Spec 1):
    - 在 5s 内，同一侧 (bid/ask)
    - 在 best ± N ticks 范围内
    - >= M 个价位的 drop_ratio >= 60%
    - 这些 drop 时间高度集中 (标准差 < 1s)
    """

    def __init__(self):
        # 价位下降事件 {(token_id, side): [(timestamp, price, drop_ratio), ...]}
        self.drop_events: Dict[Tuple[str, str], List[Tuple[int, Decimal, float]]] = defaultdict(list)

        # 已检测的事件
        self.detected_events: Set[Tuple[str, str, int]] = set()

        # 统计
        self.total_detected = 0

    def record_drop(
        self,
        token_id: str,
        price: Decimal,
        side: str,
        drop_ratio: float,
        timestamp: int
    ):
        """记录价位下降事件"""
        if drop_ratio < DEPTH_COLLAPSE_DROP_RATIO:
            return

        key = (token_id, side)
        self.drop_events[key].append((timestamp, price, drop_ratio))

        # 清理旧数据 (保留 10s)
        cutoff = timestamp - 10000
        self.drop_events[key] = [
            (ts, p, dr) for ts, p, dr in self.drop_events[key] if ts > cutoff
        ]

    def check_depth_collapse(
        self,
        token_id: str,
        side: str,
        best_price: Decimal,
        tick_size: Decimal,
        current_time: int
    ) -> Optional[LeadingEvent]:
        """检查是否触发 DEPTH_COLLAPSE"""
        key = (token_id, side)
        events = self.drop_events.get(key, [])

        if len(events) < DEPTH_COLLAPSE_MIN_LEVELS:
            return None

        # 过滤窗口内的事件
        window_start = current_time - DEPTH_COLLAPSE_WINDOW_MS
        recent_events = [
            (ts, p, dr) for ts, p, dr in events if ts >= window_start
        ]

        if len(recent_events) < DEPTH_COLLAPSE_MIN_LEVELS:
            return None

        # 过滤在价格范围内的事件
        price_range = DEPTH_COLLAPSE_TICKS * tick_size
        in_range_events = []

        for ts, p, dr in recent_events:
            if abs(p - best_price) <= price_range:
                in_range_events.append((ts, p, dr))

        if len(in_range_events) < DEPTH_COLLAPSE_MIN_LEVELS:
            return None

        # 检查时间同步性 (标准差 < 1s)
        timestamps = [ts for ts, _, _ in in_range_events]
        mean_ts = sum(timestamps) / len(timestamps)
        variance = sum((ts - mean_ts) ** 2 for ts in timestamps) / len(timestamps)
        std_ms = math.sqrt(variance)

        if std_ms > DEPTH_COLLAPSE_TIME_STD_MS:
            return None

        # 避免重复检测
        event_key = (token_id, side, int(mean_ts) // 1000)
        if event_key in self.detected_events:
            return None

        self.detected_events.add(event_key)
        self.total_detected += 1

        # 计算平均 drop_ratio
        avg_drop = sum(dr for _, _, dr in in_range_events) / len(in_range_events)

        return LeadingEvent(
            event_type=LeadingEventType.DEPTH_COLLAPSE,
            timestamp=current_time,
            token_id=token_id,
            price=best_price,
            side=side,
            drop_ratio=avg_drop,
            affected_levels=len(in_range_events),
            time_std_ms=std_ms
        )

    def get_stats(self) -> dict:
        return {
            "total_detected": self.total_detected,
            "tracked_sides": len(self.drop_events)
        }


class GradualThinningDetector:
    """
    [v3] GRADUAL_THINNING 检测器 - 渐进撤退

    触发条件:
    - 在 60s 内，best ± N ticks 范围内的总深度下降 >= 40%
    - 成交驱动占比 < 10% (即不是被动消耗，而是主动撤退)

    这是"风险上升/参与者退出"的另一种领先信号，
    与 DEPTH_COLLAPSE (同步撤离) 互补。
    """

    def __init__(self):
        # 深度快照历史 {(token_id, side): [(timestamp, total_depth, trade_volume), ...]}
        self.depth_history: Dict[Tuple[str, str], List[Tuple[int, float, float]]] = defaultdict(list)

        # 累计成交量 {(token_id, side): [(timestamp, volume), ...]}
        self.trade_volumes: Dict[Tuple[str, str], List[Tuple[int, float]]] = defaultdict(list)

        # 已检测的事件
        self.detected_events: Set[Tuple[str, str, int]] = set()

        # 统计
        self.total_detected = 0

    def record_depth_snapshot(
        self,
        token_id: str,
        side: str,
        total_depth: float,
        timestamp: int
    ):
        """记录总深度快照"""
        key = (token_id, side)
        self.depth_history[key].append((timestamp, total_depth, 0.0))

        # 清理旧数据 (保留 90s)
        cutoff = timestamp - 90000
        self.depth_history[key] = [
            (ts, d, v) for ts, d, v in self.depth_history[key] if ts > cutoff
        ]

    def record_trade(
        self,
        token_id: str,
        side: str,
        volume: float,
        timestamp: int
    ):
        """记录成交量"""
        key = (token_id, side)
        self.trade_volumes[key].append((timestamp, volume))

        # 清理旧数据 (保留 90s)
        cutoff = timestamp - 90000
        self.trade_volumes[key] = [
            (ts, v) for ts, v in self.trade_volumes[key] if ts > cutoff
        ]

    def check_gradual_thinning(
        self,
        token_id: str,
        side: str,
        current_time: int
    ) -> Optional[LeadingEvent]:
        """检查是否触发 GRADUAL_THINNING"""
        key = (token_id, side)
        history = self.depth_history.get(key, [])

        if len(history) < 2:
            return None

        # 找到窗口开始时的深度
        window_start = current_time - GRADUAL_THINNING_WINDOW_MS

        start_depth = None
        for ts, depth, _ in history:
            if ts >= window_start:
                start_depth = depth
                break

        if start_depth is None or start_depth <= 0:
            return None

        # 当前深度
        current_depth = history[-1][1]

        # 计算下降比例
        depth_drop_ratio = (start_depth - current_depth) / start_depth

        if depth_drop_ratio < GRADUAL_THINNING_DROP_RATIO:
            return None

        # 计算成交驱动占比
        trades = self.trade_volumes.get(key, [])
        total_trade_volume = sum(
            v for ts, v in trades
            if window_start <= ts <= current_time
        )

        depth_lost = start_depth - current_depth
        trade_driven_ratio = total_trade_volume / depth_lost if depth_lost > 0 else 0

        if trade_driven_ratio >= GRADUAL_THINNING_TRADE_RATIO:
            return None  # 成交驱动太多，不算渐进撤退

        # 避免重复检测 (每分钟最多一次)
        event_key = (token_id, side, current_time // 60000)
        if event_key in self.detected_events:
            return None

        self.detected_events.add(event_key)
        self.total_detected += 1

        return LeadingEvent(
            event_type=LeadingEventType.GRADUAL_THINNING,
            timestamp=current_time,
            token_id=token_id,
            price=Decimal("0"),  # GRADUAL_THINNING 不特定于某个价位
            side=side,
            drop_ratio=depth_drop_ratio,
            duration_ms=GRADUAL_THINNING_WINDOW_MS,
            total_depth_before=start_depth,
            total_depth_after=current_depth,
            trade_driven_ratio=trade_driven_ratio
        )

    def get_stats(self) -> dict:
        return {
            "total_detected": self.total_detected,
            "tracked_sides": len(self.depth_history)
        }


class LeadingEventDetector:
    """
    领先事件检测器（总入口）v3

    整合:
    - AnchorLevelTracker: 关键价位选择
    - PreShockPullDetector: 无成交撤退
    - DepthCollapseDetector: 多价位同步塌陷
    - [v3] GradualThinningDetector: 渐进撤退
    """

    def __init__(self):
        self.anchor_tracker = AnchorLevelTracker()
        self.pre_shock_detector = PreShockPullDetector(self.anchor_tracker)
        self.depth_collapse_detector = DepthCollapseDetector()
        self.gradual_thinning_detector = GradualThinningDetector()  # v3

        # 收集到的领先事件
        self.events: List[LeadingEvent] = []

        # 统计
        self.total_events = 0
        self.events_by_type: Dict[LeadingEventType, int] = defaultdict(int)

    def on_level_update(
        self,
        level: PriceLevel,
        baseline: float,
        timestamp: int,
        best_price: Optional[Decimal] = None,
        tick_size: Decimal = Decimal("0.01")
    ) -> List[LeadingEvent]:
        """
        处理价位更新，检测领先事件

        Returns:
            检测到的领先事件列表
        """
        detected = []

        # 更新 anchor 统计
        self.anchor_tracker.update_level(level, timestamp)

        # 记录快照
        self.pre_shock_detector.record_level_snapshot(
            level.token_id, level.price, level.side,
            level.size_now, baseline, timestamp
        )

        # 计算 drop_ratio
        if baseline > 0:
            drop_ratio = (baseline - level.size_now) / baseline

            # 记录下降事件
            self.depth_collapse_detector.record_drop(
                level.token_id, level.price, level.side,
                drop_ratio, timestamp
            )

        # 检测 PRE_SHOCK_PULL
        pre_shock = self.pre_shock_detector.check_pre_shock_pull(
            level.token_id, level.price, level.side, timestamp
        )
        if pre_shock:
            detected.append(pre_shock)
            self.events_by_type[LeadingEventType.PRE_SHOCK_PULL] += 1

        # 检测 DEPTH_COLLAPSE (只在最佳价格附近)
        if best_price is not None:
            collapse = self.depth_collapse_detector.check_depth_collapse(
                level.token_id, level.side, best_price, tick_size, timestamp
            )
            if collapse:
                detected.append(collapse)
                self.events_by_type[LeadingEventType.DEPTH_COLLAPSE] += 1

        # 记录事件
        self.events.extend(detected)
        self.total_events += len(detected)

        return detected

    def on_trade(self, token_id: str, price: Decimal, size: float, timestamp: int):
        """记录成交（用于 PRE_SHOCK_PULL 检测）"""
        self.pre_shock_detector.record_trade(token_id, price, size, timestamp)

    def on_book_depth_update(
        self,
        token_id: str,
        side: str,
        total_depth: float,
        trade_volume: float,
        timestamp: int
    ) -> Optional[LeadingEvent]:
        """
        [v3] 记录总深度更新，用于 GRADUAL_THINNING 检测

        Args:
            token_id: Token ID
            side: 'bid' or 'ask'
            total_depth: 当前 best ± N ticks 范围内的总深度
            trade_volume: 自上次更新以来的成交量
            timestamp: 时间戳

        Returns:
            检测到的 GRADUAL_THINNING 事件 (如果有)
        """
        # 记录深度和成交
        self.gradual_thinning_detector.record_depth_snapshot(
            token_id, side, total_depth, timestamp
        )
        if trade_volume > 0:
            self.gradual_thinning_detector.record_trade(
                token_id, side, trade_volume, timestamp
            )

        # 检测 GRADUAL_THINNING
        thinning = self.gradual_thinning_detector.check_gradual_thinning(
            token_id, side, timestamp
        )
        if thinning:
            self.events.append(thinning)
            self.total_events += 1
            self.events_by_type[LeadingEventType.GRADUAL_THINNING] += 1
            return thinning

        return None

    def update_anchors(self, token_id: str, current_time: int) -> List[AnchorLevel]:
        """更新 anchor 列表"""
        return self.anchor_tracker.compute_anchors(token_id, current_time)

    def get_anchors(self, token_id: str) -> List[AnchorLevel]:
        """获取当前 anchor 列表"""
        return self.anchor_tracker.get_anchors(token_id)

    def get_recent_events(self, window_ms: int = 60000, reference_ts: int = None) -> List[LeadingEvent]:
        """
        获取最近的领先事件

        v5.13: 支持传入参考时间以确保确定性
        """
        # v5.13: Use reference timestamp if provided, otherwise deterministic clock
        current_time = reference_ts if reference_ts else deterministic_now(context="LeadingEventDetector.get_recent_events")
        cutoff = current_time - window_ms
        return [e for e in self.events if e.timestamp >= cutoff]

    def get_stats(self) -> dict:
        return {
            "total_events": self.total_events,
            "by_type": {t.value: c for t, c in self.events_by_type.items()},
            "pre_shock_pull": self.pre_shock_detector.get_stats(),
            "depth_collapse": self.depth_collapse_detector.get_stats(),
            "gradual_thinning": self.gradual_thinning_detector.get_stats(),  # v3
            "anchor_tokens": len(self.anchor_tracker.anchors)
        }
