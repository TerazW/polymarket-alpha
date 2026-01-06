"""
Belief Reaction System - v1 API Routes
Implements OpenAPI spec endpoints
"""

from fastapi import APIRouter, Query, HTTPException, WebSocket, WebSocketDisconnect
from typing import Optional, Literal, List
import time
import base64
import psycopg2
from psycopg2.extras import RealDictCursor

# v5.9: WebSocket stream support
from ..stream import (
    stream_manager, parse_subscription_message,
    StreamEventType, StreamMessage, publish_alert
)

from ..schemas.v1 import (
    # Responses
    RadarResponse, RadarRow, MarketSummary, DataHealth, LastCriticalAlert,
    EvidenceResponse, EvidenceWindow, TilesManifest, AnchorLevel,
    ShockEvent, ReactionEvent, ReactionProof, LeadingEvent, PriceBand,
    BeliefStateChange,
    AlertsResponse, Alert,
    ReplayCatalogResponse, ReplayCatalogEntry,
    HeatmapTilesResponse, HeatmapTilesManifest, HeatmapTileMeta,
    TileEncoding, TileCompression, TileChecksum,
    ErrorResponse, EvidenceRef,
    # Enums
    BeliefState, ReactionType, LeadingEventType, AlertSeverity, AlertStatus,
    Side, ShockTrigger, ReactionWindow, TileBand, ReplayCatalogKind,
    # v5.25: Attribution and Explainability
    ReactionAttributionSummary, RadarStateExplanationCompact,
    StateExplanationInfo, ExplainFactor, ExplainFactorType,
    CounterfactualCondition, TrendDirection,
)

# v5.3: Bundle hash computation for evidence verification
from backend.evidence.bundle_hash import compute_bundle_hash

# v5.4: Heatmap tile generation
from backend.heatmap.tile_generator import (
    HeatmapTileGenerator,
    TileBand as GeneratorTileBand,
    tile_to_api_response
)

# v5.25: Attribution and Explainability
from backend.radar.explain import (
    generate_explanation,
    Language as ExplainLanguage,
    STATE_HEADLINES,
)
from backend.common.attribution import (
    compute_attribution,
    AttributionType,
)

router = APIRouter(prefix="/v1", tags=["v1"])

# Database config
DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 5433,
    'database': 'belief_reaction',
    'user': 'postgres',
    'password': 'postgres'
}

STATE_SEVERITY = {
    'STABLE': 0,
    'FRAGILE': 1,
    'CRACKING': 2,
    'BROKEN': 3,
}


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


def ts_to_ms(dt) -> int:
    """Convert datetime to milliseconds since epoch"""
    if dt is None:
        return 0
    return int(dt.timestamp() * 1000)


# =============================================================================
# Health Check
# =============================================================================

@router.get("/health")
def health_check():
    """Health check endpoint"""
    return {"ok": True, "version": "1.0.0"}


@router.get("/health/deep")
async def deep_health_check():
    """
    Deep health check - comprehensive system diagnostics.

    Checks:
    - Database connectivity and performance
    - WebSocket stream manager status
    - Data pipeline freshness
    - Alert queue status
    - Tile generation status

    Returns detailed health report for monitoring systems.
    """
    from backend.monitoring.health import HealthChecker

    checker = HealthChecker(db_config=DB_CONFIG, version="1.0.0")
    report = await checker.run_all_checks()

    return report.to_dict()


# =============================================================================
# Radar API
# =============================================================================

@router.get("/radar", response_model=RadarResponse)
def get_radar(
    event_id: Optional[int] = Query(None, ge=1, description="Filter by event id"),
    tag: Optional[str] = Query(None, description="Optional tag/segment filter"),
    outcome: Optional[Literal["YES", "NO", "BOTH"]] = Query("YES", description="Token outcome filter: YES (default), NO, or BOTH"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort: Literal["fragile_index_10m", "leading_rate_10m", "confidence", "last_critical_ts", "state_severity"] = Query("fragile_index_10m"),
    order: Literal["asc", "desc"] = Query("desc"),
):
    """
    Multi-market radar list for overview sorting.
    Returns markets with belief states and metrics.

    v5.35: Support for both YES and NO token tracking.
    - outcome=YES (default): Only YES tokens
    - outcome=NO: Only NO tokens
    - outcome=BOTH: Both YES and NO tokens (doubles the results per market)
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Build query based on outcome filter
            # v5.35: Support YES, NO, or BOTH token tracking
            if outcome == "BOTH":
                token_select = """
                    SELECT m.yes_token_id as token_id, 'YES' as outcome,
                           m.condition_id, m.question as title, m.slug as market_slug,
                           m.tick_size, m.volume_24h, m.liquidity, m.created_at
                    FROM markets m
                    WHERE m.active = true AND m.closed = false AND m.yes_token_id IS NOT NULL
                    UNION ALL
                    SELECT m.no_token_id as token_id, 'NO' as outcome,
                           m.condition_id, m.question as title, m.slug as market_slug,
                           m.tick_size, m.volume_24h, m.liquidity, m.created_at
                    FROM markets m
                    WHERE m.active = true AND m.closed = false AND m.no_token_id IS NOT NULL
                """
            elif outcome == "NO":
                token_select = """
                    SELECT m.no_token_id as token_id, 'NO' as outcome,
                           m.condition_id, m.question as title, m.slug as market_slug,
                           m.tick_size, m.volume_24h, m.liquidity, m.created_at
                    FROM markets m
                    WHERE m.active = true AND m.closed = false AND m.no_token_id IS NOT NULL
                """
            else:  # YES (default)
                token_select = """
                    SELECT m.yes_token_id as token_id, 'YES' as outcome,
                           m.condition_id, m.question as title, m.slug as market_slug,
                           m.tick_size, m.volume_24h, m.liquidity, m.created_at
                    FROM markets m
                    WHERE m.active = true AND m.closed = false AND m.yes_token_id IS NOT NULL
                """

            # Get markets with latest belief states
            cur.execute(f"""
                WITH latest_states AS (
                    SELECT DISTINCT ON (token_id)
                        token_id,
                        new_state,
                        ts as state_ts
                    FROM belief_states
                    ORDER BY token_id, ts DESC
                ),
                market_tokens AS (
                    {token_select}
                ),
                market_metrics AS (
                    SELECT
                        mt.token_id,
                        mt.outcome,
                        mt.condition_id,
                        mt.title,
                        mt.market_slug,
                        mt.tick_size,
                        mt.volume_24h,
                        mt.liquidity,
                        COALESCE(ls.new_state, 'STABLE') as belief_state,
                        COALESCE(ls.state_ts, mt.created_at) as state_since_ts,
                        -- Count leading events in last 10 min
                        (SELECT COUNT(*) FROM leading_events le
                         WHERE le.token_id = mt.token_id
                         AND le.ts > NOW() - INTERVAL '10 minutes') as leading_count_10m,
                        -- Count reactions in last 10 min
                        (SELECT COUNT(*) FROM reaction_events re
                         WHERE re.token_id = mt.token_id
                         AND re.ts > NOW() - INTERVAL '10 minutes') as reaction_count_10m
                    FROM market_tokens mt
                    LEFT JOIN latest_states ls ON ls.token_id = mt.token_id
                )
                SELECT * FROM market_metrics
                ORDER BY
                    CASE belief_state
                        WHEN 'BROKEN' THEN 0
                        WHEN 'CRACKING' THEN 1
                        WHEN 'FRAGILE' THEN 2
                        ELSE 3
                    END ASC,
                    leading_count_10m DESC
                LIMIT %s OFFSET %s
            """, (limit, offset))

            rows = cur.fetchall()

            # Get total count based on outcome filter (v5.35)
            if outcome == "BOTH":
                cur.execute("""
                    SELECT
                        (SELECT COUNT(*) FROM markets WHERE active = true AND closed = false AND yes_token_id IS NOT NULL) +
                        (SELECT COUNT(*) FROM markets WHERE active = true AND closed = false AND no_token_id IS NOT NULL)
                    as count
                """)
            elif outcome == "NO":
                cur.execute("""
                    SELECT COUNT(*) FROM markets
                    WHERE active = true AND closed = false AND no_token_id IS NOT NULL
                """)
            else:  # YES
                cur.execute("""
                    SELECT COUNT(*) FROM markets
                    WHERE active = true AND closed = false AND yes_token_id IS NOT NULL
                """)
            total = cur.fetchone()['count']

        conn.close()

        # Build response
        radar_rows = []
        for row in rows:
            state = row['belief_state'] or 'STABLE'
            leading_count = float(row['leading_count_10m'] or 0)
            reaction_count = float(row['reaction_count_10m'] or 0)

            # v5.25: Generate compact state explanation
            headline = STATE_HEADLINES.get(state, {}).get('en', 'Unknown state')
            top_factors = []
            if state == 'STABLE':
                top_factors = ['Depth holding well', 'Low fragility signals']
            elif state == 'FRAGILE':
                top_factors = ['Early stress signals detected']
                if leading_count > 2:
                    top_factors.append(f'{int(leading_count)} leading events')
            elif state == 'CRACKING':
                top_factors = ['Significant stress on depth']
                if leading_count > 0:
                    top_factors.append(f'{int(leading_count)} leading events')
            elif state == 'BROKEN':
                top_factors = ['Depth severely compromised']
                if leading_count > 0:
                    top_factors.append(f'{int(leading_count)} vacuum/pull events')

            explanation = RadarStateExplanationCompact(
                headline=headline,
                trend='STABLE',  # Would need historical data for actual trend
                top_factors=top_factors[:3],
            )

            radar_rows.append(RadarRow(
                market=MarketSummary(
                    token_id=row['token_id'] or '',
                    condition_id=row['condition_id'] or '',
                    title=row['title'] or 'Unknown Market',
                    market_slug=row['market_slug'],
                    outcome=row.get('outcome', 'YES'),  # v5.35: Support YES/NO
                    tick_size=float(row['tick_size'] or 0.01),
                    last_price=None,
                ),
                belief_state=BeliefState(state),
                state_since_ts=ts_to_ms(row['state_since_ts']),
                state_severity=STATE_SEVERITY.get(state, 0),
                fragile_index_10m=reaction_count * 0.5 + leading_count * 1.5,
                leading_rate_10m=leading_count,
                # v5.36: Renamed from confidence to evidence_confidence
                evidence_confidence=85.0 if state == 'STABLE' else 70.0 if state == 'FRAGILE' else 50.0,
                data_health=DataHealth(
                    missing_bucket_ratio_10m=0.0,
                    rebuild_count_10m=0,
                    hash_mismatch_count_10m=0,
                ),
                last_critical_alert=None,
                explanation=explanation,
            ))

        return RadarResponse(
            rows=radar_rows,
            limit=limit,
            offset=offset,
            total=total,
        )

    except Exception as e:
        # Return empty response on error
        return RadarResponse(rows=[], limit=limit, offset=offset, total=0)


# =============================================================================
# Evidence API
# =============================================================================

@router.get("/evidence", response_model=EvidenceResponse)
def get_evidence(
    token_id: str = Query(..., min_length=1, description="Token ID"),
    t0: int = Query(..., description="Server timestamp (ms since epoch)"),
    window_before_ms: int = Query(30000, ge=0, le=3600000),
    window_after_ms: int = Query(60000, ge=0, le=3600000),
    include_tiles_manifest: bool = Query(True),
    lod: Literal[250, 1000, 5000] = Query(250, description="Suggested LOD for heatmap tiles"),
):
    """
    Evidence window package for a specific token and anchor time (t0).
    Returns shocks, reactions, leading events, and state changes within the window.
    """
    from_ts = t0 - window_before_ms
    to_ts = t0 + window_after_ms

    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Get market info
            cur.execute("""
                SELECT condition_id, question, slug, tick_size
                FROM markets
                WHERE yes_token_id = %s OR no_token_id = %s
                LIMIT 1
            """, (token_id, token_id))
            market_row = cur.fetchone()

            if not market_row:
                raise HTTPException(status_code=404, detail="Market not found")

            # Get anchor levels
            cur.execute("""
                SELECT price, side, anchor_score, rank
                FROM anchor_levels
                WHERE token_id = %s
                AND ts <= to_timestamp(%s / 1000.0)
                ORDER BY ts DESC, rank ASC
                LIMIT 10
            """, (token_id, t0))
            anchor_rows = cur.fetchall()

            # Get shocks
            cur.execute("""
                SELECT shock_id, ts, price, side, trade_volume, baseline_size, trigger_type
                FROM shock_events
                WHERE token_id = %s
                AND ts BETWEEN to_timestamp(%s / 1000.0) AND to_timestamp(%s / 1000.0)
                ORDER BY ts ASC
            """, (token_id, from_ts, to_ts))
            shock_rows = cur.fetchall()

            # Get reactions
            cur.execute("""
                SELECT reaction_id, shock_id, ts, price, side, reaction_type, window_type,
                       refill_ratio, drop_ratio, vacuum_duration_ms, shift_ticks, time_to_refill_ms
                FROM reaction_events
                WHERE token_id = %s
                AND ts BETWEEN to_timestamp(%s / 1000.0) AND to_timestamp(%s / 1000.0)
                ORDER BY ts ASC
            """, (token_id, from_ts, to_ts))
            reaction_rows = cur.fetchall()

            # Get leading events
            cur.execute("""
                SELECT event_id, ts, event_type, price, side, drop_ratio, duration_ms,
                       trade_volume_nearby, affected_levels
                FROM leading_events
                WHERE token_id = %s
                AND ts BETWEEN to_timestamp(%s / 1000.0) AND to_timestamp(%s / 1000.0)
                ORDER BY ts ASC
            """, (token_id, from_ts, to_ts))
            leading_rows = cur.fetchall()

            # Get belief state changes
            cur.execute("""
                SELECT id, ts, old_state, new_state, trigger_reaction_id, evidence
                FROM belief_states
                WHERE token_id = %s
                AND ts BETWEEN to_timestamp(%s / 1000.0) AND to_timestamp(%s / 1000.0)
                ORDER BY ts ASC
            """, (token_id, from_ts, to_ts))
            state_rows = cur.fetchall()

        conn.close()

        # Build response
        anchors = [
            AnchorLevel(
                price=float(r['price']),
                side=Side.BID if r['side'] == 'bid' else Side.ASK,
                score=float(r['anchor_score'] or 0),
                rank=r['rank'] or 1,
            )
            for r in anchor_rows
        ]

        shocks = [
            ShockEvent(
                id=str(r['shock_id']),
                token_id=token_id,
                ts=ts_to_ms(r['ts']),
                price=float(r['price']),
                side=Side.BID if r['side'] == 'bid' else Side.ASK,
                trade_vol=float(r['trade_volume']) if r['trade_volume'] else None,
                baseline_size=float(r['baseline_size']) if r['baseline_size'] else None,
                tick_size=float(market_row['tick_size'] or 0.01),
                trigger=ShockTrigger(r['trigger_type'].upper()) if r['trigger_type'] else ShockTrigger.VOLUME,
            )
            for r in shock_rows
        ]

        reactions = []
        for r in reaction_rows:
            # v5.25: Compute attribution for reaction
            drop_ratio = float(r['drop_ratio']) if r['drop_ratio'] else 0.0
            refill_ratio = float(r['refill_ratio']) if r['refill_ratio'] else 0.0

            # Estimate attribution from reaction type and proof data
            reaction_type = r['reaction_type']
            if reaction_type in ('VACUUM', 'SWEEP'):
                # Trade-driven reactions
                attr = ReactionAttributionSummary(
                    trade_driven_ratio=0.85,
                    cancel_driven_ratio=0.15,
                    attribution_type='TRADE_DRIVEN',
                )
            elif reaction_type == 'PULL':
                # Cancel-driven reaction
                attr = ReactionAttributionSummary(
                    trade_driven_ratio=0.15,
                    cancel_driven_ratio=0.85,
                    attribution_type='CANCEL_DRIVEN',
                )
            elif reaction_type == 'HOLD':
                # Minimal change
                attr = ReactionAttributionSummary(
                    trade_driven_ratio=0.0,
                    cancel_driven_ratio=0.0,
                    attribution_type='NO_CHANGE',
                )
            else:
                # Mixed or other
                attr = ReactionAttributionSummary(
                    trade_driven_ratio=0.5,
                    cancel_driven_ratio=0.5,
                    attribution_type='MIXED',
                )

            reactions.append(ReactionEvent(
                id=str(r['reaction_id']),
                token_id=token_id,
                shock_id=str(r['shock_id']) if r['shock_id'] else None,
                ts_start=ts_to_ms(r['ts']),
                ts_end=ts_to_ms(r['ts']) + 5000,  # Approximate end
                window=ReactionWindow(r['window_type']) if r['window_type'] else ReactionWindow.SLOW,
                price=float(r['price']),
                side=Side.BID if r['side'] == 'bid' else Side.ASK,
                reaction=ReactionType(reaction_type),
                proof=ReactionProof(
                    drop_ratio=drop_ratio if drop_ratio else None,
                    refill_ratio=refill_ratio if refill_ratio else None,
                    vacuum_duration_ms=r['vacuum_duration_ms'],
                    shift_ticks=r['shift_ticks'],
                    time_to_refill_ms=r['time_to_refill_ms'],
                ),
                attribution=attr,
            ))

        leading_events = [
            LeadingEvent(
                id=str(r['event_id']),
                token_id=token_id,
                ts=ts_to_ms(r['ts']),
                type=LeadingEventType(r['event_type']),
                side=Side.BID if r['side'] == 'bid' else Side.ASK,
                price_band=PriceBand(
                    price_min=float(r['price']) - 0.01,
                    price_max=float(r['price']) + 0.01,
                ),
                proof={
                    'drop_ratio': float(r['drop_ratio']) if r['drop_ratio'] else None,
                    'duration_ms': r['duration_ms'],
                    'trade_volume_nearby': float(r['trade_volume_nearby']) if r['trade_volume_nearby'] else None,
                    'affected_levels': r['affected_levels'],
                },
            )
            for r in leading_rows
        ]

        belief_states = [
            BeliefStateChange(
                id=str(r['id']),
                token_id=token_id,
                ts=ts_to_ms(r['ts']),
                belief_state=BeliefState(r['new_state']),
                evidence_refs=[str(r['trigger_reaction_id'])] if r['trigger_reaction_id'] else [],
                note=None,
            )
            for r in state_rows
        ]

        tiles_manifest = None
        if include_tiles_manifest:
            tiles_manifest = TilesManifest(
                token_id=token_id,
                lod_ms=lod,
                tile_ms=10000,
                band=TileBand.FULL,
                available_from_ts=from_ts,
                available_to_ts=to_ts,
            )

        # v5.3: Compute bundle hash for evidence verification
        bundle_data = {
            'token_id': token_id,
            't0': t0,
            'window': {'from_ts': from_ts, 'to_ts': to_ts},
            'shocks': [s.model_dump() for s in shocks],
            'reactions': [r.model_dump() for r in reactions],
            'leading_events': [e.model_dump() for e in leading_events],
            'belief_states': [b.model_dump() for b in belief_states],
            'anchors': [a.model_dump() for a in anchors],
        }
        bundle_hash = compute_bundle_hash(bundle_data)

        # v5.25: Generate detailed state explanation
        current_state = belief_states[-1].belief_state.value if belief_states else 'STABLE'
        previous_state = belief_states[-2].belief_state.value if len(belief_states) >= 2 else None

        # Count reactions by type for metrics
        hold_count = sum(1 for r in reactions if r.reaction == ReactionType.HOLD)
        vacuum_count = sum(1 for r in reactions if r.reaction == ReactionType.VACUUM)
        pull_count = sum(1 for r in reactions if r.reaction == ReactionType.PULL)
        total_reactions = len(reactions)

        # Build metrics for explanation
        metrics = {
            'hold_ratio': hold_count / max(1, total_reactions),
            'fragile_signals': len(leading_events),
            'vacuum_count': vacuum_count,
            'pull_count': pull_count,
            'depth_collapse_count': sum(1 for le in leading_events if 'COLLAPSE' in str(le.type.value)),
            'pre_shock_pull_count': sum(1 for le in leading_events if 'PRE_SHOCK' in str(le.type.value)),
            'fragility_index': len(leading_events) * 15 + vacuum_count * 25 + pull_count * 10,
            'cancel_driven_ratio': sum(1 for r in reactions if r.attribution and r.attribution.attribution_type == 'CANCEL_DRIVEN') / max(1, total_reactions),
        }

        explanation_obj = generate_explanation(
            token_id=token_id,
            current_state=current_state,
            metrics=metrics,
            previous_state=previous_state,
        )

        # Convert to API schema
        state_explanation = StateExplanationInfo(
            token_id=token_id,
            current_state=current_state,
            classification_confidence=explanation_obj.confidence,
            headline=explanation_obj.headline_en,
            summary=explanation_obj.summary_en,
            positive_factors=[
                ExplainFactor(
                    factor=ExplainFactorType(f.factor_type.value),
                    weight=f.weight,
                    value=f.value,
                    threshold=f.threshold,
                    description={'en': f.description_en, 'cn': f.description_cn},
                )
                for f in explanation_obj.positive_factors
            ],
            negative_factors=[
                ExplainFactor(
                    factor=ExplainFactorType(f.factor_type.value),
                    weight=f.weight,
                    value=f.value,
                    threshold=f.threshold,
                    description={'en': f.description_en, 'cn': f.description_cn},
                )
                for f in explanation_obj.negative_factors
            ],
            trend=TrendDirection(explanation_obj.trend.value),
            trend_reason=explanation_obj.trend_reason_en,
            counterfactuals=[
                CounterfactualCondition(
                    target_state=c.target_state,
                    conditions=c.conditions,
                    likelihood=c.likelihood,
                )
                for c in explanation_obj.counterfactuals
            ],
            generated_at=explanation_obj.generated_at,
            window_minutes=explanation_obj.window_minutes,
        )

        return EvidenceResponse(
            token_id=token_id,
            t0=t0,
            window=EvidenceWindow(from_ts=from_ts, to_ts=to_ts),
            market=MarketSummary(
                token_id=token_id,
                condition_id=market_row['condition_id'],
                title=market_row['question'],
                market_slug=market_row['slug'],
                outcome='YES',
                tick_size=float(market_row['tick_size'] or 0.01),
            ),
            anchors=anchors,
            shocks=shocks,
            reactions=reactions,
            leading_events=leading_events,
            belief_states=belief_states,
            data_health=DataHealth(
                missing_bucket_ratio_10m=0.0,
                rebuild_count_10m=0,
                hash_mismatch_count_10m=0,
            ),
            tiles_manifest=tiles_manifest,
            bundle_hash=bundle_hash,
            state_explanation=state_explanation,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Alerts API
# =============================================================================

@router.get("/alerts", response_model=AlertsResponse)
def get_alerts(
    since: Optional[int] = Query(None, description="Server timestamp (ms)"),
    token_id: Optional[str] = Query(None),
    severity: Optional[AlertSeverity] = Query(None),
    status: Optional[AlertStatus] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    List alerts for ops panel and inbox.
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Build query conditions
            conditions = []
            params = []

            if since:
                conditions.append("ts >= to_timestamp(%s / 1000.0)")
                params.append(since)
            if token_id:
                conditions.append("token_id = %s")
                params.append(token_id)
            if severity:
                conditions.append("severity = %s")
                params.append(severity.value)
            if status:
                conditions.append("status = %s")
                params.append(status.value)

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            # Get alerts
            cur.execute(f"""
                SELECT alert_id, ts, token_id, severity, status, alert_type,
                       summary, confidence, evidence_token, evidence_t0, payload
                FROM alerts
                {where_clause}
                ORDER BY ts DESC
                LIMIT %s OFFSET %s
            """, params + [limit, offset])
            rows = cur.fetchall()

            # Get total
            cur.execute(f"""
                SELECT COUNT(*) FROM alerts {where_clause}
            """, params)
            total = cur.fetchone()['count']

        conn.close()

        alerts = [
            Alert(
                alert_id=str(r['alert_id']),
                token_id=r['token_id'],
                ts=ts_to_ms(r['ts']),
                severity=AlertSeverity(r['severity']),
                status=AlertStatus(r['status']),
                type=r['alert_type'],
                summary=r['summary'],
                confidence=float(r['confidence'] or 80),
                evidence_ref=EvidenceRef(
                    token_id=r['evidence_token'],
                    t0=r['evidence_t0'],
                ),
                payload=r['payload'],
            )
            for r in rows
        ]

        return AlertsResponse(
            rows=alerts,
            limit=limit,
            offset=offset,
            total=total,
        )

    except Exception as e:
        return AlertsResponse(rows=[], limit=limit, offset=offset, total=0)


# =============================================================================
# Replay Catalog API
# =============================================================================

@router.get("/replay/catalog", response_model=ReplayCatalogResponse)
def get_replay_catalog(
    from_ts: int = Query(..., description="Start timestamp (ms)"),
    to_ts: int = Query(..., description="End timestamp (ms)"),
    token_id: Optional[str] = Query(None),
    event_type: Optional[ReplayCatalogKind] = Query(None),
    severity: Optional[AlertSeverity] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    Search historical alerts/events for replay entry.
    Returns a catalog of events that can be used as entry points for replay.
    """
    try:
        conn = get_db_connection()
        entries = []

        with conn.cursor() as cur:
            # Query shocks
            if not event_type or event_type == ReplayCatalogKind.SHOCK:
                token_filter = "AND token_id = %s" if token_id else ""
                params = [from_ts, to_ts]
                if token_id:
                    params.append(token_id)

                cur.execute(f"""
                    SELECT shock_id as id, token_id, ts, price, side, trigger_type
                    FROM shock_events
                    WHERE ts BETWEEN to_timestamp(%s / 1000.0) AND to_timestamp(%s / 1000.0)
                    {token_filter}
                    ORDER BY ts DESC
                    LIMIT %s
                """, params + [limit])

                for r in cur.fetchall():
                    entries.append(ReplayCatalogEntry(
                        kind=ReplayCatalogKind.SHOCK,
                        id=str(r['id']),
                        token_id=r['token_id'],
                        ts=ts_to_ms(r['ts']),
                        label=f"Shock @ {float(r['price'])*100:.0f}% ({r['side']})",
                        evidence_ref=EvidenceRef(token_id=r['token_id'], t0=ts_to_ms(r['ts'])),
                    ))

            # Query reactions
            if not event_type or event_type == ReplayCatalogKind.REACTION:
                token_filter = "AND token_id = %s" if token_id else ""
                params = [from_ts, to_ts]
                if token_id:
                    params.append(token_id)

                cur.execute(f"""
                    SELECT reaction_id as id, token_id, ts, price, reaction_type
                    FROM reaction_events
                    WHERE ts BETWEEN to_timestamp(%s / 1000.0) AND to_timestamp(%s / 1000.0)
                    {token_filter}
                    ORDER BY ts DESC
                    LIMIT %s
                """, params + [limit])

                for r in cur.fetchall():
                    entries.append(ReplayCatalogEntry(
                        kind=ReplayCatalogKind.REACTION,
                        id=str(r['id']),
                        token_id=r['token_id'],
                        ts=ts_to_ms(r['ts']),
                        label=f"{r['reaction_type']} @ {float(r['price'])*100:.0f}%",
                        evidence_ref=EvidenceRef(token_id=r['token_id'], t0=ts_to_ms(r['ts'])),
                    ))

            # Query belief state changes
            if not event_type or event_type == ReplayCatalogKind.BELIEF_STATE:
                token_filter = "AND token_id = %s" if token_id else ""
                params = [from_ts, to_ts]
                if token_id:
                    params.append(token_id)

                cur.execute(f"""
                    SELECT id, token_id, ts, old_state, new_state
                    FROM belief_states
                    WHERE ts BETWEEN to_timestamp(%s / 1000.0) AND to_timestamp(%s / 1000.0)
                    {token_filter}
                    ORDER BY ts DESC
                    LIMIT %s
                """, params + [limit])

                for r in cur.fetchall():
                    entries.append(ReplayCatalogEntry(
                        kind=ReplayCatalogKind.BELIEF_STATE,
                        id=str(r['id']),
                        token_id=r['token_id'],
                        ts=ts_to_ms(r['ts']),
                        label=f"{r['old_state']} -> {r['new_state']}",
                        evidence_ref=EvidenceRef(token_id=r['token_id'], t0=ts_to_ms(r['ts'])),
                    ))

        conn.close()

        # Sort by timestamp and apply pagination
        entries.sort(key=lambda x: x.ts, reverse=True)
        total = len(entries)
        entries = entries[offset:offset + limit]

        return ReplayCatalogResponse(
            rows=entries,
            limit=limit,
            offset=offset,
            total=total,
        )

    except Exception as e:
        return ReplayCatalogResponse(rows=[], limit=limit, offset=offset, total=0)


# =============================================================================
# Heatmap Tiles API
# =============================================================================

@router.get("/heatmap/tiles", response_model=HeatmapTilesResponse)
def get_heatmap_tiles(
    token_id: str = Query(..., min_length=1),
    from_ts: int = Query(..., description="Start timestamp (ms)"),
    to_ts: int = Query(..., description="End timestamp (ms)"),
    lod: Literal[250, 1000, 5000] = Query(250, description="Time resolution in ms per column"),
    tile_ms: Literal[5000, 10000, 15000] = Query(10000),
    price_min: Optional[float] = Query(None),
    price_max: Optional[float] = Query(None),
    band: TileBand = Query(TileBand.FULL),
):
    """
    Fetch heatmap tiles for a token over time range.
    Returns pre-computed tiles or generates on-demand.
    """
    try:
        conn = get_db_connection()
        tiles = []

        with conn.cursor() as cur:
            # Check for pre-computed tiles
            cur.execute("""
                SELECT tile_id, lod_ms, tile_ms, band, t_start, t_end,
                       tick_size, price_min, price_max, rows, cols,
                       encoding_dtype, encoding_layout, encoding_scale,
                       clip_pctl, clip_value, compression_algo, compression_level,
                       payload, checksum_algo, checksum_value
                FROM heatmap_tiles
                WHERE token_id = %s
                AND lod_ms = %s
                AND band = %s
                AND t_start >= %s
                AND t_end <= %s
                ORDER BY t_start ASC
            """, (token_id, lod, band.value, from_ts, to_ts))

            rows = cur.fetchall()

            for r in rows:
                import base64
                tiles.append(HeatmapTileMeta(
                    tile_id=r['tile_id'],
                    token_id=token_id,
                    lod_ms=r['lod_ms'],
                    tile_ms=r['tile_ms'],
                    band=TileBand(r['band']),
                    t_start=r['t_start'],
                    t_end=r['t_end'],
                    tick_size=float(r['tick_size']),
                    price_min=float(r['price_min']),
                    price_max=float(r['price_max']),
                    rows=r['rows'],
                    cols=r['cols'],
                    encoding=TileEncoding(
                        dtype=r['encoding_dtype'],
                        layout=r['encoding_layout'],
                        scale=r['encoding_scale'],
                        clip_pctl=float(r['clip_pctl']),
                        clip_value=float(r['clip_value']) if r['clip_value'] else None,
                    ),
                    compression=TileCompression(
                        algo=r['compression_algo'],
                        level=r['compression_level'],
                    ),
                    payload_b64=base64.b64encode(r['payload']).decode('utf-8'),
                    checksum=TileChecksum(
                        algo=r['checksum_algo'],
                        value=r['checksum_value'],
                    ),
                ))

        conn.close()

        # v5.4: Generate tiles on-demand if not in cache
        if not tiles:
            try:
                generator = HeatmapTileGenerator(db_config=DB_CONFIG)
                generator_band = GeneratorTileBand(band.value)

                generated_tiles = generator.get_or_generate(
                    token_id=token_id,
                    from_ts=from_ts,
                    to_ts=to_ts,
                    lod_ms=lod,
                    tile_ms=tile_ms,
                    band=generator_band,
                    cache=True  # Cache for future requests
                )

                for t in generated_tiles:
                    tiles.append(HeatmapTileMeta(
                        tile_id=t.tile_id,
                        token_id=t.token_id,
                        lod_ms=t.lod_ms,
                        tile_ms=t.tile_ms,
                        band=TileBand(t.band.value),
                        t_start=t.t_start,
                        t_end=t.t_end,
                        tick_size=t.tick_size,
                        price_min=t.price_min,
                        price_max=t.price_max,
                        rows=t.rows,
                        cols=t.cols,
                        encoding=TileEncoding(
                            dtype=t.encoding_dtype,
                            layout=t.encoding_layout,
                            scale=t.encoding_scale,
                            clip_pctl=t.clip_pctl,
                            clip_value=t.clip_value,
                        ),
                        compression=TileCompression(
                            algo=t.compression_algo,
                            level=t.compression_level,
                        ),
                        payload_b64=base64.b64encode(t.payload).decode('utf-8'),
                        checksum=TileChecksum(
                            algo=t.checksum_algo,
                            value=t.checksum_value,
                        ),
                    ))
            except Exception as gen_error:
                print(f"[HEATMAP] Tile generation failed: {gen_error}")

        return HeatmapTilesResponse(
            manifest=HeatmapTilesManifest(
                token_id=token_id,
                from_ts=from_ts,
                to_ts=to_ts,
                lod_ms=lod,
                tile_ms=tile_ms,
                band=band,
            ),
            tiles=tiles,
        )

    except Exception as e:
        return HeatmapTilesResponse(
            manifest=HeatmapTilesManifest(
                token_id=token_id,
                from_ts=from_ts,
                to_ts=to_ts,
                lod_ms=lod,
                tile_ms=tile_ms,
                band=band,
            ),
            tiles=[],
        )


# =============================================================================
# Alert ACK API (v5.9)
# =============================================================================

from pydantic import BaseModel


class AlertAckRequest(BaseModel):
    """Request body for acknowledging an alert"""
    note: Optional[str] = None
    acked_by: Optional[str] = None


class AlertResolveRequest(BaseModel):
    """
    Request body for resolving an alert.

    v5.36: Resolution must include either:
    - System-generated recovery_evidence, OR
    - is_false_positive=True with false_positive_reason
    """
    note: Optional[str] = None
    resolved_by: Optional[str] = None
    # v5.36: False positive tracking
    is_false_positive: bool = False
    false_positive_reason: Optional[str] = None  # Required if is_false_positive=True


class AlertAckResponse(BaseModel):
    """Response for alert acknowledgment"""
    alert_id: str
    status: AlertStatus
    acked_at: int
    acked_by: Optional[str] = None
    note: Optional[str] = None


class AlertResolveResponse(BaseModel):
    """
    Response for alert resolution.

    v5.36: Includes system-generated recovery evidence.
    """
    alert_id: str
    status: AlertStatus
    resolved_at: int
    resolved_by: Optional[str] = None
    note: Optional[str] = None
    # v5.36: System-generated recovery evidence
    recovery_evidence: List[str] = []
    is_false_positive: bool = False
    false_positive_reason: Optional[str] = None


@router.put("/alerts/{alert_id}/ack", response_model=AlertAckResponse)
async def acknowledge_alert(
    alert_id: str,
    body: AlertAckRequest = None,
):
    """
    Acknowledge an alert, changing its status from OPEN to ACKED.

    - **alert_id**: The ID of the alert to acknowledge
    - **note**: Optional note explaining the acknowledgment
    - **acked_by**: Optional identifier of who acknowledged (user/system)
    """
    try:
        conn = get_db_connection()
        acked_at = int(time.time() * 1000)
        note = body.note if body else None
        acked_by = body.acked_by if body else None

        with conn.cursor() as cur:
            # Check if alert exists and is in OPEN state
            cur.execute("""
                SELECT alert_id, status, token_id, severity, summary
                FROM alerts
                WHERE alert_id = %s
            """, (alert_id,))
            row = cur.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

            current_status = row['status']

            if current_status == 'RESOLVED':
                raise HTTPException(
                    status_code=400,
                    detail=f"Alert {alert_id} is already resolved and cannot be acknowledged"
                )

            # Update alert status
            cur.execute("""
                UPDATE alerts
                SET status = 'ACKED',
                    acked_at = to_timestamp(%s / 1000.0),
                    acked_by = %s,
                    ack_note = %s
                WHERE alert_id = %s
                RETURNING alert_id, status
            """, (acked_at, acked_by, note, alert_id))

            conn.commit()

        conn.close()

        # Broadcast alert update via WebSocket
        await publish_alert(
            {
                "alert_id": alert_id,
                "token_id": row['token_id'],
                "status": "ACKED",
                "severity": row['severity'],
                "summary": row['summary'],
                "acked_at": acked_at,
                "acked_by": acked_by,
            },
            event_type=StreamEventType.ALERT_UPDATED
        )

        return AlertAckResponse(
            alert_id=alert_id,
            status=AlertStatus.ACKED,
            acked_at=acked_at,
            acked_by=acked_by,
            note=note,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/alerts/{alert_id}/resolve", response_model=AlertResolveResponse)
async def resolve_alert(
    alert_id: str,
    body: AlertResolveRequest = None,
):
    """
    Resolve an alert, changing its status to RESOLVED.

    v5.36: Resolution must include system-generated recovery evidence.
    The system automatically queries current market state to generate evidence.

    - **alert_id**: The ID of the alert to resolve
    - **note**: Optional note explaining the resolution
    - **resolved_by**: Optional identifier of who resolved (user/system)
    - **is_false_positive**: Mark as false positive (for algorithm improvement)
    - **false_positive_reason**: Required if is_false_positive=True
    """
    try:
        conn = get_db_connection()
        resolved_at = int(time.time() * 1000)
        note = body.note if body else None
        resolved_by = body.resolved_by if body else None
        is_false_positive = body.is_false_positive if body else False
        false_positive_reason = body.false_positive_reason if body else None

        # Validate false positive requires reason
        if is_false_positive and not false_positive_reason:
            raise HTTPException(
                status_code=400,
                detail="false_positive_reason is required when is_false_positive=True"
            )

        with conn.cursor() as cur:
            # Check if alert exists and get details
            cur.execute("""
                SELECT alert_id, status, token_id, severity, summary, alert_type,
                       evidence_token, evidence_t0
                FROM alerts
                WHERE alert_id = %s
            """, (alert_id,))
            row = cur.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

            token_id = row['token_id']
            alert_type = row['alert_type']

            # v5.36: Generate recovery evidence from current state
            recovery_evidence = []

            if not is_false_positive:
                # Query current belief state
                cur.execute("""
                    SELECT new_state, ts
                    FROM belief_states
                    WHERE token_id = %s
                    ORDER BY ts DESC
                    LIMIT 1
                """, (token_id,))
                current_state = cur.fetchone()

                if current_state:
                    state_name = current_state['new_state']
                    state_ts = ts_to_ms(current_state['ts'])
                    recovery_evidence.append(f"Current belief state: {state_name}")
                    recovery_evidence.append(f"State last changed at: {state_ts}")

                    # If recovering to STABLE or FRAGILE, it's a positive sign
                    if state_name in ('STABLE', 'FRAGILE'):
                        recovery_evidence.append(f"State has recovered from alert trigger condition")

                # Query recent reactions (last 10 minutes)
                cur.execute("""
                    SELECT reaction_type, COUNT(*) as cnt
                    FROM reaction_events
                    WHERE token_id = %s
                    AND ts > NOW() - INTERVAL '10 minutes'
                    GROUP BY reaction_type
                """, (token_id,))
                reaction_counts = cur.fetchall()

                if reaction_counts:
                    total = sum(r['cnt'] for r in reaction_counts)
                    hold_count = sum(r['cnt'] for r in reaction_counts if r['reaction_type'] == 'HOLD')
                    if total > 0:
                        hold_ratio = hold_count / total
                        recovery_evidence.append(f"Recent HOLD ratio: {hold_ratio:.1%} ({hold_count}/{total} reactions)")
                        if hold_ratio > 0.5:
                            recovery_evidence.append("Depth defense active (HOLD > 50%)")

                # If no evidence found, require explicit reason
                if not recovery_evidence:
                    recovery_evidence.append("No automatic recovery evidence found - manual resolution")
                    recovery_evidence.append(f"Resolved by: {resolved_by or 'unknown'}")
                    if note:
                        recovery_evidence.append(f"Operator note: {note}")

            else:
                # False positive - record the reason
                recovery_evidence.append(f"Marked as FALSE POSITIVE")
                recovery_evidence.append(f"Reason: {false_positive_reason}")
                if note:
                    recovery_evidence.append(f"Additional note: {note}")

            # Update alert status with recovery evidence
            cur.execute("""
                UPDATE alerts
                SET status = 'RESOLVED',
                    resolved_at = to_timestamp(%s / 1000.0),
                    resolved_by = %s,
                    resolve_note = %s,
                    recovery_evidence = %s,
                    is_false_positive = %s,
                    false_positive_reason = %s
                WHERE alert_id = %s
                RETURNING alert_id, status
            """, (resolved_at, resolved_by, note,
                  recovery_evidence, is_false_positive, false_positive_reason, alert_id))

            conn.commit()

        conn.close()

        # Broadcast alert resolution via WebSocket
        await publish_alert(
            {
                "alert_id": alert_id,
                "token_id": row['token_id'],
                "status": "RESOLVED",
                "severity": row['severity'],
                "summary": row['summary'],
                "resolved_at": resolved_at,
                "resolved_by": resolved_by,
                "recovery_evidence": recovery_evidence,
                "is_false_positive": is_false_positive,
            },
            event_type=StreamEventType.ALERT_RESOLVED
        )

        return AlertResolveResponse(
            alert_id=alert_id,
            status=AlertStatus.RESOLVED,
            resolved_at=resolved_at,
            resolved_by=resolved_by,
            note=note,
            recovery_evidence=recovery_evidence,
            is_false_positive=is_false_positive,
            false_positive_reason=false_positive_reason,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WebSocket Stream API (v5.9)
# =============================================================================

@router.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    """
    Real-time event stream via WebSocket.

    Clients connect and receive events matching their subscription.

    ## Connection Flow:
    1. Connect to ws://host/v1/stream
    2. Receive subscription.confirmed message
    3. Optionally send subscription update:
       ```json
       {
         "action": "subscribe",
         "token_ids": ["token1", "token2"],
         "event_types": ["shock", "alert.new"],
         "min_severity": "HIGH"
       }
       ```
    4. Receive events matching subscription

    ## Event Types:
    - shock: Shock detection events
    - reaction: Reaction classification events
    - leading_event: Leading indicator events
    - belief_state: Belief state changes
    - alert.new: New alerts
    - alert.updated: Alert status changes
    - alert.resolved: Alert resolutions
    - tile.ready: New heatmap tile available
    - data.gap: Data gap warning
    - hash.mismatch: Hash verification failure
    - heartbeat: Connection keepalive (every 30s)
    """
    conn_id = await stream_manager.connect(websocket)

    try:
        while True:
            # Wait for messages from client (subscription updates)
            data = await websocket.receive_text()

            # Parse subscription update
            subscription = parse_subscription_message(data)
            if subscription:
                await stream_manager.update_subscription(conn_id, subscription)
            else:
                # Unknown message, send error
                await websocket.send_text(StreamMessage(
                    type=StreamEventType.ERROR,
                    payload={"message": "Invalid message format", "received": data[:100]}
                ).to_json())

    except WebSocketDisconnect:
        await stream_manager.disconnect(conn_id)
    except Exception as e:
        print(f"[STREAM] Error in connection {conn_id}: {e}")
        await stream_manager.disconnect(conn_id)
