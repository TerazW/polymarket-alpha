# ADR 001: Market Sensemaking Paradigm Principles

**Status:** Accepted
**Date:** 2024-01-05
**Authors:** System Architecture Team

## Context

This document records the fundamental design principles of the Market Sensemaking system. These principles guide all architectural and implementation decisions, ensuring the system produces reliable, auditable evidence of market behavior.

## Core Philosophy

> "看存在没意义，看反应才有意义"
> "Observing existence is meaningless; observing reactions reveals meaning."

Traditional order book analysis focuses on static snapshots—what orders exist at a moment. This system instead observes **reactions**: how the order book responds to external shocks (trades). The reaction pattern reveals the market maker's true belief state, which static analysis cannot capture.

## Decision

We adopt the following paradigm principles as immutable constraints:

### Principle 1: Reaction Classification (7 Atomic Types)

All observed market behavior must be classified into exactly 7 reaction types, ordered by severity:

| Priority | Type | Chinese | Meaning |
|----------|------|---------|---------|
| 1 | VACUUM | 真空 | Complete liquidity disappearance |
| 2 | SWEEP | 扫单 | Multiple levels swept / rapid repricing |
| 3 | CHASE | 追价 | Anchor moved, belief repricing |
| 4 | PULL | 撤退 | Immediate cancellation after shock |
| 5 | HOLD | 防守 | Quick refill, firm belief defense |
| 6 | DELAYED | 犹豫 | Partial/slow refill, wavering belief |
| 7 | NO_IMPACT | 无影响 | Shock too small to matter |

**Rationale:** These 7 types form a complete vocabulary for describing market maker behavior. They are mutually exclusive and collectively exhaustive. The priority order ensures deterministic classification when multiple conditions apply.

**Constraint:** The 7-type classification must be consistent between:
- POC engine (`poc/models.py`)
- Backend schemas (`backend/common/schemas.py`)
- API responses (`/api/reaction-types`)
- Frontend displays

### Principle 2: Belief State Machine (4 States)

Market belief transitions through 4 discrete states:

```
STABLE ──> FRAGILE ──> CRACKING ──> BROKEN
   │          │           │           │
   └──────────┴───────────┴───────────┘
              (recovery possible)
```

| State | Indicator | Meaning |
|-------|-----------|---------|
| STABLE | 🟢 | Strong defense, hold_ratio >= 70% |
| FRAGILE | 🟡 | Wavering, single PULL or CHASE/SWEEP detected |
| CRACKING | 🟠 | Breaking, VACUUM or multiple PULLs |
| BROKEN | 🔴 | Collapsed, multi-anchor VACUUM or repeated warning signals |

**State Transition Rules (Deterministic):**

```
BROKEN (highest priority):
  - n_vacuum >= 2 from different anchors
  - OR (n_depth_collapse >= 1 AND n_vacuum >= 1)
  - OR n_pre_shock_pull >= 2

CRACKING:
  - n_vacuum >= 1
  - OR n_pull >= 2
  - OR n_pre_shock_pull >= 1
  - OR n_depth_collapse >= 1

FRAGILE:
  - (n_delayed >= 2 AND hold_ratio < 0.7)
  - OR n_pull == 1
  - OR n_chase + n_sweep >= 1

STABLE (default):
  - All other cases
```

### Principle 3: Determinism Guarantee

> "同一证据包，不同机器回放结果必须相同"
> "Same evidence bundle, different machines, identical replay results."

The system must produce **bit-identical** outputs for identical inputs:

1. **Event Ordering:** Events with same timestamp must have stable sort order via `(ts, sort_seq, token_id, type)` tuple.

2. **Time Source:** System must use event timestamps, never wall clock. The `ReplayContext` enforces this during replay.

3. **Hash Computation:** Bundle hashes must be:
   - Order-independent (internal sorting)
   - Float-normalized (8 decimal places)
   - Platform-independent (xxhash64)

4. **State Machine:** Given same event sequence, belief state transitions must be identical.

**Testing Requirement:** All determinism guarantees must have adversarial tests in `tests/adversarial/test_determinism.py` and `tests/adversarial/test_belief_state_replay.py`.

### Principle 4: Evidence Trail Completeness

Every state change must be traceable to source events:

```
StateChange
  ├── timestamp
  ├── old_state / new_state
  ├── evidence[] (human-readable descriptions)
  └── evidence_refs[] (event IDs for replay)
```

**Constraint:** No state change without evidence. The `evidence_refs` must point to actual events in the 30-minute rolling window.

### Principle 5: Anchor-Centric Analysis

Only events at **anchor price levels** affect belief state. Non-anchor events are observed but not counted for state transitions.

Anchor selection criteria:
- `peak_size`: Historical maximum depth at price level
- `persistence`: Time maintaining >50% of peak
- `anchor_score = w1 * log(1+peak) + w2 * log(1+persistence_seconds)`

Top K anchors (default K=5) per side (bid/ask) are tracked.

### Principle 6: Security by Design

Dangerous operations require multiple authorization layers:

| Operation | Requirements |
|-----------|--------------|
| Event injection | ENV flag + ADMIN role + `dangerous:inject` permission |
| System restart | ADMIN role + `dangerous:restart` permission |
| Data deletion | ADMIN role + `dangerous:delete` permission |

All dangerous operations are logged to audit trail with:
- Actor identification
- Timestamp
- Operation details
- Client IP and user agent

## Consequences

### Positive

1. **Auditability:** Every decision traceable to evidence
2. **Reproducibility:** Replays produce identical results
3. **Testability:** Deterministic rules enable comprehensive testing
4. **Interpretability:** 7 reaction types + 4 states = human-understandable vocabulary

### Negative

1. **Rigidity:** Changing classification rules requires careful migration
2. **Complexity:** Determinism constraints add implementation overhead
3. **Performance:** Evidence tracking has storage/memory costs

### Neutral

1. **Learning Curve:** New developers must understand the paradigm
2. **Documentation:** Principles must be kept in sync with implementation

## Compliance Verification

The following tests verify compliance with these principles:

| Principle | Test Location |
|-----------|---------------|
| 7 Reaction Types | `tests/test_reaction_engine.py` |
| 4 Belief States | `tests/adversarial/test_belief_state_replay.py` |
| Determinism | `tests/adversarial/test_determinism.py` |
| Evidence Trail | `tests/adversarial/test_belief_state_replay.py::TestEvidenceIntegrity` |
| Anchor Analysis | `tests/test_leading_events.py` |
| Security | `tests/test_reactor_api.py::TestEventInjection` |

## References

- [Belief Reaction System Whitebook](../Belief_Reaction_System_Whitebook.txt)
- [Engineering Spec](../Belief_Reaction_System_Engineering_Spec.txt)
- [Replay Spec](../REPLAY_SPEC.md)
- [Consistency Spec](../CONSISTENCY_SPEC.md)
