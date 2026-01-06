"""
Storage module - Conditional storage and retention policies.

"平时不存全量，关键时刻才保留完整证据链。"
"""

from .audit_window import (
    AuditWindowManager,
    AuditWindow,
    StorageMode,
    get_audit_window_manager,
    should_store_full_audit,
    AUDIT_WINDOW_CONFIG,
    AUDIT_TRIGGER_STATES,
    AUDIT_TRIGGER_SEVERITIES,
)

__all__ = [
    "AuditWindowManager",
    "AuditWindow",
    "StorageMode",
    "get_audit_window_manager",
    "should_store_full_audit",
    "AUDIT_WINDOW_CONFIG",
    "AUDIT_TRIGGER_STATES",
    "AUDIT_TRIGGER_SEVERITIES",
]
