# Belief Reaction System v5.36 - Final Review Report

> "看存在没意义，看反应才有意义"
> (Watching existence is meaningless; watching reactions is meaningful)

---

## Executive Summary

The Belief Reaction System is a real-time market microstructure analysis platform that detects and classifies market maker behavior ("reactions") following significant trading events ("shocks"). The system transforms raw order book data into belief state assessments (STABLE/FRAGILE/CRACKING/BROKEN) with full evidence traceability.

**Key Metrics:**
- **Code Base**: ~53,000 lines Python + ~5,000 lines TypeScript
- **Test Coverage**: 938 tests (all passing)
- **Engine Version**: v4.1.0
- **API Version**: v5.36

---

## Part 1: Architecture Overview

### 1.1 Service Architecture (Docker Compose)

```
┌─────────────────────────────────────────────────────────────────┐
│                    External Data Sources                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │   Polymarket WebSocket (wss://ws-subscriptions-clob...)  │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    COLLECTOR SERVICE                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  • WebSocket connection management                       │   │
│  │  • Connection state machine (DISCONNECTED/RECONNECTING)  │   │
│  │  • 250ms time bucket sampling                            │   │
│  │  • raw_events persistence                                │   │
│  │  • Event publishing to Redis                             │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│      REDIS       │  │   TimescaleDB    │  │   REACTOR        │
│  • Pub/Sub       │  │  • raw_events    │  │  SERVICE         │
│  • Event queue   │  │  • book_bins     │  │  • ShockDetector │
│  • Cache         │  │  • shock_events  │  │  • ReactionClass │
│  • 256MB limit   │  │  • reactions     │  │  • BeliefState   │
└──────────────────┘  │  • alerts        │  │  • AlertGen      │
                      │  • heatmap_tiles │  └──────────────────┘
                      └──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                                 ▼
┌──────────────────────────────┐  ┌──────────────────────────────┐
│         API SERVICE          │  │      TILE_WORKER SERVICE     │
│  • FastAPI REST endpoints    │  │  • Async heatmap generation  │
│  • WebSocket streaming       │  │  • Multi-LOD tile creation   │
│  • /v1/radar, /v1/evidence   │  │  • zstd compression          │
│  • /v1/alerts, /v1/heatmap   │  │  • LOD retention policy      │
│  • Port 8000                 │  │  • 250ms/1s/5s tiles         │
└──────────────────────────────┘  └──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FRONTEND (Next.js)                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  • HeatmapRenderer         • TileStalenessIndicator      │   │
│  │  • EvidencePlayer          • EvidenceChainPanel          │   │
│  │  • ReactionDistribution    • HashVerification            │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Resource Limits

| Service | Memory Limit | Memory Reserved |
|---------|--------------|-----------------|
| Collector | 512MB | 256MB |
| Reactor | 1GB | 512MB |
| API | 1GB | 256MB |
| Tile Worker | 2GB | 512MB |
| TimescaleDB | - | - |
| Redis | 256MB | - |

---

## Part 2: Core Engine (POC)

### 2.1 Shock Detection (`poc/shock_detector.py`)

Detects when a price level is significantly impacted by trading activity.

**Trigger Conditions:**
1. **Volume Trigger**: `trade_volume >= 35% × baseline_size` AND `trade_volume >= 200` (absolute)
2. **Consecutive Trigger**: 3+ consecutive trades at same price

**Key Parameters:**
```python
SHOCK_TIME_WINDOW_MS = 2000        # 2s window
SHOCK_VOLUME_THRESHOLD = 0.35      # 35% of baseline
MIN_ABS_VOL = 200                  # Absolute minimum
SHOCK_CONSECUTIVE_TRADES = 3       # Consecutive trades
BASELINE_WINDOW_START_MS = 500     # -500ms baseline start
BASELINE_WINDOW_END_MS = 100       # -100ms baseline end
```

### 2.2 Reaction Classification (`poc/reaction_classifier.py`)

Classifies market maker response within observation window.

**Dual Window System:**
- **FAST Window**: 8 seconds (detects information-driven retreat)
- **SLOW Window**: 30 seconds (detects slow refill/rebalancing)

**Reaction Types (Priority Order):**

| # | Type | Signal | Detection Rule |
|---|------|--------|----------------|
| 0 | NO_IMPACT | - | `drop < 15%` (v3 fix) |
| 1 | VACUUM | 🔴 Strongest | `min_liq ≤ 5% baseline` AND `≤ 10 absolute`, `duration ≥ 3s` |
| 2 | SWEEP | 🟠 Strong | `shift ≥ 2 ticks` OR (`shift ≥ 1` AND `drop ≥ 50%`) |
| 3 | CHASE | 🟡 Medium | `shift ≥ 1 tick` (persisted 500ms+) |
| 4 | PULL | 🟣 Medium | `drop ≥ 60%` AND `refill < 30%` |
| 5 | HOLD | 🟢 Defensive | `refill ≥ 80%` AND `time_to_refill ≤ 5s` |
| 6 | DELAYED | ⚪ Weak | Default (30% ≤ refill < 80%) |

**v3 Fixes:**
- **refill_ratio explosion fix**: Only calculate when `drop >= 15%`
- **Vacuum dual threshold**: Both relative AND absolute must be satisfied
- **CHASE/SWEEP persistence**: Price shifts must persist 500ms+

### 2.3 Leading Events (`poc/leading_events.py`)

Early warning signals that often precede shocks.

| Type | Meaning | Detection |
|------|---------|-----------|
| PRE_SHOCK_PULL | Leading evidence | 80%→20% drop without trades |
| DEPTH_COLLAPSE | Structural evidence | 3+ levels drop 60%+ within 1s std |
| GRADUAL_THINNING | Slow withdrawal | 40%+ depth drop in 60s, <10% trade-driven |

### 2.4 Belief State Machine (`poc/belief_state_machine.py`)

Deterministic state machine with 30-minute rolling window.

**States:**
| State | Indicator | Meaning |
|-------|-----------|---------|
| STABLE | 🟢 | Market belief is firm/consistent |
| FRAGILE | 🟡 | Market belief shows weakness |
| CRACKING | 🟠 | Market belief actively breaking |
| BROKEN | 🔴 | Market belief has collapsed |

**Transition Rules (Priority Order):**

```
BROKEN (highest priority):
  - n_vacuum >= 2 (from ≥2 different anchors)
  - OR (n_collapse >= 1 AND n_vacuum >= 1)
  - OR n_pre_pull >= 2

CRACKING:
  - n_vacuum >= 1
  - OR n_pull >= 2
  - OR n_pre_pull >= 1
  - OR n_collapse >= 1

FRAGILE:
  - (n_delayed >= 2 AND hold_ratio < 0.7)
  - OR n_pull == 1
  - OR n_chase + n_sweep >= 1

STABLE (default):
  - hold_ratio >= 0.7
  - AND n_vacuum == 0
  - AND n_pre_pull == 0
  - AND n_collapse == 0
```

---

## Part 3: Backend Services

### 3.1 API Endpoints (`backend/api/`)

**Core Endpoints:**
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/radar` | GET | Market overview with belief states |
| `/v1/evidence` | GET | Complete evidence window for a market |
| `/v1/alerts` | GET | Alert listing with filters |
| `/v1/alerts/{id}/ack` | POST | Acknowledge an alert |
| `/v1/alerts/{id}/resolve` | POST | Resolve with recovery evidence |
| `/v1/alerts/{id}/false-positive` | POST | Mark as false positive |
| `/v1/heatmap/tiles` | GET | Heatmap tile data |
| `/v1/replay/catalog` | GET | Historical event catalog |
| `/v1/stream` | WebSocket | Real-time event stream |
| `/v1/health` | GET | Service health check |

**v5.36 New Endpoints:**
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/evidence/{token_id}/chain` | GET | Evidence chain (Shock→Reaction→Alert) |
| `/v1/evidence/{token_id}/distribution` | GET | Reaction type distribution |
| `/v1/markets/{token_id}/eligibility` | GET | Market eligibility score |

### 3.2 Data Schemas (`backend/api/schemas/v1.py`)

**Key Types:**
- `BeliefState`: STABLE, FRAGILE, CRACKING, BROKEN
- `ReactionType`: VACUUM, SWEEP, CHASE, PULL, HOLD, DELAYED, NO_IMPACT
- `LeadingEventType`: PRE_SHOCK_PULL, DEPTH_COLLAPSE, GRADUAL_THINNING
- `AlertSeverity`: LOW, MEDIUM, HIGH, CRITICAL
- `EvidenceGrade`: A, B, C, D (v5.34)
- `FalsePositiveReason`: THIN_MARKET, NOISE, MANIPULATION, STALE_DATA, OTHER (v5.36)

**v5.36 Schema Additions:**
```python
# Alert schema
class Alert:
    disclaimer: str = "This alert indicates observed belief instability. It does NOT imply outcome direction..."
    recovery_evidence: List[str]  # System-generated resolution evidence
    is_false_positive: bool
    false_positive_reason: Optional[str]

# Latency disclosure
class LatencyInfo:
    event_ts: int          # When market event occurred
    detected_ts: int       # When system detected it
    detection_latency_ms: int
    window_type: str       # FAST/SLOW/IMMEDIATE
```

### 3.3 Market Eligibility (`backend/market/eligibility.py`)

**v5.36 Feature**: Evaluates market suitability for belief reaction processing.

**Eligibility Statuses:**
| Status | Processing | Alerts |
|--------|------------|--------|
| ELIGIBLE | Full | All severities |
| DEGRADED | Full | Capped at HIGH |
| OBSERVE_ONLY | Heatmap only | None |
| EXCLUDED | None | None |

**Scoring Components (Weighted):**
- Liquidity Score (30%): baseline_liquidity threshold
- Diversity Score (25%): unique traders, concentration
- Rhythm Score (20%): human vs bot pattern detection
- Manipulation Score (25%): spoofing/wash trading detection

### 3.4 Fire Drill (`backend/audit/fire_drill.py`)

**v5.36 Feature**: Periodic rebuild verification from raw_events.

```python
class FireDrillExecutor:
    def run(self, window_hours: int = 24) -> FireDrillReport:
        # 1. Backup derived data
        # 2. Clear derived tables
        # 3. Replay raw_events through reactor
        # 4. Compare rebuilt vs original
        # 5. Report determinism verification
```

### 3.5 Audit Window Storage (`backend/storage/audit_window.py`)

**v5.36 Feature**: Conditional raw_events storage.

- **Normal operation**: Store downsampled data only
- **CRACKING/BROKEN triggered**: Store full audit window (configurable duration)
- **Reduces storage by ~70%** while preserving critical forensic data

### 3.6 Local Recorder (`backend/export/local_recorder.py`)

**v5.36 Feature**: Pro user local data export.

**Capabilities:**
- Real-time streaming to local files
- Batch export of historical data
- Formats: JSONL, CSV, JSON (Parquet-ready)
- Compression: gzip, zstd
- Auto file rotation by size (100MB) / time (24h)
- Recording session manifests

---

## Part 4: Heatmap System

### 4.1 Tile Generation (`backend/heatmap/tile_generator.py`)

**LOD (Level of Detail) System:**
| LOD | Resolution | Use Case |
|-----|------------|----------|
| 250ms | High | Detailed forensic analysis |
| 1s | Medium | Overview |
| 5s | Low | Long-range view |

**Tile Structure:**
- Time window: 5s, 10s, or 15s per tile
- Encoding: uint16 with log1p scaling
- Compression: zstd level 3
- Checksum: xxHash64

**Band Filtering:**
| Band | Levels | Use |
|------|--------|-----|
| FULL | All prices | Complete view |
| BEST_5 | Top 5 | Tight focus |
| BEST_10 | Top 10 | Standard view |
| BEST_20 | Top 20 | Wide focus |

### 4.2 Retention Policy (v5.36)

```sql
-- LOD-based retention
250ms tiles: 48 hours
1s tiles: 14 days
5s tiles: 180 days (6 months)
```

### 4.3 Staleness Indicator

Frontend component shows tile freshness:
- 🟢 Fresh (< 5 min old)
- 🟡 Stale (5-30 min old)
- 🔴 Very stale (> 30 min old)

---

## Part 5: Frontend Components

### 5.1 React Components (`frontend/src/components/`)

| Component | Purpose |
|-----------|---------|
| `HeatmapRenderer` | WebGL-based heatmap visualization |
| `EvidencePlayer` | Playback of evidence windows |
| `TapePanel` | Time & Sales display |
| `ContextPanel` | Market context information |
| `ReactionDistributionPanel` | Reaction type distribution charts |
| `EvidenceDisclaimer` | v5.36 counterfactual disclaimer |
| `TileStalenessIndicator` | Data freshness indicator |
| `SimilarCasesPanel` | Related historical events |
| `HashVerification` | Evidence bundle hash verification |
| `EvidenceChainPanel` | v5.36 causal chain visualization |

### 5.2 TypeScript Types (`frontend/src/types/api.ts`)

Fully typed API interfaces matching backend schemas:
- `RadarMarket`, `RadarResponse`
- `EvidenceResponse`, `ShockEvent`, `ReactionEvent`
- `Alert`, `TilesManifest`, `TileData`
- State indicators and color mappings

---

## Part 6: Infrastructure

### 6.1 Docker Services

| File | Service |
|------|---------|
| `infra/Dockerfile.api` | FastAPI REST server |
| `infra/Dockerfile.collector` | WebSocket data collector |
| `infra/Dockerfile.reactor` | Event processing engine |
| `infra/Dockerfile.tile_worker` | Async tile generation |
| `infra/docker-compose.yml` | Full stack orchestration |

### 6.2 Database (TimescaleDB)

**Hypertables:**
- `raw_events` - WebSocket messages (7-day retention)
- `book_bins` - Order book snapshots (14-day retention)
- `book_bins_1s`, `book_bins_1m` - Continuous aggregates
- `shock_events` - Detected shocks (1-year retention)
- `reaction_events` - Classified reactions
- `leading_events` - Leading indicators
- `belief_states` - State change history
- `alerts` - Generated alerts
- `heatmap_tiles` - Cached tiles

### 6.3 Configuration (`poc/config.py`)

```python
# Shock Detection
SHOCK_TIME_WINDOW_MS = 2000
SHOCK_VOLUME_THRESHOLD = 0.35
MIN_ABS_VOL = 200

# Reaction Windows
REACTION_FAST_WINDOW_MS = 8000    # 8s
REACTION_SLOW_WINDOW_MS = 30000   # 30s

# Time Sampling
TIME_BUCKET_MS = 250              # 250ms buckets

# Retention (v5.36)
RETENTION_RAW_EVENTS_DAYS = 7
RETENTION_TILES_250MS_HOURS = 48
RETENTION_TILES_1S_DAYS = 14
RETENTION_TILES_5S_DAYS = 180
```

---

## Part 7: Quality Assurance

### 7.1 Test Coverage

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_market_eligibility.py` | 17 | Market eligibility layer |
| `test_fire_drill.py` | 16 | Fire drill verification |
| `test_audit_window.py` | 20 | Audit window storage |
| `test_local_recorder.py` | 26 | Local recorder |
| `test_alerting.py` | 50+ | Alert system |
| `test_api_v5_36.py` | 40+ | v5.36 API endpoints |
| `test_determinism.py` | 30+ | Deterministic replay |
| `test_attribution.py` | 40+ | Trade/cancel attribution |
| ... | ... | ... |
| **TOTAL** | **938** | **All passing** |

### 7.2 Golden Tests (`tests/golden/`)

Pre-recorded test scenarios with verified outputs:
- Shock detection scenarios
- Reaction classification edge cases
- State transition sequences
- Evidence bundle verification

### 7.3 Adversarial Tests (`tests/adversarial/`)

Security and edge case testing:
- Manipulation detection
- Data integrity verification
- Rate limiting validation

---

## Part 8: v5.36 Feature Checklist

### P0 (Critical) ✅

| Feature | Status | Files |
|---------|--------|-------|
| Market Eligibility Layer | ✅ | `backend/market/eligibility.py` |
| Fire Drill Script | ✅ | `backend/audit/fire_drill.py` |
| Alert Counterfactual Labels | ✅ | `backend/api/schemas/v1.py` |

### P1 (Important) ✅

| Feature | Status | Files |
|---------|--------|-------|
| raw_events Conditional Storage | ✅ | `backend/storage/audit_window.py` |
| Docker Service Split | ✅ | `infra/Dockerfile.*`, `docker-compose.yml` |
| Tile LOD Retention | ✅ | `infra/migrations/v5.36_tile_lod_retention.sql` |

### P2 (Nice to Have) ✅

| Feature | Status | Files |
|---------|--------|-------|
| Local Recorder | ✅ | `backend/export/local_recorder.py` |

### Pre-existing Features ✅

| Feature | Status |
|---------|--------|
| Band Filtering (BEST_10/20) | ✅ |
| Multi-LOD Tiles | ✅ |
| Politics/Sports/Crypto Filtering | ✅ |
| Heatmap Staleness Indicator | ✅ |
| Evidence Grade (A/B/C/D) | ✅ |
| Alert Lifecycle (OPEN→ACK→RESOLVED) | ✅ |
| False Positive Tracking | ✅ |
| Detection Latency Disclosure | ✅ |

---

## Part 9: Documentation

### 9.1 Specification Documents

| Document | Description |
|----------|-------------|
| `docs/Belief_Reaction_System_Engineering_Spec.txt` | Core engineering spec |
| `docs/Belief_Reaction_System_Whitebook.txt` | Conceptual overview |
| `docs/REPLAY_SPEC.md` | Deterministic replay specification |
| `docs/CONSISTENCY_SPEC.md` | Consistency verification |
| `docs/TILE_SPEC.md` | Heatmap tile specification |
| `docs/API_V536.md` | v5.36 API documentation |
| `docs/DEPLOYMENT.md` | Deployment guide |
| `docs/RUNBOOK.md` | Operations runbook |

### 9.2 Architecture Decision Records

| ADR | Topic |
|-----|-------|
| `001-paradigm-principles.md` | Core paradigm principles |
| `002-api-endpoint-separation.md` | API design decisions |
| `003-language-governance.md` | Terminology governance |
| `004-evidence-integrity.md` | Evidence integrity requirements |

---

## Part 10: Key Principles

### 10.1 Paradigm Principles

1. **"看反应" (Watch Reactions)**: Focus on market maker behavior, not price
2. **Evidence-First**: Every state/alert must have traceable evidence
3. **Deterministic**: Same inputs must produce same outputs (replay-safe)
4. **Humble Latency**: Disclose detection delay, not claim prediction
5. **Counterfactual**: Alerts indicate instability, NOT outcome direction

### 10.2 Data Integrity

- **Evidence Grade**: A/B/C/D quality classification
- **Bundle Hash**: Cryptographic verification of evidence bundles
- **Fire Drill**: Periodic rebuild verification
- **Audit Windows**: Full data retention during critical events

### 10.3 Alert Philosophy (v5.36)

```
"This alert indicates observed belief instability.
It does NOT imply outcome direction or trading recommendation."
```

- CRITICAL alerts require Grade A/B evidence
- Resolution requires system-generated recovery evidence
- False positives tracked for algorithm improvement

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| v5.36 | 2026-01-06 | Market eligibility, fire drill, local recorder |
| v5.34 | 2026-01-05 | Evidence grade, false positive tracking |
| v4.1.0 | 2026-01-04 | Deterministic replay, collector/reactor decoupling |
| v4.0.0 | 2026-01-04 | ChatGPT audit, time bucket sampling |
| v3.0.0 | 2026-01-04 | Reaction v3 fixes, GRADUAL_THINNING |
| v2.0.0 | - | Core belief reaction system |

---

## Final Checklist

- [x] All 938 tests passing
- [x] P0/P1/P2 features implemented
- [x] Docker services configured
- [x] Database migrations ready
- [x] API documentation complete
- [x] Evidence integrity verified
- [x] Alert disclaimers in place
- [x] Market eligibility layer active
- [x] Fire drill script ready
- [x] Local recorder available

---

**Report Generated**: 2026-01-06
**Branch**: `claude/initial-setup-xsnPm`
**Engine Version**: v4.1.0
