# WebSocket Stream Guide

Real-time event streaming for the Belief Reaction System.

> **Important**: This stream provides *observed evidence* of market microstructure changes.
> It does NOT provide trading signals or outcome predictions.

---

## Quick Start

### Connect

```javascript
const ws = new WebSocket('wss://api.your-domain.com/v1/stream');

// With API key (recommended)
const ws = new WebSocket('wss://api.your-domain.com/v1/stream?api_key=brm_xxx');
```

### Subscribe to Topics

```javascript
ws.onopen = () => {
  // Subscribe to specific markets
  ws.send(JSON.stringify({
    action: 'subscribe',
    topics: ['alerts', 'states'],
    token_ids: ['token_abc', 'token_def']  // Optional: filter by tokens
  }));
};
```

### Receive Events

```javascript
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  switch (msg.type) {
    case 'alert':
      console.log('Alert:', msg.data);
      break;
    case 'state_update':
      console.log('State changed:', msg.data);
      break;
    case 'data_health':
      console.log('Data issue:', msg.data);
      break;
  }
};
```

---

## Topics

| Topic | Description | Message Type |
|-------|-------------|--------------|
| `alerts` | New alerts (CRITICAL/HIGH/MEDIUM/LOW) | `alert` |
| `states` | Belief state changes | `state_update` |
| `health` | Data integrity warnings | `data_health` |

### Subscription Limits by Tier

| Tier | Max Topics | Max Tokens | Concurrent Connections |
|------|------------|------------|------------------------|
| Observer | 1 | 20 | 1 |
| Analyst | 3 | 100 | 2 |
| Institution | All | 500 | 5 |

---

## Message Formats

### Alert Message

```json
{
  "type": "alert",
  "data": {
    "alert_id": "alert_abc123",
    "token_id": "token_xyz",
    "ts": 1704067200000,
    "severity": "HIGH",
    "evidence_grade": "A",
    "type": "STATE_CHANGE",
    "summary": "Belief state → CRACKING",
    "evidence_ref": {
      "token_id": "token_xyz",
      "t0": 1704067200000
    },
    "disclaimer": "This alert indicates observed belief instability. It does NOT imply outcome direction or trading recommendation."
  }
}
```

### State Update Message

```json
{
  "type": "state_update",
  "data": {
    "token_id": "token_xyz",
    "state": "CRACKING",
    "previous_state": "FRAGILE",
    "timestamp": 1704067200000,
    "evidence_refs": ["reaction_abc", "reaction_def"]
  }
}
```

### Data Health Message

```json
{
  "type": "data_health",
  "data": {
    "token_id": "token_xyz",
    "issue": "MISSING_BUCKETS",
    "severity": "WARNING",
    "timestamp": 1704067200000,
    "details": {
      "missing_count": 3,
      "window_minutes": 10
    }
  }
}
```

---

## Connection Management

### Heartbeat

Server sends ping every 30 seconds. Client must respond with pong.

```javascript
ws.on('ping', () => {
  ws.pong();
});
```

### Reconnection Strategy

If disconnected, implement exponential backoff:

```javascript
const INITIAL_DELAY = 1000;   // 1 second
const MAX_DELAY = 60000;      // 60 seconds
const MULTIPLIER = 2;

let delay = INITIAL_DELAY;

function reconnect() {
  setTimeout(() => {
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      delay = INITIAL_DELAY;  // Reset on success
      resubscribe(ws);
    };

    ws.onclose = () => {
      delay = Math.min(delay * MULTIPLIER, MAX_DELAY);
      reconnect();
    };
  }, delay);
}
```

### Subscription Management

```javascript
// Subscribe
ws.send(JSON.stringify({
  action: 'subscribe',
  topics: ['alerts'],
  token_ids: ['token_abc']
}));

// Unsubscribe
ws.send(JSON.stringify({
  action: 'unsubscribe',
  topics: ['alerts'],
  token_ids: ['token_abc']
}));

// List current subscriptions
ws.send(JSON.stringify({
  action: 'list_subscriptions'
}));
```

---

## Rate Limits

| Action | Limit |
|--------|-------|
| Connection attempts | 10/minute per IP |
| Subscribe/Unsubscribe | 30/minute per connection |
| Message receive | Unlimited (server-push only) |

### Rate Limit Response

```json
{
  "type": "error",
  "code": "RATE_LIMITED",
  "message": "Too many subscription changes",
  "retry_after_seconds": 60
}
```

---

## Error Handling

### Error Codes

| Code | Meaning | Action |
|------|---------|--------|
| `INVALID_TOKEN` | API key invalid | Check credentials |
| `RATE_LIMITED` | Too many requests | Wait and retry |
| `SUBSCRIPTION_LIMIT` | Too many subscriptions | Upgrade tier or reduce |
| `INVALID_TOPIC` | Unknown topic | Check topic name |
| `INVALID_TOKEN_ID` | Token not found | Verify token_id |

### Error Message Format

```json
{
  "type": "error",
  "code": "SUBSCRIPTION_LIMIT",
  "message": "Maximum 20 tokens allowed for Observer tier",
  "details": {
    "current": 20,
    "requested": 25,
    "limit": 20
  }
}
```

---

## Best Practices

### DO

- ✅ Subscribe only to tokens you actively monitor
- ✅ Implement reconnection with exponential backoff
- ✅ Handle all message types (including errors)
- ✅ Keep connections alive with pong responses
- ✅ Unsubscribe when tokens no longer needed

### DON'T

- ❌ Subscribe to all available tokens
- ❌ Reconnect immediately without backoff
- ❌ Ignore data_health warnings
- ❌ Treat alerts as trading signals
- ❌ Open multiple connections unnecessarily

---

## Example: Full Client Implementation

```javascript
class BeliefReactionClient {
  constructor(apiKey, options = {}) {
    this.apiKey = apiKey;
    this.baseUrl = options.baseUrl || 'wss://api.belief-reaction.com';
    this.reconnectDelay = 1000;
    this.maxReconnectDelay = 60000;
    this.subscriptions = new Set();
    this.ws = null;
  }

  connect() {
    const url = `${this.baseUrl}/v1/stream?api_key=${this.apiKey}`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log('[WS] Connected');
      this.reconnectDelay = 1000;  // Reset
      this.resubscribe();
    };

    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      this.handleMessage(msg);
    };

    this.ws.onclose = (event) => {
      console.log(`[WS] Disconnected: ${event.code}`);
      this.scheduleReconnect();
    };

    this.ws.onerror = (error) => {
      console.error('[WS] Error:', error);
    };
  }

  handleMessage(msg) {
    switch (msg.type) {
      case 'alert':
        this.onAlert(msg.data);
        break;
      case 'state_update':
        this.onStateUpdate(msg.data);
        break;
      case 'data_health':
        this.onDataHealth(msg.data);
        break;
      case 'error':
        this.onError(msg);
        break;
      case 'subscribed':
        console.log('[WS] Subscription confirmed:', msg.topics);
        break;
    }
  }

  subscribe(topics, tokenIds = []) {
    const sub = { topics, token_ids: tokenIds };
    this.subscriptions.add(JSON.stringify(sub));

    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        action: 'subscribe',
        ...sub
      }));
    }
  }

  unsubscribe(topics, tokenIds = []) {
    const sub = { topics, token_ids: tokenIds };
    this.subscriptions.delete(JSON.stringify(sub));

    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        action: 'unsubscribe',
        ...sub
      }));
    }
  }

  resubscribe() {
    for (const sub of this.subscriptions) {
      const { topics, token_ids } = JSON.parse(sub);
      this.ws.send(JSON.stringify({
        action: 'subscribe',
        topics,
        token_ids
      }));
    }
  }

  scheduleReconnect() {
    setTimeout(() => {
      console.log(`[WS] Reconnecting in ${this.reconnectDelay}ms...`);
      this.connect();
      this.reconnectDelay = Math.min(
        this.reconnectDelay * 2,
        this.maxReconnectDelay
      );
    }, this.reconnectDelay);
  }

  // Override these in your application
  onAlert(alert) {
    console.log('[Alert]', alert.severity, alert.summary);
  }

  onStateUpdate(update) {
    console.log('[State]', update.token_id, update.state);
  }

  onDataHealth(health) {
    console.warn('[Health]', health.token_id, health.issue);
  }

  onError(error) {
    console.error('[Error]', error.code, error.message);
  }

  close() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}

// Usage
const client = new BeliefReactionClient('brm_your_api_key');
client.connect();
client.subscribe(['alerts', 'states'], ['token_abc', 'token_def']);
```

---

## Paradigm Reminder

> **This WebSocket stream provides evidence of observed market behavior.**
>
> - Alerts indicate *what has been detected*, not *what will happen*
> - State changes reflect *structural patterns*, not *price predictions*
> - Evidence grade indicates *data quality*, not *confidence in outcomes*
>
> **Never interpret these signals as trading recommendations.**

---

## Support

- API Documentation: `/docs/API_V536.md`
- Runbook: `/docs/RUNBOOK.md`
- Issues: https://github.com/anthropics/claude-code/issues
