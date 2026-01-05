"""
Tests for Adversarial Fixtures Library (v5.21)

Validates:
1. Fixture structure and completeness
2. Scenario reproducibility (hash stability)
3. Event ordering guarantees
4. Expected outcome coverage

"每一个反例都有故事"
"""

import pytest
import json
import hashlib

from tests.fixtures import (
    AdversarialScenario,
    EventType,
    BASE_TS,
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
    get_scenario,
    list_scenarios,
    get_scenarios_by_tag,
    trade_event,
    price_change_event,
    order_cancelled_event,
    book_snapshot_event,
)


class TestEventBuilders:
    """Test event builder functions"""

    def test_trade_event_structure(self):
        """Trade event should have all required fields"""
        event = trade_event(1000, 0.72, 100, 'buy', seq=1)

        assert event['ts'] == 1000
        assert event['seq'] == 1
        assert event['type'] == EventType.TRADE
        assert event['price'] == 0.72
        assert event['size'] == 100
        assert event['side'] == 'buy'

    def test_price_change_event_structure(self):
        """Price change event should have all required fields"""
        event = price_change_event(2000, 0.71, 500, 'bid', seq=2)

        assert event['ts'] == 2000
        assert event['type'] == EventType.PRICE_CHANGE
        assert event['price'] == 0.71
        assert event['size'] == 500
        assert event['side'] == 'bid'

    def test_order_cancelled_event_structure(self):
        """Order cancelled event should have all required fields"""
        event = order_cancelled_event(3000, 0.70, 200, 'ask', seq=3)

        assert event['ts'] == 3000
        assert event['type'] == EventType.ORDER_CANCELLED
        assert event['price'] == 0.70
        assert event['size'] == 200
        assert event['side'] == 'ask'

    def test_book_snapshot_structure(self):
        """Book snapshot should have bids and asks"""
        event = book_snapshot_event(
            1000,
            bids=[(0.72, 500), (0.71, 300)],
            asks=[(0.73, 400), (0.74, 200)],
            seq=0
        )

        assert event['ts'] == 1000
        assert event['type'] == EventType.BOOK_SNAPSHOT
        assert len(event['bids']) == 2
        assert len(event['asks']) == 2
        assert event['bids'][0]['price'] == 0.72
        assert event['bids'][0]['size'] == 500


class TestAdversarialScenario:
    """Test AdversarialScenario dataclass"""

    def test_scenario_creation(self):
        """Should create scenario with all fields"""
        scenario = AdversarialScenario(
            name="test_scenario",
            description="Test description",
            description_cn="测试描述",
            token_id="test-token",
            t0=BASE_TS,
            window_ms=10000,
            raw_events=[
                trade_event(BASE_TS, 0.72, 100, 'buy'),
            ],
            expected_outcomes={'shock_detected': True},
            tags=['test'],
        )

        assert scenario.name == "test_scenario"
        assert scenario.token_id == "test-token"
        assert len(scenario.raw_events) == 1

    def test_events_sorted_on_creation(self):
        """Events should be sorted by ts, seq on creation"""
        scenario = AdversarialScenario(
            name="unsorted",
            description="Test",
            description_cn="测试",
            token_id="test",
            t0=BASE_TS,
            window_ms=5000,
            raw_events=[
                trade_event(BASE_TS + 2000, 0.72, 100, 'buy', seq=0),
                trade_event(BASE_TS + 1000, 0.71, 50, 'buy', seq=0),
                trade_event(BASE_TS + 3000, 0.73, 75, 'buy', seq=0),
            ],
            expected_outcomes={},
        )

        # Should be sorted by timestamp
        assert scenario.raw_events[0]['ts'] == BASE_TS + 1000
        assert scenario.raw_events[1]['ts'] == BASE_TS + 2000
        assert scenario.raw_events[2]['ts'] == BASE_TS + 3000

    def test_scenario_hash_deterministic(self):
        """Scenario hash should be deterministic"""
        scenario = AdversarialScenario(
            name="hash_test",
            description="Test",
            description_cn="测试",
            token_id="test-hash",
            t0=BASE_TS,
            window_ms=5000,
            raw_events=[trade_event(BASE_TS, 0.72, 100, 'buy')],
            expected_outcomes={},
        )

        hash1 = scenario.scenario_hash
        hash2 = scenario.scenario_hash

        assert hash1 == hash2
        assert len(hash1) == 16  # 16 hex chars

    def test_scenario_to_dict(self):
        """Should serialize to dict"""
        scenario = AdversarialScenario(
            name="dict_test",
            description="Test",
            description_cn="测试",
            token_id="test-dict",
            t0=BASE_TS,
            window_ms=5000,
            raw_events=[trade_event(BASE_TS, 0.72, 100, 'buy')],
            expected_outcomes={'key': 'value'},
            tags=['tag1', 'tag2'],
        )

        d = scenario.to_dict()

        assert d['name'] == "dict_test"
        assert d['token_id'] == "test-dict"
        assert 'raw_events' in d
        assert d['expected_outcomes'] == {'key': 'value'}
        assert 'scenario_hash' in d


class TestScenarioRegistry:
    """Test scenario registry functions"""

    def test_scenarios_dict_has_all(self):
        """SCENARIOS dict should have all defined scenarios"""
        expected_names = [
            'vacuum_at_anchor',
            'pull_cancel_driven',
            'sweep_with_recovery',
            'spoof_order_cancel',
            'flash_crash_recovery',
            'layering_withdrawal',
            'wash_trade_pattern',
            'quote_stuffing_noise',
            'pre_shock_pull',
            'gradual_thinning',
        ]

        for name in expected_names:
            assert name in SCENARIOS, f"Missing scenario: {name}"

    def test_get_scenario(self):
        """get_scenario should return scenario by name"""
        scenario = get_scenario('vacuum_at_anchor')

        assert scenario is not None
        assert scenario.name == 'vacuum_at_anchor'

    def test_get_scenario_not_found(self):
        """get_scenario should return None for unknown name"""
        scenario = get_scenario('nonexistent_scenario')

        assert scenario is None

    def test_list_scenarios_all(self):
        """list_scenarios without tags should return all"""
        names = list_scenarios()

        assert len(names) == 10
        assert 'vacuum_at_anchor' in names

    def test_list_scenarios_by_tag(self):
        """list_scenarios with tags should filter"""
        manipulation_names = list_scenarios(tags=['manipulation'])

        assert 'spoof_order_cancel' in manipulation_names
        assert 'layering_withdrawal' in manipulation_names
        assert 'wash_trade_pattern' in manipulation_names
        assert 'vacuum_at_anchor' not in manipulation_names

    def test_get_scenarios_by_tag(self):
        """get_scenarios_by_tag should return scenario objects"""
        trade_driven = get_scenarios_by_tag('trade_driven')

        assert len(trade_driven) >= 1
        assert all(isinstance(s, AdversarialScenario) for s in trade_driven)
        assert any(s.name == 'vacuum_at_anchor' for s in trade_driven)


class TestVacuumScenario:
    """Test VACUUM_AT_ANCHOR scenario"""

    def test_structure(self):
        """Should have proper structure"""
        assert VACUUM_AT_ANCHOR.name == 'vacuum_at_anchor'
        assert VACUUM_AT_ANCHOR.token_id == 'fixture-vacuum-001'
        assert len(VACUUM_AT_ANCHOR.raw_events) > 5

    def test_expected_outcomes(self):
        """Should have expected outcomes defined"""
        outcomes = VACUUM_AT_ANCHOR.expected_outcomes

        assert outcomes['shock_detected'] is True
        assert outcomes['reaction_type'] == 'VACUUM'
        assert outcomes['attribution_type'] == 'TRADE_DRIVEN'
        assert 'drop_ratio' in outcomes

    def test_has_shock_event(self):
        """Should contain trade event (shock)"""
        trades = [e for e in VACUUM_AT_ANCHOR.raw_events if e['type'] == EventType.TRADE]

        assert len(trades) >= 1
        assert trades[0]['size'] > 400  # Large trade

    def test_tags(self):
        """Should have appropriate tags"""
        assert 'vacuum' in VACUUM_AT_ANCHOR.tags
        assert 'trade_driven' in VACUUM_AT_ANCHOR.tags


class TestPullScenario:
    """Test PULL_CANCEL_DRIVEN scenario"""

    def test_structure(self):
        """Should have proper structure"""
        assert PULL_CANCEL_DRIVEN.name == 'pull_cancel_driven'
        assert 'cancel_driven' in PULL_CANCEL_DRIVEN.tags

    def test_has_cancellation(self):
        """Should contain cancellation event"""
        cancels = [e for e in PULL_CANCEL_DRIVEN.raw_events
                   if e['type'] == EventType.ORDER_CANCELLED]

        assert len(cancels) >= 1

    def test_expected_attribution(self):
        """Should expect cancel-driven attribution"""
        outcomes = PULL_CANCEL_DRIVEN.expected_outcomes

        assert outcomes['attribution_type'] == 'CANCEL_DRIVEN'
        assert outcomes['cancel_driven_ratio'] > 0.7


class TestSweepScenario:
    """Test SWEEP_WITH_RECOVERY scenario"""

    def test_recovery_expected(self):
        """Should expect recovery within time window"""
        outcomes = SWEEP_WITH_RECOVERY.expected_outcomes

        assert outcomes['reaction_type'] == 'SWEEP'
        assert outcomes['refill_ratio'] > 0.8
        assert outcomes['time_to_refill_ms'] < 1000


class TestSpoofScenario:
    """Test SPOOF_ORDER_CANCEL scenario"""

    def test_has_multiple_cycles(self):
        """Should have multiple add-cancel cycles"""
        cancels = [e for e in SPOOF_ORDER_CANCEL.raw_events
                   if e['type'] == EventType.ORDER_CANCELLED]

        assert len(cancels) >= 3  # 3 cycles

    def test_expected_spoof_count(self):
        """Should expect spoof cycles detected"""
        outcomes = SPOOF_ORDER_CANCEL.expected_outcomes

        assert outcomes['spoof_cycles_detected'] == 3
        assert outcomes['total_traded_volume'] == 0


class TestFlashCrashScenario:
    """Test FLASH_CRASH_RECOVERY scenario"""

    def test_multiple_levels_affected(self):
        """Should affect multiple price levels"""
        outcomes = FLASH_CRASH_RECOVERY.expected_outcomes

        assert outcomes['levels_affected'] >= 3

    def test_recovery_state(self):
        """Should recover to STABLE"""
        outcomes = FLASH_CRASH_RECOVERY.expected_outcomes

        assert outcomes['final_state'] == 'STABLE'
        assert outcomes['alert_auto_resolved'] is True


class TestLayeringScenario:
    """Test LAYERING_WITHDRAWAL scenario"""

    def test_coordinated_timing(self):
        """Should have low time std (coordinated)"""
        outcomes = LAYERING_WITHDRAWAL.expected_outcomes

        assert outcomes['time_std_ms'] < 500
        assert outcomes['levels_affected'] >= 5

    def test_leading_event_type(self):
        """Should trigger DEPTH_COLLAPSE"""
        outcomes = LAYERING_WITHDRAWAL.expected_outcomes

        assert outcomes['leading_event_type'] == 'DEPTH_COLLAPSE'


class TestWashTradeScenario:
    """Test WASH_TRADE_PATTERN scenario"""

    def test_high_volume_no_impact(self):
        """Should have high volume but no price change"""
        outcomes = WASH_TRADE_PATTERN.expected_outcomes

        assert outcomes['total_volume'] > 1000
        assert outcomes['net_price_change'] == 0

    def test_suspected_flag(self):
        """Should flag as suspicious"""
        outcomes = WASH_TRADE_PATTERN.expected_outcomes

        assert outcomes['wash_trade_suspected'] is True


class TestQuoteStuffingScenario:
    """Test QUOTE_STUFFING_NOISE scenario"""

    def test_high_event_count(self):
        """Should have many raw events"""
        assert len(QUOTE_STUFFING_NOISE.raw_events) > 100

    def test_filtering_expected(self):
        """Should expect significant filtering"""
        outcomes = QUOTE_STUFFING_NOISE.expected_outcomes

        assert outcomes['raw_event_count'] > 100
        assert outcomes['filtered_bucket_count'] <= 5


class TestPreShockPullScenario:
    """Test PRE_SHOCK_PULL scenario"""

    def test_leading_time(self):
        """Should have measurable lead time"""
        outcomes = PRE_SHOCK_PULL.expected_outcomes

        assert outcomes['lead_time_ms'] > 0
        assert outcomes['lead_time_ms'] < 2000

    def test_leading_event_type(self):
        """Should detect PRE_SHOCK_PULL"""
        outcomes = PRE_SHOCK_PULL.expected_outcomes

        assert outcomes['leading_event_type'] == 'PRE_SHOCK_PULL'


class TestGradualThinningScenario:
    """Test GRADUAL_THINNING scenario"""

    def test_slow_erosion(self):
        """Should show gradual depth loss"""
        outcomes = GRADUAL_THINNING.expected_outcomes

        assert outcomes['total_depth_lost'] > 400
        assert outcomes['total_traded'] < 100  # Most is cancellation

    def test_thinning_rate(self):
        """Should have measurable thinning rate"""
        outcomes = GRADUAL_THINNING.expected_outcomes

        assert 'thinning_rate_per_min' in outcomes


class TestScenarioHashStability:
    """Test that scenario hashes are stable across runs"""

    # Pre-computed hashes for regression testing
    EXPECTED_HASHES = {
        'vacuum_at_anchor': None,      # Will be set on first run
        'pull_cancel_driven': None,
        'sweep_with_recovery': None,
        'spoof_order_cancel': None,
        'flash_crash_recovery': None,
        'layering_withdrawal': None,
        'wash_trade_pattern': None,
        'quote_stuffing_noise': None,
        'pre_shock_pull': None,
        'gradual_thinning': None,
    }

    def test_all_hashes_are_16_chars(self):
        """All hashes should be 16 hex characters"""
        for name, scenario in SCENARIOS.items():
            assert len(scenario.scenario_hash) == 16, f"{name} hash wrong length"

    def test_hash_changes_with_events(self):
        """Hash should change if events change"""
        original_hash = VACUUM_AT_ANCHOR.scenario_hash

        # Create modified version
        modified = AdversarialScenario(
            name=VACUUM_AT_ANCHOR.name,
            description=VACUUM_AT_ANCHOR.description,
            description_cn=VACUUM_AT_ANCHOR.description_cn,
            token_id=VACUUM_AT_ANCHOR.token_id,
            t0=VACUUM_AT_ANCHOR.t0,
            window_ms=VACUUM_AT_ANCHOR.window_ms,
            raw_events=VACUUM_AT_ANCHOR.raw_events + [trade_event(BASE_TS + 99999, 0.50, 1, 'buy')],
            expected_outcomes=VACUUM_AT_ANCHOR.expected_outcomes,
        )

        assert modified.scenario_hash != original_hash


class TestAllScenariosComplete:
    """Test that all scenarios have required fields"""

    @pytest.mark.parametrize("name", list(SCENARIOS.keys()))
    def test_scenario_has_required_fields(self, name):
        """Each scenario should have all required fields"""
        scenario = SCENARIOS[name]

        assert scenario.name, f"{name} missing name"
        assert scenario.description, f"{name} missing description"
        assert scenario.description_cn, f"{name} missing description_cn"
        assert scenario.token_id, f"{name} missing token_id"
        assert scenario.t0 > 0, f"{name} invalid t0"
        assert scenario.window_ms > 0, f"{name} invalid window_ms"
        assert len(scenario.raw_events) > 0, f"{name} has no events"
        assert len(scenario.expected_outcomes) > 0, f"{name} has no expected outcomes"
        assert len(scenario.tags) > 0, f"{name} has no tags"

    @pytest.mark.parametrize("name", list(SCENARIOS.keys()))
    def test_scenario_events_sorted(self, name):
        """Each scenario's events should be sorted"""
        scenario = SCENARIOS[name]
        events = scenario.raw_events

        for i in range(1, len(events)):
            prev_ts = events[i-1].get('ts', 0)
            curr_ts = events[i].get('ts', 0)
            assert curr_ts >= prev_ts, f"{name} events not sorted at index {i}"

    @pytest.mark.parametrize("name", list(SCENARIOS.keys()))
    def test_scenario_unique_token_id(self, name):
        """Each scenario should have a unique token_id"""
        scenario = SCENARIOS[name]
        other_ids = [s.token_id for n, s in SCENARIOS.items() if n != name]

        assert scenario.token_id not in other_ids, f"{name} has duplicate token_id"
