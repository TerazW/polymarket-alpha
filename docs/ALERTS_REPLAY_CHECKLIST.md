# Alerts & Replay Verification Checklist

## Alerts (API + UI)
- [ ] `/v1/alerts` returns `OPEN | ACKED | RESOLVED | MUTED` statuses
- [ ] `ACK` only works for `OPEN` alerts; `RESOLVED` is rejected
- [ ] `RESOLVE` includes recovery evidence **or** false-positive reason
- [ ] `MUTED` alerts auto-return to `OPEN` after `muted_until`
- [ ] Alert payloads include evidence-only disclaimer
- [ ] Alerts list renders severity, status, summary, and timestamp
- [ ] No predictive or directional language in alert summaries

## Replay (Determinism)
- [ ] Replay uses event timestamps only (no wall clock in processing)
- [ ] Event ordering uses `(token_id, ts_ms, seq)` stable sort
- [ ] `/v1/replay/verify` returns `input_hash`, `output_hash`, `expected_hash`, `match`
- [ ] `strict_order=true` fails on sort violations
- [ ] Hash match is deterministic across repeated runs
