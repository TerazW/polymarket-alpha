# Operator Guide

## Batch test 50 events (category = politics)
Run from repo root:

```bash
python backend/scripts/event_batch_test.py --category politics --target-events 50 --format json --output event_report.json
```

Notes:
- `--source auto` (default) uses DB if category data exists, otherwise Polymarket API.
- Use `--source api` to force Polymarket API fetch (requires network access).
- Use `--format table` for a quick tabular report.

## Replay hash consistency check
Run a deterministic replay verification for a token window:

```bash
curl -X POST http://localhost:8000/v1/replay/verify ^
  -H "Content-Type: application/json" ^
  -d "{\"token_id\":\"<TOKEN_ID>\",\"from_ts\":1700000000000,\"to_ts\":1700003600000,\"strict_order\":true}"
```

Expected response fields:
- `input_hash`, `output_hash`, `expected_hash`, `match`
- `events_count`, `replay_status`
