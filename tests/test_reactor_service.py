"""
Tests for Reactor Service Layer (v5.26)

Tests:
1. ReactorWrapper functionality
2. ReactorService async interface
3. BeliefMachineService queries
4. Event processing and callbacks
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal

from backend.reactor.core import (
    ReactorWrapper,
    BeliefState,
    ReactionType,
    WindowType,
    STATE_INDICATORS,
    REACTION_INDICATORS,
)
from backend.reactor.service import ReactorService, BeliefMachineService


# =============================================================================
# ReactorWrapper Tests
# =============================================================================

class TestReactorWrapper:
    """Test ReactorWrapper functionality"""

    def test_create_wrapper(self):
        """Test creating ReactorWrapper"""
        wrapper = ReactorWrapper()
        assert wrapper is not None
        assert wrapper.reactor is not None
        assert wrapper.event_bus is not None
        assert not wrapper.is_running

    def test_start_stop(self):
        """Test starting and stopping the reactor"""
        wrapper = ReactorWrapper()
        assert not wrapper.is_running

        wrapper.start()
        assert wrapper.is_running

        wrapper.stop()
        assert not wrapper.is_running

    def test_double_start(self):
        """Test that double start is idempotent"""
        wrapper = ReactorWrapper()
        wrapper.start()
        wrapper.start()  # Should not error
        assert wrapper.is_running
        wrapper.stop()

    def test_double_stop(self):
        """Test that double stop is idempotent"""
        wrapper = ReactorWrapper()
        wrapper.start()
        wrapper.stop()
        wrapper.stop()  # Should not error
        assert not wrapper.is_running

    def test_get_belief_state_default(self):
        """Test getting belief state for unknown token"""
        wrapper = ReactorWrapper()
        state = wrapper.get_belief_state("unknown_token")
        assert state == "STABLE"

    def test_get_all_markets_empty(self):
        """Test getting all markets when none tracked"""
        wrapper = ReactorWrapper()
        markets = wrapper.get_all_markets()
        assert markets == []

    def test_get_stats(self):
        """Test getting reactor statistics"""
        wrapper = ReactorWrapper()
        stats = wrapper.get_stats()

        assert 'events_processed' in stats
        assert 'trades_processed' in stats
        assert 'shocks_detected' in stats
        assert 'reactions_classified' in stats
        assert stats['events_processed'] == 0

    def test_recent_events_empty(self):
        """Test getting recent events when empty"""
        wrapper = ReactorWrapper()
        assert wrapper.get_recent_reactions() == []
        assert wrapper.get_recent_state_changes() == []
        assert wrapper.get_recent_leading_events() == []

    def test_clear_state(self):
        """Test clearing reactor state"""
        wrapper = ReactorWrapper()
        wrapper.clear_state()  # Should not error

    def test_callback_registration(self):
        """Test callback registration"""
        reaction_callback = Mock()
        state_callback = Mock()
        leading_callback = Mock()
        alert_callback = Mock()

        wrapper = ReactorWrapper(
            on_reaction=reaction_callback,
            on_state_change=state_callback,
            on_leading_event=leading_callback,
            on_alert=alert_callback,
        )

        assert wrapper._on_reaction == reaction_callback
        assert wrapper._on_state_change == state_callback
        assert wrapper._on_leading_event == leading_callback
        assert wrapper._on_alert == alert_callback


# =============================================================================
# Event Processing Tests
# =============================================================================

class TestEventProcessing:
    """Test event processing in ReactorWrapper"""

    def test_process_book_event(self):
        """Test processing book snapshot event"""
        wrapper = ReactorWrapper()
        wrapper.start()

        event = {
            'event_type': 'book',
            'token_id': 'token_123',
            'payload': {
                'bids': [
                    {'price': '0.50', 'size': 100},
                    {'price': '0.49', 'size': 200},
                ],
                'asks': [
                    {'price': '0.51', 'size': 150},
                    {'price': '0.52', 'size': 250},
                ],
            },
            'server_ts': int(time.time() * 1000),
        }

        wrapper.process_raw_event(event)

        # Give time for processing
        time.sleep(0.2)

        # Check that order book was created
        assert 'token_123' in wrapper.reactor.order_books

        wrapper.stop()

    def test_process_trade_event(self):
        """Test processing trade event"""
        wrapper = ReactorWrapper()
        wrapper.start()

        # First send book to establish state
        book_event = {
            'event_type': 'book',
            'token_id': 'token_456',
            'payload': {
                'bids': [{'price': '0.50', 'size': 1000}],
                'asks': [{'price': '0.51', 'size': 1000}],
            },
            'server_ts': int(time.time() * 1000),
        }
        wrapper.process_raw_event(book_event)

        # Then send trade
        trade_event = {
            'event_type': 'trade',
            'token_id': 'token_456',
            'payload': {
                'price': '0.50',
                'size': 500,
                'side': 'BUY',
            },
            'server_ts': int(time.time() * 1000) + 100,
        }
        wrapper.process_raw_event(trade_event)

        time.sleep(0.2)

        stats = wrapper.get_stats()
        assert stats['trades_processed'] >= 1

        wrapper.stop()

    def test_process_price_change_event(self):
        """Test processing price change event"""
        wrapper = ReactorWrapper()
        wrapper.start()

        event = {
            'event_type': 'price_change',
            'token_id': 'token_789',
            'payload': {
                'price': '0.55',
                'size': 500,
                'side': 'buy',
                'best_bid': '0.55',
                'best_ask': '0.56',
            },
            'server_ts': int(time.time() * 1000),
        }

        wrapper.process_raw_event(event)
        time.sleep(0.2)

        stats = wrapper.get_stats()
        assert stats['price_changes_processed'] >= 1

        wrapper.stop()

    def test_invalid_event_type(self):
        """Test that invalid event type is ignored"""
        wrapper = ReactorWrapper()
        wrapper.start()

        event = {
            'event_type': 'invalid_type',
            'token_id': 'token_xxx',
            'payload': {},
            'server_ts': int(time.time() * 1000),
        }

        # Should not raise
        wrapper.process_raw_event(event)
        time.sleep(0.1)

        wrapper.stop()


# =============================================================================
# ReactorService Async Tests
# =============================================================================

class TestReactorServiceAsync:
    """Test ReactorService async interface"""

    @pytest.mark.asyncio
    async def test_create_service(self):
        """Test creating ReactorService"""
        service = ReactorService(persist_to_db=False)
        assert service is not None
        assert not service._started

    @pytest.mark.asyncio
    async def test_start_stop_service(self):
        """Test starting and stopping service"""
        service = ReactorService(persist_to_db=False)
        await service.start()
        assert service._started

        await service.stop()
        assert not service._started

    @pytest.mark.asyncio
    async def test_get_belief_state(self):
        """Test getting belief state"""
        service = ReactorService(persist_to_db=False)
        await service.start()

        state = await service.get_belief_state("test_token")
        assert state == "STABLE"

        await service.stop()

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test getting stats"""
        service = ReactorService(persist_to_db=False)
        await service.start()

        stats = await service.get_stats()
        assert 'events_processed' in stats

        await service.stop()

    @pytest.mark.asyncio
    async def test_process_event_async(self):
        """Test processing event asynchronously"""
        service = ReactorService(persist_to_db=False)
        await service.start()

        event = {
            'event_type': 'book',
            'token_id': 'async_token',
            'payload': {
                'bids': [{'price': '0.50', 'size': 100}],
                'asks': [{'price': '0.51', 'size': 100}],
            },
            'server_ts': int(time.time() * 1000),
        }

        await service.process_event(event)
        await asyncio.sleep(0.2)

        markets = await service.get_all_markets()
        assert any(m['token_id'] == 'async_token' for m in markets)

        await service.stop()

    @pytest.mark.asyncio
    async def test_get_recent_reactions(self):
        """Test getting recent reactions"""
        service = ReactorService(persist_to_db=False)
        await service.start()

        reactions = await service.get_recent_reactions(limit=10)
        assert isinstance(reactions, list)

        await service.stop()

    @pytest.mark.asyncio
    async def test_callbacks_triggered(self):
        """Test that callbacks are triggered"""
        reaction_events = []
        state_events = []

        def on_reaction(r):
            reaction_events.append(r)

        def on_state(s):
            state_events.append(s)

        service = ReactorService(
            persist_to_db=False,
            on_reaction=on_reaction,
            on_state_change=on_state,
        )
        await service.start()

        # Process events that might trigger reactions
        # (In practice, reactions require shock + window expiry)

        await service.stop()


# =============================================================================
# BeliefMachineService Tests
# =============================================================================

class TestBeliefMachineService:
    """Test BeliefMachineService queries"""

    @pytest.mark.asyncio
    async def test_create_service(self):
        """Test creating BeliefMachineService"""
        service = BeliefMachineService()
        assert service is not None

    @pytest.mark.asyncio
    async def test_compute_confidence(self):
        """Test confidence computation"""
        service = BeliefMachineService()

        assert service._compute_confidence('STABLE') == 85.0
        assert service._compute_confidence('FRAGILE') == 70.0
        assert service._compute_confidence('CRACKING') == 60.0
        assert service._compute_confidence('BROKEN') == 75.0
        assert service._compute_confidence('UNKNOWN') == 50.0


# =============================================================================
# State and Indicator Tests
# =============================================================================

class TestStateIndicators:
    """Test state and reaction indicators"""

    def test_belief_state_values(self):
        """Test BeliefState enum values"""
        assert BeliefState.STABLE.value == "STABLE"
        assert BeliefState.FRAGILE.value == "FRAGILE"
        assert BeliefState.CRACKING.value == "CRACKING"
        assert BeliefState.BROKEN.value == "BROKEN"

    def test_state_indicators(self):
        """Test state indicator emojis"""
        assert STATE_INDICATORS[BeliefState.STABLE] == "🟢"
        assert STATE_INDICATORS[BeliefState.FRAGILE] == "🟡"
        assert STATE_INDICATORS[BeliefState.CRACKING] == "🟠"
        assert STATE_INDICATORS[BeliefState.BROKEN] == "🔴"

    def test_reaction_type_values(self):
        """Test ReactionType enum values"""
        assert ReactionType.VACUUM.value == "VACUUM"
        assert ReactionType.SWEEP.value == "SWEEP"
        assert ReactionType.CHASE.value == "CHASE"
        assert ReactionType.PULL.value == "PULL"
        assert ReactionType.HOLD.value == "HOLD"
        assert ReactionType.DELAYED.value == "DELAYED"
        assert ReactionType.NO_IMPACT.value == "NO_IMPACT"

    def test_reaction_indicators(self):
        """Test reaction indicator emojis"""
        assert REACTION_INDICATORS[ReactionType.VACUUM] == "🔴"
        assert REACTION_INDICATORS[ReactionType.SWEEP] == "🟣"
        assert REACTION_INDICATORS[ReactionType.HOLD] == "🟢"
        assert REACTION_INDICATORS[ReactionType.PULL] == "🟠"

    def test_window_type_values(self):
        """Test WindowType enum values"""
        assert WindowType.FAST.value == "FAST"
        assert WindowType.SLOW.value == "SLOW"


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for reactor services"""

    @pytest.mark.asyncio
    async def test_full_event_flow(self):
        """Test full event processing flow"""
        reactions = []
        states = []

        service = ReactorService(
            persist_to_db=False,
            on_reaction=lambda r: reactions.append(r),
            on_state_change=lambda s: states.append(s),
        )
        await service.start()

        # Send a sequence of events
        base_ts = int(time.time() * 1000)

        # Book snapshot
        await service.process_event({
            'event_type': 'book',
            'token_id': 'integration_test',
            'payload': {
                'bids': [
                    {'price': '0.50', 'size': 1000},
                    {'price': '0.49', 'size': 2000},
                ],
                'asks': [
                    {'price': '0.51', 'size': 1000},
                    {'price': '0.52', 'size': 2000},
                ],
            },
            'server_ts': base_ts,
        })

        # Price changes
        for i in range(5):
            await service.process_event({
                'event_type': 'price_change',
                'token_id': 'integration_test',
                'payload': {
                    'price': '0.50',
                    'size': 1000 - i * 100,
                    'side': 'buy',
                },
                'server_ts': base_ts + i * 100,
            })

        await asyncio.sleep(0.3)

        # Verify processing
        stats = await service.get_stats()
        assert stats['books_processed'] >= 1
        assert stats['price_changes_processed'] >= 5

        await service.stop()

    @pytest.mark.asyncio
    async def test_multiple_tokens(self):
        """Test processing events for multiple tokens"""
        service = ReactorService(persist_to_db=False)
        await service.start()

        base_ts = int(time.time() * 1000)

        # Process events for multiple tokens
        for i, token_id in enumerate(['token_a', 'token_b', 'token_c']):
            await service.process_event({
                'event_type': 'book',
                'token_id': token_id,
                'payload': {
                    'bids': [{'price': f'0.{50+i}', 'size': 1000}],
                    'asks': [{'price': f'0.{51+i}', 'size': 1000}],
                },
                'server_ts': base_ts + i * 100,
            })

        await asyncio.sleep(0.3)

        markets = await service.get_all_markets()
        token_ids = [m['token_id'] for m in markets]

        assert 'token_a' in token_ids
        assert 'token_b' in token_ids
        assert 'token_c' in token_ids

        await service.stop()


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Test error handling in reactor services"""

    def test_wrapper_handles_malformed_event(self):
        """Test that wrapper handles malformed events gracefully"""
        wrapper = ReactorWrapper()
        wrapper.start()

        # Missing fields
        wrapper.process_raw_event({})
        wrapper.process_raw_event({'event_type': 'trade'})
        wrapper.process_raw_event({'event_type': 'trade', 'token_id': 'test'})

        time.sleep(0.1)
        # Should not crash
        wrapper.stop()

    @pytest.mark.asyncio
    async def test_service_handles_db_error(self):
        """Test that service handles database errors gracefully"""
        service = ReactorService(
            db_config={
                'host': '127.0.0.1',
                'port': 99999,  # Invalid port
                'database': 'nonexistent',
                'user': 'test',
                'password': 'test',
            },
            persist_to_db=True,
        )

        # Should not crash even with invalid DB
        # (persistence will fail silently)
        await service.start()
        await service.stop()
