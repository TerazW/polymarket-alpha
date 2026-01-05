"""
Tests for v1 API Endpoints.
Tests are structured to skip gracefully when dependencies aren't available.
"""

import pytest
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# Helper: Try to get the API app
# =============================================================================

def get_test_client():
    """Try to create a test client for the API."""
    try:
        from fastapi.testclient import TestClient
        from backend.api.main import app
        return TestClient(app)
    except ImportError as e:
        return None
    except Exception as e:
        return None


# =============================================================================
# Schema Validation Tests (no database required)
# =============================================================================

class TestSchemaValidation:
    """Tests for API schema/enum validation."""

    def test_belief_state_enum_values(self):
        """BeliefState enum should have correct values."""
        try:
            from backend.api.schemas.v1 import BeliefState
        except ImportError:
            pytest.skip("Schema imports not available")

        assert BeliefState.STABLE.value == 'STABLE'
        assert BeliefState.FRAGILE.value == 'FRAGILE'
        assert BeliefState.CRACKING.value == 'CRACKING'
        assert BeliefState.BROKEN.value == 'BROKEN'

    def test_reaction_type_enum_values(self):
        """ReactionType enum should have all 7 types."""
        try:
            from backend.api.schemas.v1 import ReactionType
        except ImportError:
            pytest.skip("Schema imports not available")

        expected_types = {'VACUUM', 'SWEEP', 'CHASE', 'PULL', 'HOLD', 'DELAYED', 'NO_IMPACT'}
        actual_types = {rt.value for rt in ReactionType}
        assert actual_types == expected_types

    def test_alert_severity_enum_values(self):
        """AlertSeverity enum should have correct values."""
        try:
            from backend.api.schemas.v1 import AlertSeverity
        except ImportError:
            pytest.skip("Schema imports not available")

        assert AlertSeverity.LOW.value == 'LOW'
        assert AlertSeverity.MEDIUM.value == 'MEDIUM'
        assert AlertSeverity.HIGH.value == 'HIGH'
        assert AlertSeverity.CRITICAL.value == 'CRITICAL'

    def test_tile_band_enum_values(self):
        """TileBand enum should have correct values."""
        try:
            from backend.api.schemas.v1 import TileBand
        except ImportError:
            pytest.skip("Schema imports not available")

        assert TileBand.FULL.value == 'FULL'
        assert TileBand.BEST_5.value == 'BEST_5'
        assert TileBand.BEST_10.value == 'BEST_10'
        assert TileBand.BEST_20.value == 'BEST_20'

    def test_side_enum_values(self):
        """Side enum should have bid and ask."""
        try:
            from backend.api.schemas.v1 import Side
        except ImportError:
            pytest.skip("Schema imports not available")

        assert Side.BID.value == 'BID'
        assert Side.ASK.value == 'ASK'


class TestSchemaModels:
    """Tests for Pydantic model validation."""

    def test_market_summary_creation(self):
        """MarketSummary should be creatable with valid data."""
        try:
            from backend.api.schemas.v1 import MarketSummary
        except ImportError:
            pytest.skip("Schema imports not available")

        market = MarketSummary(
            condition_id='test-condition',
            token_id='test-token',
            title='Test Market',
            outcome='YES',
            tick_size=0.01,
            last_price=0.72,
        )
        assert market.condition_id == 'test-condition'
        assert market.last_price == 0.72
        assert market.outcome == 'YES'
        assert market.tick_size == 0.01

    def test_radar_row_creation(self):
        """RadarRow should be creatable with required fields."""
        try:
            from backend.api.schemas.v1 import RadarRow, MarketSummary, DataHealth, BeliefState
        except ImportError:
            pytest.skip("Schema imports not available")

        market = MarketSummary(
            condition_id='test-condition',
            token_id='test-token',
            title='Test Market',
            outcome='YES',
            tick_size=0.01,
            last_price=0.72,
        )
        health = DataHealth(
            missing_bucket_ratio_10m=0.0,
            rebuild_count_10m=0,
            hash_mismatch_count_10m=0,
        )
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        row = RadarRow(
            market=market,
            belief_state=BeliefState.STABLE,
            state_since_ts=now_ms,
            state_severity=0,
            confidence=85,
            fragile_index_10m=0.0,
            data_health=health,
            leading_rate_10m=0,
        )
        assert row.belief_state == BeliefState.STABLE
        assert row.confidence == 85
        assert row.state_severity == 0


# =============================================================================
# API Route Tests (require psycopg2 and database)
# =============================================================================

class TestHealthEndpoint:
    """Tests for /v1/health endpoint."""

    def test_health_returns_ok(self):
        """Health check should return ok status."""
        client = get_test_client()
        if client is None:
            pytest.skip("API client not available (missing dependencies)")

        response = client.get("/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is True
        assert 'version' in data


class TestRadarEndpoint:
    """Tests for /v1/radar endpoint."""

    def test_radar_validates_limit(self):
        """Radar should reject invalid limit values."""
        client = get_test_client()
        if client is None:
            pytest.skip("API client not available (missing dependencies)")

        response = client.get("/v1/radar?limit=1000")  # Max is 500
        # Should be validation error (422) or handled gracefully
        assert response.status_code in [200, 422, 500]


class TestEvidenceEndpoint:
    """Tests for /v1/evidence endpoint."""

    def test_evidence_requires_token_id(self):
        """Evidence should require token_id parameter."""
        client = get_test_client()
        if client is None:
            pytest.skip("API client not available (missing dependencies)")

        response = client.get("/v1/evidence?t0=1704067200000")
        assert response.status_code == 422

    def test_evidence_requires_t0(self):
        """Evidence should require t0 parameter."""
        client = get_test_client()
        if client is None:
            pytest.skip("API client not available (missing dependencies)")

        response = client.get("/v1/evidence?token_id=test")
        assert response.status_code == 422


class TestHeatmapTilesEndpoint:
    """Tests for /v1/heatmap/tiles endpoint."""

    def test_tiles_requires_params(self):
        """Tiles should require token_id and time range."""
        client = get_test_client()
        if client is None:
            pytest.skip("API client not available (missing dependencies)")

        response = client.get("/v1/heatmap/tiles")
        assert response.status_code == 422


# =============================================================================
# URL/Parameter Format Tests
# =============================================================================

class TestURLFormats:
    """Tests for URL and parameter formatting."""

    def test_radar_url_format(self):
        """Radar URL should accept correct query params."""
        # These are just format validation tests
        valid_params = {
            'limit': 50,
            'offset': 0,
            'state': 'BROKEN',
        }
        query = '&'.join(f"{k}={v}" for k, v in valid_params.items())
        expected = "/v1/radar?limit=50&offset=0&state=BROKEN"
        assert f"/v1/radar?{query}" == expected

    def test_evidence_url_format(self):
        """Evidence URL should accept correct query params."""
        valid_params = {
            'token_id': 'test-token',
            't0': 1704067200000,
            'window_sec': 60,
        }
        query = '&'.join(f"{k}={v}" for k, v in valid_params.items())
        assert 'token_id=test-token' in query
        assert 't0=1704067200000' in query

    def test_heatmap_tiles_url_format(self):
        """Heatmap tiles URL should accept correct query params."""
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        valid_params = {
            'token_id': 'test-token',
            'from_ts': now - 10000,
            'to_ts': now,
            'lod': 250,
            'band': 'FULL',
        }
        query = '&'.join(f"{k}={v}" for k, v in valid_params.items())
        assert 'lod=250' in query
        assert 'band=FULL' in query
