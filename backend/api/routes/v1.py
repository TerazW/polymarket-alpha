"""
Belief Reaction System - v1 API Routes
Implements OpenAPI spec endpoints
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional, Literal
import time
import psycopg2
from psycopg2.extras import RealDictCursor

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


# =============================================================================
# Radar API
# =============================================================================

@router.get("/radar", response_model=RadarResponse)
def get_radar(
    event_id: Optional[int] = Query(None, ge=1, description="Filter by event id"),
    tag: Optional[str] = Query(None, description="Optional tag/segment filter"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort: Literal["fragile_index_10m", "leading_rate_10m", "confidence", "last_critical_ts", "state_severity"] = Query("fragile_index_10m"),
    order: Literal["asc", "desc"] = Query("desc"),
):
    """
    Multi-market radar list for overview sorting.
    Returns markets with belief states and metrics.
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Get markets with latest belief states
            cur.execute("""
                WITH latest_states AS (
                    SELECT DISTINCT ON (token_id)
                        token_id,
                        new_state,
                        ts as state_ts
                    FROM belief_states
                    ORDER BY token_id, ts DESC
                ),
                market_metrics AS (
                    SELECT
                        m.yes_token_id as token_id,
                        m.condition_id,
                        m.question as title,
                        m.slug as market_slug,
                        m.tick_size,
                        m.volume_24h,
                        m.liquidity,
                        COALESCE(ls.new_state, 'STABLE') as belief_state,
                        COALESCE(ls.state_ts, m.created_at) as state_since_ts,
                        -- Count leading events in last 10 min
                        (SELECT COUNT(*) FROM leading_events le
                         WHERE le.token_id = m.yes_token_id
                         AND le.ts > NOW() - INTERVAL '10 minutes') as leading_count_10m,
                        -- Count reactions in last 10 min
                        (SELECT COUNT(*) FROM reaction_events re
                         WHERE re.token_id = m.yes_token_id
                         AND re.ts > NOW() - INTERVAL '10 minutes') as reaction_count_10m
                    FROM markets m
                    LEFT JOIN latest_states ls ON ls.token_id = m.yes_token_id
                    WHERE m.active = true AND m.closed = false
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

            # Get total count
            cur.execute("""
                SELECT COUNT(*) FROM markets
                WHERE active = true AND closed = false
            """)
            total = cur.fetchone()['count']

        conn.close()

        # Build response
        radar_rows = []
        for row in rows:
            state = row['belief_state'] or 'STABLE'
            radar_rows.append(RadarRow(
                market=MarketSummary(
                    token_id=row['token_id'] or '',
                    condition_id=row['condition_id'] or '',
                    title=row['title'] or 'Unknown Market',
                    market_slug=row['market_slug'],
                    outcome='YES',
                    tick_size=float(row['tick_size'] or 0.01),
                    last_price=None,
                ),
                belief_state=BeliefState(state),
                state_since_ts=ts_to_ms(row['state_since_ts']),
                state_severity=STATE_SEVERITY.get(state, 0),
                fragile_index_10m=float(row['reaction_count_10m'] or 0) * 0.5 + float(row['leading_count_10m'] or 0) * 1.5,
                leading_rate_10m=float(row['leading_count_10m'] or 0),
                confidence=85.0 if state == 'STABLE' else 70.0 if state == 'FRAGILE' else 50.0,
                data_health=DataHealth(
                    missing_bucket_ratio_10m=0.0,
                    rebuild_count_10m=0,
                    hash_mismatch_count_10m=0,
                ),
                last_critical_alert=None,
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

        reactions = [
            ReactionEvent(
                id=str(r['reaction_id']),
                token_id=token_id,
                shock_id=str(r['shock_id']) if r['shock_id'] else None,
                ts_start=ts_to_ms(r['ts']),
                ts_end=ts_to_ms(r['ts']) + 5000,  # Approximate end
                window=ReactionWindow(r['window_type']) if r['window_type'] else ReactionWindow.SLOW,
                price=float(r['price']),
                side=Side.BID if r['side'] == 'bid' else Side.ASK,
                reaction=ReactionType(r['reaction_type']),
                proof=ReactionProof(
                    drop_ratio=float(r['drop_ratio']) if r['drop_ratio'] else None,
                    refill_ratio=float(r['refill_ratio']) if r['refill_ratio'] else None,
                    vacuum_duration_ms=r['vacuum_duration_ms'],
                    shift_ticks=r['shift_ticks'],
                    time_to_refill_ms=r['time_to_refill_ms'],
                ),
            )
            for r in reaction_rows
        ]

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

        # If no pre-computed tiles, generate placeholder response
        # Real implementation would generate tiles from book_bins
        if not tiles:
            # This is a placeholder - real implementation generates tiles on demand
            pass

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
