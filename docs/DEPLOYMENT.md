# Deployment Guide

## Overview

This document covers deployment, configuration, and operations for the Belief Reaction System.

## Prerequisites

- Python 3.11+
- PostgreSQL 15+ with TimescaleDB extension
- Redis (optional, for caching)
- Docker (optional, for containerized deployment)

## Quick Start

### 1. Environment Setup

```bash
# Clone and enter directory
cd market-sensemaking

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: .\venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # For development
```

### 2. Database Setup

```bash
# Start PostgreSQL with TimescaleDB (Docker)
docker run -d \
  --name belief-reaction-db \
  -p 5433:5432 \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=belief_reaction \
  timescale/timescaledb:latest-pg15

# Apply migrations
python -m backend.db.migrate
```

### 3. Configuration

Create a `.env` file or set environment variables:

```bash
# Database
DB_HOST=127.0.0.1
DB_PORT=5433
DB_NAME=belief_reaction
DB_USER=postgres
DB_PASSWORD=postgres

# Security
REQUIRE_AUTH=false          # Set to 'true' in production
ENABLE_THROTTLING=true
ENABLE_AUDIT=true
ADMIN_BOOTSTRAP_TOKEN=      # Optional: token for creating admin keys

# Alerting (optional)
SLACK_WEBHOOK_URL=          # Slack webhook URL
SLACK_CHANNEL=#alerts
SMTP_HOST=                  # SMTP server
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM_ADDR=alerts@belief-reaction.local
SMTP_TO_ADDRS=admin@example.com

# Polymarket
POLYMARKET_WS_URL=wss://ws-subscriptions-clob.polymarket.com/ws/market

# Logging
LOG_LEVEL=INFO
```

### 4. Start Services

```bash
# Start API server
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000

# In production, use gunicorn:
gunicorn backend.api.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

## API Key Management

### Bootstrap First Admin Key

When starting with no API keys, use the bootstrap endpoint:

```bash
# First-time bootstrap (no keys exist)
curl -X POST http://localhost:8000/admin/bootstrap

# Returns:
# {
#   "status": "success",
#   "message": "Admin API key created. Store this key securely...",
#   "key_id": "key_abc123",
#   "api_key": "brm_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
#   "roles": ["admin"]
# }
```

**Save the API key immediately - it will never be shown again!**

### Create Additional Keys

```bash
# Create a viewer key
curl -X POST http://localhost:8000/admin/keys \
  -H "X-API-Key: brm_YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Dashboard Viewer",
    "roles": ["viewer"],
    "expires_in_days": 90
  }'

# Create an operator key
curl -X POST http://localhost:8000/admin/keys \
  -H "X-API-Key: brm_YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Operations Team",
    "roles": ["operator"],
    "expires_in_days": 30
  }'
```

### Role Permissions

| Role | Permissions |
|------|-------------|
| `viewer` | radar:read, evidence:read, alerts:read, heatmap:read, metrics:read |
| `operator` | All viewer permissions + alerts:ack, alerts:resolve |
| `analyst` | All operator permissions + replay:read, replay:trigger |
| `admin` | All permissions (full access) |

## Production Deployment

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DB_HOST=db
      - DB_PORT=5432
      - DB_NAME=belief_reaction
      - DB_USER=postgres
      - DB_PASSWORD=${DB_PASSWORD}
      - REQUIRE_AUTH=true
      - ENABLE_THROTTLING=true
      - ENABLE_AUDIT=true
    depends_on:
      - db
    restart: unless-stopped

  db:
    image: timescale/timescaledb:latest-pg15
    environment:
      - POSTGRES_PASSWORD=${DB_PASSWORD}
      - POSTGRES_DB=belief_reaction
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    restart: unless-stopped

volumes:
  postgres_data:
```

### Kubernetes (Helm)

See `deploy/helm/` for Kubernetes deployment charts.

### Nginx Reverse Proxy

```nginx
upstream belief_api {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name api.belief-reaction.example.com;

    ssl_certificate /etc/ssl/certs/api.crt;
    ssl_certificate_key /etc/ssl/private/api.key;

    location / {
        proxy_pass http://belief_api;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket support for /v1/stream
    location /v1/stream {
        proxy_pass http://belief_api;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```

## Monitoring

### Health Checks

```bash
# Basic health check
curl http://localhost:8000/health

# Deep health check (system diagnostics)
curl http://localhost:8000/v1/health/deep
```

### Prometheus Metrics

Metrics are available at `/metrics` in Prometheus format:

```bash
curl http://localhost:8000/metrics
```

Key metrics:
- `belief_reaction_requests_total` - Total API requests
- `belief_reaction_request_duration_seconds` - Request latency histogram
- `belief_reaction_alerts_total` - Total alerts generated
- `belief_reaction_reactions_total` - Reactions classified by type
- `belief_reaction_tainted_windows_total` - Data integrity issues

### Alerting Configuration

Configure alert destinations via environment variables:

```bash
# Slack
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
SLACK_CHANNEL=#alerts
SLACK_MIN_PRIORITY=high
SLACK_CRITICAL_MENTIONS=U123456,U789012  # User IDs for @mentions

# Email
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=alerts@example.com
SMTP_PASSWORD=secret
SMTP_FROM_ADDR=alerts@example.com
SMTP_TO_ADDRS=admin@example.com,ops@example.com
SMTP_MIN_PRIORITY=high

# Generic Webhook
ALERT_WEBHOOK_URL=https://api.example.com/alerts
ALERT_WEBHOOK_AUTH=Authorization: Bearer your-token
WEBHOOK_MIN_PRIORITY=medium
```

## Operations

### System Control

```bash
# Start all services
curl -X POST http://localhost:8000/system/start \
  -H "X-API-Key: brm_YOUR_ADMIN_KEY"

# Stop all services
curl -X POST http://localhost:8000/system/stop \
  -H "X-API-Key: brm_YOUR_ADMIN_KEY"

# Restart specific service
curl -X POST http://localhost:8000/system/restart/collector \
  -H "X-API-Key: brm_YOUR_ADMIN_KEY"

# Check service status
curl http://localhost:8000/system/services \
  -H "X-API-Key: brm_YOUR_ADMIN_KEY"
```

### Data Collection

```bash
# Check collector status
curl http://localhost:8000/collector/status \
  -H "X-API-Key: brm_YOUR_ADMIN_KEY"

# Add token to track
curl -X POST http://localhost:8000/collector/tokens \
  -H "X-API-Key: brm_YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"token_ids": ["token_abc123"]}'

# List tracked tokens
curl http://localhost:8000/collector/tokens \
  -H "X-API-Key: brm_YOUR_ADMIN_KEY"
```

### Alert Management

```bash
# List alerts
curl "http://localhost:8000/v1/alerts?severity=HIGH&status=OPEN" \
  -H "X-API-Key: brm_YOUR_KEY"

# Acknowledge alert
curl -X PUT http://localhost:8000/v1/alerts/alert_123/ack \
  -H "X-API-Key: brm_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"note": "Investigating", "acked_by": "operator1"}'

# Resolve alert
curl -X PUT http://localhost:8000/v1/alerts/alert_123/resolve \
  -H "X-API-Key: brm_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"note": "False positive - market closed", "acked_by": "operator1"}'
```

## Troubleshooting

### Common Issues

#### Database Connection Failed
```
Error: could not connect to server: Connection refused
```
- Verify PostgreSQL is running: `docker ps | grep postgres`
- Check DB_HOST and DB_PORT environment variables
- Ensure firewall allows connection

#### API Key Invalid
```
{"error": "Invalid API key", "code": "INVALID_KEY"}
```
- Verify key starts with `brm_` prefix
- Check key hasn't been revoked: `GET /admin/keys`
- Ensure key hasn't expired

#### Rate Limited
```
{"error": "Rate limit exceeded", "code": "RATE_LIMITED", "retry_after_seconds": 1}
```
- Wait for retry_after period
- Consider increasing rate limits for production
- Use API key for higher limits

#### Evidence Grade Degraded
```
{"evidence_grade": "C", "warning": "Degraded evidence..."}
```
- Check for data gaps in time range
- Verify collector is running
- Review tainted_windows metric

### Logs

```bash
# API logs
tail -f /var/log/belief-reaction/api.log

# Collector logs
tail -f /var/log/belief-reaction/collector.log

# Audit logs (security events)
curl http://localhost:8000/v1/admin/audit \
  -H "X-API-Key: brm_YOUR_ADMIN_KEY"
```

## Security Considerations

### Production Checklist

- [ ] Set `REQUIRE_AUTH=true`
- [ ] Use HTTPS with valid certificates
- [ ] Set strong `ADMIN_BOOTSTRAP_TOKEN`
- [ ] Enable rate limiting (`ENABLE_THROTTLING=true`)
- [ ] Enable audit logging (`ENABLE_AUDIT=true`)
- [ ] Use secrets manager for credentials
- [ ] Set appropriate key expiration
- [ ] Review ACL permissions regularly
- [ ] Monitor for unusual API patterns

### Evidence Grade Policy (ADR-004)

The system enforces evidence quality requirements:

| Grade | Meaning | Max Alert Severity |
|-------|---------|-------------------|
| A | Full integrity | CRITICAL |
| B | Minor issues | CRITICAL |
| C | Degraded | MEDIUM (no CRITICAL/HIGH) |
| D | Tainted | LOW only |

CRITICAL/HIGH alerts require Grade A or B evidence.

## Backup & Recovery

### Database Backup

```bash
# Full backup
pg_dump -h localhost -p 5433 -U postgres belief_reaction > backup.sql

# Restore
psql -h localhost -p 5433 -U postgres belief_reaction < backup.sql
```

### Configuration Backup

Backup these items:
- `.env` file
- API keys (export from /admin/keys before deletion)
- ACL entries (export from /admin/acl)
- Alert configurations

## Support

- Documentation: `docs/`
- ADRs: `docs/adr/`
- Issues: https://github.com/anthropics/claude-code/issues
