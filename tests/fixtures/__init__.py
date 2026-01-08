"""
Adversarial Test Fixtures Library (v5.21)

Provides fixed, reproducible raw_events fixtures for adversarial testing.

Usage:
    from tests.fixtures import get_scenario, list_scenarios, SCENARIOS

    # Get a specific scenario
    scenario = get_scenario('vacuum_at_anchor')
    raw_events = scenario.raw_events
    expected = scenario.expected_outcomes

    # List all scenarios
    all_scenarios = list_scenarios()

    # Filter by tag
    manipulation_scenarios = list_scenarios(tags=['manipulation'])

"每一个反例都有故事"
"""

from .scenarios import (
    # Core types
    AdversarialScenario,
    EventType,
    BASE_TS,
    # Scenarios
    SCENARIOS,
    VACUUM_AT_ANCHOR,
    PULL_CANCEL_DRIVEN,
    SWEEP_WITH_RECOVERY,
    SPOOF_ORDER_CANCEL,
    FLASH_CRASH_RECOVERY,
    LAYERING_WITHDRAWAL,
    WASH_TRADE_PATTERN,
    QUOTE_STUFFING_NOISE,
    PRE_SHOCK_PULL,
    GRADUAL_THINNING,
    # Functions
    get_scenario,
    list_scenarios,
    get_scenarios_by_tag,
    # Event builders
    trade_event,
    price_change_event,
    order_cancelled_event,
    book_snapshot_event,
)

__all__ = [
    # Types
    'AdversarialScenario',
    'EventType',
    'BASE_TS',
    # Scenario registry
    'SCENARIOS',
    # Individual scenarios
    'VACUUM_AT_ANCHOR',
    'PULL_CANCEL_DRIVEN',
    'SWEEP_WITH_RECOVERY',
    'SPOOF_ORDER_CANCEL',
    'FLASH_CRASH_RECOVERY',
    'LAYERING_WITHDRAWAL',
    'WASH_TRADE_PATTERN',
    'QUOTE_STUFFING_NOISE',
    'PRE_SHOCK_PULL',
    'GRADUAL_THINNING',
    # Functions
    'get_scenario',
    'list_scenarios',
    'get_scenarios_by_tag',
    # Event builders
    'trade_event',
    'price_change_event',
    'order_cancelled_event',
    'book_snapshot_event',
]
