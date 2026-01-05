# ADR 004: Evidence Integrity Contract

**Status:** Accepted
**Date:** 2024-01-05
**Authors:** System Architecture Team

## Context

The system's core value proposition is **auditable, reproducible evidence**. Without strict integrity guarantees, the system degrades into just another unreliable data pipeline.

This ADR defines the contract for what constitutes valid evidence and how integrity is maintained.

## Decision

We establish the following evidence integrity contracts:

---

### Contract 1: What Is Truth?

The system has three data layers. Truth flows from raw to derived:

```
Layer 1: raw_events     (SOURCE OF TRUTH)
    ↓
Layer 2: tiles          (COMPRESSED REPRESENTATION)
    ↓
Layer 3: derived_events (COMPUTED: reactions, states, alerts)
```

**Truth Hierarchy:**

| Layer | Description | Mutability | Authority |
|-------|-------------|------------|-----------|
| raw_events | WebSocket messages as received | Append-only | Highest |
| tiles | Time-bucketed depth snapshots | Recomputable | Medium |
| derived_events | Reactions, states, alerts | Recomputable | Lowest |

**Conflict Resolution:** If tiles or derived_events conflict with raw_events, raw_events are always correct. The other layers must be recomputed.

---

### Contract 2: Tainted Windows

A window is **tainted** when its evidence cannot be trusted for deterministic replay:

| Taint Reason | Code | Description |
|--------------|------|-------------|
| DATA_GAP | `T1` | Missing events in time range |
| REBUILD_REQUIRED | `T2` | Tiles need regeneration |
| HASH_MISMATCH | `T3` | Computed hash differs from stored |
| CLOCK_DRIFT | `T4` | Event timestamps out of expected order |
| SOURCE_DISCONNECT | `T5` | WebSocket disconnect during window |

**Tainted Window Handling:**

```python
class TaintedWindow:
    token_id: str
    window_start: int  # ms
    window_end: int    # ms
    taint_codes: List[str]  # ["T1", "T3"]
    detected_at: int
    resolved_at: Optional[int]
    resolution: Optional[str]  # "REBUILD", "DISCARD", "MANUAL"
```

**Policy:** Tainted windows MUST be:
1. Logged with full details
2. Excluded from determinism tests
3. Marked in API responses (`tainted: true`)
4. Tracked in `tainted_window_rate` metric

---

### Contract 3: Hash Computation

Bundle hashes ensure evidence integrity. The hash algorithm is:

```python
def compute_bundle_hash(bundle: dict) -> str:
    """
    Compute deterministic hash for evidence bundle.

    Requirements:
    1. Order-independent (sort all arrays)
    2. Float-normalized (8 decimal places)
    3. Platform-independent (xxhash64)
    4. Encoding-independent (UTF-8)
    """
    # 1. Canonicalize
    canonical = canonicalize(bundle)

    # 2. Serialize to JSON with sorted keys
    json_bytes = json.dumps(canonical, sort_keys=True).encode('utf-8')

    # 3. Hash with xxhash64
    return xxhash.xxh64(json_bytes).hexdigest()
```

**Canonicalization Rules:**

| Data Type | Rule |
|-----------|------|
| Floats | Round to 8 decimal places |
| Timestamps | Integer milliseconds |
| Arrays | Sort by stable key before hashing |
| Nulls | Exclude from hash (not "null") |
| Strings | UTF-8, no trailing whitespace |

---

### Contract 4: Rebuild Policy

When evidence must be rebuilt:

| Trigger | Action | Scope |
|---------|--------|-------|
| Hash mismatch | Rebuild tiles + derived | Single bundle |
| Data gap filled | Rebuild affected windows | Time range |
| Algorithm update | Rebuild all | Full dataset |
| Manual request | Rebuild specified | As requested |

**Rebuild Constraints:**

1. **Audit Trail:** Every rebuild is logged with:
   - Trigger reason
   - Scope (bundles affected)
   - Old hash vs new hash
   - Timestamp

2. **Idempotency:** Rebuilding the same bundle twice produces the same hash

3. **Notification:** API consumers are notified when bundles they've cached have been rebuilt

---

### Contract 5: Evidence Retention

| Data Type | Retention | Storage |
|-----------|-----------|---------|
| raw_events | 90 days | TimescaleDB hypertable |
| tiles | 30 days | TimescaleDB + S3 archive |
| derived_events | 30 days | TimescaleDB |
| bundle_hashes | Indefinite | PostgreSQL |
| audit_log | 1 year | PostgreSQL |

**Pruning Policy:**

1. Raw events older than 90 days are deleted
2. Before deletion, verify archived tiles exist
3. Bundle hashes are NEVER deleted (audit trail)

---

### Contract 6: Verification Tests

The following tests verify evidence integrity:

```python
# tests/adversarial/test_evidence_integrity.py

class TestHashStability:
    """Same bundle → same hash (100 runs)"""

class TestRebuildIdempotency:
    """Rebuild twice → same result"""

class TestTaintDetection:
    """Data gaps → window marked tainted"""

class TestCrossArchitectureHash:
    """Same bundle on x86 vs ARM → same hash"""

class TestFloatNormalization:
    """0.123456789 → 0.12345679 (8 decimals)"""

class TestArrayOrdering:
    """Shuffled arrays → same hash after sort"""
```

---

### Contract 7: API Evidence Headers

All evidence API responses include integrity headers:

```http
HTTP/1.1 200 OK
X-Bundle-Hash: a1b2c3d4e5f6g7h8
X-Bundle-Computed-At: 2024-01-05T12:00:00Z
X-Bundle-Tainted: false
X-Bundle-Rebuild-Count: 0
Content-Type: application/json
```

Clients SHOULD cache `X-Bundle-Hash` and verify on subsequent requests.

---

## Consequences

### Positive

1. **Auditability:** Every bundle has cryptographic proof
2. **Detectability:** Integrity violations are caught automatically
3. **Recoverability:** Tainted windows are logged for investigation
4. **Reproducibility:** Rebuilds produce identical results

### Negative

1. **Overhead:** Hash computation adds latency
2. **Storage:** Hash history requires permanent storage
3. **Complexity:** Taint handling adds code paths

### Neutral

1. **Monitoring:** Requires `tainted_window_rate` metric tracking

---

## References

- [ADR-001: Paradigm Principles](./001-paradigm-principles.md)
- [ADR-003: Language Governance](./003-language-governance.md)
- [Consistency Spec](../CONSISTENCY_SPEC.md)
- [Replay Spec](../REPLAY_SPEC.md)
