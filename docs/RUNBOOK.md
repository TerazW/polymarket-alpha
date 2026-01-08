# Belief Reaction System - Runbook

Operational runbook for incident response and system management.

## Quick Reference

| Severity | Response Time | Escalation | On-Call |
|----------|---------------|------------|---------|
| CRITICAL | 5 min | Immediate | Page |
| HIGH | 15 min | 30 min | Slack |
| MEDIUM | 1 hour | 4 hours | Ticket |
| LOW | 24 hours | 1 week | Backlog |

---

## 1. Alert Response Procedures

### 1.1 CRACKING/BROKEN State Alert

**Symptoms:**
- Belief state transitioned to CRACKING or BROKEN
- High VACUUM/PULL ratio
- Low HOLD ratio (< 50%)

**Investigation Steps:**
1. Open Evidence view for the token
2. Check evidence chain (Shock → Reaction → State)
3. Review reaction distribution
4. Compare with similar historical cases

**Actions:**
```
# Check current state
GET /v1/evidence/{token_id}

# Review evidence chain
GET /v1/alerts/{alert_id}/chain

# Check reaction distribution
GET /v1/reactions/distribution?token_id={token_id}
```

**Resolution:**
- If market naturally recovered: Resolve with evidence
- If false positive: Mark as false positive with reason

---

### 1.2 Data Integrity Alert (Grade C/D)

**Symptoms:**
- Evidence grade degraded to C or D
- Hash mismatch detected
- Missing data buckets

**Investigation Steps:**
1. Check DataHealth metrics
2. Review hash verification status
3. Check upstream data sources

**Actions:**
```bash
# Check data health
curl http://localhost:8000/v1/health/deep

# Verify bundle hash
python cli/replay_audit.py verify --token {token_id} --t0 {timestamp}

# Check for gaps
python cli/replay_audit.py gaps --token {token_id} --from {start} --to {end}
```

**Resolution:**
- If data source issue: Contact upstream provider
- If hash mismatch: Trigger rebuild for affected window
- Update evidence grade after recovery

---

### 1.3 System Performance Alert

**Symptoms:**
- P95 latency > 500ms
- Error rate > 1%
- WebSocket disconnections

**Investigation Steps:**
1. Check resource utilization (CPU, memory, connections)
2. Review recent deployments
3. Check database query performance

**Actions:**
```bash
# Check system metrics
curl http://localhost:8000/v1/system/metrics

# Check connection pool
curl http://localhost:8000/v1/health/deep

# Review slow queries
psql -c "SELECT * FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 10"
```

**Resolution:**
- Scale resources if needed
- Roll back recent deployment if correlated
- Optimize slow queries

---

## 2. Common Operations

### 2.1 Alert Management

**Acknowledge Alert:**
```bash
curl -X PUT http://localhost:8000/v1/alerts/{alert_id}/ack \
  -H "Content-Type: application/json" \
  -d '{"note": "Investigating", "acked_by": "operator1"}'
```

**Mute Alert (v5.36):**
```bash
curl -X PUT http://localhost:8000/v1/alerts/{alert_id}/mute \
  -H "Content-Type: application/json" \
  -d '{"duration_minutes": 30, "reason": "Known issue, fix in progress", "muted_by": "operator1"}'
```

**Unmute Alert:**
```bash
curl -X PUT http://localhost:8000/v1/alerts/{alert_id}/unmute?unmuted_by=operator1
```

**Resolve Alert:**
```bash
curl -X PUT http://localhost:8000/v1/alerts/{alert_id}/resolve \
  -H "Content-Type: application/json" \
  -d '{"note": "Market stabilized", "resolved_by": "operator1"}'
```

**Mark as False Positive:**
```bash
curl -X PUT http://localhost:8000/v1/alerts/{alert_id}/resolve \
  -H "Content-Type: application/json" \
  -d '{
    "is_false_positive": true,
    "false_positive_reason": "THIN_MARKET",
    "note": "Low liquidity caused false trigger",
    "resolved_by": "operator1"
  }'
```

---

### 2.2 Replay Operations

**Trigger Replay:**
```bash
python cli/replay_audit.py replay \
  --token {token_id} \
  --from {start_ts} \
  --to {end_ts} \
  --verify
```

**Verify Bundle:**
```bash
python cli/replay_audit.py verify \
  --token {token_id} \
  --t0 {timestamp}
```

**Export Evidence:**
```bash
python cli/replay_audit.py export \
  --token {token_id} \
  --from {start_ts} \
  --to {end_ts} \
  --format json \
  > evidence_export.json
```

---

### 2.3 Data Operations

**Check Data Health:**
```bash
# Overall health
curl http://localhost:8000/v1/health/deep

# Token-specific health
curl http://localhost:8000/v1/evidence/{token_id} | jq '.proof_summary.data_health'
```

**Rebuild Data Window:**
```bash
# Request rebuild (admin only)
curl -X POST http://localhost:8000/admin/rebuild \
  -H "X-API-Key: {admin_key}" \
  -d '{"token_id": "{token_id}", "from_ts": {start}, "to_ts": {end}}'
```

---

## 3. Emergency Procedures

### 3.1 Full System Outage

1. **Assess** - Check all services (API, collector, reactor)
2. **Communicate** - Notify stakeholders
3. **Diagnose** - Review logs, metrics, recent changes
4. **Recover** - Follow service-specific recovery
5. **Document** - Post-incident review

**Service Health Checks:**
```bash
# API
curl http://localhost:8000/v1/health

# Collector
curl http://localhost:8001/health

# WebSocket
wscat -c ws://localhost:8000/v1/stream
```

### 3.2 Data Corruption

1. **Stop** ingestion to prevent further corruption
2. **Identify** affected time range
3. **Isolate** corrupted data (mark as TAINTED)
4. **Rebuild** from upstream sources
5. **Verify** with hash checks

### 3.3 Runaway Alerts

If alert storm detected:

1. **Mute** affected token alerts temporarily
2. **Investigate** root cause
3. **Adjust** thresholds if needed
4. **Unmute** after resolution

---

## 4. Monitoring Dashboards

| Dashboard | Purpose | URL |
|-----------|---------|-----|
| Radar Overview | All markets state | `/dashboard/radar` |
| Alert Queue | Active alerts | `/dashboard/alerts` |
| System Health | Infrastructure | `/dashboard/health` |
| Evidence Viewer | Specific market | `/market/{tokenId}` |

---

## 5. Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| Primary On-Call | TBD | PagerDuty |
| Secondary | TBD | PagerDuty |
| Engineering Lead | TBD | Slack |
| Product | TBD | Email |

---

## 6. Key Metrics

### SLAs
- API P95 latency: < 500ms
- WebSocket reconnect: < 5s
- Data freshness: < 10s
- Alert delivery: < 1s

### Thresholds
- HOLD ratio healthy: > 60%
- Data coverage: > 95%
- Hash verification: 100%

---

## 7. Paradigm Reminders

When handling incidents, remember:

1. **Evidence, not prediction** - We show what happened, not what will happen
2. **Structure over events** - Focus on reaction patterns, not individual trades
3. **No outcomes in similar cases** - Never show what happened after a pattern match
4. **Grade-severity binding** - Low-grade evidence cannot produce high-severity alerts

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-06 | System | Initial runbook |
