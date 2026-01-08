"""
Belief Reaction System - Alert System v1
Handles alert generation, persistence, and delivery.

Alert Types:
1. SHOCK: 冲击检测到
2. REACTION: 反应已分类 (VACUUM/SWEEP/CHASE/PULL/HOLD/DELAYED/NO_IMPACT)
3. LEADING_EVENT: 领先事件 (PRE_SHOCK_PULL/DEPTH_COLLAPSE/GRADUAL_THINNING)
4. STATE_CHANGE: 信念状态变化 (STABLE/FRAGILE/CRACKING/BROKEN)

"看存在没意义，看反应才有意义"
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from decimal import Decimal
from typing import Optional, Dict, List, Callable
from collections import defaultdict
import time
import uuid
import json

from .models import (
    ShockEvent, ReactionEvent, ReactionType,
    LeadingEvent, LeadingEventType,
    BeliefState, BeliefStateChange,
    STATE_INDICATORS, REACTION_INDICATORS
)


class AlertPriority(Enum):
    """警报优先级"""
    LOW = 1       # 正常事件 (HOLD, DELAYED, NO_IMPACT)
    MEDIUM = 2    # 值得关注 (CHASE, SWEEP, GRADUAL_THINNING)
    HIGH = 3      # 重要警报 (PULL, PRE_SHOCK_PULL, FRAGILE)
    CRITICAL = 4  # 紧急警报 (VACUUM, DEPTH_COLLAPSE, CRACKING, BROKEN)


class AlertType(Enum):
    """警报类型"""
    SHOCK = "SHOCK"
    REACTION = "REACTION"
    LEADING_EVENT = "LEADING_EVENT"
    STATE_CHANGE = "STATE_CHANGE"


@dataclass
class Alert:
    """警报对象"""
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    alert_type: AlertType = AlertType.REACTION
    priority: AlertPriority = AlertPriority.LOW
    timestamp: int = 0
    token_id: str = ""

    # 标题和消息
    title: str = ""
    message: str = ""

    # 详细数据
    price: Optional[Decimal] = None
    side: Optional[str] = None

    # 子类型 (ReactionType / LeadingEventType / BeliefState)
    subtype: Optional[str] = None

    # 证据列表
    evidence: List[str] = field(default_factory=list)

    # 原始事件ID引用
    source_event_id: Optional[str] = None

    # 是否已读/已处理
    is_read: bool = False
    is_dismissed: bool = False

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "alert_id": self.alert_id,
            "alert_type": self.alert_type.value,
            "priority": self.priority.value,
            "priority_name": self.priority.name,
            "timestamp": self.timestamp,
            "token_id": self.token_id,
            "title": self.title,
            "message": self.message,
            "price": str(self.price) if self.price else None,
            "side": self.side,
            "subtype": self.subtype,
            "evidence": self.evidence,
            "source_event_id": self.source_event_id,
            "is_read": self.is_read,
            "is_dismissed": self.is_dismissed,
            "created_at": datetime.fromtimestamp(self.timestamp / 1000).isoformat() if self.timestamp else None
        }

    def to_json(self) -> str:
        """转换为JSON"""
        return json.dumps(self.to_dict())


# 优先级映射
REACTION_PRIORITY = {
    ReactionType.VACUUM: AlertPriority.CRITICAL,
    ReactionType.SWEEP: AlertPriority.MEDIUM,
    ReactionType.CHASE: AlertPriority.MEDIUM,
    ReactionType.PULL: AlertPriority.HIGH,
    ReactionType.HOLD: AlertPriority.LOW,
    ReactionType.DELAYED: AlertPriority.LOW,
    ReactionType.NO_IMPACT: AlertPriority.LOW,
}

LEADING_EVENT_PRIORITY = {
    LeadingEventType.PRE_SHOCK_PULL: AlertPriority.HIGH,
    LeadingEventType.DEPTH_COLLAPSE: AlertPriority.CRITICAL,
    LeadingEventType.GRADUAL_THINNING: AlertPriority.MEDIUM,
}

STATE_PRIORITY = {
    BeliefState.STABLE: AlertPriority.LOW,
    BeliefState.FRAGILE: AlertPriority.HIGH,
    BeliefState.CRACKING: AlertPriority.CRITICAL,
    BeliefState.BROKEN: AlertPriority.CRITICAL,
}


class AlertSystem:
    """
    警报系统

    功能:
    1. 接收各类事件，生成标准化警报
    2. 维护警报历史
    3. 提供查询接口
    4. 支持回调通知
    """

    def __init__(
        self,
        on_alert: Optional[Callable[[Alert], None]] = None,
        max_alerts_per_token: int = 100,
        max_total_alerts: int = 10000
    ):
        self.on_alert_callback = on_alert
        self.max_alerts_per_token = max_alerts_per_token
        self.max_total_alerts = max_total_alerts

        # 警报存储
        self.alerts: List[Alert] = []
        self.alerts_by_token: Dict[str, List[Alert]] = defaultdict(list)

        # 统计
        self.stats = {
            "total_alerts": 0,
            "by_type": defaultdict(int),
            "by_priority": defaultdict(int),
        }

    # =========================================================================
    # 事件处理
    # =========================================================================

    def on_shock(self, shock: ShockEvent) -> Alert:
        """处理冲击事件"""
        alert = Alert(
            alert_type=AlertType.SHOCK,
            priority=AlertPriority.MEDIUM,
            timestamp=shock.ts_start,
            token_id=shock.token_id,
            title=f"冲击检测 @ {shock.price}",
            message=f"在 {shock.price} ({shock.side}) 检测到冲击，"
                    f"成交量 {shock.trade_volume:.1f}，触发类型: {shock.trigger_type}",
            price=shock.price,
            side=shock.side,
            subtype=shock.trigger_type,
            evidence=[
                f"成交量: {shock.trade_volume:.1f}",
                f"冲击前流动性: {shock.liquidity_before:.1f}",
                f"基准深度: {shock.baseline_size:.1f}",
            ],
            source_event_id=shock.shock_id
        )

        return self._emit_alert(alert)

    def on_reaction(self, reaction: ReactionEvent) -> Alert:
        """处理反应事件"""
        indicator = REACTION_INDICATORS.get(reaction.reaction_type, "⚪")
        priority = REACTION_PRIORITY.get(reaction.reaction_type, AlertPriority.LOW)

        # 构建证据
        evidence = [
            f"回补率: {reaction.refill_ratio:.0%}",
            f"下降率: {reaction.drop_ratio:.0%}",
        ]
        if reaction.time_to_refill_ms:
            evidence.append(f"回补时间: {reaction.time_to_refill_ms/1000:.1f}s")
        if reaction.shift_ticks != 0:
            evidence.append(f"价格偏移: {reaction.shift_ticks} ticks")
        if reaction.vacuum_duration_ms > 0:
            evidence.append(f"真空持续: {reaction.vacuum_duration_ms/1000:.1f}s")

        alert = Alert(
            alert_type=AlertType.REACTION,
            priority=priority,
            timestamp=reaction.timestamp,
            token_id=reaction.token_id,
            title=f"{indicator} {reaction.reaction_type.value} @ {reaction.price}",
            message=self._get_reaction_message(reaction),
            price=reaction.price,
            side=reaction.side,
            subtype=reaction.reaction_type.value,
            evidence=evidence,
            source_event_id=reaction.reaction_id
        )

        return self._emit_alert(alert)

    def on_leading_event(self, event: LeadingEvent) -> Alert:
        """处理领先事件"""
        priority = LEADING_EVENT_PRIORITY.get(event.event_type, AlertPriority.MEDIUM)

        # 构建证据
        evidence = [f"下降率: {event.drop_ratio:.0%}"]

        if event.event_type == LeadingEventType.PRE_SHOCK_PULL:
            evidence.extend([
                f"持续时间: {event.duration_ms/1000:.1f}s",
                f"附近成交量: {event.trade_volume_nearby:.1f}",
                f"是否锚点: {'是' if event.is_anchor else '否'}",
            ])
        elif event.event_type == LeadingEventType.DEPTH_COLLAPSE:
            evidence.extend([
                f"影响价位数: {event.affected_levels}",
                f"时间标准差: {event.time_std_ms:.0f}ms",
            ])
        elif event.event_type == LeadingEventType.GRADUAL_THINNING:
            evidence.extend([
                f"前深度: {event.total_depth_before:.1f}",
                f"后深度: {event.total_depth_after:.1f}",
                f"成交驱动占比: {event.trade_driven_ratio:.0%}",
            ])

        alert = Alert(
            alert_type=AlertType.LEADING_EVENT,
            priority=priority,
            timestamp=event.timestamp,
            token_id=event.token_id,
            title=f"⚡ {event.event_type.value}",
            message=self._get_leading_event_message(event),
            price=event.price,
            side=event.side,
            subtype=event.event_type.value,
            evidence=evidence,
            source_event_id=event.event_id
        )

        return self._emit_alert(alert)

    def on_state_change(self, change: BeliefStateChange) -> Alert:
        """处理状态变化事件"""
        old_indicator = STATE_INDICATORS.get(change.old_state, "⚪")
        new_indicator = STATE_INDICATORS.get(change.new_state, "⚪")
        priority = STATE_PRIORITY.get(change.new_state, AlertPriority.LOW)

        alert = Alert(
            alert_type=AlertType.STATE_CHANGE,
            priority=priority,
            timestamp=change.timestamp,
            token_id=change.token_id,
            title=f"{old_indicator} → {new_indicator} 信念状态变化",
            message=f"信念状态从 {change.old_state.value} 变为 {change.new_state.value}",
            subtype=change.new_state.value,
            evidence=change.evidence,
            source_event_id=change.trigger_reaction_id or change.trigger_leading_event_id
        )

        return self._emit_alert(alert)

    # =========================================================================
    # 内部方法
    # =========================================================================

    def _emit_alert(self, alert: Alert) -> Alert:
        """发出警报"""
        # 存储
        self.alerts.append(alert)
        self.alerts_by_token[alert.token_id].append(alert)

        # 更新统计
        self.stats["total_alerts"] += 1
        self.stats["by_type"][alert.alert_type.value] += 1
        self.stats["by_priority"][alert.priority.name] += 1

        # 清理旧警报
        self._prune_alerts()

        # 回调
        if self.on_alert_callback:
            self.on_alert_callback(alert)

        return alert

    def _prune_alerts(self):
        """清理过多的警报"""
        # 全局限制
        if len(self.alerts) > self.max_total_alerts:
            self.alerts = self.alerts[-self.max_total_alerts:]

        # 每个 token 限制
        for token_id, token_alerts in self.alerts_by_token.items():
            if len(token_alerts) > self.max_alerts_per_token:
                self.alerts_by_token[token_id] = token_alerts[-self.max_alerts_per_token:]

    def _get_reaction_message(self, reaction: ReactionEvent) -> str:
        """生成反应消息"""
        messages = {
            ReactionType.VACUUM: f"流动性真空！最低深度降至 {reaction.min_liquidity:.1f}，持续 {reaction.vacuum_duration_ms/1000:.1f}s",
            ReactionType.SWEEP: f"多档被扫，价格偏移 {reaction.shift_ticks} ticks",
            ReactionType.CHASE: f"追价信号，锚点迁移 {reaction.shift_ticks} tick(s)",
            ReactionType.PULL: f"撤退信号，回补率仅 {reaction.refill_ratio:.0%}",
            ReactionType.HOLD: f"防守成功，回补率 {reaction.refill_ratio:.0%}",
            ReactionType.DELAYED: f"犹豫反应，回补率 {reaction.refill_ratio:.0%}",
            ReactionType.NO_IMPACT: f"无明显影响，下降幅度较小",
        }
        return messages.get(reaction.reaction_type, "反应已分类")

    def _get_leading_event_message(self, event: LeadingEvent) -> str:
        """生成领先事件消息"""
        messages = {
            LeadingEventType.PRE_SHOCK_PULL:
                f"无成交撤退检测！在 {event.price} ({event.side}) 深度下降 {event.drop_ratio:.0%}，"
                f"可能是信息前兆",
            LeadingEventType.DEPTH_COLLAPSE:
                f"多价位同步塌陷！{event.affected_levels} 个价位在 {event.time_std_ms:.0f}ms 内同步下降，"
                f"恐慌信号",
            LeadingEventType.GRADUAL_THINNING:
                f"渐进撤退检测！深度从 {event.total_depth_before:.0f} 降至 {event.total_depth_after:.0f}，"
                f"非成交驱动",
        }
        return messages.get(event.event_type, "领先事件检测到")

    # =========================================================================
    # 查询接口
    # =========================================================================

    def get_alerts(
        self,
        token_id: Optional[str] = None,
        alert_type: Optional[AlertType] = None,
        min_priority: Optional[AlertPriority] = None,
        limit: int = 50,
        include_dismissed: bool = False
    ) -> List[Alert]:
        """查询警报"""
        # 选择数据源
        if token_id:
            alerts = self.alerts_by_token.get(token_id, [])
        else:
            alerts = self.alerts

        # 过滤
        result = []
        for alert in reversed(alerts):  # 最新的在前
            if not include_dismissed and alert.is_dismissed:
                continue
            if alert_type and alert.alert_type != alert_type:
                continue
            if min_priority and alert.priority.value < min_priority.value:
                continue
            result.append(alert)
            if len(result) >= limit:
                break

        return result

    def get_critical_alerts(self, limit: int = 10) -> List[Alert]:
        """获取紧急警报"""
        return self.get_alerts(min_priority=AlertPriority.CRITICAL, limit=limit)

    def get_unread_count(self, token_id: Optional[str] = None) -> int:
        """获取未读警报数量"""
        if token_id:
            alerts = self.alerts_by_token.get(token_id, [])
        else:
            alerts = self.alerts
        return sum(1 for a in alerts if not a.is_read and not a.is_dismissed)

    def mark_as_read(self, alert_id: str) -> bool:
        """标记为已读"""
        for alert in self.alerts:
            if alert.alert_id == alert_id:
                alert.is_read = True
                return True
        return False

    def dismiss_alert(self, alert_id: str) -> bool:
        """忽略警报"""
        for alert in self.alerts:
            if alert.alert_id == alert_id:
                alert.is_dismissed = True
                return True
        return False

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "total_alerts": self.stats["total_alerts"],
            "by_type": dict(self.stats["by_type"]),
            "by_priority": dict(self.stats["by_priority"]),
            "unread_count": self.get_unread_count(),
            "stored_alerts": len(self.alerts),
            "tracked_tokens": len(self.alerts_by_token)
        }
