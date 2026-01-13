# Feature Coverage Matrix

Sources:
- docs/feature guide.txt
- docs/# Belief Reaction System - user whitepaper

Legend: Implemented? = Yes / Partial / No

## Core Principles and Determinism
| Feature | Spec source | Implemented? | Code location | Gap / mismatch | Proposed fix |
|---|---|---|---|---|---|
| Evidence-only paradigm (no prediction) | Both | Partial | `frontend/src/components/evidence/EvidenceDisclaimer.tsx`, `backend/api/schemas/v1.py` | Disclaimers exist but are not enforced across all UI surfaces; no automated language checks | Small: add language-check CI + require disclaimer on all major panels |
| Evidence-first framing (observe reactions, not existence) | Both | Partial | `backend/collector/main.py`, `poc/reaction_classifier.py` | Pipeline aligns with spec, but UI wording is not uniformly evidence-first | Small: scrub UI copy for evidence-only tone |
| Determinism guarantee (same inputs -> same outputs) | Both | Partial | `backend/common/determinism.py`, `backend/replay/engine.py`, `backend/api/routes/v1.py` | Replay verify endpoint exists, but not wired into UI; live pipeline still allows wall clock | Small: surface replay verify in UI and enforce event-time in live pipeline |
| Language governance (forbidden terms list) | Both | Partial | `docs/adr/003-language-governance.md` | No CI enforcement and no repository-level scan | Small: add language-check workflow and fix violations |

## Data Collection and Processing
| Feature | Spec source | Implemented? | Code location | Gap / mismatch | Proposed fix |
|---|---|---|---|---|---|
| Polymarket data source connection | Both | Yes | `utils/polymarket_ws.py`, `backend/collector/main.py`, `utils/polymarket_api.py` | None noted | Small: add reconnect metrics (optional) |
| Time bucket sampling | Feature guide | Yes | `poc/config.py`, `backend/collector/main.py` | None noted | Small: make bucket size configurable via config file |
| Price level tracking | Feature guide | Yes | `poc/models.py`, `backend/collector/main.py` | None noted | Small: persist in DB for audit if needed |
| Baseline calculation per level | Feature guide | Yes | `poc/models.py`, `poc/shock_detector.py`, `poc/leading_events.py` | None noted | Small: export baseline to evidence response (optional) |
| Raw event storage for replay/debug | Both | Yes | `backend/collector/main.py` (save_raw_event) | None noted | Small: add retention policy metrics |
| Market metadata ingestion | Whitepaper | Partial | `backend/collector/main.py` (get_top_markets) | No event-level selection flow or eligibility rules | Medium: implement event eligibility layer (Task F) |

## Event Detection System
| Feature | Spec source | Implemented? | Code location | Gap / mismatch | Proposed fix |
|---|---|---|---|---|---|
| Shock detection (volume/consecutive) | Both | Yes | `poc/shock_detector.py`, `backend/collector/main.py` | None noted | Small: expose thresholds in config API |
| Dual-window FAST/SLOW reaction windows | Feature guide | Yes | `poc/shock_detector.py`, `poc/reaction_classifier.py` | None noted | Small: add window config export |
| Leading event: PRE_SHOCK_PULL | Both | Yes | `poc/leading_events.py` | None noted | Small: add proof fields to API |
| Leading event: DEPTH_COLLAPSE | Both | Yes | `poc/leading_events.py` | None noted | Small: add proof fields to API |
| Leading event: GRADUAL_THINNING | Both | Yes | `poc/leading_events.py` | None noted | Small: add proof fields to API |

## Reaction Classification Engine
| Feature | Spec source | Implemented? | Code location | Gap / mismatch | Proposed fix |
|---|---|---|---|---|---|
| Priority order for classification | Feature guide | Partial | `poc/reaction_classifier.py` | NO_IMPACT is handled as a pre-check; spec lists it as lowest priority | Small: document the pre-check in docs or align ordering |
| Reaction: VACUUM | Both | Yes | `poc/reaction_classifier.py`, `poc/models.py` | None noted | Small: expose proof fields in API consistently |
| Reaction: SWEEP | Both | Yes | `poc/reaction_classifier.py`, `poc/models.py` | None noted | Small: expose proof fields in API consistently |
| Reaction: CHASE | Both | Yes | `poc/reaction_classifier.py`, `poc/models.py` | None noted | Small: expose proof fields in API consistently |
| Reaction: PULL | Both | Yes | `poc/reaction_classifier.py`, `poc/models.py` | None noted | Small: expose proof fields in API consistently |
| Reaction: HOLD | Both | Yes | `poc/reaction_classifier.py`, `poc/models.py` | None noted | Small: expose proof fields in API consistently |
| Reaction: DELAYED | Both | Yes | `poc/reaction_classifier.py`, `poc/models.py` | None noted | Small: expose proof fields in API consistently |
| Reaction: NO_IMPACT | Both | Yes | `poc/reaction_classifier.py`, `poc/models.py` | None noted | Small: expose proof fields in API consistently |
| Reaction proof metrics (drop_ratio, refill_ratio, shift_ticks, durations) | Feature guide | Partial | `poc/reaction_classifier.py`, `backend/api/routes/v1.py` | Some fields are missing or defaulted in UI conversion | Small: pass proof fields end-to-end |
| Reaction attribution (trade vs cancel) | Feature guide | Partial | `backend/common/attribution.py` | Library exists but is not wired into reaction pipeline or API | Medium: compute attribution during classification and expose in API |
| Reaction distribution summary | Whitepaper | Yes | `backend/api/routes/v1.py` (`/v1/reactions/distribution`), `frontend/src/components/evidence/ReactionDistributionPanel.tsx` | None noted | Small: add data health badge per window |

## Belief State Machine
| Feature | Spec source | Implemented? | Code location | Gap / mismatch | Proposed fix |
|---|---|---|---|---|---|
| Four-state model (STABLE/FRAGILE/CRACKING/BROKEN) | Both | Yes | `poc/belief_state_machine.py`, `backend/api/schemas/v1.py` | None noted | Small: add state tests in UI |
| Deterministic transition rules | Feature guide | Partial | `poc/belief_state_machine.py` | Uses wall-clock in parts of pipeline; no replay enforcement | Medium: ensure event-time usage for transitions |
| State explanation (headline, factors) | Feature guide | Partial | `backend/radar/explain.py`, `backend/api/routes/v1.py` | Generated but not shown in UI | Small: render explanation in ContextPanel |
| Counterfactual conditions | Feature guide | Partial | `backend/radar/explain.py` | Generated but not shown in UI | Small: add counterfactuals to UI |
| Trend direction | Feature guide | Partial | `backend/radar/explain.py` | Not surfaced in UI | Small: add optional trend display |

## Visualization Components
| Feature | Spec source | Implemented? | Code location | Gap / mismatch | Proposed fix |
|---|---|---|---|---|---|
| Radar view | Both | Yes | `frontend/src/app/page.tsx`, `frontend/src/lib/api.ts` | None noted | Small: add evidence grade badge |
| Evidence Player (heatmap + overlays + timeline) | Both | Yes | `frontend/src/components/evidence/EvidencePlayer.tsx` | None noted | Small: tune layout spacing as needed |
| Depth heatmap (L2) | Both | Yes | `frontend/src/components/evidence/HeatmapRenderer.tsx`, `backend/heatmap/tile_generator.py` | None noted | Small: verify normalization controls |
| Event overlay (shock/reaction/leading/state) | Feature guide | Yes | `frontend/src/components/evidence/EvidencePlayer.tsx` (drawOverlay) | None noted | Small: add legend |
| Timeline controls (scrubber and markers) | Feature guide | Yes | `frontend/src/components/evidence/EvidencePlayer.tsx` | None noted | Small: add zoom indicators |
| Anchor level markers | Feature guide | Yes | `frontend/src/components/evidence/EvidencePlayer.tsx`, `frontend/src/components/evidence/ContextPanel.tsx` | None noted | Small: show anchor rank |
| Heatmap tiles (LOD + compression) | Both | Yes | `backend/heatmap/tile_generator.py`, `backend/api/routes/v1.py` | None noted | Small: add tile freshness metadata |
| Context panel | Feature guide | Yes | `frontend/src/components/evidence/ContextPanel.tsx` | None noted | Small: show evidence grade |
| Reaction timeline | Feature guide | Yes | `frontend/src/components/evidence/EvidencePlayer.tsx` | None noted | Small: add state change labels |
| Data degradation overlay (STALE/TAINTED) | Feature guide | Yes | `frontend/src/components/evidence/EvidencePlayer.tsx` | None noted | Small: include reason code |
| Evidence disclaimer watermark | Both | Yes | `frontend/src/components/evidence/EvidenceDisclaimer.tsx` | None noted | Small: ensure visible on radar |
| Tile staleness indicator | Feature guide | Yes | `frontend/src/components/evidence/TileStalenessIndicator.tsx` | None noted | Small: wire to data health events |
| Hash verification badge | Feature guide | Partial | `frontend/src/components/evidence/HashVerification.tsx`, `backend/evidence/bundle_hash.py` | UI does not compute hash; only echoes stored value | Medium: compute hash client-side or expose computed hash in API |
| Evidence chain panel | Whitepaper | Partial | `frontend/src/components/evidence/EvidenceChainPanel.tsx`, `backend/api/routes/v1.py` (`/v1/alerts/{id}/chain`) | Component not wired into main UI | Small: add panel toggle in alert detail |
| Similar cases panel | Whitepaper | Yes | `frontend/src/components/evidence/SimilarCasesPanel.tsx`, `backend/api/routes/v1.py` (`/v1/similar-cases`) | None noted | Small: show data health badge |

## Alerts System
| Feature | Spec source | Implemented? | Code location | Gap / mismatch | Proposed fix |
|---|---|---|---|---|---|
| Alert generation (shock/reaction/leading/state) | Both | Yes | `backend/reactor/alert_generator.py`, `backend/collector/main.py` | None noted | Small: include evidence grade in generation |
| Alert types: SHOCK/REACTION/LEADING_EVENT/STATE_CHANGE | Both | Partial | `backend/reactor/alert_generator.py`, `backend/api/schemas/v1.py` | Router uses category-based routing that does not match type enums | Medium: unify alert type and category schemas |
| Severity levels: CRITICAL/HIGH/MEDIUM/LOW | Both | Yes | `backend/reactor/alert_generator.py`, `backend/api/schemas/v1.py` | None noted | Small: enforce grade-based severity policy |
| Alert lifecycle (OPEN -> ACKED -> RESOLVED, plus MUTED with expiry) | Feature guide | Partial | `backend/alerting/ops.py`, `backend/api/routes/v1.py` | Auto-unmute added in alerts API, but ops manager still uses expanded statuses and UI actions are missing | Medium: align ops state machine and add UI actions |
| Resolution requirements (recovery evidence or false-positive reason) | Feature guide | Yes | `backend/api/routes/v1.py` | None noted | Small: add UI for false-positive reasons |
| Alert disclaimer (evidence-only) | Feature guide | Partial | `backend/api/schemas/v1.py`, `backend/api/routes/reactor.py`, `frontend/src/components/evidence/AlertsPanel.tsx` | Now included in WS payloads and alerts list, but not shown in all alert surfaces | Small: render disclaimer wherever alerts are displayed |
| Alert operations endpoints (ack/resolve/mute/unmute) | Feature guide | Partial | `backend/api/routes/v1.py` | Not wired to ops manager; no UI for actions | Medium: align ops + add UI actions |
| Alert inbox UI | Whitepaper | Partial | `frontend/src/components/evidence/AlertsPanel.tsx` | Basic list exists, but no filters/actions or alert details | Medium: add filters, ack/resolve actions, and detail view |

## Replay System
| Feature | Spec source | Implemented? | Code location | Gap / mismatch | Proposed fix |
|---|---|---|---|---|---|
| Replay catalog | Both | Yes | `backend/api/routes/v1.py` (`/v1/replay/catalog`), `frontend/src/app/replay/page.tsx` | None noted | Small: add data health badge |
| Deterministic replay engine | Both | Partial | `backend/replay/engine.py`, `backend/common/determinism.py`, `backend/api/routes/v1.py` | Replay verify API exists but not wired into UI | Small: add replay verify to UI |
| Event ordering (token_id, ts_ms, seq) | Feature guide | Partial | `backend/replay/engine.py`, `backend/api/routes/v1.py` | Replay verify uses canonical ordering; live pipeline still allows non-canonical order | Medium: enforce ordering in live pipeline and report violations |
| Replay context strict mode | Feature guide | Yes | `backend/common/determinism.py`, `backend/api/routes/v1.py` | None noted | Small: surface strict toggle in UI |
| Hash verification (input_hash/output_hash/expected_hash) | Both | Partial | `backend/replay/engine.py`, `backend/replay/verifier.py`, `backend/api/routes/v1.py` | Replay verify API exists but no UI and expected hash may be missing for long windows | Small: add UI + bundle hash coverage checks |
| Replay modes (strict vs lenient) | Feature guide | Partial | `backend/api/routes/v1.py` | API supports strict flag; no UI toggle | Small: add UI toggle |
| Replay UI playback | Whitepaper | Partial | `frontend/src/app/replay/page.tsx` | Catalog only; no replay execution or hash check | Medium: add replay run/check UI |

## Evidence Integrity and Data Health
| Feature | Spec source | Implemented? | Code location | Gap / mismatch | Proposed fix |
|---|---|---|---|---|---|
| Evidence grade (A/B/C/D) | Both | Partial | `backend/alerting/evidence_grade.py`, `backend/api/schemas/v1.py`, `frontend/src/components/evidence/EvidencePlayer.tsx` | API returns default grade; no real computation | Medium: compute grade from data health and hashes |
| Data health monitoring (missing buckets, rebuilds, hash mismatch) | Both | Partial | `backend/monitoring/health.py`, `backend/api/routes/v1.py` | API returns placeholder zeros; UI assumes health | Medium: compute and persist metrics |
| Bundle hash | Both | Partial | `backend/evidence/bundle_hash.py`, `backend/api/routes/v1.py` | Hash computed but no expected hash verification or response headers | Medium: store and verify hashes |
| Tile checksum / validation | Feature guide | Partial | `backend/heatmap/tile_generator.py` | Checksum is emitted but not verified on read | Small: add optional checksum verification |
| Tainted window tracking | Feature guide | No | N/A | No taint tracking or API fields | Medium: implement taint model and API flag |

## API Coverage
| Feature | Spec source | Implemented? | Code location | Gap / mismatch | Proposed fix |
|---|---|---|---|---|---|
| Core endpoints: /v1/radar, /v1/evidence, /v1/alerts, /v1/heatmap/tiles, /v1/replay/catalog | Both | Yes | `backend/api/routes/v1.py` | None noted | Small: add auth requirement on prod |
| Alert operations: ack/resolve/mute/unmute | Feature guide | Yes | `backend/api/routes/v1.py` | Behavior not aligned with alert ops manager | Medium: align status model |
| Analysis endpoints: /v1/alerts/{id}/chain, /v1/reactions/distribution, /v1/similar-cases | Feature guide | Yes | `backend/api/routes/v1.py` | None noted | Small: add pagination for similar cases |
| Authentication (API key) | Whitepaper | Partial | `backend/security/auth.py`, `backend/api/middleware.py` | Not required by default (REQUIRE_AUTH=false) | Small: enforce in prod |
| Subscription tiers | Whitepaper | No | N/A | No tier enforcement or limits in backend/frontend | Large: implement tiering and limits |

## Real-time Stream
| Feature | Spec source | Implemented? | Code location | Gap / mismatch | Proposed fix |
|---|---|---|---|---|---|
| WebSocket connection /v1/stream | Both | Yes | `backend/api/routes/v1.py`, `backend/api/stream.py` | None noted | Small: add auth guard |
| Subscription management (token_ids, event_types, min_severity) | Feature guide | Yes | `backend/api/stream.py` | None noted | Small: add rate limits |
| Message types (alert, state_update, data_health) | Feature guide | Partial | `backend/api/stream.py`, `frontend/src/hooks/useStream.ts` | Some types defined but not emitted (data_health) | Medium: emit data health events |
| Connection management (heartbeat, reconnect) | Feature guide | Yes | `backend/api/stream.py`, `frontend/src/hooks/useStream.ts` | None noted | Small: expose connection stats in UI |

## Advanced Features
| Feature | Spec source | Implemented? | Code location | Gap / mismatch | Proposed fix |
|---|---|---|---|---|---|
| Anchor level tracking | Feature guide | Yes | `poc/leading_events.py`, `backend/api/routes/v1.py` | None noted | Small: persist anchor history |
| Reaction attribution tracking | Feature guide | Partial | `backend/common/attribution.py` | Not used in pipeline or UI | Medium: compute and display |
| Counterfactual conditions | Feature guide | Partial | `backend/radar/explain.py` | Not surfaced in UI | Small: add to ContextPanel |
| False positive tracking | Feature guide | Partial | `backend/api/schemas/v1.py`, `backend/api/routes/v1.py` | Not enforced on resolve; no UI | Medium: enforce + add UI |
| Tile freshness indicator | Feature guide | Yes | `frontend/src/components/evidence/TileStalenessIndicator.tsx` | None noted | Small: include tile age in API |
