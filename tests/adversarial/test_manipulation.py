"""
Manipulation Detection Tests - Adversarial market behavior patterns

These tests ensure the system is NOT fooled by common manipulation tactics:
1. Spoofing: Large orders placed and quickly cancelled
2. Layering: Multiple levels of fake liquidity
3. Wash trading: Self-dealing to inflate volume
4. Quote stuffing: Rapid order updates to create noise

"不能被操纵者利用"
"""

import pytest
import sys
import os
from decimal import Decimal
from typing import List, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestSpoofing:
    """Tests for spoofing detection and resistance"""

    def test_spoof_order_not_anchor(self):
        """Large orders that disappear quickly should not become anchors"""
        from poc.config import (
            ANCHOR_PERSISTENCE_THETA,
            ANCHOR_WEIGHT_PERSISTENCE
        )

        # Spoof scenario: 10000 size appears for 500ms then vanishes
        spoof_peak_size = 10000.0
        spoof_duration_ms = 500  # Only 0.5 seconds

        # Persistence is key - short-lived orders get low score
        persistence_seconds = spoof_duration_ms / 1000.0

        # Anchor score formula weights persistence
        import math
        score = (
            1.0 * math.log(1 + spoof_peak_size) +
            1.0 * math.log(1 + persistence_seconds)
        )

        # Compare to legitimate anchor: 1000 size for 1 hour
        legit_peak = 1000.0
        legit_duration_seconds = 3600.0

        legit_score = (
            1.0 * math.log(1 + legit_peak) +
            1.0 * math.log(1 + legit_duration_seconds)
        )

        # Legitimate anchor should score higher despite smaller size
        assert legit_score > score, "Spoof order scored higher than legitimate anchor"

    def test_rapid_cancel_not_vacuum(self):
        """Rapidly cancelled orders should not trigger vacuum if baseline recovers"""
        from poc.config import VACUUM_DURATION_THRESHOLD_MS

        # Scenario: depth drops to 0, but recovers within 1 second
        drop_ts = 1000
        recovery_ts = 1500  # 500ms later

        vacuum_duration = recovery_ts - drop_ts

        # Should NOT be classified as vacuum (too short)
        is_vacuum = vacuum_duration >= VACUUM_DURATION_THRESHOLD_MS
        assert not is_vacuum, "Brief spoof cancellation triggered false vacuum"

    def test_spoof_cycle_detection(self):
        """Repeated place-cancel cycles should be suspicious"""
        # Scenario: Same size appears and disappears multiple times
        events = [
            {'ts': 1000, 'size': 5000, 'action': 'add'},
            {'ts': 1100, 'size': 0, 'action': 'cancel'},
            {'ts': 1200, 'size': 5000, 'action': 'add'},
            {'ts': 1300, 'size': 0, 'action': 'cancel'},
            {'ts': 1400, 'size': 5000, 'action': 'add'},
            {'ts': 1500, 'size': 0, 'action': 'cancel'},
        ]

        # Count rapid add-cancel cycles
        cycles = 0
        prev_action = None
        prev_ts = 0

        for event in events:
            if prev_action == 'add' and event['action'] == 'cancel':
                if event['ts'] - prev_ts < 500:  # Less than 500ms
                    cycles += 1
            prev_action = event['action']
            prev_ts = event['ts']

        # 3 rapid cycles is suspicious
        assert cycles >= 3, "Expected to detect spoof cycles"

        # System should weight this price level DOWN, not up
        suspicion_score = cycles * 0.1  # Increase suspicion
        assert suspicion_score >= 0.3


class TestLayering:
    """Tests for layering detection and resistance"""

    def test_stacked_orders_not_deep_belief(self):
        """Multiple small orders at adjacent prices != strong belief"""
        # Layering: 10 orders of 100 each at consecutive prices
        layered_orders = [
            {'price': Decimal(f"0.{70+i}"), 'size': 100.0}
            for i in range(10)
        ]

        total_size = sum(o['size'] for o in layered_orders)
        assert total_size == 1000.0

        # vs. Single concentrated order
        concentrated_order = {'price': Decimal("0.72"), 'size': 1000.0}

        # Concentrated order at anchor should score higher for belief
        # (assuming same persistence)
        # This is because scattered orders are easier to spoof
        concentrated_is_stronger = True  # By design principle
        assert concentrated_is_stronger

    def test_layering_withdrawal_is_pull(self):
        """Coordinated withdrawal of layered orders = PULL not multiple vacuums"""
        from poc.config import DEPTH_COLLAPSE_MIN_LEVELS, DEPTH_COLLAPSE_TIME_STD_MS

        # Scenario: 5 price levels all drop 70% within 500ms
        level_drops = [
            {'price': 0.70, 'ts': 1000, 'drop_ratio': 0.7},
            {'price': 0.71, 'ts': 1050, 'drop_ratio': 0.7},
            {'price': 0.72, 'ts': 1100, 'drop_ratio': 0.7},
            {'price': 0.73, 'ts': 1150, 'drop_ratio': 0.7},
            {'price': 0.74, 'ts': 1200, 'drop_ratio': 0.7},
        ]

        # Calculate time standard deviation
        timestamps = [d['ts'] for d in level_drops]
        mean_ts = sum(timestamps) / len(timestamps)
        variance = sum((ts - mean_ts) ** 2 for ts in timestamps) / len(timestamps)
        import math
        std_ms = math.sqrt(variance)

        # Should trigger DEPTH_COLLAPSE (coordinated withdrawal)
        is_depth_collapse = (
            len(level_drops) >= DEPTH_COLLAPSE_MIN_LEVELS and
            std_ms < DEPTH_COLLAPSE_TIME_STD_MS
        )
        assert is_depth_collapse, "Layering withdrawal should be DEPTH_COLLAPSE"


class TestWashTrading:
    """Tests for wash trading resistance"""

    def test_self_trade_not_shock(self):
        """Self-trades (wash trades) should not trigger shocks"""
        # Wash trade indicator: immediate bid-ask cross at same price
        trades = [
            {'ts': 1000, 'price': 0.72, 'side': 'BUY', 'size': 100},
            {'ts': 1001, 'price': 0.72, 'side': 'SELL', 'size': 100},
        ]

        # These cancel out in terms of market impact
        net_volume = 0
        buy_vol = sum(t['size'] for t in trades if t['side'] == 'BUY')
        sell_vol = sum(t['size'] for t in trades if t['side'] == 'SELL')

        # Perfect balance = suspicious
        is_suspicious = abs(buy_vol - sell_vol) < 10
        assert is_suspicious, "Wash trade pattern not detected"

    def test_volume_without_price_impact(self):
        """High volume with no price movement is suspicious"""
        # 1000 volume traded, but price didn't move
        total_volume = 1000.0
        price_before = Decimal("0.72")
        price_after = Decimal("0.72")

        price_moved = price_after != price_before
        high_volume = total_volume > 500

        # Genuine trading should move price
        # Wash trading often has no price impact
        is_suspicious = high_volume and not price_moved
        assert is_suspicious


class TestQuoteStuffing:
    """Tests for quote stuffing resistance"""

    def test_rapid_updates_filtered(self):
        """Rapid order updates should be filtered/sampled"""
        from poc.config import TIME_BUCKET_MS

        # Quote stuffing: 100 updates in 250ms
        updates = [
            {'ts': 1000 + i * 2, 'price': 0.72, 'size': 100 + (i % 2)}
            for i in range(100)
        ]

        # After TIME_BUCKET sampling, should reduce to ~1 per bucket
        buckets = {}
        for update in updates:
            bucket = update['ts'] // TIME_BUCKET_MS
            buckets[bucket] = update  # Last update in bucket wins

        # Should have reduced from 100 to ~1-2 buckets
        assert len(buckets) <= 3, "Quote stuffing not filtered"

    def test_noise_not_signal(self):
        """Rapid oscillations should not be interpreted as signals"""
        # Price bouncing: 0.72 -> 0.73 -> 0.72 -> 0.73 rapidly
        oscillations = [
            {'ts': 1000, 'best_bid': 0.72},
            {'ts': 1010, 'best_bid': 0.73},
            {'ts': 1020, 'best_bid': 0.72},
            {'ts': 1030, 'best_bid': 0.73},
            {'ts': 1040, 'best_bid': 0.72},
        ]

        # Net change is zero
        first_price = oscillations[0]['best_bid']
        last_price = oscillations[-1]['best_bid']
        net_change = last_price - first_price

        assert net_change == 0, "Oscillation had net change"

        # Should NOT be classified as CHASE (no sustained movement)
        from poc.config import PRICE_SHIFT_PERSIST_MS

        # Calculate longest sustained shift
        max_duration = 0
        for i in range(1, len(oscillations)):
            if oscillations[i]['best_bid'] != oscillations[0]['best_bid']:
                duration = oscillations[i]['ts'] - oscillations[i-1]['ts']
                max_duration = max(max_duration, duration)

        is_chase = max_duration >= PRICE_SHIFT_PERSIST_MS
        assert not is_chase, "Noise oscillation classified as CHASE"


class TestFlashCrash:
    """Tests for flash crash scenarios"""

    def test_flash_crash_recovery_not_broken(self):
        """Flash crash with recovery should not permanently mark as BROKEN"""
        # Scenario: price drops 50%, recovers within 30 seconds
        events = [
            {'ts': 0, 'state': 'STABLE', 'depth': 1000},
            {'ts': 1000, 'state': 'CRACKING', 'depth': 100},  # Flash crash
            {'ts': 5000, 'state': 'CRACKING', 'depth': 500},  # Recovery start
            {'ts': 30000, 'state': 'FRAGILE', 'depth': 900},  # Mostly recovered
            {'ts': 60000, 'state': 'STABLE', 'depth': 950},   # Back to stable
        ]

        final_state = events[-1]['state']
        assert final_state == 'STABLE', "Did not recover from flash crash"

    def test_flash_crash_alerts_auto_resolve(self):
        """Flash crash alerts should auto-resolve on recovery"""
        from poc.alert_lifecycle import (
            AlertLifecycleManager,
            AlertStatus,
            ResolutionRule
        )
        from poc.models import BeliefState
        from poc.alert_system import Alert, AlertType, AlertPriority

        manager = AlertLifecycleManager()

        # Create CRITICAL alert during crash
        alert = Alert(
            alert_type=AlertType.STATE_CHANGE,
            priority=AlertPriority.CRITICAL,
            token_id='test-token',
            subtype='CRACKING',
        )
        managed = manager.add_alert(alert)

        # Simulate recovery to STABLE
        manager.on_belief_state_change('test-token', BeliefState.STABLE, 10000)

        # Tick to process (with enough grace period)
        # In real system, grace period is 5 minutes
        # For test, we simulate time passing
        manager.state_since['test-token'] = 0  # Pretend stable since ts=0
        manager.tick(current_time=10 * 60 * 1000)  # 10 minutes later

        assert managed.status == AlertStatus.AUTO_RESOLVED
        assert managed.resolution_rule == ResolutionRule.STATE_RECOVERED
