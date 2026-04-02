"""
Historical Data Loader

Loads data from TimescaleDB for backtesting:
1. belief_states — state transitions with timestamps
2. reaction_events — what reaction triggered each transition
3. trade_ticks — price history for measuring outcomes
4. book_bins — order book snapshots for spread/depth estimation

Can also work with CSV exports for offline use.
"""

import os
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)


@dataclass
class BeliefTransition:
    """A single belief state transition with context."""
    ts: datetime
    token_id: str
    old_state: str
    new_state: str
    trigger_reaction_id: Optional[str] = None
    # Filled from reaction_events join
    reaction_type: Optional[str] = None
    reaction_side: Optional[str] = None
    reaction_drop_ratio: Optional[float] = None
    # Price at event time
    price_at_event: Optional[float] = None
    # Price outcomes (filled later)
    price_1m: Optional[float] = None
    price_5m: Optional[float] = None
    price_15m: Optional[float] = None
    price_30m: Optional[float] = None
    price_60m: Optional[float] = None
    # Book context at event time
    bid_depth_usd: Optional[float] = None
    ask_depth_usd: Optional[float] = None
    spread: Optional[float] = None


@dataclass
class TradeRecord:
    """A historical trade."""
    ts: datetime
    token_id: str
    price: float
    size: float
    side: str


@dataclass
class BookSnapshot:
    """A historical book snapshot."""
    ts: datetime
    token_id: str
    bids: List[Tuple[float, float]]  # [(price, size), ...]
    asks: List[Tuple[float, float]]


class HistoricalDataLoader:
    """
    Loads historical data from the database for backtesting.

    Usage:
        loader = HistoricalDataLoader(db_config)
        transitions = loader.load_belief_transitions(days_back=30)
        transitions = loader.enrich_with_prices(transitions)
    """

    def __init__(self, db_config: Optional[Dict] = None):
        """
        Args:
            db_config: Database connection params. If None, reads from env.
        """
        self.db_config = db_config or {
            'host': os.getenv('DB_HOST', '127.0.0.1'),
            'port': int(os.getenv('DB_PORT', '5432')),
            'database': os.getenv('DB_NAME', 'belief_reaction'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', 'postgres'),
        }

    def _get_connection(self):
        """Get a database connection."""
        import psycopg2
        return psycopg2.connect(**self.db_config)

    def load_belief_transitions(
        self,
        days_back: int = 30,
        min_severity: str = "FRAGILE",
        token_id: Optional[str] = None,
    ) -> List[BeliefTransition]:
        """
        Load belief state transitions with reaction context.

        Joins belief_states with reaction_events to get:
        - What state transition occurred
        - What reaction triggered it
        - Which side (bid/ask) the reaction was on
        """
        severity_filter = {
            "FRAGILE": ("'FRAGILE'", "'CRACKING'", "'BROKEN'"),
            "CRACKING": ("'CRACKING'", "'BROKEN'"),
            "BROKEN": ("'BROKEN'",),
        }
        states = severity_filter.get(min_severity, ("'FRAGILE'", "'CRACKING'", "'BROKEN'"))
        states_sql = ", ".join(states)

        query = f"""
        SELECT
            bs.ts,
            bs.token_id,
            bs.old_state,
            bs.new_state,
            bs.trigger_reaction_id,
            COALESCE(bs.reaction_side, re.side) AS reaction_side,
            re.reaction_type,
            re.drop_ratio AS reaction_drop_ratio,
            bs.market_price
        FROM belief_states bs
        LEFT JOIN reaction_events re ON bs.trigger_reaction_id = re.reaction_id
        WHERE bs.ts > NOW() - INTERVAL '{days_back} days'
          AND bs.new_state IN ({states_sql})
          AND bs.old_state != bs.new_state
        """
        if token_id:
            query += f" AND bs.token_id = '{token_id}'"
        query += " ORDER BY bs.ts ASC"

        transitions = []
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(query)
            for row in cur.fetchall():
                transitions.append(BeliefTransition(
                    ts=row[0],
                    token_id=row[1],
                    old_state=row[2],
                    new_state=row[3],
                    trigger_reaction_id=str(row[4]) if row[4] else None,
                    reaction_side=row[5],
                    reaction_type=row[6],
                    reaction_drop_ratio=float(row[7]) if row[7] else None,
                    price_at_event=float(row[8]) if row[8] else None,
                ))
            cur.close()
            conn.close()
            logger.info(f"Loaded {len(transitions)} belief transitions from DB")
        except Exception as e:
            logger.error(f"Failed to load belief transitions: {e}")

        return transitions

    def enrich_with_prices(
        self,
        transitions: List[BeliefTransition],
        horizons_minutes: List[int] = None,
    ) -> List[BeliefTransition]:
        """
        For each transition, look up the price at event time and at
        future horizons (1m, 5m, 15m, 30m, 60m).

        Uses trade_ticks to find the closest trade price.
        """
        if horizons_minutes is None:
            horizons_minutes = [1, 5, 15, 30, 60]

        if not transitions:
            return transitions

        try:
            conn = self._get_connection()
            cur = conn.cursor()

            for t in transitions:
                # Price at event time (closest trade within ±30s)
                cur.execute("""
                    SELECT price FROM trade_ticks
                    WHERE token_id = %s
                      AND ts BETWEEN %s - INTERVAL '30 seconds' AND %s + INTERVAL '30 seconds'
                    ORDER BY ABS(EXTRACT(EPOCH FROM (ts - %s)))
                    LIMIT 1
                """, (t.token_id, t.ts, t.ts, t.ts))
                row = cur.fetchone()
                if row:
                    t.price_at_event = float(row[0])

                # Future prices
                for horizon in horizons_minutes:
                    target_ts = t.ts + timedelta(minutes=horizon)
                    cur.execute("""
                        SELECT price FROM trade_ticks
                        WHERE token_id = %s
                          AND ts BETWEEN %s - INTERVAL '30 seconds' AND %s + INTERVAL '30 seconds'
                        ORDER BY ABS(EXTRACT(EPOCH FROM (ts - %s)))
                        LIMIT 1
                    """, (t.token_id, target_ts, target_ts, target_ts))
                    row = cur.fetchone()
                    if row:
                        price = float(row[0])
                        if horizon == 1:
                            t.price_1m = price
                        elif horizon == 5:
                            t.price_5m = price
                        elif horizon == 15:
                            t.price_15m = price
                        elif horizon == 30:
                            t.price_30m = price
                        elif horizon == 60:
                            t.price_60m = price

            # Book context (spread + depth at event time)
            for t in transitions:
                cur.execute("""
                    SELECT side, price, size
                    FROM book_bins
                    WHERE token_id = %s
                      AND bucket_ts = (
                          SELECT MAX(bucket_ts) FROM book_bins
                          WHERE token_id = %s AND bucket_ts <= %s
                      )
                """, (t.token_id, t.token_id, t.ts))
                rows = cur.fetchall()
                if rows:
                    bids = [(float(r[1]), float(r[2])) for r in rows if r[0] == 'bid']
                    asks = [(float(r[1]), float(r[2])) for r in rows if r[0] == 'ask']
                    bids.sort(key=lambda x: x[0], reverse=True)
                    asks.sort(key=lambda x: x[0])

                    t.bid_depth_usd = sum(p * s for p, s in bids)
                    t.ask_depth_usd = sum(p * s for p, s in asks)
                    if bids and asks:
                        t.spread = asks[0][0] - bids[0][0]

            cur.close()
            conn.close()
            logger.info(f"Enriched {len(transitions)} transitions with price data")

        except Exception as e:
            logger.error(f"Failed to enrich transitions: {e}")

        return transitions

    def load_from_csv(self, filepath: str) -> List[BeliefTransition]:
        """
        Load transitions from a CSV export for offline backtesting.

        Expected columns:
            ts, token_id, old_state, new_state, reaction_type, reaction_side,
            price_at_event, price_1m, price_5m, price_15m, price_30m, price_60m,
            spread, bid_depth_usd, ask_depth_usd
        """
        import csv
        transitions = []
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                t = BeliefTransition(
                    ts=datetime.fromisoformat(row['ts']),
                    token_id=row['token_id'],
                    old_state=row['old_state'],
                    new_state=row['new_state'],
                    reaction_type=row.get('reaction_type'),
                    reaction_side=row.get('reaction_side'),
                )
                for field in ['price_at_event', 'price_1m', 'price_5m',
                              'price_15m', 'price_30m', 'price_60m',
                              'spread', 'bid_depth_usd', 'ask_depth_usd']:
                    val = row.get(field)
                    if val and val != '':
                        setattr(t, field, float(val))
                transitions.append(t)

        logger.info(f"Loaded {len(transitions)} transitions from CSV")
        return transitions

    def export_to_csv(self, transitions: List[BeliefTransition], filepath: str):
        """Export enriched transitions to CSV for offline use."""
        import csv
        fields = [
            'ts', 'token_id', 'old_state', 'new_state',
            'reaction_type', 'reaction_side', 'reaction_drop_ratio',
            'price_at_event', 'price_1m', 'price_5m', 'price_15m',
            'price_30m', 'price_60m', 'spread', 'bid_depth_usd', 'ask_depth_usd',
        ]
        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for t in transitions:
                row = {field: getattr(t, field, None) for field in fields}
                row['ts'] = t.ts.isoformat()
                writer.writerow(row)

        logger.info(f"Exported {len(transitions)} transitions to {filepath}")
