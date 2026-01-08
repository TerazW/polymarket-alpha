"""
Belief Reaction System - Belief State Machine v1
Deterministic 状态机，根据反应和领先事件判断市场信念状态。

状态 (按严重程度排序):
- STABLE: 信念稳定，防守坚定
- FRAGILE: 信念脆弱，开始动摇
- CRACKING: 信念破裂中，出现撤退/真空
- BROKEN: 信念崩溃，多点塌陷

核心原则 (Spec 2):
1. 只统计 Anchor 价位上的事件（非 anchor 事件暂不计入）
2. 滚动窗口 30 分钟
3. Deterministic 规则（可复现）
4. 每个状态必须带 evidence_ref（可回放）
"""

from collections import defaultdict
from decimal import Decimal
from typing import Optional, Dict, List, Tuple, Set
from dataclasses import dataclass, field
import time

# v5.13: Determinism infrastructure
from backend.common.determinism import deterministic_now

from .models import (
    BeliefState, BeliefStateChange, ReactionEvent, ReactionType,
    LeadingEvent, LeadingEventType, AnchorLevel, STATE_INDICATORS
)
from .config import (
    STATE_WINDOW_MS,
    STATE_HOLD_RATIO_STABLE,
    ANCHOR_TOP_K
)


@dataclass
class StateEvidence:
    """状态判定的证据"""
    event_type: str  # 'reaction' or 'leading'
    event_id: str
    timestamp: int
    description: str


@dataclass
class MarketStateContext:
    """单个市场的状态上下文"""
    token_id: str
    current_state: BeliefState = BeliefState.STABLE
    last_state_change: int = 0

    # 窗口内的事件计数 (只计 anchor 价位)
    n_vacuum: int = 0
    n_sweep: int = 0
    n_chase: int = 0
    n_pull: int = 0
    n_hold: int = 0
    n_delayed: int = 0

    # 领先事件计数
    n_pre_shock_pull: int = 0
    n_depth_collapse: int = 0

    # VACUUM 来自的不同 anchor 价位
    vacuum_anchors: Set[str] = field(default_factory=set)

    # 最近的证据
    recent_evidence: List[StateEvidence] = field(default_factory=list)


class BeliefStateMachine:
    """
    Belief State Machine v1

    Deterministic 规则 (Spec 2):

    BROKEN (最高优先级):
      - n_vacuum >= 2 (来自 ≥2 个不同 anchor)
      - OR (n_collapse >= 1 AND n_vacuum >= 1)
      - OR n_pre_pull >= 2

    CRACKING:
      - n_vacuum >= 1
      - OR n_pull >= 2
      - OR n_pre_pull >= 1
      - OR n_collapse >= 1

    FRAGILE:
      - (n_delayed >= 2 AND hold_ratio < 0.7)
      - OR n_pull == 1
      - OR n_chase + n_sweep >= 1

    STABLE (默认):
      - hold_ratio >= 0.7
      - AND n_vacuum == 0
      - AND n_pre_pull == 0
      - AND n_collapse == 0
    """

    def __init__(self):
        # 每个 market/token 的状态上下文
        self.contexts: Dict[str, MarketStateContext] = {}

        # 事件历史 (用于窗口计算)
        # {token_id: [(timestamp, event_type, event_id, anchor_key, reaction_type/leading_type), ...]}
        self.event_history: Dict[str, List[tuple]] = defaultdict(list)

        # 当前 anchor 集合 (从外部更新)
        # {token_id: {(price_str, side), ...}}
        self.anchors: Dict[str, Set[Tuple[str, str]]] = defaultdict(set)

        # 状态变化历史
        self.state_changes: List[BeliefStateChange] = []

        # 统计
        self.total_transitions = 0
        self.transitions_by_state: Dict[BeliefState, int] = defaultdict(int)

    def update_anchors(self, token_id: str, anchor_levels: List[AnchorLevel]):
        """更新 anchor 集合"""
        self.anchors[token_id] = {
            (str(a.price), a.side) for a in anchor_levels
        }

    def is_anchor(self, token_id: str, price: Decimal, side: str) -> bool:
        """检查是否为 anchor 价位"""
        return (str(price), side) in self.anchors.get(token_id, set())

    def on_reaction(
        self,
        reaction: ReactionEvent,
        is_anchor: bool = False
    ) -> Optional[BeliefStateChange]:
        """
        处理反应事件

        Args:
            reaction: 反应事件
            is_anchor: 是否发生在 anchor 价位

        Returns:
            如果状态发生变化，返回 BeliefStateChange
        """
        token_id = reaction.token_id
        now = reaction.timestamp

        # 自动检测是否为 anchor
        if not is_anchor:
            is_anchor = self.is_anchor(token_id, reaction.price, reaction.side)

        # 只统计 anchor 价位的事件 (v1 规则)
        if not is_anchor:
            return None

        # 记录事件
        anchor_key = f"{reaction.price}_{reaction.side}"
        self.event_history[token_id].append((
            now,
            'reaction',
            reaction.reaction_id,
            anchor_key,
            reaction.reaction_type.value
        ))

        # 清理过期事件
        self._prune_old_events(token_id, now)

        # 重新计算状态
        return self._recompute_state(token_id, now)

    def on_leading_event(
        self,
        event: LeadingEvent
    ) -> Optional[BeliefStateChange]:
        """
        处理领先事件

        Args:
            event: 领先事件

        Returns:
            如果状态发生变化，返回 BeliefStateChange
        """
        token_id = event.token_id
        now = event.timestamp

        # 领先事件总是重要的，不管是否在 anchor
        # 但 PRE_SHOCK_PULL 在 anchor 上更重要
        anchor_key = f"{event.price}_{event.side}"
        self.event_history[token_id].append((
            now,
            'leading',
            event.event_id,
            anchor_key,
            event.event_type.value
        ))

        # 清理过期事件
        self._prune_old_events(token_id, now)

        # 重新计算状态
        return self._recompute_state(token_id, now)

    def _prune_old_events(self, token_id: str, current_time: int):
        """清理窗口外的事件"""
        cutoff = current_time - STATE_WINDOW_MS
        self.event_history[token_id] = [
            e for e in self.event_history[token_id] if e[0] > cutoff
        ]

    def _recompute_state(self, token_id: str, current_time: int) -> Optional[BeliefStateChange]:
        """重新计算状态"""
        # 确保上下文存在
        if token_id not in self.contexts:
            self.contexts[token_id] = MarketStateContext(token_id=token_id)

        ctx = self.contexts[token_id]
        old_state = ctx.current_state

        # 统计窗口内的事件
        counts = self._count_events(token_id)

        # 更新上下文
        ctx.n_vacuum = counts.get('VACUUM', 0)
        ctx.n_sweep = counts.get('SWEEP', 0)
        ctx.n_chase = counts.get('CHASE', 0)
        ctx.n_pull = counts.get('PULL', 0)
        ctx.n_hold = counts.get('HOLD', 0)
        ctx.n_delayed = counts.get('DELAYED', 0)
        ctx.n_pre_shock_pull = counts.get('PRE_SHOCK_PULL', 0)
        ctx.n_depth_collapse = counts.get('DEPTH_COLLAPSE', 0)
        ctx.vacuum_anchors = counts.get('vacuum_anchors', set())

        # 计算 hold_ratio
        total_reactions = ctx.n_hold + ctx.n_delayed + ctx.n_pull + ctx.n_vacuum
        hold_ratio = ctx.n_hold / max(total_reactions, 1)

        # 应用 deterministic 规则
        new_state = self._apply_rules(ctx, hold_ratio)

        # 如果状态变化
        if new_state != old_state:
            ctx.current_state = new_state
            ctx.last_state_change = current_time
            self.total_transitions += 1
            self.transitions_by_state[new_state] += 1

            # 收集证据
            evidence, evidence_refs = self._collect_evidence(token_id, new_state)

            state_change = BeliefStateChange(
                timestamp=current_time,
                token_id=token_id,
                old_state=old_state,
                new_state=new_state,
                evidence=evidence,
                evidence_refs=evidence_refs
            )

            self.state_changes.append(state_change)
            return state_change

        return None

    def _count_events(self, token_id: str) -> dict:
        """统计窗口内的事件"""
        counts = defaultdict(int)
        vacuum_anchors = set()

        for ts, event_type, event_id, anchor_key, type_value in self.event_history.get(token_id, []):
            counts[type_value] += 1

            # 记录 VACUUM 来自哪些 anchor
            if type_value == 'VACUUM':
                vacuum_anchors.add(anchor_key)

        counts['vacuum_anchors'] = vacuum_anchors
        return counts

    def _apply_rules(self, ctx: MarketStateContext, hold_ratio: float) -> BeliefState:
        """
        应用 deterministic 规则

        优先级: BROKEN > CRACKING > FRAGILE > STABLE
        """
        # 1. BROKEN (最高优先级)
        if self._check_broken(ctx):
            return BeliefState.BROKEN

        # 2. CRACKING
        if self._check_cracking(ctx):
            return BeliefState.CRACKING

        # 3. FRAGILE
        if self._check_fragile(ctx, hold_ratio):
            return BeliefState.FRAGILE

        # 4. STABLE (默认)
        return BeliefState.STABLE

    def _check_broken(self, ctx: MarketStateContext) -> bool:
        """
        BROKEN 条件:
        - n_vacuum >= 2 (来自 ≥2 个不同 anchor)
        - OR (n_collapse >= 1 AND n_vacuum >= 1)
        - OR n_pre_pull >= 2
        """
        # 条件 1: 多个 anchor 出现 VACUUM
        if ctx.n_vacuum >= 2 and len(ctx.vacuum_anchors) >= 2:
            return True

        # 条件 2: COLLAPSE + VACUUM
        if ctx.n_depth_collapse >= 1 and ctx.n_vacuum >= 1:
            return True

        # 条件 3: 多次 PRE_SHOCK_PULL
        if ctx.n_pre_shock_pull >= 2:
            return True

        return False

    def _check_cracking(self, ctx: MarketStateContext) -> bool:
        """
        CRACKING 条件:
        - n_vacuum >= 1
        - OR n_pull >= 2
        - OR n_pre_pull >= 1
        - OR n_collapse >= 1
        """
        if ctx.n_vacuum >= 1:
            return True
        if ctx.n_pull >= 2:
            return True
        if ctx.n_pre_shock_pull >= 1:
            return True
        if ctx.n_depth_collapse >= 1:
            return True

        return False

    def _check_fragile(self, ctx: MarketStateContext, hold_ratio: float) -> bool:
        """
        FRAGILE 条件:
        - (n_delayed >= 2 AND hold_ratio < 0.7)
        - OR n_pull == 1
        - OR n_chase + n_sweep >= 1
        """
        if ctx.n_delayed >= 2 and hold_ratio < STATE_HOLD_RATIO_STABLE:
            return True
        if ctx.n_pull == 1:
            return True
        if ctx.n_chase + ctx.n_sweep >= 1:
            return True

        return False

    def _collect_evidence(self, token_id: str, state: BeliefState) -> Tuple[List[str], List[str]]:
        """收集状态判定的证据"""
        evidence = []
        evidence_refs = []

        # 取最近的事件作为证据
        recent = self.event_history.get(token_id, [])[-5:]  # 最多 5 条

        for ts, event_type, event_id, anchor_key, type_value in recent:
            if event_type == 'reaction':
                evidence.append(f"{type_value} at {anchor_key}")
            else:
                evidence.append(f"{type_value} at {anchor_key}")
            evidence_refs.append(event_id)

        return evidence, evidence_refs

    def get_state(self, token_id: str) -> BeliefState:
        """获取当前状态"""
        if token_id in self.contexts:
            return self.contexts[token_id].current_state
        return BeliefState.STABLE

    def get_context(self, token_id: str) -> Optional[MarketStateContext]:
        """获取状态上下文"""
        return self.contexts.get(token_id)

    def get_recent_changes(self, window_ms: int = 300000, reference_ts: int = None) -> List[BeliefStateChange]:
        """
        获取最近的状态变化

        v5.13: 支持传入参考时间以确保确定性
        """
        # v5.13: Use reference timestamp if provided, otherwise deterministic clock
        current_time = reference_ts if reference_ts else deterministic_now(context="BeliefStateMachine.get_recent_changes")
        cutoff = current_time - window_ms
        return [c for c in self.state_changes if c.timestamp >= cutoff]

    def get_stats(self) -> dict:
        """获取统计信息"""
        state_counts = defaultdict(int)
        for ctx in self.contexts.values():
            state_counts[ctx.current_state.value] += 1

        return {
            "total_tokens": len(self.contexts),
            "total_transitions": self.total_transitions,
            "by_current_state": dict(state_counts),
            "transitions_by_state": {s.value: c for s, c in self.transitions_by_state.items()}
        }

    def format_state(self, token_id: str) -> str:
        """格式化状态显示"""
        state = self.get_state(token_id)
        indicator = STATE_INDICATORS.get(state, '⚪')
        return f"{indicator} {state.value}"
