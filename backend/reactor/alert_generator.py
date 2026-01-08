"""
Alert Generator - Generates alerts from detection events

Integrates with the collector to produce alerts for:
1. Shock events
2. Reaction events
3. Leading events
4. Belief state changes

Stores alerts in the alerts table (v5 schema).
"""

import uuid
from datetime import datetime
from typing import Optional, Callable, Any, Dict
from dataclasses import dataclass
from enum import Enum
import psycopg2
from psycopg2.extras import Json


class AlertSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKED = "ACKED"
    RESOLVED = "RESOLVED"


@dataclass
class Alert:
    """Alert data structure"""
    alert_id: str
    ts: datetime
    token_id: str
    severity: AlertSeverity
    status: AlertStatus
    alert_type: str
    summary: str
    confidence: float
    evidence_token: str
    evidence_t0: int  # ms timestamp
    payload: Optional[Dict[str, Any]] = None


class AlertGenerator:
    """
    Generates alerts from detection events.

    Usage:
        generator = AlertGenerator(db_config)

        # On shock detection
        generator.on_shock(shock_event)

        # On reaction classification
        generator.on_reaction(reaction_event)

        # On leading event
        generator.on_leading_event(leading_event)

        # On state change
        generator.on_state_change(state_change)
    """

    # Reaction type to severity mapping
    REACTION_SEVERITY = {
        'VACUUM': AlertSeverity.CRITICAL,
        'SWEEP': AlertSeverity.HIGH,
        'CHASE': AlertSeverity.MEDIUM,
        'PULL': AlertSeverity.HIGH,
        'HOLD': AlertSeverity.LOW,
        'DELAYED': AlertSeverity.LOW,
        'NO_IMPACT': AlertSeverity.LOW,
    }

    # Leading event type to severity mapping
    LEADING_SEVERITY = {
        'PRE_SHOCK_PULL': AlertSeverity.HIGH,
        'DEPTH_COLLAPSE': AlertSeverity.CRITICAL,
        'GRADUAL_THINNING': AlertSeverity.MEDIUM,
    }

    # State to severity mapping
    STATE_SEVERITY = {
        'STABLE': AlertSeverity.LOW,
        'FRAGILE': AlertSeverity.MEDIUM,
        'CRACKING': AlertSeverity.HIGH,
        'BROKEN': AlertSeverity.CRITICAL,
    }

    def __init__(
        self,
        db_config: Dict[str, Any],
        on_alert: Optional[Callable[[Alert], None]] = None,
        enabled: bool = True
    ):
        """
        Initialize alert generator.

        Args:
            db_config: Database connection config dict
            on_alert: Optional callback when alert is generated
            enabled: Whether to actually save alerts
        """
        self.db_config = db_config
        self.on_alert_callback = on_alert
        self.enabled = enabled
        self._conn = None

    def _get_conn(self):
        """Get or create database connection"""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self.db_config)
        return self._conn

    def _save_alert(self, alert: Alert) -> bool:
        """Save alert to database"""
        if not self.enabled:
            return False

        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO alerts (
                        alert_id, ts, token_id, severity, status,
                        alert_type, summary, confidence,
                        evidence_token, evidence_t0, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    alert.alert_id,
                    alert.ts,
                    alert.token_id,
                    alert.severity.value,
                    alert.status.value,
                    alert.alert_type,
                    alert.summary,
                    alert.confidence,
                    alert.evidence_token,
                    alert.evidence_t0,
                    Json(alert.payload) if alert.payload else None,
                ))
                conn.commit()

            # Trigger callback
            if self.on_alert_callback:
                self.on_alert_callback(alert)

            return True

        except Exception as e:
            print(f"[ALERT ERROR] Failed to save alert: {e}")
            if self._conn:
                self._conn.rollback()
            return False

    def on_shock(
        self,
        shock_id: str,
        ts: datetime,
        token_id: str,
        price: float,
        side: str,
        trade_volume: float,
        trigger_type: str,
        baseline_size: Optional[float] = None
    ) -> Optional[Alert]:
        """
        Generate alert for shock event.

        Shocks are always MEDIUM priority - they're detection points.
        """
        if not self.enabled:
            return None

        ts_ms = int(ts.timestamp() * 1000)

        alert = Alert(
            alert_id=str(uuid.uuid4()),
            ts=ts,
            token_id=token_id,
            severity=AlertSeverity.MEDIUM,
            status=AlertStatus.OPEN,
            alert_type='SHOCK',
            summary=f"Shock at {price*100:.0f}% ({side}) - {trigger_type}",
            confidence=75.0,
            evidence_token=token_id,
            evidence_t0=ts_ms,
            payload={
                'shock_id': shock_id,
                'price': price,
                'side': side,
                'trade_volume': trade_volume,
                'trigger_type': trigger_type,
                'baseline_size': baseline_size,
            }
        )

        if self._save_alert(alert):
            print(f"[ALERT] 🔔 SHOCK at {price*100:.0f}% ({side})")
            return alert
        return None

    def on_reaction(
        self,
        reaction_id: str,
        shock_id: str,
        ts: datetime,
        token_id: str,
        price: float,
        side: str,
        reaction_type: str,
        window_type: str,
        drop_ratio: Optional[float] = None,
        refill_ratio: Optional[float] = None,
        vacuum_duration_ms: Optional[int] = None
    ) -> Optional[Alert]:
        """
        Generate alert for reaction event.

        Severity depends on reaction type:
        - VACUUM: CRITICAL
        - PULL, SWEEP: HIGH
        - CHASE: MEDIUM
        - HOLD, DELAYED, NO_IMPACT: LOW
        """
        if not self.enabled:
            return None

        severity = self.REACTION_SEVERITY.get(reaction_type, AlertSeverity.LOW)

        # Skip LOW severity reactions to reduce noise
        if severity == AlertSeverity.LOW:
            return None

        ts_ms = int(ts.timestamp() * 1000)

        # Build summary
        if reaction_type == 'VACUUM':
            summary = f"🔴 VACUUM at {price*100:.0f}% - Liquidity vanished"
        elif reaction_type == 'PULL':
            summary = f"⚠️ PULL at {price*100:.0f}% - Immediate withdrawal"
        elif reaction_type == 'SWEEP':
            summary = f"⚡ SWEEP at {price*100:.0f}% - Multiple levels swept"
        elif reaction_type == 'CHASE':
            summary = f"➡️ CHASE at {price*100:.0f}% - Price migration"
        else:
            summary = f"{reaction_type} at {price*100:.0f}%"

        alert = Alert(
            alert_id=str(uuid.uuid4()),
            ts=ts,
            token_id=token_id,
            severity=severity,
            status=AlertStatus.OPEN,
            alert_type='REACTION',
            summary=summary,
            confidence=80.0 if reaction_type in ('VACUUM', 'PULL') else 70.0,
            evidence_token=token_id,
            evidence_t0=ts_ms,
            payload={
                'reaction_id': reaction_id,
                'shock_id': shock_id,
                'price': price,
                'side': side,
                'reaction_type': reaction_type,
                'window_type': window_type,
                'drop_ratio': drop_ratio,
                'refill_ratio': refill_ratio,
                'vacuum_duration_ms': vacuum_duration_ms,
            }
        )

        if self._save_alert(alert):
            emoji = '🔴' if severity == AlertSeverity.CRITICAL else '🟠' if severity == AlertSeverity.HIGH else '🟡'
            print(f"[ALERT] {emoji} {reaction_type} reaction at {price*100:.0f}%")
            return alert
        return None

    def on_leading_event(
        self,
        event_id: str,
        ts: datetime,
        token_id: str,
        price: float,
        side: str,
        event_type: str,
        drop_ratio: Optional[float] = None,
        affected_levels: Optional[int] = None
    ) -> Optional[Alert]:
        """
        Generate alert for leading event (pre-shock signal).

        Severity depends on event type:
        - DEPTH_COLLAPSE: CRITICAL
        - PRE_SHOCK_PULL: HIGH
        - GRADUAL_THINNING: MEDIUM
        """
        if not self.enabled:
            return None

        severity = self.LEADING_SEVERITY.get(event_type, AlertSeverity.MEDIUM)
        ts_ms = int(ts.timestamp() * 1000)

        # Build summary
        if event_type == 'DEPTH_COLLAPSE':
            summary = f"🚨 DEPTH COLLAPSE near {price*100:.0f}% - {affected_levels or '?'} levels"
        elif event_type == 'PRE_SHOCK_PULL':
            summary = f"⚠️ PRE-SHOCK PULL at {price*100:.0f}% - Silent withdrawal"
        elif event_type == 'GRADUAL_THINNING':
            summary = f"📉 Gradual thinning near {price*100:.0f}%"
        else:
            summary = f"{event_type} at {price*100:.0f}%"

        alert = Alert(
            alert_id=str(uuid.uuid4()),
            ts=ts,
            token_id=token_id,
            severity=severity,
            status=AlertStatus.OPEN,
            alert_type='LEADING_EVENT',
            summary=summary,
            confidence=85.0 if event_type == 'DEPTH_COLLAPSE' else 75.0,
            evidence_token=token_id,
            evidence_t0=ts_ms,
            payload={
                'event_id': event_id,
                'price': price,
                'side': side,
                'event_type': event_type,
                'drop_ratio': drop_ratio,
                'affected_levels': affected_levels,
            }
        )

        if self._save_alert(alert):
            emoji = '🚨' if severity == AlertSeverity.CRITICAL else '⚠️' if severity == AlertSeverity.HIGH else '📉'
            print(f"[ALERT] {emoji} Leading: {event_type} at {price*100:.0f}%")
            return alert
        return None

    def on_state_change(
        self,
        state_id: str,
        ts: datetime,
        token_id: str,
        old_state: str,
        new_state: str,
        trigger_reaction_id: Optional[str] = None,
        evidence: Optional[Dict[str, Any]] = None
    ) -> Optional[Alert]:
        """
        Generate alert for belief state change.

        Severity depends on new state:
        - BROKEN: CRITICAL
        - CRACKING: HIGH
        - FRAGILE: MEDIUM
        - STABLE: LOW (skip)
        """
        if not self.enabled:
            return None

        severity = self.STATE_SEVERITY.get(new_state, AlertSeverity.LOW)

        # Skip LOW severity (STABLE state)
        if severity == AlertSeverity.LOW:
            return None

        ts_ms = int(ts.timestamp() * 1000)

        # Build summary with emoji
        state_emoji = {
            'STABLE': '🟢',
            'FRAGILE': '🟡',
            'CRACKING': '🟠',
            'BROKEN': '🔴',
        }

        summary = f"{state_emoji.get(new_state, '⚪')} State: {old_state} → {new_state}"

        alert = Alert(
            alert_id=str(uuid.uuid4()),
            ts=ts,
            token_id=token_id,
            severity=severity,
            status=AlertStatus.OPEN,
            alert_type='STATE_CHANGE',
            summary=summary,
            confidence=90.0 if new_state == 'BROKEN' else 80.0,
            evidence_token=token_id,
            evidence_t0=ts_ms,
            payload={
                'state_id': state_id,
                'old_state': old_state,
                'new_state': new_state,
                'trigger_reaction_id': trigger_reaction_id,
                'evidence': evidence,
            }
        )

        if self._save_alert(alert):
            print(f"[ALERT] {state_emoji.get(new_state, '')} STATE CHANGE: {old_state} → {new_state}")
            return alert
        return None

    def close(self):
        """Close database connection"""
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None
