"""
Events API Routes (v5.35)

Event-level aggregation for multi-market events.

In Polymarket, an event can contain multiple markets. For example:
- "Who will be nominated?" event has many candidate markets
- "Super Bowl Champion?" event has many team markets

This API provides event-level views that aggregate across all markets
within an event.
"""

from typing import List, Optional, Literal
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
import psycopg2
from psycopg2.extras import RealDictCursor
import os

from ..schemas.v1 import BeliefState, MarketSummary, DataHealth

router = APIRouter(prefix="/events", tags=["events"])

# Database config
DB_CONFIG = {
    'host': os.getenv('DB_HOST', '127.0.0.1'),
    'port': int(os.getenv('DB_PORT', '5433')),
    'database': os.getenv('DB_NAME', 'belief_reaction'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'postgres'),
}


# =============================================================================
# Response Models
# =============================================================================

class EventSummary(BaseModel):
    """Summary of an event with multiple markets"""
    event_id: str
    event_slug: Optional[str]
    event_title: str
    market_count: int
    token_count: int
    total_volume_24h: Optional[float]
    total_liquidity: Optional[float]
    active_markets: int
    closed_markets: int


class EventBeliefState(BaseModel):
    """Aggregated belief state for an event"""
    event_id: str
    event_title: Optional[str]
    market_count: int
    worst_state: BeliefState
    broken_count: int = 0
    cracking_count: int = 0
    fragile_count: int = 0
    stable_count: int = 0


class EventMarket(BaseModel):
    """Market within an event"""
    condition_id: str
    question: str
    yes_token_id: str
    no_token_id: str
    outcome_label: Optional[str] = None  # e.g., "Joe Biden", "Team A"
    yes_state: BeliefState
    no_state: BeliefState
    worst_state: BeliefState
    volume_24h: Optional[float]


class EventDetailResponse(BaseModel):
    """Detailed event information with all markets"""
    event_id: str
    event_slug: Optional[str]
    event_title: str
    market_count: int
    worst_state: BeliefState
    markets: List[EventMarket]
    state_distribution: dict  # {STABLE: n, FRAGILE: n, CRACKING: n, BROKEN: n}


class EventsListResponse(BaseModel):
    """List of events"""
    events: List[EventSummary]
    total: int
    limit: int
    offset: int


class EventRadarResponse(BaseModel):
    """Event-level radar (similar to market radar but aggregated)"""
    events: List[EventBeliefState]
    total: int
    limit: int
    offset: int


# =============================================================================
# Helper Functions
# =============================================================================

def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


def get_worst_state(yes_state: str, no_state: str) -> str:
    """Determine worst belief state between YES and NO"""
    severity = {'BROKEN': 3, 'CRACKING': 2, 'FRAGILE': 1, 'STABLE': 0}
    yes_sev = severity.get(yes_state, 0)
    no_sev = severity.get(no_state, 0)
    return yes_state if yes_sev >= no_sev else no_state


# =============================================================================
# API Endpoints
# =============================================================================

@router.get("/", response_model=EventsListResponse)
def list_events(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: Literal["volume", "markets", "title"] = Query("volume"),
    active_only: bool = Query(True, description="Only events with active markets"),
):
    """
    List all events.

    Returns events sorted by total volume, market count, or title.
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Build query
            having_clause = "HAVING COUNT(CASE WHEN m.active = true AND m.closed = false THEN 1 END) > 0" if active_only else ""

            order_by = {
                "volume": "total_volume_24h DESC NULLS LAST",
                "markets": "market_count DESC",
                "title": "event_title ASC",
            }.get(sort, "total_volume_24h DESC NULLS LAST")

            cur.execute(f"""
                SELECT
                    m.event_id,
                    m.event_slug,
                    COALESCE(m.event_title, m.question) as event_title,
                    COUNT(*) as market_count,
                    COUNT(DISTINCT m.yes_token_id) + COUNT(DISTINCT m.no_token_id) as token_count,
                    SUM(m.volume_24h) as total_volume_24h,
                    SUM(m.liquidity) as total_liquidity,
                    COUNT(CASE WHEN m.active = true AND m.closed = false THEN 1 END) as active_markets,
                    COUNT(CASE WHEN m.closed = true THEN 1 END) as closed_markets
                FROM markets m
                WHERE m.event_id IS NOT NULL
                GROUP BY m.event_id, m.event_slug, event_title
                {having_clause}
                ORDER BY {order_by}
                LIMIT %s OFFSET %s
            """, (limit, offset))

            rows = cur.fetchall()

            # Get total count
            cur.execute(f"""
                SELECT COUNT(DISTINCT event_id) as count
                FROM markets
                WHERE event_id IS NOT NULL
                {"AND active = true AND closed = false" if active_only else ""}
            """)
            total = cur.fetchone()['count']

        conn.close()

        events = [
            EventSummary(
                event_id=r['event_id'],
                event_slug=r['event_slug'],
                event_title=r['event_title'] or 'Unknown Event',
                market_count=r['market_count'],
                token_count=r['token_count'],
                total_volume_24h=float(r['total_volume_24h']) if r['total_volume_24h'] else None,
                total_liquidity=float(r['total_liquidity']) if r['total_liquidity'] else None,
                active_markets=r['active_markets'],
                closed_markets=r['closed_markets'],
            )
            for r in rows
        ]

        return EventsListResponse(
            events=events,
            total=total,
            limit=limit,
            offset=offset,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/radar", response_model=EventRadarResponse)
def event_radar(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Event-level radar showing aggregated belief states.

    Groups markets by event and shows the worst state within each event.
    Useful for monitoring large multi-market events.
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                WITH latest_states AS (
                    SELECT DISTINCT ON (token_id)
                        token_id,
                        new_state,
                        ts as state_ts
                    FROM belief_states
                    ORDER BY token_id, ts DESC
                ),
                market_states AS (
                    SELECT
                        m.event_id,
                        m.event_title,
                        m.yes_token_id,
                        m.no_token_id,
                        COALESCE(ls_yes.new_state, 'STABLE') as yes_state,
                        COALESCE(ls_no.new_state, 'STABLE') as no_state
                    FROM markets m
                    LEFT JOIN latest_states ls_yes ON ls_yes.token_id = m.yes_token_id
                    LEFT JOIN latest_states ls_no ON ls_no.token_id = m.no_token_id
                    WHERE m.event_id IS NOT NULL
                      AND m.active = true
                      AND m.closed = false
                ),
                event_agg AS (
                    SELECT
                        event_id,
                        MAX(event_title) as event_title,
                        COUNT(*) as market_count,
                        COUNT(CASE WHEN yes_state = 'BROKEN' OR no_state = 'BROKEN' THEN 1 END) as broken_count,
                        COUNT(CASE WHEN yes_state = 'CRACKING' OR no_state = 'CRACKING' THEN 1 END) as cracking_count,
                        COUNT(CASE WHEN yes_state = 'FRAGILE' OR no_state = 'FRAGILE' THEN 1 END) as fragile_count,
                        COUNT(CASE WHEN yes_state = 'STABLE' AND no_state = 'STABLE' THEN 1 END) as stable_count
                    FROM market_states
                    GROUP BY event_id
                )
                SELECT *,
                    CASE
                        WHEN broken_count > 0 THEN 'BROKEN'
                        WHEN cracking_count > 0 THEN 'CRACKING'
                        WHEN fragile_count > 0 THEN 'FRAGILE'
                        ELSE 'STABLE'
                    END as worst_state
                FROM event_agg
                ORDER BY
                    CASE
                        WHEN broken_count > 0 THEN 0
                        WHEN cracking_count > 0 THEN 1
                        WHEN fragile_count > 0 THEN 2
                        ELSE 3
                    END ASC,
                    broken_count + cracking_count + fragile_count DESC
                LIMIT %s OFFSET %s
            """, (limit, offset))

            rows = cur.fetchall()

            # Get total
            cur.execute("""
                SELECT COUNT(DISTINCT event_id) as count
                FROM markets
                WHERE event_id IS NOT NULL
                AND active = true AND closed = false
            """)
            total = cur.fetchone()['count']

        conn.close()

        events = [
            EventBeliefState(
                event_id=r['event_id'],
                event_title=r['event_title'],
                market_count=r['market_count'],
                worst_state=BeliefState(r['worst_state']),
                broken_count=r['broken_count'],
                cracking_count=r['cracking_count'],
                fragile_count=r['fragile_count'],
                stable_count=r['stable_count'],
            )
            for r in rows
        ]

        return EventRadarResponse(
            events=events,
            total=total,
            limit=limit,
            offset=offset,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Cross-Market Correlation Analysis
# =============================================================================

class MarketCorrelation(BaseModel):
    """Correlation between two markets"""
    market_a_id: str
    market_a_question: str
    market_b_id: str
    market_b_question: str
    correlation_type: str  # "INVERSE", "POSITIVE", "NEUTRAL"
    confidence: float = Field(..., ge=0, le=100)
    evidence_count: int
    description: str


class EventCorrelationResponse(BaseModel):
    """Cross-market correlation analysis for an event"""
    event_id: str
    event_title: str
    market_count: int
    correlations: List[MarketCorrelation]
    summary: str


class ReactionSyncEvent(BaseModel):
    """Synchronized reactions across markets"""
    ts: int
    affected_markets: int
    dominant_reaction: str
    markets: List[dict]


class EventReactionSyncResponse(BaseModel):
    """Synchronized reaction events across markets in an event"""
    event_id: str
    event_title: str
    sync_events: List[ReactionSyncEvent]
    total_sync_events: int
    sync_rate: float  # Percentage of reactions that are synchronized


@router.get("/{event_id}/correlation", response_model=EventCorrelationResponse)
def get_event_correlation(
    event_id: str,
    window_minutes: int = Query(60, ge=10, le=1440, description="Analysis window in minutes"),
):
    """
    Cross-market correlation analysis within an event.

    Analyzes how markets within the same event correlate:
    - INVERSE: When market A goes FRAGILE/BROKEN, market B tends to go STABLE (zero-sum)
    - POSITIVE: Markets move together (systemic event)
    - NEUTRAL: No significant correlation

    Useful for:
    - Detecting zero-sum dynamics (nomination races)
    - Identifying systemic events affecting all markets
    - Finding related market movements
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Get event info
            cur.execute("""
                SELECT event_id, event_slug, COALESCE(event_title, question) as event_title
                FROM markets WHERE event_id = %s LIMIT 1
            """, (event_id,))
            event_row = cur.fetchone()

            if not event_row:
                raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

            # Get all markets in event with their reaction history
            cur.execute("""
                SELECT
                    m.condition_id,
                    m.question,
                    m.yes_token_id,
                    m.no_token_id
                FROM markets m
                WHERE m.event_id = %s
                AND m.active = true AND m.closed = false
            """, (event_id,))
            markets = cur.fetchall()

            if len(markets) < 2:
                return EventCorrelationResponse(
                    event_id=event_id,
                    event_title=event_row['event_title'],
                    market_count=len(markets),
                    correlations=[],
                    summary="Not enough markets for correlation analysis (need at least 2).",
                )

            # Get state changes for all tokens in the time window
            all_token_ids = []
            market_tokens = {}
            for m in markets:
                all_token_ids.extend([m['yes_token_id'], m['no_token_id']])
                market_tokens[m['yes_token_id']] = m['condition_id']
                market_tokens[m['no_token_id']] = m['condition_id']

            cur.execute("""
                SELECT
                    token_id,
                    old_state,
                    new_state,
                    ts
                FROM belief_states
                WHERE token_id = ANY(%s)
                AND ts > NOW() - INTERVAL '%s minutes'
                ORDER BY ts ASC
            """, (all_token_ids, window_minutes))

            state_changes = cur.fetchall()

        conn.close()

        # Analyze correlations between market pairs
        correlations = []
        market_states = {m['condition_id']: {'changes': [], 'question': m['question']} for m in markets}

        # Group state changes by market
        for sc in state_changes:
            market_id = market_tokens.get(sc['token_id'])
            if market_id:
                market_states[market_id]['changes'].append({
                    'ts': sc['ts'],
                    'old_state': sc['old_state'],
                    'new_state': sc['new_state'],
                    'token_id': sc['token_id'],
                })

        # Compare each pair of markets
        market_list = list(market_states.keys())
        for i, market_a in enumerate(market_list):
            for market_b in market_list[i+1:]:
                changes_a = market_states[market_a]['changes']
                changes_b = market_states[market_b]['changes']

                if not changes_a or not changes_b:
                    continue

                # Look for temporally close state changes
                inverse_count = 0
                positive_count = 0
                total_pairs = 0

                for ca in changes_a:
                    for cb in changes_b:
                        # Check if within 5 minutes of each other
                        time_diff_ms = abs((ca['ts'] - cb['ts']).total_seconds() * 1000)
                        if time_diff_ms < 300000:  # 5 minutes
                            total_pairs += 1

                            # Check correlation direction
                            severity_map = {'STABLE': 0, 'FRAGILE': 1, 'CRACKING': 2, 'BROKEN': 3}
                            delta_a = severity_map.get(ca['new_state'], 0) - severity_map.get(ca['old_state'], 0)
                            delta_b = severity_map.get(cb['new_state'], 0) - severity_map.get(cb['old_state'], 0)

                            if delta_a * delta_b < 0:  # Opposite directions
                                inverse_count += 1
                            elif delta_a * delta_b > 0:  # Same direction
                                positive_count += 1

                if total_pairs > 0:
                    inverse_ratio = inverse_count / total_pairs
                    positive_ratio = positive_count / total_pairs

                    if inverse_ratio > 0.6:
                        corr_type = "INVERSE"
                        confidence = min(100, inverse_ratio * 100 + total_pairs * 5)
                        desc = f"Markets tend to move in opposite directions (zero-sum dynamic)"
                    elif positive_ratio > 0.6:
                        corr_type = "POSITIVE"
                        confidence = min(100, positive_ratio * 100 + total_pairs * 5)
                        desc = f"Markets tend to move together (systemic correlation)"
                    else:
                        corr_type = "NEUTRAL"
                        confidence = 50
                        desc = "No strong correlation detected"

                    correlations.append(MarketCorrelation(
                        market_a_id=market_a,
                        market_a_question=market_states[market_a]['question'],
                        market_b_id=market_b,
                        market_b_question=market_states[market_b]['question'],
                        correlation_type=corr_type,
                        confidence=confidence,
                        evidence_count=total_pairs,
                        description=desc,
                    ))

        # Generate summary
        inverse_count = sum(1 for c in correlations if c.correlation_type == "INVERSE")
        positive_count = sum(1 for c in correlations if c.correlation_type == "POSITIVE")

        if inverse_count > positive_count and inverse_count > 0:
            summary = f"Zero-sum dynamics detected: {inverse_count} market pairs show inverse correlation. " \
                     f"This suggests a competitive event where one market's gain is another's loss."
        elif positive_count > 0:
            summary = f"Systemic correlation detected: {positive_count} market pairs move together. " \
                     f"This suggests external factors affecting all markets simultaneously."
        else:
            summary = "No significant cross-market correlations detected in the analysis window."

        return EventCorrelationResponse(
            event_id=event_id,
            event_title=event_row['event_title'],
            market_count=len(markets),
            correlations=correlations,
            summary=summary,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{event_id}/sync", response_model=EventReactionSyncResponse)
def get_reaction_sync(
    event_id: str,
    window_minutes: int = Query(60, ge=10, le=1440),
    sync_threshold_ms: int = Query(60000, ge=1000, le=300000, description="Time window to consider reactions synchronized"),
):
    """
    Detect synchronized reactions across markets in an event.

    Identifies moments where multiple markets experienced reactions
    within a short time window, suggesting correlated market movements.
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Get event info
            cur.execute("""
                SELECT event_id, COALESCE(event_title, question) as event_title
                FROM markets WHERE event_id = %s LIMIT 1
            """, (event_id,))
            event_row = cur.fetchone()

            if not event_row:
                raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

            # Get all token IDs in event
            cur.execute("""
                SELECT yes_token_id, no_token_id, question
                FROM markets
                WHERE event_id = %s AND active = true AND closed = false
            """, (event_id,))
            markets = cur.fetchall()

            token_to_question = {}
            all_tokens = []
            for m in markets:
                all_tokens.extend([m['yes_token_id'], m['no_token_id']])
                token_to_question[m['yes_token_id']] = m['question'] + " (YES)"
                token_to_question[m['no_token_id']] = m['question'] + " (NO)"

            # Get recent reactions
            cur.execute("""
                SELECT
                    token_id,
                    reaction_type,
                    ts,
                    price,
                    side
                FROM reaction_events
                WHERE token_id = ANY(%s)
                AND ts > NOW() - INTERVAL '%s minutes'
                ORDER BY ts ASC
            """, (all_tokens, window_minutes))

            reactions = cur.fetchall()

        conn.close()

        # Group reactions into synchronized events
        sync_events = []
        total_reactions = len(reactions)
        synced_reactions = 0

        if reactions:
            # Use sliding window to find synchronized reactions
            i = 0
            while i < len(reactions):
                window_start = reactions[i]['ts']
                window_reactions = [reactions[i]]

                # Find all reactions within sync threshold
                j = i + 1
                while j < len(reactions):
                    time_diff = (reactions[j]['ts'] - window_start).total_seconds() * 1000
                    if time_diff <= sync_threshold_ms:
                        window_reactions.append(reactions[j])
                        j += 1
                    else:
                        break

                # If multiple markets affected, it's a sync event
                unique_tokens = set(r['token_id'] for r in window_reactions)
                if len(unique_tokens) >= 2:
                    # Count reaction types
                    type_counts = {}
                    for r in window_reactions:
                        rt = r['reaction_type']
                        type_counts[rt] = type_counts.get(rt, 0) + 1

                    dominant = max(type_counts.items(), key=lambda x: x[1])[0]

                    sync_events.append(ReactionSyncEvent(
                        ts=int(window_start.timestamp() * 1000),
                        affected_markets=len(unique_tokens),
                        dominant_reaction=dominant,
                        markets=[
                            {
                                "token_id": r['token_id'],
                                "question": token_to_question.get(r['token_id'], 'Unknown'),
                                "reaction_type": r['reaction_type'],
                                "price": float(r['price']) if r['price'] else None,
                            }
                            for r in window_reactions
                        ],
                    ))
                    synced_reactions += len(window_reactions)
                    i = j  # Skip processed reactions
                else:
                    i += 1

        sync_rate = (synced_reactions / total_reactions * 100) if total_reactions > 0 else 0

        return EventReactionSyncResponse(
            event_id=event_id,
            event_title=event_row['event_title'],
            sync_events=sync_events,
            total_sync_events=len(sync_events),
            sync_rate=sync_rate,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{event_id}", response_model=EventDetailResponse)
def get_event_detail(
    event_id: str,
    include_closed: bool = Query(False, description="Include closed markets"),
):
    """
    Get detailed event information with all markets.

    Shows all markets within an event, their individual belief states,
    and the overall event state.
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Get event metadata
            cur.execute("""
                SELECT
                    event_id,
                    event_slug,
                    COALESCE(event_title, question) as event_title
                FROM markets
                WHERE event_id = %s
                LIMIT 1
            """, (event_id,))

            event_row = cur.fetchone()
            if not event_row:
                raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

            # Get markets with belief states
            closed_filter = "" if include_closed else "AND m.closed = false"

            cur.execute(f"""
                WITH latest_states AS (
                    SELECT DISTINCT ON (token_id)
                        token_id,
                        new_state,
                        ts as state_ts
                    FROM belief_states
                    ORDER BY token_id, ts DESC
                )
                SELECT
                    m.condition_id,
                    m.question,
                    m.yes_token_id,
                    m.no_token_id,
                    m.volume_24h,
                    COALESCE(ls_yes.new_state, 'STABLE') as yes_state,
                    COALESCE(ls_no.new_state, 'STABLE') as no_state
                FROM markets m
                LEFT JOIN latest_states ls_yes ON ls_yes.token_id = m.yes_token_id
                LEFT JOIN latest_states ls_no ON ls_no.token_id = m.no_token_id
                WHERE m.event_id = %s
                AND m.active = true
                {closed_filter}
                ORDER BY m.volume_24h DESC NULLS LAST
            """, (event_id,))

            market_rows = cur.fetchall()

        conn.close()

        # Build markets list
        markets = []
        state_counts = {'STABLE': 0, 'FRAGILE': 0, 'CRACKING': 0, 'BROKEN': 0}

        for r in market_rows:
            yes_state = r['yes_state']
            no_state = r['no_state']
            worst = get_worst_state(yes_state, no_state)

            # Count worst state
            state_counts[worst] = state_counts.get(worst, 0) + 1

            # Extract outcome label from question (e.g., "Will Joe Biden win?" -> "Joe Biden")
            question = r['question'] or ''
            outcome_label = question  # Default to full question

            markets.append(EventMarket(
                condition_id=r['condition_id'],
                question=question,
                yes_token_id=r['yes_token_id'],
                no_token_id=r['no_token_id'],
                outcome_label=outcome_label,
                yes_state=BeliefState(yes_state),
                no_state=BeliefState(no_state),
                worst_state=BeliefState(worst),
                volume_24h=float(r['volume_24h']) if r['volume_24h'] else None,
            ))

        # Determine overall worst state
        if state_counts['BROKEN'] > 0:
            overall_worst = BeliefState.BROKEN
        elif state_counts['CRACKING'] > 0:
            overall_worst = BeliefState.CRACKING
        elif state_counts['FRAGILE'] > 0:
            overall_worst = BeliefState.FRAGILE
        else:
            overall_worst = BeliefState.STABLE

        return EventDetailResponse(
            event_id=event_row['event_id'],
            event_slug=event_row['event_slug'],
            event_title=event_row['event_title'] or 'Unknown Event',
            market_count=len(markets),
            worst_state=overall_worst,
            markets=markets,
            state_distribution=state_counts,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Multi-Market Comparison API (v5.36)
# =============================================================================

class MarketTimePoint(BaseModel):
    """Single time point for a market in comparison view"""
    ts: int
    belief_state: str
    reaction_type: Optional[str] = None
    price: Optional[float] = None
    side: Optional[str] = None


class MarketTimeSeries(BaseModel):
    """Time series data for one market"""
    token_id: str
    question: str
    outcome: str
    points: List[MarketTimePoint]
    state_changes: int = 0
    reaction_count: int = 0


class EventComparisonResponse(BaseModel):
    """
    Multi-market comparison with synchronized time axes.

    v5.36: Per expert review - "为什么 A 崩了，B 没崩？"
    Provides side-by-side comparison of market behaviors.
    """
    event_id: str
    event_title: str
    from_ts: int
    to_ts: int
    window_minutes: int
    markets: List[MarketTimeSeries]
    # Summary
    divergence_detected: bool = Field(..., description="True if markets showed divergent behavior")
    divergence_description: Optional[str] = None


@router.get("/{event_id}/compare", response_model=EventComparisonResponse)
def get_event_comparison(
    event_id: str,
    window_minutes: int = Query(60, ge=10, le=1440, description="Time window in minutes"),
    bucket_ms: int = Query(60000, ge=10000, le=300000, description="Time bucket size in ms"),
):
    """
    Get synchronized multi-market comparison for an event.

    v5.36: Per expert review - enables side-by-side analysis.
    Core question answered: "为什么 A 崩了，B 没崩？"

    Returns parallel time series for all markets in the event,
    aligned to the same time axis for direct comparison.
    """
    try:
        conn = get_db_connection()
        market_series = []

        with conn.cursor() as cur:
            # Get event info
            cur.execute("""
                SELECT event_id, COALESCE(event_title, question) as event_title
                FROM markets WHERE event_id = %s LIMIT 1
            """, (event_id,))
            event_row = cur.fetchone()

            if not event_row:
                raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

            # Get all markets in event
            cur.execute("""
                SELECT yes_token_id, no_token_id, question
                FROM markets
                WHERE event_id = %s AND active = true AND closed = false
            """, (event_id,))
            markets = cur.fetchall()

            if not markets:
                raise HTTPException(status_code=404, detail=f"No active markets in event {event_id}")

            # Calculate time range
            to_ts_dt = "NOW()"
            from_ts_dt = f"NOW() - INTERVAL '{window_minutes} minutes'"

            # For each market, get state changes and reactions
            for m in markets:
                for outcome, token_id in [('YES', m['yes_token_id']), ('NO', m['no_token_id'])]:
                    if not token_id:
                        continue

                    points = []

                    # Get state changes
                    cur.execute("""
                        SELECT ts, new_state
                        FROM belief_states
                        WHERE token_id = %s
                        AND ts > """ + from_ts_dt + """
                        ORDER BY ts ASC
                    """, (token_id,))
                    state_changes = cur.fetchall()

                    state_change_count = len(state_changes)

                    for sc in state_changes:
                        points.append(MarketTimePoint(
                            ts=int(sc['ts'].timestamp() * 1000),
                            belief_state=sc['new_state'],
                            reaction_type=None,
                        ))

                    # Get reactions
                    cur.execute("""
                        SELECT ts, reaction_type, price, side
                        FROM reaction_events
                        WHERE token_id = %s
                        AND ts > """ + from_ts_dt + """
                        ORDER BY ts ASC
                    """, (token_id,))
                    reactions = cur.fetchall()

                    reaction_count = len(reactions)

                    for r in reactions:
                        points.append(MarketTimePoint(
                            ts=int(r['ts'].timestamp() * 1000),
                            belief_state="",  # Will be filled from state context
                            reaction_type=r['reaction_type'],
                            price=float(r['price']) if r['price'] else None,
                            side=r['side'],
                        ))

                    # Sort by timestamp
                    points.sort(key=lambda p: p.ts)

                    # Get current state
                    cur.execute("""
                        SELECT new_state FROM belief_states
                        WHERE token_id = %s
                        ORDER BY ts DESC LIMIT 1
                    """, (token_id,))
                    current_state_row = cur.fetchone()
                    current_state = current_state_row['new_state'] if current_state_row else 'STABLE'

                    # Fill in belief_state for reaction points (carry forward)
                    last_state = current_state
                    for i, p in enumerate(points):
                        if p.belief_state:
                            last_state = p.belief_state
                        else:
                            points[i] = MarketTimePoint(
                                ts=p.ts,
                                belief_state=last_state,
                                reaction_type=p.reaction_type,
                                price=p.price,
                                side=p.side,
                            )

                    market_series.append(MarketTimeSeries(
                        token_id=token_id,
                        question=m['question'],
                        outcome=outcome,
                        points=points,
                        state_changes=state_change_count,
                        reaction_count=reaction_count,
                    ))

        conn.close()

        # Calculate time range
        import time
        to_ts = int(time.time() * 1000)
        from_ts = to_ts - (window_minutes * 60 * 1000)

        # Detect divergence
        divergence = False
        divergence_desc = None

        # Check if any market has BROKEN/CRACKING while others are STABLE
        broken_markets = [m for m in market_series if any(p.belief_state in ('BROKEN', 'CRACKING') for p in m.points)]
        stable_markets = [m for m in market_series if all(p.belief_state == 'STABLE' for p in m.points) or not m.points]

        if broken_markets and stable_markets:
            divergence = True
            broken_names = [f"{m.question} ({m.outcome})" for m in broken_markets[:3]]
            stable_names = [f"{m.question} ({m.outcome})" for m in stable_markets[:3]]
            divergence_desc = (
                f"Divergent behavior detected: {', '.join(broken_names)} showed stress "
                f"while {', '.join(stable_names)} remained stable. "
                f"This suggests market-specific factors rather than event-wide dynamics."
            )

        return EventComparisonResponse(
            event_id=event_id,
            event_title=event_row['event_title'],
            from_ts=from_ts,
            to_ts=to_ts,
            window_minutes=window_minutes,
            markets=market_series,
            divergence_detected=divergence,
            divergence_description=divergence_desc,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
