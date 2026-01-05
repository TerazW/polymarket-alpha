"""
Belief State Replay Verification Tests (v5.33)

Tests that the BeliefStateMachine produces IDENTICAL state transitions
when replaying the same event sequence.

Critical invariant:
    "相同的事件序列必须产生相同的状态转换"
    "same events -> same states"

These tests verify:
1. State transition determinism
2. Evidence reference integrity
3. Cross-replay consistency
4. Window boundary behavior
"""

import pytest
from typing import List, Dict, Any
from decimal import Decimal
from dataclasses import dataclass
import hashlib
import json

from poc.belief_state_machine import BeliefStateMachine, MarketStateContext
from poc.models import (
    BeliefState, BeliefStateChange, ReactionEvent, ReactionType,
    LeadingEvent, LeadingEventType, AnchorLevel
)


# =============================================================================
# Test Data: Deterministic Event Sequences
# =============================================================================

def create_anchor(
    token_id: str = "test_token",
    price: str = "0.72",
    side: str = "bid",
) -> AnchorLevel:
    """Create an anchor level for testing."""
    return AnchorLevel(
        token_id=token_id,
        price=Decimal(price),
        side=side,
        peak_size=1000.0,
        persistence_seconds=300.0,
        anchor_score=100.0,
        rank=1,
    )


def create_reaction_event(
    token_id: str = "test_token",
    reaction_type: ReactionType = ReactionType.HOLD,
    price: str = "0.72",
    side: str = "bid",
    timestamp: int = 1000,
    reaction_id: str = None,
) -> ReactionEvent:
    """Create a reaction event for testing."""
    from poc.models import WindowType

    if reaction_id is None:
        reaction_id = f"r_{timestamp}_{reaction_type.value}"

    return ReactionEvent(
        reaction_id=reaction_id,
        shock_id=f"shock_{timestamp}",
        timestamp=timestamp,
        token_id=token_id,
        price=Decimal(price),
        side=side,
        reaction_type=reaction_type,
        window_type=WindowType.FAST,
        baseline_size=1000.0,
        refill_ratio=0.8 if reaction_type == ReactionType.HOLD else 0.3,
        drop_ratio=0.5,
        time_to_refill_ms=100 if reaction_type == ReactionType.HOLD else 500,
        min_liquidity=100.0,
        max_liquidity=1000.0,
        vacuum_duration_ms=0,
        shift_ticks=0,
    )


def create_leading_event(
    token_id: str = "test_token",
    event_type: LeadingEventType = LeadingEventType.PRE_SHOCK_PULL,
    price: str = "0.72",
    side: str = "bid",
    timestamp: int = 1000,
    event_id: str = None,
) -> LeadingEvent:
    """Create a leading event for testing."""
    if event_id is None:
        event_id = f"le_{timestamp}_{event_type.value}"

    return LeadingEvent(
        event_id=event_id,
        event_type=event_type,
        timestamp=timestamp,
        token_id=token_id,
        price=Decimal(price),
        side=side,
        drop_ratio=0.8,
        duration_ms=100,
        trade_volume_nearby=0.0,
        is_anchor=True,
        affected_levels=3,
    )


# Deterministic test event sequences
STABLE_SEQUENCE = [
    ("reaction", {"reaction_type": ReactionType.HOLD, "timestamp": 1000}),
    ("reaction", {"reaction_type": ReactionType.HOLD, "timestamp": 2000}),
    ("reaction", {"reaction_type": ReactionType.HOLD, "timestamp": 3000}),
]

FRAGILE_SEQUENCE = [
    ("reaction", {"reaction_type": ReactionType.HOLD, "timestamp": 1000}),
    ("reaction", {"reaction_type": ReactionType.PULL, "timestamp": 2000}),  # Single PULL -> FRAGILE
]

CRACKING_SEQUENCE = [
    ("reaction", {"reaction_type": ReactionType.HOLD, "timestamp": 1000}),
    ("reaction", {"reaction_type": ReactionType.VACUUM, "timestamp": 2000}),  # Single VACUUM -> CRACKING
]

BROKEN_SEQUENCE = [
    ("reaction", {"reaction_type": ReactionType.HOLD, "timestamp": 1000}),
    ("reaction", {"reaction_type": ReactionType.VACUUM, "timestamp": 2000, "price": "0.72"}),
    ("reaction", {"reaction_type": ReactionType.VACUUM, "timestamp": 3000, "price": "0.73"}),  # Multiple VACUUMs -> BROKEN
]

PROGRESSIVE_DEGRADATION = [
    # Start STABLE
    ("reaction", {"reaction_type": ReactionType.HOLD, "timestamp": 1000}),
    ("reaction", {"reaction_type": ReactionType.HOLD, "timestamp": 2000}),
    # Degrade to FRAGILE
    ("reaction", {"reaction_type": ReactionType.PULL, "timestamp": 3000}),
    # Degrade to CRACKING
    ("reaction", {"reaction_type": ReactionType.VACUUM, "timestamp": 4000}),
    # Degrade to BROKEN
    ("reaction", {"reaction_type": ReactionType.VACUUM, "timestamp": 5000, "price": "0.73"}),
]


# =============================================================================
# State Transition Determinism Tests
# =============================================================================

class TestStateDeterminism:
    """Test that state transitions are deterministic."""

    def test_same_sequence_same_states(self):
        """Identical event sequence must produce identical states."""
        token_id = "test_token"

        # Run sequence through two separate machines
        machine1 = BeliefStateMachine()
        machine2 = BeliefStateMachine()

        # Setup anchors (required for events to be counted)
        anchor = create_anchor(price="0.72")
        machine1.update_anchors(token_id, [anchor])
        machine2.update_anchors(token_id, [anchor])

        states1 = []
        states2 = []

        for event_type, params in PROGRESSIVE_DEGRADATION:
            event = create_reaction_event(token_id=token_id, **params)

            machine1.on_reaction(event, is_anchor=True)
            machine2.on_reaction(event, is_anchor=True)

            states1.append(machine1.get_state(token_id).value)
            states2.append(machine2.get_state(token_id).value)

        assert states1 == states2, f"State sequences differ: {states1} vs {states2}"

    def test_multiple_replays_identical(self):
        """Multiple replays of same sequence must produce identical results."""
        token_id = "test_token"
        results = []

        for replay_num in range(5):  # Run 5 replays
            machine = BeliefStateMachine()
            machine.update_anchors(token_id, [
                create_anchor(price="0.72"),
                create_anchor(price="0.73"),
            ])

            states = []
            changes = []

            for event_type, params in BROKEN_SEQUENCE:
                event = create_reaction_event(token_id=token_id, **params)
                change = machine.on_reaction(event, is_anchor=True)

                states.append(machine.get_state(token_id).value)
                if change:
                    changes.append({
                        "old": change.old_state.value,
                        "new": change.new_state.value,
                        "ts": change.timestamp,
                    })

            results.append({
                "states": states,
                "changes": changes,
                "final": machine.get_state(token_id).value,
            })

        # All replays must produce identical results
        first = results[0]
        for i, result in enumerate(results[1:], 1):
            assert result["states"] == first["states"], \
                f"Replay {i} states differ: {result['states']} vs {first['states']}"
            assert result["changes"] == first["changes"], \
                f"Replay {i} changes differ"
            assert result["final"] == first["final"], \
                f"Replay {i} final state differs"

    def test_state_hash_determinism(self):
        """State sequence should produce deterministic hash."""
        token_id = "test_token"

        def compute_sequence_hash(sequence) -> str:
            machine = BeliefStateMachine()
            machine.update_anchors(token_id, [
                create_anchor(price="0.72"),
            ])

            state_log = []
            for event_type, params in sequence:
                event = create_reaction_event(token_id=token_id, **params)
                machine.on_reaction(event, is_anchor=True)
                state_log.append({
                    "ts": params["timestamp"],
                    "state": machine.get_state(token_id).value,
                })

            return hashlib.sha256(
                json.dumps(state_log, sort_keys=True).encode()
            ).hexdigest()

        # Compute multiple times
        hashes = [compute_sequence_hash(FRAGILE_SEQUENCE) for _ in range(3)]

        assert len(set(hashes)) == 1, f"Hash varies across runs: {hashes}"


# =============================================================================
# State Transition Rule Tests
# =============================================================================

class TestStateTransitionRules:
    """Test that state transition rules match spec."""

    def test_stable_to_fragile(self):
        """Single PULL should transition STABLE -> FRAGILE."""
        machine = BeliefStateMachine()
        token_id = "test_token"
        machine.update_anchors(token_id, [
            create_anchor(price="0.72")
        ])

        # Start with HOLD to ensure STABLE
        event1 = create_reaction_event(
            token_id=token_id,
            reaction_type=ReactionType.HOLD,
            timestamp=1000,
        )
        machine.on_reaction(event1, is_anchor=True)
        assert machine.get_state(token_id) == BeliefState.STABLE

        # Single PULL -> FRAGILE
        event2 = create_reaction_event(
            token_id=token_id,
            reaction_type=ReactionType.PULL,
            timestamp=2000,
        )
        change = machine.on_reaction(event2, is_anchor=True)

        assert machine.get_state(token_id) == BeliefState.FRAGILE
        assert change is not None
        assert change.old_state == BeliefState.STABLE
        assert change.new_state == BeliefState.FRAGILE

    def test_fragile_to_cracking(self):
        """VACUUM should transition to CRACKING."""
        machine = BeliefStateMachine()
        token_id = "test_token"
        machine.update_anchors(token_id, [
            create_anchor(price="0.72")
        ])

        # Get to FRAGILE first
        machine.on_reaction(create_reaction_event(
            token_id=token_id,
            reaction_type=ReactionType.PULL,
            timestamp=1000,
        ), is_anchor=True)

        assert machine.get_state(token_id) == BeliefState.FRAGILE

        # VACUUM -> CRACKING
        change = machine.on_reaction(create_reaction_event(
            token_id=token_id,
            reaction_type=ReactionType.VACUUM,
            timestamp=2000,
        ), is_anchor=True)

        assert machine.get_state(token_id) == BeliefState.CRACKING
        assert change.old_state == BeliefState.FRAGILE
        assert change.new_state == BeliefState.CRACKING

    def test_cracking_to_broken(self):
        """Multiple VACUUMs from different anchors -> BROKEN."""
        machine = BeliefStateMachine()
        token_id = "test_token"
        machine.update_anchors(token_id, [
            create_anchor(price="0.72"),
            create_anchor(price="0.73"),
        ])

        # First VACUUM -> CRACKING
        machine.on_reaction(create_reaction_event(
            token_id=token_id,
            reaction_type=ReactionType.VACUUM,
            price="0.72",
            timestamp=1000,
        ), is_anchor=True)

        assert machine.get_state(token_id) == BeliefState.CRACKING

        # Second VACUUM from different anchor -> BROKEN
        change = machine.on_reaction(create_reaction_event(
            token_id=token_id,
            reaction_type=ReactionType.VACUUM,
            price="0.73",
            timestamp=2000,
        ), is_anchor=True)

        assert machine.get_state(token_id) == BeliefState.BROKEN
        assert change.old_state == BeliefState.CRACKING
        assert change.new_state == BeliefState.BROKEN


# =============================================================================
# Evidence Reference Integrity Tests
# =============================================================================

class TestEvidenceIntegrity:
    """Test that evidence references are correctly maintained."""

    def test_state_change_has_evidence(self):
        """State changes must include evidence references."""
        machine = BeliefStateMachine()
        token_id = "test_token"
        machine.update_anchors(token_id, [
            create_anchor(price="0.72")
        ])

        # Create transition
        event = create_reaction_event(
            token_id=token_id,
            reaction_type=ReactionType.VACUUM,
            timestamp=1000,
            reaction_id="r_vacuum_001",
        )
        change = machine.on_reaction(event, is_anchor=True)

        assert change is not None
        assert len(change.evidence_refs) > 0
        assert "r_vacuum_001" in change.evidence_refs

    def test_evidence_traceable_to_events(self):
        """All evidence refs must trace to actual events."""
        machine = BeliefStateMachine()
        token_id = "test_token"
        machine.update_anchors(token_id, [
            create_anchor(price="0.72")
        ])

        event_ids = []
        for i, (_, params) in enumerate(CRACKING_SEQUENCE):
            event = create_reaction_event(
                token_id=token_id,
                reaction_id=f"r_{i}",
                **params
            )
            event_ids.append(event.reaction_id)
            machine.on_reaction(event, is_anchor=True)

        # Get state changes
        changes = machine.state_changes

        # All evidence refs must be in our event IDs
        for change in changes:
            for ref in change.evidence_refs:
                assert ref in event_ids, f"Evidence ref {ref} not in events"


# =============================================================================
# Leading Event Tests
# =============================================================================

class TestLeadingEventStates:
    """Test state transitions triggered by leading events."""

    def test_pre_shock_pull_to_cracking(self):
        """PRE_SHOCK_PULL should trigger CRACKING."""
        machine = BeliefStateMachine()
        token_id = "test_token"
        machine.update_anchors(token_id, [
            create_anchor(price="0.72")
        ])

        # PRE_SHOCK_PULL -> CRACKING
        event = create_leading_event(
            token_id=token_id,
            event_type=LeadingEventType.PRE_SHOCK_PULL,
            timestamp=1000,
        )
        change = machine.on_leading_event(event)

        assert machine.get_state(token_id) == BeliefState.CRACKING
        assert change is not None

    def test_multiple_pre_shock_pull_to_broken(self):
        """Multiple PRE_SHOCK_PULL should trigger BROKEN."""
        machine = BeliefStateMachine()
        token_id = "test_token"
        machine.update_anchors(token_id, [
            create_anchor(price="0.72")
        ])

        # First PRE_SHOCK_PULL -> CRACKING
        machine.on_leading_event(create_leading_event(
            token_id=token_id,
            event_type=LeadingEventType.PRE_SHOCK_PULL,
            timestamp=1000,
        ))
        assert machine.get_state(token_id) == BeliefState.CRACKING

        # Second PRE_SHOCK_PULL -> BROKEN
        machine.on_leading_event(create_leading_event(
            token_id=token_id,
            event_type=LeadingEventType.PRE_SHOCK_PULL,
            timestamp=2000,
        ))
        assert machine.get_state(token_id) == BeliefState.BROKEN


# =============================================================================
# Window Boundary Tests
# =============================================================================

class TestWindowBoundaries:
    """Test 30-minute rolling window behavior."""

    def test_events_expire_after_window(self):
        """Events outside 30-minute window should not count."""
        machine = BeliefStateMachine()
        token_id = "test_token"
        machine.update_anchors(token_id, [
            create_anchor(price="0.72")
        ])

        base_ts = 0
        window_ms = 30 * 60 * 1000  # 30 minutes

        # VACUUM at T=0
        machine.on_reaction(create_reaction_event(
            token_id=token_id,
            reaction_type=ReactionType.VACUUM,
            timestamp=base_ts,
        ), is_anchor=True)

        assert machine.get_state(token_id) == BeliefState.CRACKING

        # HOLD at T=31 minutes (outside window)
        machine.on_reaction(create_reaction_event(
            token_id=token_id,
            reaction_type=ReactionType.HOLD,
            timestamp=base_ts + window_ms + 60000,  # 31 minutes later
        ), is_anchor=True)

        # VACUUM should have expired, should be back to STABLE
        assert machine.get_state(token_id) == BeliefState.STABLE

    def test_window_boundary_exact(self):
        """Test exact window boundary behavior."""
        machine = BeliefStateMachine()
        token_id = "test_token"
        machine.update_anchors(token_id, [
            create_anchor(price="0.72")
        ])

        base_ts = 0
        window_ms = 30 * 60 * 1000  # 30 minutes

        # VACUUM at T=0
        machine.on_reaction(create_reaction_event(
            token_id=token_id,
            reaction_type=ReactionType.VACUUM,
            timestamp=base_ts,
        ), is_anchor=True)

        # Just inside window (T=29:59)
        machine.on_reaction(create_reaction_event(
            token_id=token_id,
            reaction_type=ReactionType.HOLD,
            timestamp=base_ts + window_ms - 1000,  # 1 second before expiry
        ), is_anchor=True)

        # VACUUM should still be in window
        assert machine.get_state(token_id) == BeliefState.CRACKING


# =============================================================================
# Regression Tests
# =============================================================================

class TestStateRegressions:
    """Regression tests for known edge cases."""

    def test_chase_sweep_triggers_fragile(self):
        """CHASE or SWEEP should trigger FRAGILE."""
        for reaction_type in [ReactionType.CHASE, ReactionType.SWEEP]:
            machine = BeliefStateMachine()
            token_id = "test_token"
            machine.update_anchors(token_id, [
                create_anchor(price="0.72")
            ])

            machine.on_reaction(create_reaction_event(
                token_id=token_id,
                reaction_type=reaction_type,
                timestamp=1000,
            ), is_anchor=True)

            assert machine.get_state(token_id) == BeliefState.FRAGILE, \
                f"{reaction_type} should trigger FRAGILE"

    def test_delayed_without_low_hold_ratio_stays_stable(self):
        """DELAYED without low hold_ratio should not trigger FRAGILE."""
        machine = BeliefStateMachine()
        token_id = "test_token"
        machine.update_anchors(token_id, [
            create_anchor(price="0.72")
        ])

        # Many HOLDs first
        for i in range(5):
            machine.on_reaction(create_reaction_event(
                token_id=token_id,
                reaction_type=ReactionType.HOLD,
                timestamp=1000 + i * 1000,
            ), is_anchor=True)

        # Single DELAYED (n_delayed=1, but need 2)
        machine.on_reaction(create_reaction_event(
            token_id=token_id,
            reaction_type=ReactionType.DELAYED,
            timestamp=6000,
        ), is_anchor=True)

        # Should still be STABLE (need n_delayed >= 2 AND low hold_ratio)
        assert machine.get_state(token_id) == BeliefState.STABLE

    def test_non_anchor_events_ignored(self):
        """Events on non-anchor prices should not affect state."""
        machine = BeliefStateMachine()
        token_id = "test_token"

        # Only anchor at 0.72
        machine.update_anchors(token_id, [
            create_anchor(price="0.72")
        ])

        # VACUUM at non-anchor price (0.75)
        event = create_reaction_event(
            token_id=token_id,
            reaction_type=ReactionType.VACUUM,
            price="0.75",
            timestamp=1000,
        )
        change = machine.on_reaction(event, is_anchor=False)

        # Should remain STABLE (event was on non-anchor)
        assert machine.get_state(token_id) == BeliefState.STABLE
        assert change is None
