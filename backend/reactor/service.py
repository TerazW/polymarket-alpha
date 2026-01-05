"""
Reactor Service Layer (v5.26)

Provides async services for FastAPI integration:
- ReactorService: Main reactor service with database persistence
- BeliefMachineService: Belief state queries and management

Usage:
    from backend.reactor.service import ReactorService

    reactor_service = ReactorService(db_config=DB_CONFIG)
    await reactor_service.start()

    # Process event
    await reactor_service.process_event(event_data)

    # Query
    state = await reactor_service.get_belief_state(token_id)

    await reactor_service.stop()
"""

import asyncio
from typing import Optional, Dict, List, Any, Callable
from datetime import datetime
from decimal import Decimal
import threading
import time
import psycopg2
from psycopg2.extras import RealDictCursor

from .core import ReactorWrapper, BeliefState, STATE_INDICATORS


class ReactorService:
    """
    Async service wrapper for ReactorWrapper.

    Features:
    - Async event processing
    - Database persistence for reactions, states, alerts
    - Event callbacks for WebSocket broadcasting
    """

    def __init__(
        self,
        db_config: Optional[Dict] = None,
        on_reaction: Optional[Callable[[Dict], None]] = None,
        on_state_change: Optional[Callable[[Dict], None]] = None,
        on_leading_event: Optional[Callable[[Dict], None]] = None,
        on_alert: Optional[Callable[[Dict], None]] = None,
        persist_to_db: bool = True,
    ):
        """
        Initialize reactor service.

        Args:
            db_config: PostgreSQL connection config
            on_reaction: Async callback for reactions
            on_state_change: Async callback for state changes
            on_leading_event: Async callback for leading events
            on_alert: Async callback for alerts
            persist_to_db: Whether to persist events to database
        """
        self.db_config = db_config or {
            'host': '127.0.0.1',
            'port': 5433,
            'database': 'belief_reaction',
            'user': 'postgres',
            'password': 'postgres'
        }

        self.persist_to_db = persist_to_db

        # External callbacks
        self._ext_on_reaction = on_reaction
        self._ext_on_state_change = on_state_change
        self._ext_on_leading_event = on_leading_event
        self._ext_on_alert = on_alert

        # Create reactor with internal callbacks
        self.reactor = ReactorWrapper(
            on_reaction=self._handle_reaction,
            on_state_change=self._handle_state_change,
            on_leading_event=self._handle_leading_event,
            on_alert=self._handle_alert,
            replay_mode=False,
        )

        self._started = False
        self._lock = asyncio.Lock()

    async def start(self):
        """Start the reactor service."""
        async with self._lock:
            if not self._started:
                self.reactor.start()
                self._started = True

    async def stop(self):
        """Stop the reactor service."""
        async with self._lock:
            if self._started:
                self.reactor.stop()
                self._started = False

    async def process_event(self, event_data: Dict) -> None:
        """
        Process a raw event asynchronously.

        Args:
            event_data: Event dictionary (see ReactorWrapper.process_raw_event)
        """
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self.reactor.process_raw_event,
            event_data
        )

    async def get_belief_state(self, token_id: str) -> str:
        """Get current belief state for a token."""
        return self.reactor.get_belief_state(token_id)

    async def get_market_summary(self, token_id: str) -> Optional[Dict]:
        """Get market summary."""
        return self.reactor.get_market_summary(token_id)

    async def get_all_markets(self) -> List[Dict]:
        """Get all market summaries."""
        return self.reactor.get_all_markets()

    async def get_stats(self) -> Dict:
        """Get reactor statistics."""
        return self.reactor.get_stats()

    async def get_recent_reactions(
        self,
        token_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Get recent reactions, optionally filtered by token."""
        reactions = self.reactor.get_recent_reactions(limit=limit * 2)
        if token_id:
            reactions = [r for r in reactions if r['token_id'] == token_id]
        return reactions[:limit]

    async def get_recent_state_changes(
        self,
        token_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Get recent state changes, optionally filtered by token."""
        changes = self.reactor.get_recent_state_changes(limit=limit * 2)
        if token_id:
            changes = [c for c in changes if c['token_id'] == token_id]
        return changes[:limit]

    async def get_alerts(
        self,
        token_id: Optional[str] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Get alerts from the alert system."""
        return self.reactor.get_alerts(
            token_id=token_id,
            status=status,
            severity=severity,
            limit=limit,
        )

    # Internal callback handlers

    def _handle_reaction(self, reaction: Dict):
        """Handle reaction event."""
        # Persist to database
        if self.persist_to_db:
            self._persist_reaction(reaction)

        # Call external callback
        if self._ext_on_reaction:
            self._ext_on_reaction(reaction)

    def _handle_state_change(self, change: Dict):
        """Handle state change."""
        # Persist to database
        if self.persist_to_db:
            self._persist_state_change(change)

        # Call external callback
        if self._ext_on_state_change:
            self._ext_on_state_change(change)

    def _handle_leading_event(self, event: Dict):
        """Handle leading event."""
        # Persist to database
        if self.persist_to_db:
            self._persist_leading_event(event)

        # Call external callback
        if self._ext_on_leading_event:
            self._ext_on_leading_event(event)

    def _handle_alert(self, alert: Dict):
        """Handle alert."""
        # Call external callback
        if self._ext_on_alert:
            self._ext_on_alert(alert)

    # Database persistence

    def _get_db_connection(self):
        """Get database connection."""
        return psycopg2.connect(**self.db_config, cursor_factory=RealDictCursor)

    def _persist_reaction(self, reaction: Dict):
        """Persist reaction event to database."""
        try:
            conn = self._get_db_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO reaction_events (
                        reaction_id, shock_id, token_id, ts, price, side,
                        reaction_type, window_type, refill_ratio, drop_ratio,
                        vacuum_duration_ms, shift_ticks, time_to_refill_ms
                    ) VALUES (
                        %s, %s, %s, to_timestamp(%s / 1000.0), %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    ) ON CONFLICT (reaction_id) DO NOTHING
                """, (
                    reaction['reaction_id'],
                    reaction['shock_id'],
                    reaction['token_id'],
                    reaction['timestamp'],
                    Decimal(reaction['price']),
                    reaction['side'],
                    reaction['reaction_type'],
                    reaction['window_type'],
                    reaction['refill_ratio'],
                    reaction['drop_ratio'],
                    reaction['vacuum_duration_ms'],
                    reaction['shift_ticks'],
                    reaction['time_to_refill_ms'],
                ))
                conn.commit()
            conn.close()
        except Exception as e:
            print(f"[ReactorService] Failed to persist reaction: {e}")

    def _persist_state_change(self, change: Dict):
        """Persist state change to database."""
        try:
            conn = self._get_db_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO belief_states (
                        token_id, ts, old_state, new_state,
                        trigger_reaction_id, evidence
                    ) VALUES (
                        %s, to_timestamp(%s / 1000.0), %s, %s, %s, %s
                    )
                """, (
                    change['token_id'],
                    change['timestamp'],
                    change['old_state'],
                    change['new_state'],
                    change['trigger_reaction_id'],
                    change['evidence'],
                ))
                conn.commit()
            conn.close()
        except Exception as e:
            print(f"[ReactorService] Failed to persist state change: {e}")

    def _persist_leading_event(self, event: Dict):
        """Persist leading event to database."""
        try:
            conn = self._get_db_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO leading_events (
                        event_id, token_id, ts, event_type, price, side,
                        drop_ratio, duration_ms, trade_volume_nearby, affected_levels
                    ) VALUES (
                        %s, %s, to_timestamp(%s / 1000.0), %s, %s, %s,
                        %s, %s, %s, %s
                    ) ON CONFLICT (event_id) DO NOTHING
                """, (
                    event['event_id'],
                    event['token_id'],
                    event['timestamp'],
                    event['event_type'],
                    Decimal(event['price']),
                    event['side'],
                    event['drop_ratio'],
                    event['duration_ms'],
                    event['trade_volume_nearby'],
                    event['affected_levels'],
                ))
                conn.commit()
            conn.close()
        except Exception as e:
            print(f"[ReactorService] Failed to persist leading event: {e}")


class BeliefMachineService:
    """
    Service for querying belief state information.

    Provides:
    - State queries from database
    - State history
    - State explanations
    """

    def __init__(self, db_config: Optional[Dict] = None):
        """
        Initialize belief machine service.

        Args:
            db_config: PostgreSQL connection config
        """
        self.db_config = db_config or {
            'host': '127.0.0.1',
            'port': 5433,
            'database': 'belief_reaction',
            'user': 'postgres',
            'password': 'postgres'
        }

    def _get_db_connection(self):
        """Get database connection."""
        return psycopg2.connect(**self.db_config, cursor_factory=RealDictCursor)

    async def get_state(self, token_id: str) -> Dict:
        """
        Get current belief state for a token.

        Returns dict with:
        - state: Current state value
        - indicator: State emoji indicator
        - since_ts: When state was entered
        - confidence: State confidence score
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_state_sync, token_id)

    def _get_state_sync(self, token_id: str) -> Dict:
        """Synchronous implementation of get_state."""
        try:
            conn = self._get_db_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT new_state, ts
                    FROM belief_states
                    WHERE token_id = %s
                    ORDER BY ts DESC
                    LIMIT 1
                """, (token_id,))
                row = cur.fetchone()
            conn.close()

            if row:
                state = row['new_state']
                state_enum = BeliefState(state)
                return {
                    'token_id': token_id,
                    'state': state,
                    'indicator': STATE_INDICATORS.get(state_enum, '⚪'),
                    'since_ts': int(row['ts'].timestamp() * 1000),
                    'confidence': self._compute_confidence(state),
                }
            else:
                return {
                    'token_id': token_id,
                    'state': 'STABLE',
                    'indicator': STATE_INDICATORS.get(BeliefState.STABLE, '🟢'),
                    'since_ts': 0,
                    'confidence': 85.0,
                }
        except Exception as e:
            print(f"[BeliefMachineService] Error getting state: {e}")
            return {
                'token_id': token_id,
                'state': 'STABLE',
                'indicator': '🟢',
                'since_ts': 0,
                'confidence': 50.0,
            }

    async def get_state_history(
        self,
        token_id: str,
        limit: int = 100,
    ) -> List[Dict]:
        """Get state change history for a token."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._get_state_history_sync,
            token_id,
            limit
        )

    def _get_state_history_sync(self, token_id: str, limit: int) -> List[Dict]:
        """Synchronous implementation of get_state_history."""
        try:
            conn = self._get_db_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, ts, old_state, new_state, trigger_reaction_id, evidence
                    FROM belief_states
                    WHERE token_id = %s
                    ORDER BY ts DESC
                    LIMIT %s
                """, (token_id, limit))
                rows = cur.fetchall()
            conn.close()

            return [
                {
                    'id': str(row['id']),
                    'timestamp': int(row['ts'].timestamp() * 1000),
                    'old_state': row['old_state'],
                    'new_state': row['new_state'],
                    'trigger_reaction_id': row['trigger_reaction_id'],
                    'evidence': row['evidence'] or [],
                    'old_indicator': STATE_INDICATORS.get(
                        BeliefState(row['old_state']), '⚪'
                    ),
                    'new_indicator': STATE_INDICATORS.get(
                        BeliefState(row['new_state']), '⚪'
                    ),
                }
                for row in rows
            ]
        except Exception as e:
            print(f"[BeliefMachineService] Error getting history: {e}")
            return []

    async def get_all_states(self) -> Dict[str, Dict]:
        """Get current states for all tracked markets."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_all_states_sync)

    def _get_all_states_sync(self) -> Dict[str, Dict]:
        """Synchronous implementation of get_all_states."""
        try:
            conn = self._get_db_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT ON (token_id)
                        token_id, new_state, ts
                    FROM belief_states
                    ORDER BY token_id, ts DESC
                """)
                rows = cur.fetchall()
            conn.close()

            return {
                row['token_id']: {
                    'state': row['new_state'],
                    'indicator': STATE_INDICATORS.get(
                        BeliefState(row['new_state']), '⚪'
                    ),
                    'since_ts': int(row['ts'].timestamp() * 1000),
                    'confidence': self._compute_confidence(row['new_state']),
                }
                for row in rows
            }
        except Exception as e:
            print(f"[BeliefMachineService] Error getting all states: {e}")
            return {}

    async def get_state_distribution(self) -> Dict[str, int]:
        """Get distribution of states across all markets."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_state_distribution_sync)

    def _get_state_distribution_sync(self) -> Dict[str, int]:
        """Synchronous implementation of get_state_distribution."""
        try:
            conn = self._get_db_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT new_state, COUNT(DISTINCT token_id) as count
                    FROM (
                        SELECT DISTINCT ON (token_id) token_id, new_state
                        FROM belief_states
                        ORDER BY token_id, ts DESC
                    ) latest
                    GROUP BY new_state
                """)
                rows = cur.fetchall()
            conn.close()

            return {row['new_state']: row['count'] for row in rows}
        except Exception as e:
            print(f"[BeliefMachineService] Error getting distribution: {e}")
            return {}

    def _compute_confidence(self, state: str) -> float:
        """Compute confidence score for a state."""
        confidence_map = {
            'STABLE': 85.0,
            'FRAGILE': 70.0,
            'CRACKING': 60.0,
            'BROKEN': 75.0,
        }
        return confidence_map.get(state, 50.0)


__all__ = ['ReactorService', 'BeliefMachineService']
