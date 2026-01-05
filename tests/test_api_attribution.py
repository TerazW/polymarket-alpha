"""
Tests for API Attribution and Explainability Integration (v5.25)

Verifies that:
1. Radar endpoint includes state explanations
2. Evidence endpoint includes reaction attributions
3. Evidence endpoint includes detailed state explanations
"""

import pytest
from backend.api.schemas.v1 import (
    # Attribution schemas
    ReactionAttributionSummary,
    AttributionTypeEnum,
    DepthChangeAttributionInfo,
    MultiLevelAttributionInfo,
    # Explainability schemas
    RadarStateExplanationCompact,
    StateExplanationInfo,
    ExplainFactor,
    ExplainFactorType,
    CounterfactualCondition,
    TrendDirection,
    # Response schemas
    RadarRow,
    ReactionEvent,
    EvidenceResponse,
    # Other schemas needed
    MarketSummary,
    DataHealth,
    BeliefState,
    ReactionType,
    ReactionWindow,
    Side,
    EvidenceWindow,
)


# =============================================================================
# Attribution Schema Tests
# =============================================================================

class TestAttributionSchemas:
    """Test attribution Pydantic models"""

    def test_reaction_attribution_summary(self):
        """Test ReactionAttributionSummary schema"""
        attr = ReactionAttributionSummary(
            trade_driven_ratio=0.85,
            cancel_driven_ratio=0.15,
            attribution_type='TRADE_DRIVEN',
        )
        assert attr.trade_driven_ratio == 0.85
        assert attr.cancel_driven_ratio == 0.15
        assert attr.attribution_type == 'TRADE_DRIVEN'

    def test_attribution_type_enum(self):
        """Test AttributionTypeEnum values"""
        assert AttributionTypeEnum.TRADE_DRIVEN == "TRADE_DRIVEN"
        assert AttributionTypeEnum.CANCEL_DRIVEN == "CANCEL_DRIVEN"
        assert AttributionTypeEnum.MIXED == "MIXED"
        assert AttributionTypeEnum.REPLENISHMENT == "REPLENISHMENT"
        assert AttributionTypeEnum.NO_CHANGE == "NO_CHANGE"

    def test_depth_change_attribution_info(self):
        """Test DepthChangeAttributionInfo schema"""
        attr = DepthChangeAttributionInfo(
            depth_before=1000.0,
            depth_after=500.0,
            trade_volume=300.0,
            depth_removed=500.0,
            trade_driven_volume=300.0,
            cancel_driven_volume=200.0,
            trade_driven_ratio=0.6,
            cancel_driven_ratio=0.4,
            attribution_type=AttributionTypeEnum.MIXED,
        )
        assert attr.depth_before == 1000.0
        assert attr.depth_removed == 500.0
        assert attr.attribution_type == AttributionTypeEnum.MIXED

    def test_multi_level_attribution_info(self):
        """Test MultiLevelAttributionInfo schema"""
        attr = MultiLevelAttributionInfo(
            levels_affected=5,
            total_depth_removed=2500.0,
            total_trade_driven=2000.0,
            total_cancel_driven=500.0,
            trade_driven_ratio=0.8,
            cancel_driven_ratio=0.2,
            attribution_type=AttributionTypeEnum.TRADE_DRIVEN,
        )
        assert attr.levels_affected == 5
        assert attr.trade_driven_ratio == 0.8


# =============================================================================
# Explainability Schema Tests
# =============================================================================

class TestExplainabilitySchemas:
    """Test explainability Pydantic models"""

    def test_trend_direction_enum(self):
        """Test TrendDirection enum values"""
        assert TrendDirection.IMPROVING == "IMPROVING"
        assert TrendDirection.STABLE == "STABLE"
        assert TrendDirection.WORSENING == "WORSENING"
        assert TrendDirection.VOLATILE == "VOLATILE"

    def test_explain_factor_type_enum(self):
        """Test ExplainFactorType enum values"""
        assert ExplainFactorType.HIGH_HOLD_RATIO == "HIGH_HOLD_RATIO"
        assert ExplainFactorType.VACUUM_AT_KEY_LEVEL == "VACUUM_AT_KEY_LEVEL"
        assert ExplainFactorType.CANCEL_DOMINATED == "CANCEL_DOMINATED"

    def test_explain_factor(self):
        """Test ExplainFactor schema"""
        factor = ExplainFactor(
            factor=ExplainFactorType.HIGH_HOLD_RATIO,
            weight=0.8,
            value="75%",
            threshold="≥70%",
            description={"en": "High hold ratio", "cn": "高保持率"},
        )
        assert factor.factor == ExplainFactorType.HIGH_HOLD_RATIO
        assert factor.weight == 0.8
        assert factor.description["en"] == "High hold ratio"

    def test_counterfactual_condition(self):
        """Test CounterfactualCondition schema"""
        cf = CounterfactualCondition(
            target_state="STABLE",
            conditions=["Increase hold ratio to ≥70%", "Zero vacuum events"],
            likelihood="high",
        )
        assert cf.target_state == "STABLE"
        assert len(cf.conditions) == 2
        assert cf.likelihood == "high"

    def test_radar_state_explanation_compact(self):
        """Test RadarStateExplanationCompact schema"""
        exp = RadarStateExplanationCompact(
            headline="Market depth is holding well",
            trend="STABLE",
            top_factors=["High hold ratio", "Low fragility"],
        )
        assert exp.headline == "Market depth is holding well"
        assert exp.trend == "STABLE"
        assert len(exp.top_factors) == 2

    def test_state_explanation_info(self):
        """Test StateExplanationInfo schema"""
        exp = StateExplanationInfo(
            token_id="token_123",
            current_state="FRAGILE",
            confidence=70.0,
            headline="Early stress signals",
            summary="The market is showing early signs of stress.",
            positive_factors=[
                ExplainFactor(
                    factor=ExplainFactorType.QUICK_REFILL,
                    weight=0.5,
                    value="800ms",
                    description={"en": "Quick refill", "cn": "快速补充"},
                )
            ],
            negative_factors=[
                ExplainFactor(
                    factor=ExplainFactorType.VACUUM_AT_KEY_LEVEL,
                    weight=-0.7,
                    value=1,
                    description={"en": "Vacuum at key level", "cn": "关键价位真空"},
                )
            ],
            trend=TrendDirection.WORSENING,
            trend_reason="Declined from STABLE to FRAGILE",
            counterfactuals=[
                CounterfactualCondition(
                    target_state="STABLE",
                    conditions=["Zero vacuum events"],
                    likelihood="high",
                )
            ],
            generated_at=1704067200000,
            window_minutes=10,
        )
        assert exp.current_state == "FRAGILE"
        assert exp.confidence == 70.0
        assert len(exp.positive_factors) == 1
        assert len(exp.negative_factors) == 1
        assert exp.trend == TrendDirection.WORSENING


# =============================================================================
# Radar Response Integration Tests
# =============================================================================

class TestRadarIntegration:
    """Test radar response includes explanations"""

    def test_radar_row_with_explanation(self):
        """Test RadarRow with explanation field"""
        explanation = RadarStateExplanationCompact(
            headline="Market depth is holding well",
            trend="STABLE",
            top_factors=["High hold ratio", "Low fragility signals"],
        )

        row = RadarRow(
            market=MarketSummary(
                token_id="token_abc",
                condition_id="cond_123",
                title="Test Market",
                outcome="YES",
                tick_size=0.01,
            ),
            belief_state=BeliefState.STABLE,
            state_since_ts=1704067200000,
            state_severity=0,
            fragile_index_10m=5.0,
            leading_rate_10m=2.0,
            confidence=85.0,
            data_health=DataHealth(
                missing_bucket_ratio_10m=0.0,
                rebuild_count_10m=0,
                hash_mismatch_count_10m=0,
            ),
            explanation=explanation,
        )

        assert row.explanation is not None
        assert row.explanation.headline == "Market depth is holding well"
        assert row.explanation.trend == "STABLE"

    def test_radar_row_without_explanation(self):
        """Test RadarRow works without explanation (backward compatible)"""
        row = RadarRow(
            market=MarketSummary(
                token_id="token_abc",
                condition_id="cond_123",
                title="Test Market",
                outcome="YES",
                tick_size=0.01,
            ),
            belief_state=BeliefState.STABLE,
            state_since_ts=1704067200000,
            state_severity=0,
            fragile_index_10m=5.0,
            leading_rate_10m=2.0,
            confidence=85.0,
            data_health=DataHealth(
                missing_bucket_ratio_10m=0.0,
                rebuild_count_10m=0,
                hash_mismatch_count_10m=0,
            ),
        )

        assert row.explanation is None

    def test_radar_row_all_states(self):
        """Test explanations for all belief states"""
        states = [
            (BeliefState.STABLE, "Market depth is holding well"),
            (BeliefState.FRAGILE, "Market showing early stress signals"),
            (BeliefState.CRACKING, "Market depth under significant stress"),
            (BeliefState.BROKEN, "Market depth severely compromised"),
        ]

        for state, expected_headline in states:
            explanation = RadarStateExplanationCompact(
                headline=expected_headline,
                trend="STABLE",
                top_factors=[],
            )

            row = RadarRow(
                market=MarketSummary(
                    token_id="token_abc",
                    condition_id="cond_123",
                    title="Test Market",
                    outcome="YES",
                    tick_size=0.01,
                ),
                belief_state=state,
                state_since_ts=1704067200000,
                state_severity=0,
                fragile_index_10m=5.0,
                leading_rate_10m=2.0,
                confidence=85.0,
                data_health=DataHealth(
                    missing_bucket_ratio_10m=0.0,
                    rebuild_count_10m=0,
                    hash_mismatch_count_10m=0,
                ),
                explanation=explanation,
            )

            assert row.belief_state == state
            assert row.explanation.headline == expected_headline


# =============================================================================
# Reaction Attribution Integration Tests
# =============================================================================

class TestReactionAttributionIntegration:
    """Test reaction events include attribution"""

    def test_reaction_event_with_attribution(self):
        """Test ReactionEvent with attribution field"""
        attr = ReactionAttributionSummary(
            trade_driven_ratio=0.85,
            cancel_driven_ratio=0.15,
            attribution_type='TRADE_DRIVEN',
        )

        reaction = ReactionEvent(
            id="reaction_001",
            token_id="token_abc",
            ts_start=1704067200000,
            ts_end=1704067205000,
            window=ReactionWindow.SLOW,
            price=0.55,
            side=Side.BID,
            reaction=ReactionType.VACUUM,
            attribution=attr,
        )

        assert reaction.attribution is not None
        assert reaction.attribution.trade_driven_ratio == 0.85
        assert reaction.attribution.attribution_type == 'TRADE_DRIVEN'

    def test_reaction_event_without_attribution(self):
        """Test ReactionEvent works without attribution (backward compatible)"""
        reaction = ReactionEvent(
            id="reaction_001",
            token_id="token_abc",
            ts_start=1704067200000,
            ts_end=1704067205000,
            window=ReactionWindow.SLOW,
            price=0.55,
            side=Side.BID,
            reaction=ReactionType.VACUUM,
        )

        assert reaction.attribution is None

    def test_reaction_types_with_attribution(self):
        """Test different reaction types have correct attribution patterns"""
        test_cases = [
            (ReactionType.VACUUM, 'TRADE_DRIVEN', 0.85, 0.15),
            (ReactionType.SWEEP, 'TRADE_DRIVEN', 0.85, 0.15),
            (ReactionType.PULL, 'CANCEL_DRIVEN', 0.15, 0.85),
            (ReactionType.HOLD, 'NO_CHANGE', 0.0, 0.0),
            (ReactionType.CHASE, 'MIXED', 0.5, 0.5),
        ]

        for reaction_type, attr_type, trade_ratio, cancel_ratio in test_cases:
            attr = ReactionAttributionSummary(
                trade_driven_ratio=trade_ratio,
                cancel_driven_ratio=cancel_ratio,
                attribution_type=attr_type,
            )

            reaction = ReactionEvent(
                id=f"reaction_{reaction_type.value}",
                token_id="token_abc",
                ts_start=1704067200000,
                ts_end=1704067205000,
                window=ReactionWindow.SLOW,
                price=0.55,
                side=Side.BID,
                reaction=reaction_type,
                attribution=attr,
            )

            assert reaction.reaction == reaction_type
            assert reaction.attribution.attribution_type == attr_type


# =============================================================================
# Evidence Response Integration Tests
# =============================================================================

class TestEvidenceIntegration:
    """Test evidence response includes attribution and explanation"""

    def test_evidence_response_with_explanation(self):
        """Test EvidenceResponse with state explanation"""
        explanation = StateExplanationInfo(
            token_id="token_abc",
            current_state="FRAGILE",
            confidence=70.0,
            headline="Early stress signals",
            summary="The market is showing early signs of stress.",
            positive_factors=[],
            negative_factors=[],
            trend=TrendDirection.WORSENING,
            trend_reason="Declined from STABLE to FRAGILE",
            counterfactuals=[],
            generated_at=1704067200000,
            window_minutes=10,
        )

        response = EvidenceResponse(
            token_id="token_abc",
            t0=1704067200000,
            window=EvidenceWindow(from_ts=1704067170000, to_ts=1704067260000),
            market=MarketSummary(
                token_id="token_abc",
                condition_id="cond_123",
                title="Test Market",
                outcome="YES",
                tick_size=0.01,
            ),
            anchors=[],
            shocks=[],
            reactions=[],
            leading_events=[],
            belief_states=[],
            data_health=DataHealth(
                missing_bucket_ratio_10m=0.0,
                rebuild_count_10m=0,
                hash_mismatch_count_10m=0,
            ),
            state_explanation=explanation,
        )

        assert response.state_explanation is not None
        assert response.state_explanation.current_state == "FRAGILE"
        assert response.state_explanation.confidence == 70.0

    def test_evidence_response_without_explanation(self):
        """Test EvidenceResponse works without explanation (backward compatible)"""
        response = EvidenceResponse(
            token_id="token_abc",
            t0=1704067200000,
            window=EvidenceWindow(from_ts=1704067170000, to_ts=1704067260000),
            market=MarketSummary(
                token_id="token_abc",
                condition_id="cond_123",
                title="Test Market",
                outcome="YES",
                tick_size=0.01,
            ),
            anchors=[],
            shocks=[],
            reactions=[],
            leading_events=[],
            belief_states=[],
            data_health=DataHealth(
                missing_bucket_ratio_10m=0.0,
                rebuild_count_10m=0,
                hash_mismatch_count_10m=0,
            ),
        )

        assert response.state_explanation is None

    def test_evidence_response_with_reactions_and_attribution(self):
        """Test EvidenceResponse with reactions containing attribution"""
        reaction1 = ReactionEvent(
            id="reaction_001",
            token_id="token_abc",
            ts_start=1704067200000,
            ts_end=1704067205000,
            window=ReactionWindow.SLOW,
            price=0.55,
            side=Side.BID,
            reaction=ReactionType.VACUUM,
            attribution=ReactionAttributionSummary(
                trade_driven_ratio=0.85,
                cancel_driven_ratio=0.15,
                attribution_type='TRADE_DRIVEN',
            ),
        )

        reaction2 = ReactionEvent(
            id="reaction_002",
            token_id="token_abc",
            ts_start=1704067210000,
            ts_end=1704067215000,
            window=ReactionWindow.SLOW,
            price=0.56,
            side=Side.BID,
            reaction=ReactionType.PULL,
            attribution=ReactionAttributionSummary(
                trade_driven_ratio=0.15,
                cancel_driven_ratio=0.85,
                attribution_type='CANCEL_DRIVEN',
            ),
        )

        response = EvidenceResponse(
            token_id="token_abc",
            t0=1704067200000,
            window=EvidenceWindow(from_ts=1704067170000, to_ts=1704067260000),
            market=MarketSummary(
                token_id="token_abc",
                condition_id="cond_123",
                title="Test Market",
                outcome="YES",
                tick_size=0.01,
            ),
            anchors=[],
            shocks=[],
            reactions=[reaction1, reaction2],
            leading_events=[],
            belief_states=[],
            data_health=DataHealth(
                missing_bucket_ratio_10m=0.0,
                rebuild_count_10m=0,
                hash_mismatch_count_10m=0,
            ),
        )

        assert len(response.reactions) == 2
        assert response.reactions[0].attribution.attribution_type == 'TRADE_DRIVEN'
        assert response.reactions[1].attribution.attribution_type == 'CANCEL_DRIVEN'


# =============================================================================
# Serialization Tests
# =============================================================================

class TestSerialization:
    """Test JSON serialization of new schemas"""

    def test_attribution_serialization(self):
        """Test attribution serializes correctly"""
        attr = ReactionAttributionSummary(
            trade_driven_ratio=0.85,
            cancel_driven_ratio=0.15,
            attribution_type='TRADE_DRIVEN',
        )

        data = attr.model_dump()
        assert data['trade_driven_ratio'] == 0.85
        assert data['cancel_driven_ratio'] == 0.15
        assert data['attribution_type'] == 'TRADE_DRIVEN'

    def test_explanation_serialization(self):
        """Test explanation serializes correctly"""
        exp = RadarStateExplanationCompact(
            headline="Market depth is holding well",
            trend="STABLE",
            top_factors=["High hold ratio", "Low fragility"],
        )

        data = exp.model_dump()
        assert data['headline'] == "Market depth is holding well"
        assert data['trend'] == "STABLE"
        assert len(data['top_factors']) == 2

    def test_state_explanation_info_serialization(self):
        """Test detailed explanation serializes correctly"""
        exp = StateExplanationInfo(
            token_id="token_123",
            current_state="FRAGILE",
            confidence=70.0,
            headline="Early stress signals",
            summary="The market is showing early signs of stress.",
            positive_factors=[
                ExplainFactor(
                    factor=ExplainFactorType.QUICK_REFILL,
                    weight=0.5,
                    value="800ms",
                    description={"en": "Quick refill", "cn": "快速补充"},
                )
            ],
            negative_factors=[],
            trend=TrendDirection.WORSENING,
            trend_reason="Declined from STABLE to FRAGILE",
            counterfactuals=[],
            generated_at=1704067200000,
        )

        data = exp.model_dump()
        assert data['token_id'] == "token_123"
        assert data['current_state'] == "FRAGILE"
        assert data['confidence'] == 70.0
        assert len(data['positive_factors']) == 1
        assert data['positive_factors'][0]['factor'] == 'QUICK_REFILL'

    def test_radar_row_full_serialization(self):
        """Test full RadarRow with explanation serializes correctly"""
        explanation = RadarStateExplanationCompact(
            headline="Market depth is holding well",
            trend="STABLE",
            top_factors=["High hold ratio"],
        )

        row = RadarRow(
            market=MarketSummary(
                token_id="token_abc",
                condition_id="cond_123",
                title="Test Market",
                outcome="YES",
                tick_size=0.01,
            ),
            belief_state=BeliefState.STABLE,
            state_since_ts=1704067200000,
            state_severity=0,
            fragile_index_10m=5.0,
            leading_rate_10m=2.0,
            confidence=85.0,
            data_health=DataHealth(
                missing_bucket_ratio_10m=0.0,
                rebuild_count_10m=0,
                hash_mismatch_count_10m=0,
            ),
            explanation=explanation,
        )

        data = row.model_dump()
        assert 'explanation' in data
        assert data['explanation']['headline'] == "Market depth is holding well"


# =============================================================================
# Validation Tests
# =============================================================================

class TestValidation:
    """Test validation of new schemas"""

    def test_attribution_ratio_bounds(self):
        """Test attribution ratios are bounded 0-1"""
        # Valid
        attr = ReactionAttributionSummary(
            trade_driven_ratio=0.0,
            cancel_driven_ratio=1.0,
            attribution_type='CANCEL_DRIVEN',
        )
        assert attr.trade_driven_ratio == 0.0

        # Invalid - will raise ValidationError
        with pytest.raises(Exception):
            ReactionAttributionSummary(
                trade_driven_ratio=1.5,  # > 1
                cancel_driven_ratio=0.15,
                attribution_type='TRADE_DRIVEN',
            )

    def test_factor_weight_bounds(self):
        """Test factor weights are bounded -1 to 1"""
        # Valid
        factor = ExplainFactor(
            factor=ExplainFactorType.HIGH_HOLD_RATIO,
            weight=1.0,
            value="80%",
        )
        assert factor.weight == 1.0

        factor = ExplainFactor(
            factor=ExplainFactorType.VACUUM_AT_KEY_LEVEL,
            weight=-1.0,
            value=1,
        )
        assert factor.weight == -1.0

        # Invalid
        with pytest.raises(Exception):
            ExplainFactor(
                factor=ExplainFactorType.HIGH_HOLD_RATIO,
                weight=1.5,  # > 1
                value="80%",
            )

    def test_confidence_bounds(self):
        """Test confidence is bounded 0-100"""
        # Valid
        exp = StateExplanationInfo(
            token_id="token_123",
            current_state="STABLE",
            confidence=0.0,
            headline="Test",
            summary="Test",
            generated_at=1704067200000,
        )
        assert exp.confidence == 0.0

        exp = StateExplanationInfo(
            token_id="token_123",
            current_state="STABLE",
            confidence=100.0,
            headline="Test",
            summary="Test",
            generated_at=1704067200000,
        )
        assert exp.confidence == 100.0

        # Invalid
        with pytest.raises(Exception):
            StateExplanationInfo(
                token_id="token_123",
                current_state="STABLE",
                confidence=150.0,  # > 100
                headline="Test",
                summary="Test",
                generated_at=1704067200000,
            )
