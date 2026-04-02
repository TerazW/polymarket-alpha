# Market-Sensemaking Codebase Analysis

## Executive Summary

**Market-Sensemaking** is a sophisticated "Belief Reaction System" for detecting and classifying market participant behavior changes in Polymarket prediction markets. Rather than predicting prices, it observes and classifies *reactions* to market shocks (large trades), providing evidence-based market microstructure analysis.

**Core Philosophy:** "看存在没意义，看反应才有意义" (Observing existence is meaningless; observing reactions reveals meaning)

The system is **NOT** a trading system—it produces structured evidence of market behavior, suitable as a foundation for quantitative trading but requiring significant modifications for autonomous trading capabilities.

---

## 1. Project Structure

```
market-sensemaking/
├── poc/                          # Proof-of-concept core engine
│   ├── collector.py             # WebSocket data collection
│   ├── event_bus.py             # In-memory event distribution
│   ├── models.py                # Data structures (7 reactions, 4 states)
│   ├── shock_detector.py        # Trade-triggered shock detection
│   ├── reaction_classifier.py   # Observable reaction classification
│   ├── belief_state.py          # Event aggregation
│   ├── belief_state_machine.py  # Deterministic state transitions
│   ├── alert_system.py          # Alert generation
│   ├── reactor.py               # Main orchestration loop
│   └── test_poc.py              # Core tests
│
├── backend/                      # Production FastAPI server
│   ├── api/
│   │   ├── main.py              # FastAPI app setup
│   │   ├── routes/
│   │   │   ├── v1.py            # Main API endpoints (radar, evidence, alerts)
│   │   │   ├── reactor.py       # Reaction/state queries
│   │   │   ├── collector.py     # Collector control
│   │   │   ├── system.py        # System lifecycle
│   │   │   ├── admin.py         # Admin operations
│   │   │   └── events.py        # Multi-market aggregation
│   │   ├── schemas/
│   │   │   └── v1.py            # Pydantic response models (701 lines)
│   │   ├── stream.py            # WebSocket streaming manager
│   │   ├── middleware.py        # Security/throttling
│   │   └── __init__.py
│   │
│   ├── collector/
│   │   ├── main.py              # Polymarket integration
│   │   └── service.py           # Async wrapper
│   │
│   ├── reactor/
│   │   ├── core.py              # Reactor wrapper
│   │   ├── service.py           # Async service layer
│   │   ├── alert_generator.py   # Alert generation
│   │   └── __init__.py
│   │
│   ├── heatmap/
│   │   ├── tile_generator.py    # Precomputed tile generation
│   │   ├── precompute.py        # Background tile generation
│   │   └── dual_track.py        # Bid/ask separation
│   │
│   ├── common/
│   │   ├── config.py            # Environment-based configuration
│   │   ├── schemas.py           # Shared Pydantic models
│   │   ├── db.py                # SQLAlchemy async setup
│   │   ├── attribution.py       # Event attribution
│   │   ├── determinism.py       # Determinism verification
│   │   ├── throttle.py          # Rate limiting
│   │   └── logging.py           # Structured logging
│   │
│   ├── evidence/
│   │   └── bundle_hash.py       # Cryptographic verification
│   │
│   ├── radar/
│   │   └── explain.py           # Natural language explanations
│   │
│   ├── security/
│   │   ├── auth.py              # Authentication
│   │   ├── acl.py               # Access control
│   │   └── audit.py             # Audit trail
│   │
│   ├── monitoring/
│   │   ├── health.py            # Deep health checks
│   │   ├── metrics.py           # Prometheus metrics
│   │   ├── cost_alerts.py       # Cost monitoring
│   │   └── remediation.py       # Auto-remediation
│   │
│   ├── market/
│   │   └── eligibility.py       # Market filtering
│   │
│   ├── replay/
│   │   ├── engine.py            # Deterministic replay
│   │   ├── verifier.py          # Result verification
│   │   └── cli.py               # Replay CLI
│   │
│   ├── storage/
│   │   └── audit_window.py      # Retention policies
│   │
│   ├── alerting/
│   │   ├── router.py            # Alert routing
│   │   ├── ops.py               # Alert operations
│   │   └── evidence_grade.py    # Evidence quality
│   │
│   ├── system/
│   │   └── startup.py           # System initialization
│   │
│   ├── main.py                  # Entry point
│   ├── version.py               # Version tracking
│   └── requirements.txt         # Backend dependencies
│
├── frontend/                     # Next.js + React UI
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx         # Radar dashboard
│   │   │   ├── layout.tsx       # Layout
│   │   │   ├── market/[tokenId]/page.tsx  # Evidence details
│   │   │   └── replay/page.tsx  # Replay catalog
│   │   ├── components/
│   │   │   └── evidence/
│   │   │       ├── EvidencePlayer.tsx    # Main viewer
│   │   │       ├── HeatmapRenderer.tsx   # Bookmap-style heatmap
│   │   │       ├── TapePanel.tsx         # Trade tape
│   │   │       ├── AlertsPanel.tsx       # Alert list
│   │   │       ├── ReactionDistributionPanel.tsx
│   │   │       ├── ContextPanel.tsx
│   │   │       ├── EvidenceChainPanel.tsx
│   │   │       ├── HashVerification.tsx
│   │   │       └── TileStalenessIndicator.tsx
│   │   ├── hooks/
│   │   │   ├── useEvidenceFetch.ts       # Data fetching
│   │   │   └── useStream.ts              # WebSocket streaming
│   │   ├── lib/
│   │   │   └── api.ts                    # API client
│   │   ├── types/
│   │   │   └── api.ts                    # TypeScript types
│   │   └── styles/
│   ├── package.json
│   ├── next.config.ts
│   ├── tsconfig.json
│   └── tailwind.config.js
│
├── infra/                        # DevOps configuration
│   ├── docker-compose.yml       # Local development
│   ├── init.sql                 # Database schema initialization
│   ├── init_postgresql.sql
│   ├── Dockerfile.api           # API container
│   ├── Dockerfile.collector     # Collector container
│   ├── Dockerfile.reactor       # Reactor container
│   ├── Dockerfile.tile_worker   # Tile generation worker
│   ├── Dockerfile.migrate       # Migration container
│   ├── cloudformation.yml       # AWS infrastructure
│   └── migrations/
│       ├── v5.3_add_provenance.sql
│       ├── v5.35_add_event_relationship.sql
│       ├── v5.36_alert_recovery_evidence.sql
│       └── v5.36_tile_lod_retention.sql
│
├── docs/                         # Documentation
│   ├── adr/
│   │   ├── 001-paradigm-principles.md     # Core design principles
│   │   ├── 002-api-endpoint-separation.md
│   │   ├── 003-language-governance.md
│   │   └── 004-evidence-integrity.md
│   ├── OPERATOR_GUIDE.md
│   ├── API_V536.md
│   ├── TILE_SPEC.md
│   ├── CONSISTENCY_SPEC.md
│   ├── DEPLOYMENT.md
│   └── legal/
│
├── tests/                        # Test suite
│   ├── test_*.py               # Unit tests
│   ├── golden/                 # Golden replay tests
│   └── adversarial/            # Determinism/security tests
│
├── scripts/                      # Utility scripts
├── research/                     # Research notebooks
├── .github/workflows/
│   ├── ci.yml                  # CI pipeline
│   ├── deploy.yml              # AWS deployment
│   └── language-check.yml
│
├── schema.sql                    # Legacy schema
├── init_db.py                   # Database initialization
├── requirements.txt
├── SETUP_GUIDE.md
├── CLAUDE.md                    # Development notes
└── README.md
```

---

## 2. Backend Architecture

### 2.1 Core Configuration

**File:** `backend/common/config.py` (200 lines)

Centralized environment-based configuration with dataclass structure:

```python
@dataclass
class Config:
    database: DatabaseConfig          # PostgreSQL async connection pool
    polymarket: PolymarketConfig      # WebSocket + REST endpoints
    shock: ShockConfig                # Shock detection thresholds
    reaction: ReactionConfig          # Reaction classification window
    belief_state: BeliefStateConfig    # State machine parameters
    collector: CollectorConfig        # Data collection settings
    alerting: AlertConfig             # Multi-destination alert routing
```

**Key Configuration Parameters:**

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `SHOCK_TIME_WINDOW_MS` | 2000 | Time window for consecutive trade detection |
| `SHOCK_VOLUME_THRESHOLD` | 0.35 | Volume threshold for shock trigger (35% of baseline) |
| `SHOCK_CONSECUTIVE_TRADES` | 3 | Number of consecutive trades to trigger shock |
| `REACTION_WINDOW_MS` | 20000 | Post-shock observation window |
| `HOLD_REFILL_THRESHOLD` | 0.8 | Refill ratio for HOLD classification (80%) |
| `HOLD_TIME_THRESHOLD_MS` | 5000 | Max time for HOLD refill (5 seconds) |
| `VACUUM_THRESHOLD` | 0.05 | Minimum liquidity threshold (5%) |
| `PULL_THRESHOLD` | 0.1 | Minimum liquidity threshold for PULL |
| `KEY_LEVELS_COUNT` | 5 | Top K anchor levels per side |
| `BIN_INTERVAL_MS` | 250 | Order book snapshot interval |
| `MAX_MARKETS` | 100 | Maximum markets to monitor simultaneously |

### 2.2 API Routes Architecture

**Primary Route File:** `backend/api/routes/v1.py` (1000+ lines)

#### Endpoint Organization

| Endpoint | Method | Purpose | Response |
|----------|--------|---------|----------|
| `/v1/radar` | GET | Multi-market overview with belief states | RadarResponse (paginated rows) |
| `/v1/evidence` | GET | Detailed evidence for a market at time t0 | EvidenceResponse (shocks, reactions, states) |
| `/v1/heatmap/tiles` | GET | Precomputed heatmap tiles (bid/ask separated) | HeatmapTilesResponse |
| `/v1/alerts` | GET | Alert history with filtering | AlertsResponse |
| `/v1/alerts/:id/ack` | POST | Acknowledge alert | AlertResponse |
| `/v1/alerts/:id/resolve` | POST | Mark alert resolved | AlertResponse |
| `/v1/replay/catalog` | GET | Event catalog for replay | ReplayCatalogResponse |
| `/v1/health` | GET | Basic health check | {ok: boolean} |
| `/v1/health/deep` | GET | Comprehensive system diagnostics | HealthReport |
| `/v1/belief-states` | GET | Current belief states | StateSummaryResponse |

### 2.3 Data Models & Schemas

**Primary Schema File:** `backend/common/schemas.py` (200 lines)

Core Pydantic models for WebSocket messages:

```python
class ReactionType(Enum):
    VACUUM = "VACUUM"           # Liquidity falls below threshold
    SWEEP = "SWEEP"             # Consecutive trades across levels
    CHASE = "CHASE"             # Liquidity reappears at shifted levels
    PULL = "PULL"               # Immediate cancellation
    HOLD = "HOLD"               # Replenishment within bounded time
    DELAYED = "DELAYED"         # Partial/delayed replenishment
    NO_IMPACT = "NO_IMPACT"     # Changes below thresholds

class BeliefState(Enum):
    STABLE = "STABLE"           # Strong structural defense
    FRAGILE = "FRAGILE"         # Structural weakening signals
    CRACKING = "CRACKING"       # Structural failure signals
    BROKEN = "BROKEN"           # Structural collapse signals
```

**WebSocket Message Types (from Polymarket):**
- `book`: Full order book snapshot
- `price_change`: Incremental level updates (size = NEW aggregate, NOT delta)
- `last_trade_price`: Trade execution
- `tick_size_change`: Tick size adjustment (at extreme prices)

### 2.4 Database Schema (TimescaleDB)

**Schema File:** `infra/init.sql` (500+ lines)

**TimescaleDB-based design** with hypertable compression and retention policies.

#### Core Tables

**markets** - Market metadata
```sql
CREATE TABLE markets (
    condition_id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    yes_token_id TEXT NOT NULL,
    no_token_id TEXT NOT NULL,
    tick_size NUMERIC(5,4),
    active BOOLEAN,
    closed BOOLEAN,
    volume_24h NUMERIC,
    liquidity NUMERIC,
    created_at TIMESTAMPTZ
);
```

**raw_events** - Raw WebSocket messages (7-day retention)
```sql
CREATE TABLE raw_events (
    ts TIMESTAMPTZ NOT NULL,
    arrival_ts TIMESTAMPTZ NOT NULL,
    event_type TEXT,
    token_id TEXT,
    payload JSONB,
    hash TEXT
);
SELECT create_hypertable('raw_events', 'ts', if_not_exists => TRUE);
```

**book_bins** - Order book snapshots (250ms buckets, 14-day retention)
```sql
CREATE TABLE book_bins (
    bucket_ts TIMESTAMPTZ NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    token_id TEXT,
    side TEXT,
    price NUMERIC(5,3),
    size NUMERIC
);
SELECT create_hypertable('book_bins', 'bucket_ts', if_not_exists => TRUE);
```

**trade_ticks** - Trade executions (14-day retention)
```sql
CREATE TABLE trade_ticks (
    ts TIMESTAMPTZ NOT NULL,
    token_id TEXT,
    price NUMERIC(5,3),
    size NUMERIC,
    side TEXT
);
SELECT create_hypertable('trade_ticks', 'ts', if_not_exists => TRUE);
```

**shock_events** - Detected shocks
```sql
CREATE TABLE shock_events (
    shock_id UUID PRIMARY KEY,
    ts TIMESTAMPTZ,
    token_id TEXT,
    price NUMERIC(5,3),
    side TEXT,
    trade_volume NUMERIC,
    liquidity_before NUMERIC,
    baseline_size NUMERIC,
    trigger_type TEXT
);
```

**reaction_events** - Classified reactions
```sql
CREATE TABLE reaction_events (
    reaction_id UUID PRIMARY KEY,
    shock_id UUID REFERENCES shock_events,
    ts TIMESTAMPTZ,
    token_id TEXT,
    reaction_type TEXT,
    window_type TEXT,
    refill_ratio NUMERIC,
    time_to_refill_ms INTEGER,
    min_liquidity NUMERIC,
    price_shift NUMERIC(5,3)
);
```

**leading_events** - Pre-shock warning signals
```sql
CREATE TABLE leading_events (
    event_id UUID PRIMARY KEY,
    ts TIMESTAMPTZ,
    event_type TEXT,
    token_id TEXT,
    price NUMERIC(5,3),
    side TEXT,
    drop_ratio NUMERIC,
    duration_ms INTEGER
);
```

**belief_states** - State transitions
```sql
CREATE TABLE belief_states (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ,
    token_id TEXT,
    old_state TEXT,
    new_state TEXT,
    trigger_reaction_id UUID REFERENCES reaction_events,
    evidence JSONB
);
```

**alerts** - Alert records
```sql
CREATE TABLE alerts (
    alert_id UUID PRIMARY KEY,
    ts TIMESTAMPTZ,
    token_id TEXT,
    severity alert_severity,
    status alert_status,
    alert_type TEXT,
    summary TEXT,
    confidence NUMERIC(5,2),
    evidence_token TEXT,
    evidence_t0 BIGINT,
    payload JSONB
);
```

**heatmap_tiles** - Precomputed visualization tiles
```sql
CREATE TABLE heatmap_tiles (
    tile_id TEXT PRIMARY KEY,
    token_id TEXT,
    lod_ms INTEGER,
    tile_ms INTEGER,
    band TEXT,
    t_start BIGINT,
    t_end BIGINT,
    tick_size NUMERIC(5,4),
    price_min NUMERIC(5,3),
    price_max NUMERIC(5,3),
    rows INTEGER,
    cols INTEGER,
    encoding_dtype TEXT,
    encoding_scale TEXT,
    compression_algo TEXT,
    compression_level INTEGER,
    payload BYTEA,
    checksum_algo TEXT,
    checksum_value TEXT
);
```

**data_health** - Data quality monitoring (90-day retention)
```sql
CREATE TABLE data_health (
    ts TIMESTAMPTZ,
    token_id TEXT,
    missing_bucket_ratio NUMERIC(5,4),
    rebuild_count INTEGER,
    hash_mismatch_count INTEGER
);
```

#### Materialized Views (Time Downsampling)

- **book_bins_1s**: 250ms → 1s aggregation (90-day retention)
- **book_bins_1m**: 250ms → 1m aggregation (permanent retention)

### 2.5 Collector System (Polymarket Integration)

**Files:** `backend/collector/main.py`, `backend/collector/service.py`

#### Architecture
```
Polymarket WebSocket
        ↓
  DataCollector (POC)
        ↓
  InMemoryEventBus
        ↓
  ReactorService (FastAPI)
        ↓
  Database Persistence
```

**DataCollector** connects to `wss://ws-subscriptions-clob.polymarket.com/ws/market` and:
1. Subscribes to market-level WebSocket (not individual orders)
2. Receives aggregated order book snapshots
3. Publishes raw events to EventBus
4. Handles reconnection with exponential backoff

**Market Selection:**
- Category: "politics" (configurable via ENV)
- Volume threshold: 5000 USDC 24h (configurable)
- Max markets: 100 (configurable)
- Fetched via Polymarket Data API `/markets?status=open`

### 2.6 Heatmap/Tile Generation System

**Files:** `backend/heatmap/tile_generator.py`, `backend/heatmap/precompute.py`

#### Tile Structure

```
Tile = {
    t_start, t_end              # Time coverage
    lod_ms: 250|1000|5000       # Column resolution
    tile_ms: 5000|10000|15000   # Tile time window
    band: FULL|BEST_5|10|20     # Price band selection
    rows, cols                  # Matrix dimensions
    price_min, price_max        # Price range
}
```

#### Encoding Pipeline

1. **Fetch Data** from book_bins (or downsampled views)
2. **Build Matrix** from (price, time) → size mapping
3. **Clip Values** at 95th percentile
4. **Scale** using `log1p(value) / log1p(max)` → [0, 1]
5. **Encode** as uint16 (0-65535)
6. **Compress** with zstd (level 3)
7. **Checksum** with xxHash64 for integrity

---

## 3. Frontend Architecture

**Stack:** Next.js 16.1.1 + React 19.2.3 + TypeScript + Tailwind CSS

### 3.1 Pages & Routing

| Page | Route | Purpose |
|------|-------|---------|
| Radar Dashboard | `/` | Multi-market overview, fragility index, states |
| Market Details | `/market/[tokenId]` | Evidence player for specific market |
| Replay Catalog | `/replay` | Event catalog for historical playback |

### 3.2 Main Components

- **EvidencePlayer**: Central visualization orchestrating all sub-components
- **HeatmapRenderer**: Canvas-based Bookmap-style visualization (bid=green, ask=red)
- **TapePanel**: Trade execution tape
- **AlertsPanel**: Alert timeline
- **ReactionDistributionPanel**: Reaction type histogram

### 3.3 API Client (`frontend/src/lib/api.ts`)

Type-safe API wrapper with error handling, rate limit support, AbortSignal.

---

## 4. Data Pipeline (End-to-End)

```
POLYMARKET WEBSOCKET
    ↓
POC DATA COLLECTOR (WebSocket → Event Normalization)
    ↓
IN-MEMORY EVENT BUS
    ↓
POC REACTOR ENGINE
    ├── OrderBookState
    ├── ShockDetector
    ├── ReactionClassifier
    └── BeliefStateMachine
    ↓
DATABASE (TimescaleDB)
    ├── raw_events, book_bins, trade_ticks
    ├── shock_events, reaction_events, leading_events
    ├── belief_states, alerts
    └── heatmap_tiles
    ↓
FASTAPI BACKEND (/v1 endpoints)
    ↓
NEXT.JS FRONTEND
```

---

## 5. Infrastructure

- **Local**: Docker Compose (TimescaleDB + Redis + API)
- **Production**: AWS ECS (4 services: api, collector, reactor, tile-worker)
- **Database**: RDS PostgreSQL with TimescaleDB
- **DNS**: Cloudflare → marketsensemaking.com
- **CI/CD**: GitHub Actions (ci.yml, deploy.yml)

---

## 6. Reusable Components (for Trading System)

### Can Be Kept As-Is
- ✅ POC Core Engine (collector, event bus, shock detector, reaction classifier, state machine)
- ✅ TimescaleDB schema and retention policies
- ✅ API endpoints (radar, evidence, belief-states, health)
- ✅ Docker/AWS infrastructure patterns
- ✅ CI/CD pipeline structure

### Needs Modification
| Component | Current | Needed |
|-----------|---------|--------|
| Polymarket Connector | Read-only | Add order placement API |
| Portfolio Management | None | Position tracking, P&L |
| Order Execution | None | Order routing, slippage |
| Risk Management | None | Position limits, hedging |
| Backtesting | Replay (read-only) | Trade simulation, P&L |
| Signal Generation | Observation only | Entry/exit rules |

### Missing for Trading
1. Market order execution (Polymarket CLOB API integration)
2. Portfolio state management (positions, balances, P&L)
3. Risk controls (position limits, stop-loss, hedging)
4. Trade decision logic (signal → order mapping)
5. Backtesting framework (simulated fills, walk-forward testing)
6. Cross-market correlation analysis

---

## 7. Current Limitations & Technical Debt

- **Single-process event bus** (InMemoryEventBus) — not horizontally scalable
- **No cross-market correlation** — each market analyzed independently
- **Mixed SQLAlchemy approaches** — some async ORM, some raw SQL
- **No trading capabilities** — purely observational
- **Heatmap tile lag** during high-volatility periods
- **Some `/v1/radar` queries** do 100+ subqueries

---

## 8. Key Files Reference

### Core POC Engine
- `poc/models.py` - Data structures
- `poc/reactor.py` - Main orchestration
- `poc/shock_detector.py` - Shock detection
- `poc/reaction_classifier.py` - Classification

### Backend Services
- `backend/api/routes/v1.py` - API endpoints (1000+ lines)
- `backend/collector/main.py` - Polymarket integration
- `backend/heatmap/tile_generator.py` - Heatmap generation
- `backend/common/config.py` - Configuration

### Database
- `infra/init.sql` - Schema initialization (500+ lines)

### Frontend
- `frontend/src/lib/api.ts` - API client
- `frontend/src/components/evidence/EvidencePlayer.tsx` - Main viewer
- `frontend/src/components/evidence/HeatmapRenderer.tsx` - Visualization
