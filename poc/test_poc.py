#!/usr/bin/env python3
"""
Unit tests for Belief Reaction System POC.
Tests the core logic without requiring network access.
"""

import sys
import os
from decimal import Decimal
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from poc.models import (
    ReactionType, BeliefState, PriceLevel, TradeEvent,
    ShockEvent, ReactionEvent, STATE_INDICATORS
)
from poc.config import (
    SHOCK_VOLUME_THRESHOLD, REACTION_WINDOW_MS,
    HOLD_REFILL_THRESHOLD, VACUUM_THRESHOLD
)
from poc.shock_detector import ShockDetector
from poc.reaction_classifier import ReactionClassifier
from poc.belief_state import BeliefStateMachine, BeliefStateEngine
from poc.reaction_engine import ReactionEngine, OrderBookState


def test_models():
    """Test model creation and basic operations."""
    print("Testing models...")

    # Test ReactionType
    assert len(ReactionType) == 6
    assert ReactionType.HOLD.value == 'HOLD'
    assert ReactionType.VACUUM.value == 'VACUUM'

    # Test BeliefState
    assert len(BeliefState) == 4
    assert BeliefState.STABLE.value == 'STABLE'
    assert BeliefState.BROKEN.value == 'BROKEN'

    # Test STATE_INDICATORS
    assert STATE_INDICATORS[BeliefState.STABLE] == '🟢'
    assert STATE_INDICATORS[BeliefState.BROKEN] == '🔴'

    # Test PriceLevel
    level = PriceLevel(
        token_id='test_token',
        price=Decimal('0.72'),
        side='bid',
        size_now=100.0
    )
    assert level.token_id == 'test_token'
    assert level.price == Decimal('0.72')
    delta = level.update_size(150.0, 1000)
    assert delta == 50.0
    assert level.size_now == 150.0
    assert level.size_peak == 150.0

    # Test TradeEvent
    trade = TradeEvent(
        token_id='test_token',
        price=Decimal('0.72'),
        size=50.0,
        side='BUY',
        timestamp=1000
    )
    assert trade.side == 'BUY'

    print("  Models OK")


def test_shock_detector():
    """Test shock detection logic."""
    print("Testing ShockDetector...")

    detector = ShockDetector()

    # Create a price level
    level = PriceLevel(
        token_id='test_token',
        price=Decimal('0.72'),
        side='bid',
        size_now=100.0
    )

    # Trade that doesn't trigger shock (too small)
    trade1 = TradeEvent(
        token_id='test_token',
        price=Decimal('0.72'),
        size=10.0,  # 10% of level, below 35% threshold
        side='SELL',
        timestamp=1000
    )
    shock = detector.on_trade(trade1, level)
    assert shock is None, "Small trade should not trigger shock"

    # Trade that triggers shock (volume threshold)
    trade2 = TradeEvent(
        token_id='test_token',
        price=Decimal('0.72'),
        size=40.0,  # 40% of level, above 35% threshold
        side='SELL',
        timestamp=1500
    )
    shock = detector.on_trade(trade2, level)
    assert shock is not None, "Large trade should trigger shock"
    assert shock.trigger_type == 'volume'
    assert shock.liquidity_before == 100.0

    stats = detector.get_stats()
    assert stats['total_shocks'] == 1
    assert stats['active_shocks'] == 1

    print("  ShockDetector OK")


def test_shock_consecutive():
    """Test shock detection with consecutive trades."""
    print("Testing ShockDetector (consecutive)...")

    detector = ShockDetector()

    # Create a level with no size (can't trigger volume threshold)
    level = PriceLevel(
        token_id='test_token',
        price=Decimal('0.50'),
        side='ask',
        size_now=0  # No existing liquidity
    )

    # Three consecutive trades at same price
    for i in range(3):
        trade = TradeEvent(
            token_id='test_token',
            price=Decimal('0.50'),
            size=10.0,
            side='BUY',
            timestamp=1000 + i * 100
        )
        shock = detector.on_trade(trade, level)

        if i < 2:
            assert shock is None, f"Trade {i+1} should not trigger shock"
        else:
            assert shock is not None, "Third consecutive trade should trigger shock"
            assert shock.trigger_type == 'consecutive'

    print("  ShockDetector (consecutive) OK")


def test_reaction_classifier():
    """Test reaction classification logic."""
    print("Testing ReactionClassifier...")

    classifier = ReactionClassifier()

    # Create a shock
    shock = ShockEvent(
        token_id='test_token',
        price=Decimal('0.72'),
        side='bid',
        ts_start=1000,
        trade_volume=40.0,
        liquidity_before=100.0,
        trigger_type='volume',
        reaction_window_end=1000 + REACTION_WINDOW_MS
    )

    # Start observation
    classifier.start_observation(shock)
    assert classifier.has_active_observation('test_token', Decimal('0.72'))

    # Simulate HOLD behavior: quick refill
    # Sample at different times showing recovery
    classifier.record_sample('test_token', Decimal('0.72'), 1500, 60.0)  # After shock
    classifier.record_sample('test_token', Decimal('0.72'), 2000, 70.0)  # Recovering
    classifier.record_sample('test_token', Decimal('0.72'), 3000, 85.0)  # Almost recovered
    classifier.record_sample('test_token', Decimal('0.72'), 4000, 95.0)  # Fully recovered

    # Classify
    reaction = classifier.classify(shock)
    assert reaction is not None
    assert reaction.reaction_type == ReactionType.HOLD, f"Expected HOLD, got {reaction.reaction_type}"

    stats = classifier.get_stats()
    assert stats['total_classified'] == 1
    assert stats['by_type']['HOLD'] == 1

    print("  ReactionClassifier OK")


def test_vacuum_classification():
    """Test VACUUM classification."""
    print("Testing VACUUM classification...")

    classifier = ReactionClassifier()

    shock = ShockEvent(
        token_id='test_token',
        price=Decimal('0.72'),
        side='bid',
        ts_start=1000,
        trade_volume=40.0,
        liquidity_before=100.0,
        trigger_type='volume',
        reaction_window_end=1000 + REACTION_WINDOW_MS
    )

    classifier.start_observation(shock)

    # Simulate VACUUM: liquidity stays near zero
    for t in range(1500, 21000, 500):
        classifier.record_sample('test_token', Decimal('0.72'), t, 2.0)  # Only 2% of original

    reaction = classifier.classify(shock)
    assert reaction is not None
    assert reaction.reaction_type == ReactionType.VACUUM, f"Expected VACUUM, got {reaction.reaction_type}"

    print("  VACUUM classification OK")


def test_belief_state_machine():
    """Test belief state machine transitions."""
    print("Testing BeliefStateMachine...")

    state_changes = []

    def on_change(change):
        state_changes.append(change)

    machine = BeliefStateMachine(
        token_id='test_token',
        key_levels=[Decimal('0.72'), Decimal('0.75'), Decimal('0.78')],
        on_state_change=on_change
    )

    assert machine.state == BeliefState.STABLE

    # PULL at key level should trigger CRACKING
    reaction1 = ReactionEvent(
        token_id='test_token',
        price=Decimal('0.72'),
        side='bid',
        reaction_type=ReactionType.PULL,
        refill_ratio=0.2,
        min_liquidity=5.0,
        liquidity_before=100.0
    )

    change = machine.on_reaction(reaction1)
    assert change is not None, "PULL should trigger state change"
    assert machine.state == BeliefState.CRACKING, f"Expected CRACKING, got {machine.state}"
    assert len(state_changes) == 1

    # VACUUM at one key level (stays CRACKING since we need 2+ VACUUM for BROKEN)
    reaction2 = ReactionEvent(
        token_id='test_token',
        price=Decimal('0.75'),
        side='bid',
        reaction_type=ReactionType.VACUUM,
        refill_ratio=0.05,
        min_liquidity=2.0,
        liquidity_before=100.0
    )

    change = machine.on_reaction(reaction2)
    # Still CRACKING with one VACUUM (need 2+ for BROKEN)
    assert machine.state == BeliefState.CRACKING

    # VACUUM at a second key level should trigger BROKEN
    reaction3 = ReactionEvent(
        token_id='test_token',
        price=Decimal('0.78'),
        side='bid',
        reaction_type=ReactionType.VACUUM,
        refill_ratio=0.03,
        min_liquidity=1.0,
        liquidity_before=100.0
    )

    change = machine.on_reaction(reaction3)
    assert change is not None, "Second VACUUM should trigger BROKEN"
    assert machine.state == BeliefState.BROKEN, f"Expected BROKEN, got {machine.state}"

    print("  BeliefStateMachine OK")


def test_order_book_state():
    """Test order book state management."""
    print("Testing OrderBookState...")

    book = OrderBookState('test_token')

    # Simulate book snapshot
    bids = [
        {'price': '0.72', 'size': '100'},
        {'price': '0.71', 'size': '50'},
    ]
    asks = [
        {'price': '0.73', 'size': '80'},
        {'price': '0.74', 'size': '60'},
    ]

    book.on_book_snapshot(bids, asks, 1000)

    assert book.best_bid == Decimal('0.72')
    assert book.best_ask == Decimal('0.73')

    level = book.get_level('bid', Decimal('0.72'))
    assert level is not None
    assert level.size_now == 100.0

    # Test price change
    level, delta = book.on_price_change(
        Decimal('0.72'), 80.0, 'bid', None, None, 1500
    )
    assert delta == -20.0
    assert level.size_now == 80.0

    # Test key levels
    bid_keys = book.get_key_levels('bid', count=2)
    assert len(bid_keys) == 2
    assert Decimal('0.72') in bid_keys  # Highest peak

    print("  OrderBookState OK")


def test_reaction_engine_integration():
    """Test full integration of reaction engine."""
    print("Testing ReactionEngine integration...")

    reactions = []
    state_changes = []
    alerts = []

    engine = ReactionEngine(
        on_reaction=lambda r: reactions.append(r),
        on_state_change=lambda c: state_changes.append(c),
        on_alert=lambda a: alerts.append(a)
    )

    # Start engine
    engine.start()

    # Simulate book snapshot
    book_data = {
        'asset_id': 'test_token',
        'timestamp': '1000',
        'bids': [
            {'price': '0.72', 'size': '100'},
            {'price': '0.71', 'size': '50'},
        ],
        'asks': [
            {'price': '0.73', 'size': '80'},
        ]
    }
    engine.on_book(book_data)

    assert 'test_token' in engine.order_books
    assert engine.stats['books_processed'] == 1

    # Simulate a large trade (should trigger shock)
    trade_data = {
        'asset_id': 'test_token',
        'price': '0.72',
        'size': '50',  # 50% of 100
        'side': 'SELL',
        'timestamp': '2000'
    }
    engine.on_trade(trade_data)

    assert engine.stats['trades_processed'] == 1
    assert engine.stats['shocks_detected'] == 1
    assert len(alerts) >= 1  # At least shock alert

    # Simulate price change (level depleted)
    price_change_data = {
        'timestamp': '2500',
        'price_changes': [
            {
                'asset_id': 'test_token',
                'price': '0.72',
                'size': '5',  # Dropped to 5% - VACUUM territory
                'side': 'BUY',
                'best_bid': '0.71',
                'best_ask': '0.73'
            }
        ]
    }
    engine.on_price_change(price_change_data)

    # Stop engine
    engine.stop()

    # Check stats
    stats = engine.get_stats()
    print(f"    Trades: {stats['trades_processed']}")
    print(f"    Shocks: {stats['shocks_detected']}")
    print(f"    Alerts: {len(alerts)}")

    print("  ReactionEngine integration OK")


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("  Belief Reaction System - POC Tests")
    print("=" * 60)
    print()

    tests = [
        test_models,
        test_shock_detector,
        test_shock_consecutive,
        test_reaction_classifier,
        test_vacuum_classification,
        test_belief_state_machine,
        test_order_book_state,
        test_reaction_engine_integration,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    print()
    print("=" * 60)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
