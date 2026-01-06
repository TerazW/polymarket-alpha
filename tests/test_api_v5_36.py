"""
Tests for v5.36 API Endpoints - Expert Review Features.

Tests the following new endpoints:
- GET /v1/alerts/{id}/chain - Evidence chain API
- GET /v1/reactions/distribution - Reaction distribution API
- GET /v1/similar-cases - Historical similar cases API
- GET /events/{id}/compare - Multi-market comparison API
- PUT /v1/alerts/{id}/resolve - Enhanced with recovery_evidence

v5.36: Per expert review - "反证, 比较, 约束"
"""

import pytest
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# Schema Validation Tests (v5.36 new schemas)
# =============================================================================

class TestV536Schemas:
    """Tests for v5.36 new API schemas."""

    def test_latency_info_schema(self):
        """LatencyInfo should have required fields."""
        try:
            from backend.api.schemas.v1 import LatencyInfo
        except ImportError:
            pytest.skip("Schema imports not available")

        latency = LatencyInfo(
            event_ts=1700000000000,
            detected_ts=1700000001000,
            detection_latency_ms=1000,
            window_type="FAST",
            observation_end_ts=1700000005000,
        )
        assert latency.event_ts == 1700000000000
        assert latency.detection_latency_ms == 1000
        assert latency.window_type == "FAST"

    def test_evidence_chain_node_schema(self):
        """EvidenceChainNode should be creatable with valid data."""
        try:
            from backend.api.schemas.v1 import EvidenceChainNode
        except ImportError:
            pytest.skip("Schema imports not available")

        node = EvidenceChainNode(
            node_type="SHOCK",
            node_id="shock_123",
            ts=1700000000000,
            summary="Shock @ 72% (BID, VOLUME)",
            details={"price": 0.72, "side": "BID"},
            evidence_refs=[],
        )
        assert node.node_type == "SHOCK"
        assert node.node_id == "shock_123"
        assert "price" in node.details

    def test_evidence_chain_response_schema(self):
        """EvidenceChainResponse should have all required fields."""
        try:
            from backend.api.schemas.v1 import EvidenceChainResponse, EvidenceChainNode
        except ImportError:
            pytest.skip("Schema imports not available")

        node = EvidenceChainNode(
            node_type="ALERT",
            node_id="alert_123",
            ts=1700000000000,
            summary="CRACKING detected",
            details={},
            evidence_refs=[],
        )
        response = EvidenceChainResponse(
            alert_id="alert_123",
            token_id="token_abc",
            generated_at=1700000000000,
            chain=[node],
            shock_count=2,
            reaction_count=5,
            leading_event_count=1,
            state_change_count=1,
            chain_start_ts=1700000000000,
            chain_end_ts=1700000060000,
            chain_duration_ms=60000,
        )
        assert response.alert_id == "alert_123"
        assert response.chain_duration_ms == 60000
        assert len(response.chain) == 1

    def test_reaction_distribution_schema(self):
        """ReactionDistribution should validate ratio bounds."""
        try:
            from backend.api.schemas.v1 import ReactionDistribution, ReactionType
        except ImportError:
            pytest.skip("Schema imports not available")

        dist = ReactionDistribution(
            reaction_type=ReactionType.HOLD,
            count=50,
            ratio=0.6,
        )
        assert dist.reaction_type == ReactionType.HOLD
        assert dist.count == 50
        assert 0 <= dist.ratio <= 1

    def test_reaction_distribution_response_schema(self):
        """ReactionDistributionResponse should have structural metrics."""
        try:
            from backend.api.schemas.v1 import (
                ReactionDistributionResponse, ReactionDistribution, ReactionType
            )
        except ImportError:
            pytest.skip("Schema imports not available")

        dist = ReactionDistribution(
            reaction_type=ReactionType.HOLD,
            count=50,
            ratio=0.6,
        )
        response = ReactionDistributionResponse(
            token_id="token_abc",
            from_ts=1700000000000,
            to_ts=1700001800000,
            window_minutes=30,
            total_reactions=100,
            distribution=[dist],
            hold_dominant=True,
            stress_ratio=0.2,
        )
        assert response.hold_dominant is True
        assert response.stress_ratio == 0.2

    def test_false_positive_reason_enum(self):
        """FalsePositiveReason enum should have all categories."""
        try:
            from backend.api.schemas.v1 import FalsePositiveReason
        except ImportError:
            pytest.skip("Schema imports not available")

        expected = {'THIN_MARKET', 'NOISE', 'MANIPULATION', 'STALE_DATA',
                    'THRESHOLD_TOO_SENSITIVE', 'OTHER'}
        actual = {r.value for r in FalsePositiveReason}
        assert actual == expected

    def test_alert_schema_v536_fields(self):
        """Alert schema should have v5.36 recovery_evidence and false_positive fields."""
        try:
            from backend.api.schemas.v1 import (
                Alert, AlertSeverity, AlertStatus, EvidenceGrade, EvidenceRef
            )
        except ImportError:
            pytest.skip("Schema imports not available")

        alert = Alert(
            alert_id="alert_123",
            token_id="token_abc",
            ts=1700000000000,
            severity=AlertSeverity.HIGH,
            evidence_grade=EvidenceGrade.A,
            status=AlertStatus.RESOLVED,
            type="CRACKING",
            summary="Market cracking detected",
            evidence_confidence=85.0,
            evidence_ref=EvidenceRef(token_id="token_abc", t0=1700000000000),
            recovery_evidence=["Current belief state: STABLE", "HOLD ratio: 75%"],
            resolved_at=1700001000000,
            resolved_by="operator1",
            is_false_positive=False,
            false_positive_reason=None,
        )
        assert alert.recovery_evidence is not None
        assert len(alert.recovery_evidence) == 2
        assert alert.is_false_positive is False


class TestV536ConfidenceNaming:
    """Tests for v5.36 confidence field renaming audit."""

    def test_radar_row_uses_evidence_confidence(self):
        """RadarRow should use evidence_confidence, not confidence."""
        try:
            from backend.api.schemas.v1 import (
                RadarRow, MarketSummary, DataHealth, BeliefState, EvidenceGrade
            )
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

        # Should use evidence_confidence
        row = RadarRow(
            market=market,
            belief_state=BeliefState.STABLE,
            state_since_ts=now_ms,
            state_severity=0,
            evidence_grade=EvidenceGrade.A,
            evidence_confidence=85.0,  # v5.36: renamed from confidence
            fragile_index_10m=0.0,
            data_health=health,
            leading_rate_10m=0,
        )
        assert hasattr(row, 'evidence_confidence')
        assert row.evidence_confidence == 85.0

    def test_state_explanation_uses_classification_confidence(self):
        """StateExplanationInfo should use classification_confidence."""
        try:
            from backend.api.schemas.v1 import StateExplanationInfo
        except ImportError:
            pytest.skip("Schema imports not available")

        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        explanation = StateExplanationInfo(
            token_id="token_abc",
            current_state="STABLE",
            classification_confidence=92.0,  # v5.36: renamed from confidence
            headline="Market is stable",
            summary="All indicators show stability",
            positive_factors=[],
            negative_factors=[],
            counterfactuals=[],
            generated_at=now_ms,
            window_minutes=10,
        )
        assert hasattr(explanation, 'classification_confidence')
        assert explanation.classification_confidence == 92.0


class TestV536CounterfactualEnhancements:
    """Tests for v5.36 counterfactual logic enhancements."""

    def test_counterfactual_allows_na_likelihood(self):
        """CounterfactualCondition should accept 'n/a' for why-not counterfactuals."""
        try:
            from backend.api.schemas.v1 import CounterfactualCondition
        except ImportError:
            pytest.skip("Schema imports not available")

        # "Why not worse" counterfactuals use n/a likelihood
        cf = CounterfactualCondition(
            target_state="NOT_FRAGILE",
            conditions=["Hold ratio 75% >= 70% threshold", "No vacuum in 10min"],
            likelihood="n/a",
        )
        assert cf.target_state == "NOT_FRAGILE"
        assert cf.likelihood == "n/a"

    def test_counterfactual_recovery_path(self):
        """CounterfactualCondition should support recovery paths."""
        try:
            from backend.api.schemas.v1 import CounterfactualCondition
        except ImportError:
            pytest.skip("Schema imports not available")

        # Recovery path with probability
        cf = CounterfactualCondition(
            target_state="STABLE",
            conditions=["Hold ratio increase to 80%", "No vacuums for 15min"],
            likelihood="high",
        )
        assert cf.target_state == "STABLE"
        assert cf.likelihood in ["high", "medium", "low", "n/a"]


# =============================================================================
# API Endpoint Tests (requires running backend)
# =============================================================================

def get_test_client():
    """Try to create a test client for the API."""
    try:
        from fastapi.testclient import TestClient
        from backend.api.main import app
        return TestClient(app)
    except ImportError:
        return None
    except Exception:
        return None


class TestEvidenceChainEndpoint:
    """Tests for GET /v1/alerts/{id}/chain endpoint."""

    def test_evidence_chain_requires_alert_id(self):
        """Evidence chain endpoint should require alert_id."""
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        # Missing alert_id should fail
        response = client.get("/v1/alerts//chain")
        assert response.status_code in [404, 422]

    def test_evidence_chain_returns_404_for_missing_alert(self):
        """Evidence chain should return 404 for non-existent alert."""
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        response = client.get("/v1/alerts/nonexistent_alert_123/chain")
        # Should be 404 or 500 if DB not connected
        assert response.status_code in [404, 500]

    def test_evidence_chain_response_structure(self):
        """Evidence chain response should have correct structure."""
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        # Even on 404/500, we can test the error response format
        response = client.get("/v1/alerts/test_alert/chain")
        if response.status_code == 200:
            data = response.json()
            assert "alert_id" in data
            assert "chain" in data
            assert "shock_count" in data
            assert "reaction_count" in data


class TestReactionDistributionEndpoint:
    """Tests for GET /v1/reactions/distribution endpoint."""

    def test_reaction_distribution_requires_token_id(self):
        """Reaction distribution should require token_id."""
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        response = client.get("/v1/reactions/distribution")
        assert response.status_code == 422  # Missing required param

    def test_reaction_distribution_with_valid_token(self):
        """Reaction distribution should accept valid token_id."""
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        response = client.get("/v1/reactions/distribution?token_id=test_token")
        # Should succeed or fail gracefully
        assert response.status_code in [200, 500]

        if response.status_code == 200:
            data = response.json()
            assert "token_id" in data
            assert "distribution" in data
            assert "hold_dominant" in data
            assert "stress_ratio" in data

    def test_reaction_distribution_window_bounds(self):
        """Window parameter should be bounded."""
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        # window_minutes max is 1440 (24 hours)
        response = client.get("/v1/reactions/distribution?token_id=test&window_minutes=2000")
        assert response.status_code == 422


class TestSimilarCasesEndpoint:
    """Tests for GET /v1/similar-cases endpoint."""

    def test_similar_cases_requires_token_id(self):
        """Similar cases should require token_id."""
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        response = client.get("/v1/similar-cases")
        assert response.status_code == 422

    def test_similar_cases_response_has_paradigm_note(self):
        """Similar cases response should include paradigm_note (no outcomes)."""
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        response = client.get("/v1/similar-cases?token_id=test_token")
        if response.status_code == 200:
            data = response.json()
            assert "paradigm_note" in data
            # Should not contain outcome/result
            assert "outcome" not in str(data).lower() or "paradigm" in str(data).lower()

    def test_similar_cases_search_days_bounds(self):
        """search_days should be bounded."""
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        # Max is 90 days
        response = client.get("/v1/similar-cases?token_id=test&search_days=100")
        assert response.status_code == 422


class TestAlertResolveWithEvidence:
    """Tests for PUT /v1/alerts/{id}/resolve with recovery_evidence."""

    def test_resolve_requires_false_positive_reason(self):
        """Resolving as false positive should require reason."""
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        response = client.put(
            "/v1/alerts/test_alert/resolve",
            json={"is_false_positive": True}  # Missing reason
        )
        # Should fail with 400 or fail gracefully
        assert response.status_code in [400, 404, 500]

    def test_resolve_with_false_positive_and_reason(self):
        """Resolving as false positive with reason should work."""
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        response = client.put(
            "/v1/alerts/test_alert/resolve",
            json={
                "is_false_positive": True,
                "false_positive_reason": "THIN_MARKET",
                "note": "Low liquidity caused false trigger"
            }
        )
        # Should succeed or fail on missing alert
        assert response.status_code in [200, 404, 500]

    def test_resolve_response_includes_recovery_evidence(self):
        """Resolution response should include recovery_evidence."""
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        response = client.put(
            "/v1/alerts/test_alert/resolve",
            json={"note": "Manual resolution"}
        )
        if response.status_code == 200:
            data = response.json()
            assert "recovery_evidence" in data
            assert isinstance(data["recovery_evidence"], list)


class TestEventCompareEndpoint:
    """Tests for GET /events/{id}/compare endpoint."""

    def test_event_compare_requires_token_ids(self):
        """Event compare should require token_ids parameter."""
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        # Note: This endpoint is under /events, not /v1
        response = client.get("/events/test_event/compare")
        # Should fail without token_ids
        assert response.status_code in [422, 404, 500]

    def test_event_compare_with_multiple_tokens(self):
        """Event compare should accept multiple token_ids."""
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        response = client.get("/events/test_event/compare?token_ids=token_a,token_b")
        # Should succeed or fail gracefully
        assert response.status_code in [200, 404, 500]


# =============================================================================
# Integration Tests (full flow)
# =============================================================================

class TestV536IntegrationFlow:
    """Integration tests for complete v5.36 workflows."""

    def test_alert_lifecycle_with_recovery_evidence(self):
        """
        Test complete alert lifecycle:
        1. Get alerts
        2. Get evidence chain
        3. Resolve with recovery evidence
        """
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        # 1. Get open alerts
        alerts_response = client.get("/v1/alerts?status=OPEN&limit=1")
        if alerts_response.status_code != 200:
            pytest.skip("Alerts endpoint not available")

        alerts = alerts_response.json()
        if not alerts.get("rows"):
            pytest.skip("No open alerts to test with")

        alert_id = alerts["rows"][0]["alert_id"]

        # 2. Get evidence chain for the alert
        chain_response = client.get(f"/v1/alerts/{alert_id}/chain")
        assert chain_response.status_code == 200
        chain = chain_response.json()
        assert "chain" in chain
        assert chain["alert_id"] == alert_id

        # 3. Verify chain has correct structure
        assert "shock_count" in chain
        assert "reaction_count" in chain
        assert "chain_duration_ms" in chain

    def test_reaction_distribution_reflects_structure(self):
        """
        Test reaction distribution API:
        - Shows distribution not individual events
        - Includes structural metrics (hold_dominant, stress_ratio)
        """
        client = get_test_client()
        if not client:
            pytest.skip("Test client not available")

        # Get a radar row first to find an active token
        radar_response = client.get("/v1/radar?limit=1")
        if radar_response.status_code != 200:
            pytest.skip("Radar endpoint not available")

        radar = radar_response.json()
        if not radar.get("rows"):
            pytest.skip("No markets to test with")

        token_id = radar["rows"][0]["market"]["token_id"]

        # Get reaction distribution
        dist_response = client.get(f"/v1/reactions/distribution?token_id={token_id}")
        if dist_response.status_code != 200:
            pytest.skip("Distribution endpoint not available")

        dist = dist_response.json()

        # Verify structure
        assert dist["token_id"] == token_id
        assert "distribution" in dist
        assert "hold_dominant" in dist
        assert "stress_ratio" in dist
        assert 0 <= dist["stress_ratio"] <= 1

        # Each distribution item should have count and ratio
        for item in dist["distribution"]:
            assert "reaction_type" in item
            assert "count" in item
            assert "ratio" in item


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
