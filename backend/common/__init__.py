"""
Belief Reaction System - Common Backend Modules
Shared types, config, and utilities.

v5.19: Add unified attribution system
"""

from .determinism import (
    DeterminismError,
    ProcessingMode,
    EventSortKey,
    EventClock,
    ReplayContext,
    TokenEventQueue,
    AsyncTokenEventQueue,
    get_event_clock,
    deterministic_now,
    validate_event_order,
    sort_events,
)

from .attribution import (
    AttributionType,
    DepthChangeAttribution,
    MultiLevelAttribution,
    compute_attribution,
    compute_multi_level_attribution,
    is_trade_driven,
    is_cancel_driven,
    is_replenishment,
    classify_for_reaction,
    reconcile_volume,
    AttributionTracker,
    TRADE_DOMINANT_THRESHOLD,
    CANCEL_DOMINANT_THRESHOLD,
)

__all__ = [
    # Determinism (v5.13)
    'DeterminismError',
    'ProcessingMode',
    'EventSortKey',
    'EventClock',
    'ReplayContext',
    'TokenEventQueue',
    'AsyncTokenEventQueue',
    'get_event_clock',
    'deterministic_now',
    'validate_event_order',
    'sort_events',
    # Attribution (v5.19)
    'AttributionType',
    'DepthChangeAttribution',
    'MultiLevelAttribution',
    'compute_attribution',
    'compute_multi_level_attribution',
    'is_trade_driven',
    'is_cancel_driven',
    'is_replenishment',
    'classify_for_reaction',
    'reconcile_volume',
    'AttributionTracker',
    'TRADE_DOMINANT_THRESHOLD',
    'CANCEL_DOMINANT_THRESHOLD',
]
