"""
Pytest fixtures for Belief Reaction System tests.
"""

import pytest
import sys
import os
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# Mock Database Fixtures
# =============================================================================

@pytest.fixture
def mock_db_connection():
    """Mock database connection for testing without real DB."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


@pytest.fixture
def sample_market_data():
    """Sample market data for testing."""
    return {
        'token_id': 'test-token-123',
        'condition_id': 'test-condition-456',
        'question': 'Will this test pass?',
        'slug': 'test-market',
        'tick_size': Decimal('0.01'),
        'yes_token_id': 'test-token-123',
        'no_token_id': 'test-token-no-123',
    }


@pytest.fixture
def sample_shock_event():
    """Sample shock event for testing."""
    return {
        'shock_id': 'shock-001',
        'token_id': 'test-token-123',
        'ts': datetime.now(timezone.utc),
        'price': Decimal('0.72'),
        'side': 'bid',
        'trade_volume': Decimal('150.0'),
        'baseline_size': Decimal('500.0'),
        'trigger_type': 'volume',
    }


@pytest.fixture
def sample_reaction_event():
    """Sample reaction event for testing."""
    return {
        'reaction_id': 'reaction-001',
        'shock_id': 'shock-001',
        'token_id': 'test-token-123',
        'ts': datetime.now(timezone.utc),
        'price': Decimal('0.72'),
        'side': 'bid',
        'reaction_type': 'VACUUM',
        'window_type': 'FAST',
        'refill_ratio': Decimal('0.08'),
        'drop_ratio': Decimal('0.92'),
        'vacuum_duration_ms': 4200,
        'shift_ticks': 0,
        'time_to_refill_ms': None,
    }


@pytest.fixture
def sample_belief_state():
    """Sample belief state change for testing."""
    return {
        'id': 'state-001',
        'token_id': 'test-token-123',
        'ts': datetime.now(timezone.utc),
        'old_state': 'STABLE',
        'new_state': 'FRAGILE',
        'trigger_reaction_id': 'reaction-001',
        'evidence': {'reason': 'VACUUM detected'},
    }


@pytest.fixture
def sample_anchor_levels():
    """Sample anchor levels for testing."""
    return [
        {'price': Decimal('0.72'), 'side': 'bid', 'anchor_score': 0.95, 'rank': 1},
        {'price': Decimal('0.68'), 'side': 'bid', 'anchor_score': 0.82, 'rank': 2},
        {'price': Decimal('0.76'), 'side': 'ask', 'anchor_score': 0.78, 'rank': 3},
    ]


@pytest.fixture
def sample_evidence_bundle(sample_shock_event, sample_reaction_event, sample_anchor_levels):
    """Sample evidence bundle for testing."""
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    return {
        'token_id': 'test-token-123',
        't0': now,
        'window': {'from_ts': now - 30000, 'to_ts': now + 30000},
        'shocks': [sample_shock_event],
        'reactions': [sample_reaction_event],
        'leading_events': [],
        'belief_states': [],
        'anchors': sample_anchor_levels,
    }


# =============================================================================
# Heatmap Test Fixtures
# =============================================================================

@pytest.fixture
def sample_book_bins():
    """Sample book_bins data for heatmap tests."""
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    bins = []
    for t_offset in range(0, 10000, 250):  # 40 time buckets
        for price in [0.68, 0.69, 0.70, 0.71, 0.72, 0.73, 0.74, 0.75]:
            bins.append({
                'bucket_ts': now + t_offset,
                'token_id': 'test-token-123',
                'side': 'bid' if price < 0.72 else 'ask',
                'price': Decimal(str(price)),
                'size': Decimal(str(100 + (price * 100))),
            })
    return bins


# =============================================================================
# API Test Fixtures
# =============================================================================

@pytest.fixture
def mock_fastapi_app():
    """Create a test FastAPI app with mocked database."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    # Import and include the v1 router
    try:
        from backend.api.routes.v1 import router
        app.include_router(router)
    except ImportError:
        pass

    return app


@pytest.fixture
def api_client(mock_fastapi_app):
    """Test client for API testing."""
    from fastapi.testclient import TestClient
    return TestClient(mock_fastapi_app)
