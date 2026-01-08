"""
Tests for Collector Service (v5.29)

Tests:
1. CollectorService initialization
2. Start/stop lifecycle
3. Event forwarding to reactor
4. Token management
5. Connection state handling
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import time

from backend.collector.service import (
    CollectorService,
    IntegratedCollectorReactor,
)
from poc.collector import ConnectionState
from poc.event_bus import RawEvent, EventType


# =============================================================================
# CollectorService Tests
# =============================================================================

class TestCollectorServiceInit:
    """Test CollectorService initialization"""

    def test_create_service(self):
        """Test creating CollectorService"""
        with patch('backend.collector.service.DataCollector'):
            service = CollectorService(token_ids=['token1', 'token2'])
            assert service is not None
            assert service.token_ids == ['token1', 'token2']
            assert not service._started

    def test_create_with_reactor(self):
        """Test creating with reactor service"""
        with patch('backend.collector.service.DataCollector'):
            reactor = Mock()
            service = CollectorService(
                token_ids=['token1'],
                reactor_service=reactor,
            )
            assert service.reactor_service == reactor

    def test_create_with_callback(self):
        """Test creating with connection callback"""
        callback = Mock()
        with patch('backend.collector.service.DataCollector'):
            service = CollectorService(
                token_ids=['token1'],
                on_connection_change=callback,
            )
            assert service._on_connection_change == callback


# =============================================================================
# Lifecycle Tests
# =============================================================================

class TestCollectorLifecycle:
    """Test CollectorService start/stop lifecycle"""

    @pytest.mark.asyncio
    async def test_start_service(self):
        """Test starting the service"""
        with patch('backend.collector.service.DataCollector') as MockCollector:
            mock_collector = Mock()
            MockCollector.return_value = mock_collector

            service = CollectorService(token_ids=['token1'])
            await service.start()

            assert service._started
            mock_collector.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_service(self):
        """Test stopping the service"""
        with patch('backend.collector.service.DataCollector') as MockCollector:
            mock_collector = Mock()
            MockCollector.return_value = mock_collector

            service = CollectorService(token_ids=['token1'])
            await service.start()
            await service.stop()

            assert not service._started
            mock_collector.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_double_start(self):
        """Test that double start is idempotent"""
        with patch('backend.collector.service.DataCollector') as MockCollector:
            mock_collector = Mock()
            MockCollector.return_value = mock_collector

            service = CollectorService(token_ids=['token1'])
            await service.start()
            await service.start()  # Second start

            # Should only start once
            assert mock_collector.start.call_count == 1

    @pytest.mark.asyncio
    async def test_double_stop(self):
        """Test that double stop is idempotent"""
        with patch('backend.collector.service.DataCollector') as MockCollector:
            mock_collector = Mock()
            MockCollector.return_value = mock_collector

            service = CollectorService(token_ids=['token1'])
            await service.start()
            await service.stop()
            await service.stop()  # Second stop

            # Should only stop once
            assert mock_collector.stop.call_count == 1


# =============================================================================
# Token Management Tests
# =============================================================================

class TestTokenManagement:
    """Test token addition and removal"""

    @pytest.mark.asyncio
    async def test_add_tokens(self):
        """Test adding tokens"""
        with patch('backend.collector.service.DataCollector') as MockCollector:
            mock_collector = Mock()
            MockCollector.return_value = mock_collector

            service = CollectorService(token_ids=['token1'])
            await service.add_tokens(['token2', 'token3'])

            assert 'token2' in service.token_ids
            assert 'token3' in service.token_ids

    @pytest.mark.asyncio
    async def test_remove_tokens(self):
        """Test removing tokens"""
        with patch('backend.collector.service.DataCollector') as MockCollector:
            mock_collector = Mock()
            MockCollector.return_value = mock_collector

            service = CollectorService(token_ids=['token1', 'token2'])
            await service.remove_tokens(['token2'])

            assert 'token1' in service.token_ids
            assert 'token2' not in service.token_ids


# =============================================================================
# Connection State Tests
# =============================================================================

class TestConnectionState:
    """Test connection state handling"""

    def test_state_property(self):
        """Test state property"""
        with patch('backend.collector.service.DataCollector') as MockCollector:
            mock_collector = Mock()
            mock_collector.state = ConnectionState.CONNECTED
            MockCollector.return_value = mock_collector

            service = CollectorService(token_ids=['token1'])
            assert service.state == ConnectionState.CONNECTED

    def test_is_connected(self):
        """Test is_connected property"""
        with patch('backend.collector.service.DataCollector') as MockCollector:
            mock_collector = Mock()
            mock_collector.state = ConnectionState.CONNECTED
            MockCollector.return_value = mock_collector

            service = CollectorService(token_ids=['token1'])
            assert service.is_connected is True

            mock_collector.state = ConnectionState.DISCONNECTED
            assert service.is_connected is False

    def test_connection_callback(self):
        """Test connection state callback is called"""
        callback = Mock()
        with patch('backend.collector.service.DataCollector') as MockCollector:
            mock_collector = Mock()
            MockCollector.return_value = mock_collector

            service = CollectorService(
                token_ids=['token1'],
                on_connection_change=callback,
            )

            # Simulate state change
            service._handle_state_change(ConnectionState.CONNECTED)
            callback.assert_called_once_with(ConnectionState.CONNECTED)


# =============================================================================
# Statistics Tests
# =============================================================================

class TestStatistics:
    """Test statistics gathering"""

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test getting statistics"""
        with patch('backend.collector.service.DataCollector') as MockCollector:
            mock_collector = Mock()
            mock_collector.get_stats.return_value = {
                'messages_received': 100,
                'messages_published': 95,
            }
            MockCollector.return_value = mock_collector

            service = CollectorService(token_ids=['token1'])
            stats = await service.get_stats()

            assert 'messages_received' in stats
            assert 'events_forwarded_to_reactor' in stats


# =============================================================================
# Event Conversion Tests
# =============================================================================

class TestEventConversion:
    """Test RawEvent to dict conversion"""

    def test_book_event_conversion(self):
        """Test converting book event"""
        with patch('backend.collector.service.DataCollector'):
            service = CollectorService(token_ids=['token1'])

            raw_event = RawEvent(
                event_type=EventType.BOOK,
                token_id='token_abc',
                payload={'bids': [], 'asks': []},
                server_ts=1704067200000,
                ws_ts=1704067199900,
            )

            result = service._raw_event_to_dict(raw_event)

            assert result['event_type'] == 'book'
            assert result['token_id'] == 'token_abc'
            assert result['server_ts'] == 1704067200000

    def test_trade_event_conversion(self):
        """Test converting trade event"""
        with patch('backend.collector.service.DataCollector'):
            service = CollectorService(token_ids=['token1'])

            raw_event = RawEvent(
                event_type=EventType.TRADE,
                token_id='token_xyz',
                payload={'price': '0.50', 'size': 100},
                server_ts=1704067200000,
            )

            result = service._raw_event_to_dict(raw_event)

            assert result['event_type'] == 'trade'
            assert result['token_id'] == 'token_xyz'

    def test_price_change_event_conversion(self):
        """Test converting price_change event"""
        with patch('backend.collector.service.DataCollector'):
            service = CollectorService(token_ids=['token1'])

            raw_event = RawEvent(
                event_type=EventType.PRICE_CHANGE,
                token_id='token_123',
                payload={'price': '0.55', 'size': 500},
                server_ts=1704067200000,
            )

            result = service._raw_event_to_dict(raw_event)

            assert result['event_type'] == 'price_change'


# =============================================================================
# IntegratedCollectorReactor Tests
# =============================================================================

class TestIntegratedCollectorReactor:
    """Test IntegratedCollectorReactor"""

    @pytest.mark.asyncio
    async def test_create_integrated_service(self):
        """Test creating integrated service"""
        with patch('backend.collector.service.DataCollector'):
            with patch('backend.reactor.service.ReactorService'):
                service = IntegratedCollectorReactor(
                    token_ids=['token1', 'token2'],
                    persist_to_db=False,
                )

                assert service.token_ids == ['token1', 'token2']
                assert service.reactor_service is not None
                assert service.collector_service is not None

    @pytest.mark.asyncio
    async def test_start_stop_integrated(self):
        """Test starting and stopping integrated service"""
        with patch('backend.collector.service.DataCollector') as MockCollector:
            mock_collector = Mock()
            MockCollector.return_value = mock_collector

            with patch('backend.reactor.service.ReactorService') as MockReactor:
                mock_reactor = AsyncMock()
                MockReactor.return_value = mock_reactor

                service = IntegratedCollectorReactor(
                    token_ids=['token1'],
                    persist_to_db=False,
                )

                await service.start()
                assert service._started

                await service.stop()
                assert not service._started

    @pytest.mark.asyncio
    async def test_get_combined_stats(self):
        """Test getting combined statistics"""
        with patch('backend.collector.service.DataCollector') as MockCollector:
            mock_collector = Mock()
            mock_collector.get_stats.return_value = {'messages': 10}
            MockCollector.return_value = mock_collector

            with patch('backend.reactor.service.ReactorService') as MockReactor:
                mock_reactor = AsyncMock()
                mock_reactor.get_stats = AsyncMock(return_value={'events': 5})
                MockReactor.return_value = mock_reactor

                service = IntegratedCollectorReactor(
                    token_ids=['token1'],
                    persist_to_db=False,
                )

                stats = await service.get_stats()

                assert 'collector' in stats
                assert 'reactor' in stats


# =============================================================================
# Connection State Enum Tests
# =============================================================================

class TestConnectionStateEnum:
    """Test ConnectionState enum values"""

    def test_state_values(self):
        """Test ConnectionState enum values"""
        assert ConnectionState.DISCONNECTED.value == "DISCONNECTED"
        assert ConnectionState.CONNECTING.value == "CONNECTING"
        assert ConnectionState.CONNECTED.value == "CONNECTED"
        assert ConnectionState.RECONNECTING.value == "RECONNECTING"
