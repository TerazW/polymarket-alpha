# ADR 002: API Endpoint Separation

**Status:** Accepted
**Date:** 2024-01-05
**Authors:** System Architecture Team

## Context

The system has grown to include many API endpoints across multiple domains. Without clear organization, this leads to:
- User confusion about which endpoints to use
- Accidental access to dangerous operations
- Difficulty applying different security policies
- Poor API documentation structure

## Decision

Separate API endpoints into two logical groups with distinct security policies:

### Group 1: User-Facing (Data) APIs

**Purpose:** Read market data, evidence, and states
**Security:** Standard API key authentication (any role)
**Prefix:** `/api/v1/` and `/api/reactor/` (read endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/health` | GET | Basic health check |
| `/api/v1/radar` | GET | Market radar view |
| `/api/v1/evidence` | GET | Evidence bundles |
| `/api/v1/alerts` | GET | Alert list |
| `/api/v1/heatmap/tiles` | GET | Heatmap data |
| `/api/v1/replay/catalog` | GET | Replay bundle catalog |
| `/api/reactor/stats` | GET | Reactor statistics |
| `/api/reactor/reactions` | GET | Reaction events |
| `/api/reactor/states` | GET | Belief states |
| `/api/reactor/state/{token_id}` | GET | Single market state |
| `/api/reactor/leading-events` | GET | Leading events |
| `/api/reactor/markets` | GET | Tracked markets |
| `/api/reactor/health` | GET | Reactor health |

### Group 2: Operational (Admin) APIs

**Purpose:** Control system lifecycle, modify state
**Security:** ADMIN role required
**Prefix:** `/api/system/`, `/api/collector/`, and specific action endpoints

| Endpoint | Method | Description | Permission |
|----------|--------|-------------|------------|
| `/api/system/start` | POST | Start system | admin:config |
| `/api/system/stop` | POST | Stop system | admin:config |
| `/api/system/restart` | POST | Restart system | admin:config |
| `/api/system/config` | GET | View configuration | admin:config |
| `/api/collector/start` | POST | Start collector | admin:config |
| `/api/collector/stop` | POST | Stop collector | admin:config |
| `/api/collector/tokens` | POST/DELETE | Modify tokens | admin:config |
| `/api/reactor/start` | POST | Start reactor | admin:config |
| `/api/reactor/stop` | POST | Stop reactor | admin:config |
| `/api/reactor/events` | POST | Inject events | dangerous:inject |
| `/api/v1/alerts/{id}/ack` | PUT | Acknowledge alert | alerts:ack |
| `/api/v1/alerts/{id}/resolve` | PUT | Resolve alert | alerts:resolve |

### Group 3: Dangerous Operations (Restricted)

**Purpose:** Operations that can damage data or inject false information
**Security:** ADMIN role + specific permission + environment flag
**Audit:** All attempts logged

| Endpoint | Permission | Env Flag |
|----------|------------|----------|
| `/api/reactor/events` | dangerous:inject | REACTOR_ALLOW_INJECTION=true |

## API Documentation Tags

The OpenAPI/Swagger documentation should use these tags:

```python
tags = [
    {"name": "Data", "description": "Read-only market data endpoints"},
    {"name": "Reactor", "description": "Reaction engine state and events"},
    {"name": "Evidence", "description": "Evidence bundle operations"},
    {"name": "Alerts", "description": "Alert management"},
    {"name": "System", "description": "System lifecycle (ADMIN)"},
    {"name": "Collector", "description": "Data collection (ADMIN)"},
    {"name": "Dangerous", "description": "Dangerous operations (ADMIN + permission)"},
]
```

## Implementation

### Current State

Endpoints are organized by route files:
- `routes/v1.py` - User data APIs
- `routes/reactor.py` - Reactor APIs (mixed read/write)
- `routes/system.py` - System control (admin)
- `routes/collector.py` - Collector control (admin)

### Recommended Changes

1. **Add Permission Middleware:** Apply role checks to admin endpoints
2. **Update OpenAPI Tags:** Group endpoints by function in docs
3. **Separate Routers:** Consider moving write endpoints to separate files
4. **Document Clearly:** README should explain the separation

### Migration Path

1. Add tags to existing endpoints (no breaking changes)
2. Add permission checks to admin endpoints (authorization)
3. Document the separation in API docs
4. Future: Consider separate API versions for user vs admin

## Consequences

### Positive

- Clear separation of concerns
- Easier to apply different security policies
- Better API documentation
- Safer developer experience

### Negative

- Some code duplication in permission checks
- Must maintain documentation of separation

## Example Permission Check

```python
from fastapi import Depends, HTTPException
from backend.security import get_api_key, check_permission

async def require_admin(api_key = Depends(get_api_key)):
    if not check_permission(api_key.roles, "admin:config"):
        raise HTTPException(403, "Admin access required")
    return api_key

@router.post("/start")
async def start_system(api_key = Depends(require_admin)):
    """Start system - requires admin role."""
    pass
```
