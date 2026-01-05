"""
Belief Reaction System - Belief State Engine
Finite state machine that tracks the overall belief status of each market.

States:
- STABLE: Market belief is confident/consistent (🟢)
- FRAGILE: Market belief shows weakness signs (🟡)
- CRACKING: Market belief actively deteriorating (🟠)
- BROKEN: Market belief has collapsed (🔴)

State transitions are DETERMINISTIC - driven entirely by reaction events at key levels.
"""

from collections import defaultdict
from decimal import Decimal
from typing import Optional, Dict, List, Callable, Set
import time

# v5.13: Determinism infrastructure
from backend.common.determinism import deterministic_now

from .models import (
    BeliefState, BeliefStateChange, ReactionEvent, ReactionType,
    PriceLevel, STATE_INDICATORS
)
from .config import (
    KEY_LEVELS_COUNT,
    KEY_LEVELS_LOOKBACK_HOURS,
    STATE_REACTION_WINDOW
)


class BeliefStateMachine:
    """
    Tracks belief state for a single market.
    Transitions based on accumulated reaction events at key levels.
    """

    def __init__(
        self,
        token_id: str,
        key_levels: Optional[List[Decimal]] = None,
        on_state_change: Optional[Callable[[BeliefStateChange], None]] = None
    ):
        self.token_id = token_id
        self.state = BeliefState.STABLE  # Initial state
        self.key_levels: Set[Decimal] = set(key_levels or [])
        self.recent_reactions: List[ReactionEvent] = []
        self.on_state_change = on_state_change

        # History
        self.state_changes: List[BeliefStateChange] = []
        self.last_transition_ts: int = 0

    def update_key_levels(self, levels: List[Decimal]):
        """Update the key levels to watch."""
        self.key_levels = set(levels)

    def on_reaction(self, reaction: ReactionEvent) -> Optional[BeliefStateChange]:
        """
        Process a reaction event and potentially transition state.

        Only reactions at key levels trigger state evaluation.
        """
        # Only process reactions at key levels
        if reaction.price not in self.key_levels:
            return None

        self.recent_reactions.append(reaction)
        self._prune_old_reactions()

        return self._evaluate_transition(reaction)

    def _prune_old_reactions(self):
        """Keep only recent reactions for evaluation."""
        if len(self.recent_reactions) > STATE_REACTION_WINDOW:
            self.recent_reactions = self.recent_reactions[-STATE_REACTION_WINDOW:]

    def _evaluate_transition(self, trigger: ReactionEvent) -> Optional[BeliefStateChange]:
        """
        Evaluate if state should transition based on recent reactions.

        Transition rules (priority order):
        1. BROKEN: 2+ key levels with VACUUM
        2. CRACKING: Any PULL or VACUUM at key level
        3. FRAGILE: Mix of HOLD and DELAY
        4. STABLE: Consistent HOLD or FAKE
        """
        counts = self._count_reaction_types()
        new_state = self._determine_new_state(counts)

        if new_state != self.state:
            old_state = self.state
            self.state = new_state
            # v5.13: Use trigger event's timestamp for deterministic replay
            # The state change logically happens at the same time as the trigger
            change_ts = trigger.timestamp if hasattr(trigger, 'timestamp') and trigger.timestamp else \
                        deterministic_now(context="BeliefStateMachine._evaluate_transition")

            change = BeliefStateChange(
                timestamp=change_ts,
                token_id=self.token_id,
                old_state=old_state,
                new_state=new_state,
                trigger_reaction_id=trigger.reaction_id,
                evidence=self._gather_evidence(counts, trigger)
            )

            self.state_changes.append(change)
            self.last_transition_ts = change_ts

            if self.on_state_change:
                self.on_state_change(change)

            return change

        return None

    def _count_reaction_types(self) -> Dict[ReactionType, int]:
        """Count recent reaction types."""
        counts = defaultdict(int)
        for r in self.recent_reactions:
            counts[r.reaction_type] += 1
        return counts

    def _unique_levels_with_type(self, reaction_type: ReactionType) -> Set[Decimal]:
        """Get unique price levels with a specific reaction type."""
        return {
            r.price for r in self.recent_reactions
            if r.reaction_type == reaction_type
        }

    def _determine_new_state(self, counts: Dict[ReactionType, int]) -> BeliefState:
        """Determine new state based on reaction counts."""
        # BROKEN: 2+ key levels with VACUUM
        vacuum_levels = self._unique_levels_with_type(ReactionType.VACUUM)
        if len(vacuum_levels) >= 2:
            return BeliefState.BROKEN

        # CRACKING: Any PULL or VACUUM at key level
        if counts[ReactionType.PULL] > 0 or counts[ReactionType.VACUUM] > 0:
            return BeliefState.CRACKING

        # FRAGILE: Mix of HOLD and DELAY
        if counts[ReactionType.DELAY] > 0 and counts[ReactionType.HOLD] > 0:
            return BeliefState.FRAGILE

        # STABLE: Consistent HOLD or FAKE
        if counts[ReactionType.HOLD] >= 3 or counts[ReactionType.FAKE] >= 2:
            return BeliefState.STABLE

        # Default: maintain current state, or STABLE if new
        return self.state

    def _gather_evidence(
        self,
        counts: Dict[ReactionType, int],
        trigger: ReactionEvent
    ) -> List[str]:
        """Gather evidence strings for the state change."""
        evidence = []

        # Add trigger info
        evidence.append(
            f"Triggered by {trigger.reaction_type.value} at {trigger.price}"
        )

        # Add count summary
        if counts:
            summary = ", ".join(
                f"{t.value}:{c}" for t, c in counts.items() if c > 0
            )
            evidence.append(f"Recent reactions: {summary}")

        # Add specific evidence based on trigger type
        if trigger.reaction_type == ReactionType.VACUUM:
            evidence.append(
                f"Liquidity dropped to {trigger.min_liquidity:.1f} "
                f"(was {trigger.liquidity_before:.1f})"
            )
        elif trigger.reaction_type == ReactionType.PULL:
            evidence.append(
                f"Refill ratio only {trigger.refill_ratio:.0%}"
            )
        elif trigger.reaction_type == ReactionType.HOLD:
            if trigger.time_to_refill_ms:
                evidence.append(
                    f"Refilled in {trigger.time_to_refill_ms/1000:.1f}s"
                )

        return evidence

    def get_state_display(self) -> str:
        """Get displayable state string."""
        indicator = STATE_INDICATORS.get(self.state, "⚪")
        return f"{indicator} {self.state.value}"

    def get_summary(self) -> dict:
        """Get summary of current state machine status."""
        counts = self._count_reaction_types()
        return {
            "token_id": self.token_id,
            "state": self.state.value,
            "indicator": STATE_INDICATORS.get(self.state, "⚪"),
            "key_levels": [str(l) for l in sorted(self.key_levels)],
            "recent_reaction_counts": {t.value: c for t, c in counts.items()},
            "total_transitions": len(self.state_changes)
        }


class BeliefStateEngine:
    """
    Manages belief state for all monitored markets.
    """

    def __init__(self, on_state_change: Optional[Callable[[BeliefStateChange], None]] = None):
        self.machines: Dict[str, BeliefStateMachine] = {}
        self.on_state_change = on_state_change

        # Stats
        self.total_transitions = 0

    def get_or_create_machine(
        self,
        token_id: str,
        key_levels: Optional[List[Decimal]] = None
    ) -> BeliefStateMachine:
        """Get or create a state machine for a market."""
        if token_id not in self.machines:
            self.machines[token_id] = BeliefStateMachine(
                token_id=token_id,
                key_levels=key_levels,
                on_state_change=self._handle_state_change
            )
        return self.machines[token_id]

    def on_reaction(self, reaction: ReactionEvent) -> Optional[BeliefStateChange]:
        """Process a reaction and potentially transition state."""
        machine = self.machines.get(reaction.token_id)
        if not machine:
            # Auto-create machine for new tokens
            machine = self.get_or_create_machine(reaction.token_id)

        return machine.on_reaction(reaction)

    def update_key_levels(self, token_id: str, levels: List[Decimal]):
        """Update key levels for a market."""
        machine = self.get_or_create_machine(token_id)
        machine.update_key_levels(levels)

    def get_state(self, token_id: str) -> BeliefState:
        """Get current state for a market."""
        machine = self.machines.get(token_id)
        return machine.state if machine else BeliefState.STABLE

    def get_all_states(self) -> Dict[str, dict]:
        """Get state summary for all markets."""
        return {
            token_id: machine.get_summary()
            for token_id, machine in self.machines.items()
        }

    def _handle_state_change(self, change: BeliefStateChange):
        """Handle state change from a machine."""
        self.total_transitions += 1
        if self.on_state_change:
            self.on_state_change(change)

    def get_stats(self) -> dict:
        """Get engine statistics."""
        state_counts = defaultdict(int)
        for machine in self.machines.values():
            state_counts[machine.state.value] += 1

        return {
            "total_markets": len(self.machines),
            "total_transitions": self.total_transitions,
            "state_distribution": dict(state_counts)
        }
