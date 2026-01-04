# Changelog

## v4.0.0 (2026-01-04) - ChatGPT Audit Complete

### WebSocket v4 - Disconnect Handling State Machine
- Add `ConnectionState` enum: DISCONNECTED, RECONNECTING, REBUILDING, CONNECTED
- Implement exponential backoff for reconnection (1s base, 60s max, 2x multiplier)
- Add order book snapshot rebuild on reconnect via REST API
- Add sequence gap detection for consistency monitoring (>5s gaps logged)
- Add `OrderBookSnapshot` dataclass with hash for consistency verification
- New callbacks: `on_state_change`, `on_snapshot_rebuild`
- Track disconnect duration and sequence gaps in stats

### Collector v4 - Time Bucket Sampling
- 250ms strict time bucket sampling (replacing message count-based sampling)
- Server timestamp unification across all events
- `raw_events` table for debug/replay with 7-day retention

### Database Schema v3
- Add `raw_events` hypertable for WebSocket message replay
- Add `bucket_ts` column to `book_bins` for time bucket indexing
- Add retention policies: raw_events (7d), book_bins (14d), events (1y)
- Add continuous aggregates: 250ms → 1s → 1m downsampling

---

## v3.0.0 (2026-01-04) - ChatGPT Audit Fixes

### Reaction Classification v3
- **refill_ratio explosion fix**: Only calculate when `drop >= 15%`, otherwise return `NO_IMPACT`
- **Vacuum dual threshold**: Both relative (5% of baseline) AND absolute (<=10) must be satisfied
- **CHASE/SWEEP persistence**: Price shifts must persist 500ms to count as valid migration

### New Reaction Type
- `NO_IMPACT`: Added for drops < 15% (prevents refill_ratio division issues)

### Leading Events v3
- **GRADUAL_THINNING**: New event type for slow withdrawal detection
  - 60s window
  - Depth drops 40%+
  - Trade-driven ratio < 10%

### Configuration Updates
```python
# v3 Thresholds
DROP_MIN_THRESHOLD = 0.15            # Minimum drop for refill calculation
VACUUM_MIN_SIZE_RATIO = 0.05         # Relative vacuum threshold (5%)
VACUUM_ABS_THRESHOLD = 10            # Absolute vacuum threshold
PRICE_SHIFT_PERSIST_MS = 500         # CHASE/SWEEP persistence requirement
GRADUAL_THINNING_WINDOW_MS = 60000   # 60s window
GRADUAL_THINNING_DROP_RATIO = 0.4    # 40% depth drop
GRADUAL_THINNING_TRADE_RATIO = 0.1   # <10% trade-driven
TIME_BUCKET_MS = 250                 # 250ms time buckets
```

---

## v2.0.0 - Belief Reaction System

### Phase 1: Core Infrastructure
- WebSocket connection to Polymarket
- In-memory state store for order books
- TimescaleDB for time-series data

### Phase 2: Shock Detection + Reaction Classification
- `ShockDetector`: Volume/consecutive trade triggers
- `ReactionClassifier`: 6 reaction types (VACUUM, SWEEP, CHASE, PULL, HOLD, DELAYED)
- Dual window: FAST (8s) + SLOW (30s)
- `baseline_size` using 500ms median (manipulation-resistant)

### Phase 3: Leading Events
- `PRE_SHOCK_PULL`: No-trade withdrawals (information signal)
- `DEPTH_COLLAPSE`: Multi-level synchronized collapse (panic signal)
- `AnchorLevelTracker`: Key price level identification

### Phase 4: Belief State Machine
- Deterministic state machine: STABLE → FRAGILE → CRACKING → BROKEN
- State transitions driven by reaction events at key levels
- 30-minute rolling window for state calculation

---

## Reaction Types Reference (v3)

| Priority | Type | Meaning | Detection Rule |
|----------|------|---------|----------------|
| 1 | VACUUM | Liquidity vacuum | min_liq <= 5% baseline AND <= 10 absolute, duration >= 3s |
| 2 | SWEEP | Multi-level sweep | shift >= 2 ticks OR (shift >= 1 AND drop >= 50%) |
| 3 | CHASE | Price migration | shift >= 1 tick (persisted 500ms+) |
| 4 | PULL | Retreat | drop >= 60% AND refill < 30% |
| 5 | HOLD | Defend | refill >= 80% AND time_to_refill <= 5s |
| 6 | DELAYED | Hesitate | 30% <= refill < 80% |
| 7 | NO_IMPACT | No impact | drop < 15% |

## Leading Event Types (v3)

| Type | Meaning | Detection Rule |
|------|---------|----------------|
| PRE_SHOCK_PULL | Information signal | 80%→20% drop without trades |
| DEPTH_COLLAPSE | Panic signal | 3+ levels drop 60%+ within 1s std |
| GRADUAL_THINNING | Slow withdrawal | 40%+ depth drop in 60s, <10% trade-driven |

## Belief States

| State | Indicator | Meaning |
|-------|-----------|---------|
| STABLE | 🟢 | Market belief is firm/consistent |
| FRAGILE | 🟡 | Market belief shows weakness |
| CRACKING | 🟠 | Market belief actively breaking |
| BROKEN | 🔴 | Market belief has collapsed |
