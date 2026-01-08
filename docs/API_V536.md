# API v5.36 - Expert Review Features

This document covers the new API endpoints introduced in v5.36 based on expert review recommendations.

## Overview

v5.36 addresses three key product gaps identified in the expert review:

| Gap | Chinese | Solution |
|-----|---------|----------|
| Counter-evidence | 反证 | Evidence Chain + Counterfactual "why not worse" |
| Comparison | 比较 | Multi-market comparison + Similar cases |
| Constraints | 约束 | Evidence grade enforcement + Latency disclosure |

## New Endpoints

### 1. Evidence Chain API

**GET /v1/alerts/{alert_id}/chain**

Returns the complete evidence chain for an alert, enforcing the paradigm: "不能只看最终状态".

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| alert_id | string | Yes | Alert ID |
| window_before_ms | int | No | Time window before alert (default: 60000, max: 3600000) |

#### Response

```json
{
  "alert_id": "alert_123",
  "token_id": "token_abc",
  "generated_at": 1700000000000,
  "chain": [
    {
      "node_type": "SHOCK",
      "node_id": "shock_456",
      "ts": 1700000000000,
      "summary": "Shock @ 72% (BID, VOLUME)",
      "details": {"price": 0.72, "side": "BID", "trigger_type": "VOLUME"},
      "evidence_refs": []
    },
    {
      "node_type": "REACTION",
      "node_id": "reaction_789",
      "ts": 1700000010000,
      "summary": "VACUUM @ 72% (FAST)",
      "details": {"reaction_type": "VACUUM", "refill_ratio": 0.1},
      "evidence_refs": ["shock_456"]
    },
    {
      "node_type": "STATE_CHANGE",
      "node_id": "state_012",
      "ts": 1700000020000,
      "summary": "FRAGILE → CRACKING",
      "details": {"old_state": "FRAGILE", "new_state": "CRACKING"},
      "evidence_refs": ["reaction_789"]
    },
    {
      "node_type": "ALERT",
      "node_id": "alert_123",
      "ts": 1700000030000,
      "summary": "Market cracking detected",
      "details": {"severity": "HIGH", "alert_type": "CRACKING"},
      "evidence_refs": ["state_012"]
    }
  ],
  "shock_count": 1,
  "reaction_count": 1,
  "leading_event_count": 0,
  "state_change_count": 1,
  "chain_start_ts": 1700000000000,
  "chain_end_ts": 1700000030000,
  "chain_duration_ms": 30000
}
```

---

### 2. Reaction Distribution API

**GET /v1/reactions/distribution**

Returns aggregated reaction type distribution for a token. Implements: "强调结构，淡化事件".

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| token_id | string | Yes | Token ID |
| window_minutes | int | No | Time window (default: 30, range: 1-1440) |

#### Response

```json
{
  "token_id": "token_abc",
  "from_ts": 1700000000000,
  "to_ts": 1700001800000,
  "window_minutes": 30,
  "total_reactions": 100,
  "distribution": [
    {"reaction_type": "HOLD", "count": 60, "ratio": 0.6},
    {"reaction_type": "PULL", "count": 20, "ratio": 0.2},
    {"reaction_type": "VACUUM", "count": 10, "ratio": 0.1},
    {"reaction_type": "SWEEP", "count": 5, "ratio": 0.05},
    {"reaction_type": "CHASE", "count": 5, "ratio": 0.05}
  ],
  "hold_dominant": true,
  "stress_ratio": 0.3
}
```

#### Structural Metrics

- `hold_dominant`: True if HOLD reactions > 50% of total
- `stress_ratio`: Ratio of stress reactions (VACUUM + PULL + SWEEP) to total

---

### 3. Similar Cases API

**GET /v1/similar-cases**

Finds historically similar reaction patterns. Critical: Does NOT show outcomes.

Implements: "不给结果，只给对齐后的证据"

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| token_id | string | Yes | Token ID to find similar cases for |
| window_minutes | int | No | Window to extract pattern (default: 30, range: 5-120) |
| search_days | int | No | Days of history to search (default: 30, range: 1-90) |
| max_results | int | No | Maximum matches (default: 5, range: 1-20) |

#### Response

```json
{
  "query_pattern": ["HOLD", "PULL", "VACUUM"],
  "query_state": "CRACKING",
  "query_ts": 1700000000000,
  "matches": [
    {
      "match_id": "match_token123_1699900000",
      "token_id": "token_123",
      "market_title": "Will Event X Happen?",
      "match_ts": 1699900000000,
      "similarity_score": 0.85,
      "pattern_summary": "HOLD → PULL → VACUUM",
      "reaction_sequence": ["HOLD", "PULL", "VACUUM"],
      "state_at_match": "CRACKING"
    }
  ],
  "total_matches": 3,
  "search_window_days": 30,
  "paradigm_note": "Similar patterns identified. No outcomes shown - observe current evidence only."
}
```

#### Paradigm Enforcement

- **No outcome data**: The response intentionally excludes what happened after the matched pattern
- **paradigm_note**: Reminds users this is NOT a prediction tool

---

### 4. Multi-Market Comparison API

**GET /events/{event_id}/compare**

Compares how the same event affected multiple markets.

Implements: "同事件多市场对比"

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| event_id | string | Yes | Event ID to compare across markets |
| token_ids | string | Yes | Comma-separated list of token IDs |
| window_before_ms | int | No | Time window before event (default: 60000) |
| window_after_ms | int | No | Time window after event (default: 60000) |

#### Response

```json
{
  "event_id": "event_123",
  "event_ts": 1700000000000,
  "event_type": "SHOCK",
  "markets": [
    {
      "token_id": "token_a",
      "market_title": "Market A",
      "time_series": [
        {"ts": 1700000000000, "state": "STABLE", "hold_ratio": 0.8},
        {"ts": 1700000010000, "state": "FRAGILE", "hold_ratio": 0.6, "reaction_type": "PULL"}
      ],
      "final_state": "FRAGILE"
    },
    {
      "token_id": "token_b",
      "market_title": "Market B",
      "time_series": [
        {"ts": 1700000000000, "state": "STABLE", "hold_ratio": 0.9},
        {"ts": 1700000010000, "state": "STABLE", "hold_ratio": 0.85, "reaction_type": "HOLD"}
      ],
      "final_state": "STABLE"
    }
  ],
  "divergence_detected": true,
  "divergence_summary": "Market A transitioned to FRAGILE while Market B remained STABLE. Possible cause: lower baseline liquidity in Market A.",
  "paradigm_note": "Comparison shows structural differences in market reactions to the same event."
}
```

---

### 5. Enhanced Alert Resolution

**PUT /v1/alerts/{alert_id}/resolve**

Resolves an alert with system-generated recovery evidence.

v5.36 changes:
- `recovery_evidence`: System-generated evidence supporting resolution
- `is_false_positive`: Mark as false positive for algorithm improvement
- `false_positive_reason`: Required when `is_false_positive=true`

#### Request Body

```json
{
  "note": "Market recovered naturally",
  "resolved_by": "operator1",
  "is_false_positive": false,
  "false_positive_reason": null
}
```

For false positives:

```json
{
  "note": "Low liquidity caused false trigger",
  "resolved_by": "operator1",
  "is_false_positive": true,
  "false_positive_reason": "THIN_MARKET"
}
```

#### False Positive Reasons

| Reason | Description |
|--------|-------------|
| THIN_MARKET | Low liquidity caused false trigger |
| NOISE | Random noise, not meaningful signal |
| MANIPULATION | Detected manipulation pattern |
| STALE_DATA | Data lag/staleness caused false trigger |
| THRESHOLD_TOO_SENSITIVE | Need to adjust thresholds |
| OTHER | Other reason (requires note) |

#### Response

```json
{
  "alert_id": "alert_123",
  "status": "RESOLVED",
  "resolved_at": 1700001000000,
  "resolved_by": "operator1",
  "note": "Market recovered naturally",
  "recovery_evidence": [
    "Current belief state: STABLE",
    "State last changed at: 1700000800000",
    "State has recovered from alert trigger condition",
    "Recent HOLD ratio: 75% (15/20 reactions)",
    "Depth defense active (HOLD > 50%)"
  ],
  "is_false_positive": false,
  "false_positive_reason": null
}
```

---

## Schema Changes

### RadarRow

Field renamed: `confidence` → `evidence_confidence`

```json
{
  "evidence_confidence": 85.0,
  "evidence_grade": "A"
}
```

### StateExplanationInfo

Field renamed: `confidence` → `classification_confidence`

```json
{
  "classification_confidence": 92.0
}
```

### LatencyInfo (New)

Disclosure of detection latency to prevent system being mistaken as prediction.

```json
{
  "event_ts": 1700000000000,
  "detected_ts": 1700000001000,
  "detection_latency_ms": 1000,
  "window_type": "FAST",
  "observation_end_ts": 1700000005000
}
```

---

## Counterfactual Enhancements

v5.36 adds "why not worse" counterfactuals in addition to recovery paths:

```json
{
  "counterfactuals": [
    {
      "target_state": "STABLE",
      "conditions": ["Hold ratio increase to 80%", "No vacuums for 15min"],
      "likelihood": "high"
    },
    {
      "target_state": "NOT_FRAGILE",
      "conditions": ["Hold ratio 75% >= 70% threshold", "No vacuum in 10min"],
      "likelihood": "n/a"
    }
  ]
}
```

The "NOT_X" target states explain why the current state didn't deteriorate further, with `likelihood: "n/a"` indicating this is an explanation, not a prediction.

---

## Migration Notes

### Database

Apply migration: `infra/migrations/v5.36_alert_recovery_evidence.sql`

Adds:
- `recovery_evidence TEXT[]`
- `is_false_positive BOOLEAN`
- `false_positive_reason TEXT`
- `false_positive_analysis` view

### Frontend

Update RadarRow usage:
- `row.confidence` → `row.evidence_confidence ?? row.confidence`

New components:
- `ReactionDistributionPanel`
- `SimilarCasesPanel`
- `EvidenceChainPanel`
