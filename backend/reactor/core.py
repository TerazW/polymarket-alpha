"""
Reactor Core Wrapper (v5.26)

Provides thread-safe wrapper around POC Reactor for backend integration.

Usage:
    from backend.reactor.core import ReactorWrapper

    reactor = ReactorWrapper()
    reactor.start()

    # Process events
    reactor.process_raw_event(raw_event_dict)

    # Get market summary
    summary = reactor.get_market_summary(token_id)

    reactor.stop()
"""

from typing import Optional, Dict, List, Callable, Any
from decimal import Decimal
import threading
import time

# Import POC components
from poc.reactor import Reactor, OrderBookState
from poc.event_bus import InMemoryEventBus, RawEvent, EventType
from poc.models import (
    BeliefState, BeliefStateChange, ReactionEvent,
    ShockEvent, LeadingEvent, ReactionType, WindowType,
    STATE_INDICATORS, REACTION_INDICATORS
)
from poc.belief_state import BeliefStateEngine
from poc.belief_state_machine import BeliefStateMachine


class ReactorWrapper:
    """
    Thread-safe wrapper around POC Reactor.

    Provides:
    - In-memory event bus (single process)
    - Callback registration
    - State queries
    - Statistics
    """

    def __init__(
        self,
        on_reaction: Optional[Callable[[Dict], None]] = None,
        on_state_change: Optional[Callable[[Dict], None]] = None,
        on_leading_event: Optional[Callable[[Dict], None]] = None,
        on_alert: Optional[Callable[[Dict], None]] = None,
        replay_mode: bool = False,
    ):
        """
        Initialize reactor wrapper.

        Args:
            on_reaction: Callback for reaction events (dict format)
            on_state_change: Callback for state changes (dict format)
            on_leading_event: Callback for leading events (dict format)
            on_alert: Callback for alerts (dict format)
            replay_mode: If True, use event timestamps instead of wall clock
        """
        # Create event bus
        self.event_bus = InMemoryEventBus()

        # Store callbacks (convert to dict format)
        self._on_reaction = on_reaction
        self._on_state_change = on_state_change
        self._on_leading_event = on_leading_event
        self._on_alert = on_alert

        # Create reactor with internal callbacks
        self.reactor = Reactor(
            event_bus=self.event_bus,
            on_reaction=self._handle_reaction,
            on_state_change=self._handle_state_change,
            on_leading_event=self._handle_leading_event,
            on_alert=self._handle_alert,
            use_alert_system=True,
            replay_mode=replay_mode,
        )

        self.is_running = False
        self._lock = threading.Lock()

        # Event history for recent events
        self._recent_reactions: List[Dict] = []
        self._recent_state_changes: List[Dict] = []
        self._recent_leading_events: List[Dict] = []
        self._max_history = 1000

    def start(self):
        """Start the reactor processing loop."""
        with self._lock:
            if not self.is_running:
                self.reactor.start()
                self.is_running = True

    def stop(self):
        """Stop the reactor."""
        with self._lock:
            if self.is_running:
                self.reactor.stop()
                self.is_running = False

    def process_raw_event(self, event_data: Dict) -> None:
        """
        Process a raw event from WebSocket or replay.

        Args:
            event_data: Dictionary with:
                - event_type: 'book', 'trade', 'price_change'
                - token_id: Asset ID
                - payload: Event-specific data
                - server_ts: Server timestamp (ms)
                - ws_ts: WebSocket timestamp (ms, optional)
        """
        event_type_str = event_data.get('event_type', '').lower()

        # Map string to EventType
        event_type_map = {
            'book': EventType.BOOK,
            'trade': EventType.TRADE,
            'price_change': EventType.PRICE_CHANGE,
        }

        event_type = event_type_map.get(event_type_str)
        if not event_type:
            return

        raw_event = RawEvent(
            event_type=event_type,
            token_id=event_data.get('token_id', ''),
            payload=event_data.get('payload', {}),
            server_ts=event_data.get('server_ts', int(time.time() * 1000)),
            ws_ts=event_data.get('ws_ts'),
        )

        self.event_bus.publish(raw_event)

    def get_market_summary(self, token_id: str) -> Optional[Dict]:
        """Get summary for a specific market."""
        return self.reactor.get_market_summary(token_id)

    def get_all_markets(self) -> List[Dict]:
        """Get summary for all tracked markets."""
        summaries = []
        for token_id in self.reactor.order_books:
            summary = self.reactor.get_market_summary(token_id)
            if summary:
                summaries.append(summary)
        return summaries

    def get_belief_state(self, token_id: str) -> str:
        """Get current belief state for a token."""
        state = self.reactor.belief_state_engine.get_state(token_id)
        return state.value

    def get_all_belief_states(self) -> Dict[str, Dict]:
        """Get belief states for all tracked markets."""
        return self.reactor.belief_state_engine.get_all_states()

    def get_stats(self) -> Dict:
        """Get reactor statistics."""
        return self.reactor.get_stats()

    def get_recent_reactions(self, limit: int = 100) -> List[Dict]:
        """Get recent reaction events."""
        with self._lock:
            return self._recent_reactions[-limit:]

    def get_recent_state_changes(self, limit: int = 100) -> List[Dict]:
        """Get recent state changes."""
        with self._lock:
            return self._recent_state_changes[-limit:]

    def get_recent_leading_events(self, limit: int = 100) -> List[Dict]:
        """Get recent leading events."""
        with self._lock:
            return self._recent_leading_events[-limit:]

    def get_alerts(
        self,
        token_id: Optional[str] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Get alerts from the alert system."""
        alerts = self.reactor.get_alerts(
            token_id=token_id,
            status=status,
            severity=severity,
            limit=limit,
        )
        return [alert.to_dict() for alert in alerts]

    def clear_state(
        self,
        token_ids: Optional[List[str]] = None,
    ):
        """Clear reactor state (for rebuild)."""
        self.reactor.clear_state(token_ids=token_ids)
        with self._lock:
            self._recent_reactions.clear()
            self._recent_state_changes.clear()
            self._recent_leading_events.clear()

    # Internal callback handlers

    def _handle_reaction(self, reaction: ReactionEvent):
        """Handle reaction event from reactor."""
        reaction_dict = {
            'reaction_id': reaction.reaction_id,
            'shock_id': reaction.shock_id,
            'timestamp': reaction.timestamp,
            'token_id': reaction.token_id,
            'price': str(reaction.price),
            'side': reaction.side,
            'reaction_type': reaction.reaction_type.value,
            'window_type': reaction.window_type.value,
            'baseline_size': reaction.baseline_size,
            'refill_ratio': reaction.refill_ratio,
            'drop_ratio': reaction.drop_ratio,
            'time_to_refill_ms': reaction.time_to_refill_ms,
            'min_liquidity': reaction.min_liquidity,
            'max_liquidity': reaction.max_liquidity,
            'vacuum_duration_ms': reaction.vacuum_duration_ms,
            'shift_ticks': reaction.shift_ticks,
            'indicator': REACTION_INDICATORS.get(reaction.reaction_type, '⚪'),
        }

        with self._lock:
            self._recent_reactions.append(reaction_dict)
            if len(self._recent_reactions) > self._max_history:
                self._recent_reactions = self._recent_reactions[-self._max_history:]

        if self._on_reaction:
            self._on_reaction(reaction_dict)

    def _handle_state_change(self, change: BeliefStateChange):
        """Handle state change from reactor."""
        change_dict = {
            'timestamp': change.timestamp,
            'token_id': change.token_id,
            'old_state': change.old_state.value,
            'new_state': change.new_state.value,
            'trigger_reaction_id': change.trigger_reaction_id,
            'trigger_leading_event_id': change.trigger_leading_event_id,
            'evidence': change.evidence,
            'evidence_refs': change.evidence_refs,
            'old_indicator': STATE_INDICATORS.get(change.old_state, '⚪'),
            'new_indicator': STATE_INDICATORS.get(change.new_state, '⚪'),
        }

        with self._lock:
            self._recent_state_changes.append(change_dict)
            if len(self._recent_state_changes) > self._max_history:
                self._recent_state_changes = self._recent_state_changes[-self._max_history:]

        if self._on_state_change:
            self._on_state_change(change_dict)

    def _handle_leading_event(self, event: LeadingEvent):
        """Handle leading event from reactor."""
        event_dict = {
            'event_id': event.event_id,
            'event_type': event.event_type.value,
            'timestamp': event.timestamp,
            'token_id': event.token_id,
            'price': str(event.price),
            'side': event.side,
            'drop_ratio': event.drop_ratio,
            'duration_ms': event.duration_ms,
            'trade_volume_nearby': event.trade_volume_nearby,
            'is_anchor': event.is_anchor,
            'affected_levels': event.affected_levels,
            'time_std_ms': event.time_std_ms,
            'total_depth_before': event.total_depth_before,
            'total_depth_after': event.total_depth_after,
            'trade_driven_ratio': event.trade_driven_ratio,
        }

        with self._lock:
            self._recent_leading_events.append(event_dict)
            if len(self._recent_leading_events) > self._max_history:
                self._recent_leading_events = self._recent_leading_events[-self._max_history:]

        if self._on_leading_event:
            self._on_leading_event(event_dict)

    def _handle_alert(self, alert: Dict):
        """Handle alert from reactor."""
        if self._on_alert:
            self._on_alert(alert)


# Re-export POC models for convenience
__all__ = [
    'ReactorWrapper',
    'BeliefState',
    'BeliefStateChange',
    'ReactionEvent',
    'ShockEvent',
    'LeadingEvent',
    'ReactionType',
    'WindowType',
    'STATE_INDICATORS',
    'REACTION_INDICATORS',
]
