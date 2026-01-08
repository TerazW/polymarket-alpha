"""
Audit Window Storage (v5.36)

Conditionally stores raw_events based on belief state.

"平时不存全量，关键时刻才保留完整证据链。"

Strategy:
- Normal (STABLE/FRAGILE): Store minimal raw_events (short retention)
- Critical (CRACKING/BROKEN): Store complete audit window (t0-30s to t0+60s)

This reduces storage costs by 10-100x while preserving audit capability
for the events that matter.
"""

import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, Set
from collections import defaultdict

logger = logging.getLogger(__name__)


class StorageMode(str, Enum):
    """Storage mode for raw_events"""
    MINIMAL = "MINIMAL"       # Short retention, basic events only
    FULL_AUDIT = "FULL_AUDIT" # Complete window for audit


@dataclass
class AuditWindow:
    """Defines an audit window to preserve"""
    token_id: str
    trigger_ts: int           # When the trigger occurred
    window_start: int         # t0 - pre_window_ms
    window_end: int           # t0 + post_window_ms
    trigger_type: str         # What triggered (CRACKING, BROKEN, CRITICAL_ALERT)
    trigger_id: str           # ID of the triggering event

    def contains(self, ts: int) -> bool:
        """Check if timestamp falls within window"""
        return self.window_start <= ts <= self.window_end

    def to_dict(self) -> dict:
        return {
            "token_id": self.token_id,
            "trigger_ts": self.trigger_ts,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "trigger_type": self.trigger_type,
            "trigger_id": self.trigger_id,
        }


# Configuration
AUDIT_WINDOW_CONFIG = {
    "pre_window_ms": 30000,    # 30 seconds before trigger
    "post_window_ms": 60000,   # 60 seconds after trigger
    "max_windows_per_token": 10,  # Max concurrent windows per token
    "window_merge_threshold_ms": 10000,  # Merge windows within 10s
}

# States that trigger full audit window
AUDIT_TRIGGER_STATES = {"CRACKING", "BROKEN"}

# Alert severities that trigger full audit window
AUDIT_TRIGGER_SEVERITIES = {"CRITICAL"}


class AuditWindowManager:
    """
    Manages audit windows for conditional raw_event storage.

    Usage:
        manager = AuditWindowManager()

        # When belief state changes
        manager.on_state_change(token_id, "CRACKING", ts, event_id)

        # When processing raw events
        if manager.should_store_full(token_id, event_ts):
            store_raw_event(event)  # Full storage
        else:
            store_minimal(event)    # Minimal storage
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = {**AUDIT_WINDOW_CONFIG, **(config or {})}
        # Active audit windows: {token_id: [AuditWindow, ...]}
        self._windows: Dict[str, List[AuditWindow]] = defaultdict(list)
        # Tokens in critical state
        self._critical_tokens: Set[str] = set()

    def on_state_change(
        self,
        token_id: str,
        new_state: str,
        ts: int,
        event_id: str
    ) -> Optional[AuditWindow]:
        """
        Handle belief state change.

        Args:
            token_id: Market token ID
            new_state: New belief state (STABLE, FRAGILE, CRACKING, BROKEN)
            ts: Timestamp of state change
            event_id: ID of the event that caused the change

        Returns:
            AuditWindow if a new window was created, None otherwise
        """
        if new_state in AUDIT_TRIGGER_STATES:
            self._critical_tokens.add(token_id)
            return self._create_window(token_id, ts, f"STATE_{new_state}", event_id)
        else:
            self._critical_tokens.discard(token_id)
            return None

    def on_alert(
        self,
        token_id: str,
        severity: str,
        ts: int,
        alert_id: str
    ) -> Optional[AuditWindow]:
        """
        Handle alert generation.

        Args:
            token_id: Market token ID
            severity: Alert severity
            ts: Alert timestamp
            alert_id: Alert ID

        Returns:
            AuditWindow if a new window was created, None otherwise
        """
        if severity in AUDIT_TRIGGER_SEVERITIES:
            return self._create_window(token_id, ts, f"ALERT_{severity}", alert_id)
        return None

    def _create_window(
        self,
        token_id: str,
        ts: int,
        trigger_type: str,
        trigger_id: str
    ) -> AuditWindow:
        """Create a new audit window"""
        window = AuditWindow(
            token_id=token_id,
            trigger_ts=ts,
            window_start=ts - self.config["pre_window_ms"],
            window_end=ts + self.config["post_window_ms"],
            trigger_type=trigger_type,
            trigger_id=trigger_id,
        )

        # Check if we should merge with existing window
        merged = False
        for existing in self._windows[token_id]:
            if abs(existing.trigger_ts - ts) < self.config["window_merge_threshold_ms"]:
                # Extend existing window
                existing.window_start = min(existing.window_start, window.window_start)
                existing.window_end = max(existing.window_end, window.window_end)
                merged = True
                logger.debug(f"Merged audit window for {token_id}")
                break

        if not merged:
            self._windows[token_id].append(window)
            # Enforce max windows limit
            if len(self._windows[token_id]) > self.config["max_windows_per_token"]:
                # Remove oldest window
                self._windows[token_id].sort(key=lambda w: w.trigger_ts)
                removed = self._windows[token_id].pop(0)
                logger.debug(f"Removed oldest audit window for {token_id}: {removed.trigger_id}")

        logger.info(f"Audit window created for {token_id}: {trigger_type} @ {ts}")
        return window

    def should_store_full(self, token_id: str, ts: int) -> bool:
        """
        Check if raw event should be stored with full audit detail.

        Args:
            token_id: Market token ID
            ts: Event timestamp

        Returns:
            True if full storage is needed, False for minimal storage
        """
        # If token is in critical state, always store full
        if token_id in self._critical_tokens:
            return True

        # Check if timestamp falls within any audit window
        for window in self._windows.get(token_id, []):
            if window.contains(ts):
                return True

        return False

    def get_storage_mode(self, token_id: str, ts: int) -> StorageMode:
        """
        Get storage mode for a raw event.

        Args:
            token_id: Market token ID
            ts: Event timestamp

        Returns:
            StorageMode indicating how to store the event
        """
        if self.should_store_full(token_id, ts):
            return StorageMode.FULL_AUDIT
        return StorageMode.MINIMAL

    def cleanup_expired_windows(self, current_ts: int = None) -> int:
        """
        Remove expired audit windows.

        Args:
            current_ts: Current timestamp (uses now if None)

        Returns:
            Number of windows removed
        """
        if current_ts is None:
            current_ts = int(time.time() * 1000)

        removed = 0
        for token_id in list(self._windows.keys()):
            original_count = len(self._windows[token_id])
            self._windows[token_id] = [
                w for w in self._windows[token_id]
                if w.window_end > current_ts
            ]
            removed += original_count - len(self._windows[token_id])

            if not self._windows[token_id]:
                del self._windows[token_id]

        if removed > 0:
            logger.debug(f"Cleaned up {removed} expired audit windows")

        return removed

    def get_active_windows(self, token_id: str = None) -> List[AuditWindow]:
        """
        Get active audit windows.

        Args:
            token_id: Specific token (None for all)

        Returns:
            List of active AuditWindows
        """
        if token_id:
            return list(self._windows.get(token_id, []))

        all_windows = []
        for windows in self._windows.values():
            all_windows.extend(windows)
        return all_windows

    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics"""
        total_windows = sum(len(w) for w in self._windows.values())
        return {
            "total_windows": total_windows,
            "tokens_with_windows": len(self._windows),
            "critical_tokens": len(self._critical_tokens),
            "config": self.config,
        }


# Singleton instance
_manager: Optional[AuditWindowManager] = None


def get_audit_window_manager() -> AuditWindowManager:
    """Get singleton manager instance"""
    global _manager
    if _manager is None:
        _manager = AuditWindowManager()
    return _manager


def should_store_full_audit(token_id: str, ts: int) -> bool:
    """Convenience function to check storage mode"""
    return get_audit_window_manager().should_store_full(token_id, ts)
