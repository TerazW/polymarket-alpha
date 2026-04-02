# Polymarket CLOB API — Research Summary

## 1. API Base URLs

| Service | URL |
|---------|-----|
| **CLOB REST API** (production) | `https://clob.polymarket.com` |
| **Gamma Markets API** | `https://gamma-api.polymarket.com` (market discovery; e.g. `/markets?limit=10`) |
| **Testnet CLOB** | Same host structure but using chain ID 80002 (Polygon Amoy) |

---

## 2. Network and Chain Configuration

- **Production chain**: Polygon Mainnet (chain ID **137**)
- **Testnet**: Polygon Amoy (chain ID **80002**)
- **Collateral token decimals**: 6
- **Conditional token decimals**: 6

---

## 3. Smart Contract Addresses (Polygon Mainnet, chain 137)

| Contract | Address |
|----------|---------|
| **Main Exchange** | `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` |
| **Neg Risk Exchange** | `0xC5d563A36AE78145C45a50134d48A1215220f80a` |
| **Neg Risk Adapter** | `0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296` |
| **Collateral (USDC)** | `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` |
| **Conditional Tokens (CTF)** | `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` |

Amoy testnet addresses: Exchange `0xdFE02Eb6733538f8Ea35D585af8DE5958AD99E40`, Collateral `0x9c4e1703476e875070ee25b56a58b008cfb8fa78`, CTF `0x69308FB512518e39F9b16112fA8d994F4e2Bf8bB`.

---

## 4. Authentication

Three-tiered auth model:

| Level | What's Needed | Access |
|-------|--------------|--------|
| **L0** | Host URL only | Public market data (prices, orderbooks, markets) |
| **L1** | Host + private key + chain_id | Create/derive API keys, sign orders |
| **L2** | Host + private key + chain_id + ApiCreds | Post orders, cancel, get trades, manage account |

**Signature types** (for order signing):
- `0` (default): Standard EOA — MetaMask, hardware wallets, raw private keys
- `1`: Email/Magic wallet (delegated signing)
- `2`: Browser wallet proxy signatures

**Funder address**: Required when the signing key differs from the address holding funds (proxy/smart-contract wallets). For EOA wallets where the private key directly controls the funded address, funder can be omitted or set to the same address.

**API key flow**: Call `create_or_derive_api_creds()` which returns an `ApiCreds` object. Store it securely — credentials cannot be recovered after creation.

---

## 5. All REST Endpoints

Base: `https://clob.polymarket.com`

### Server
- `GET /time` — server timestamp

### Auth / API Keys
- `POST /auth/api-key` — create API key (L1)
- `GET /auth/api-keys` — list API keys (L2)
- `DELETE /auth/api-key` — delete API key (L2)
- `POST /auth/derive-api-key` — derive existing key (L1)
- `GET /auth/ban-status/closed-only` — check ban status
- `POST /auth/readonly-api-key` — create readonly key
- `GET /auth/readonly-api-keys` — list readonly keys
- `DELETE /auth/readonly-api-key` — delete readonly key
- `POST /auth/validate-readonly-api-key` — validate readonly key (public)

### Market Data (public, L0)
- `GET /midpoint?token_id=X` — mid-market price
- `GET /midpoints` — batch midpoints
- `GET /price?token_id=X&side=BUY` — best price for side
- `GET /prices` — batch prices
- `GET /spread?token_id=X` — bid-ask spread
- `GET /spreads` — batch spreads
- `GET /last-trade-price?token_id=X` — last executed price
- `GET /last-trades-prices` — batch last prices
- `GET /tick-size?token_id=X` — minimum tick size
- `GET /neg-risk?token_id=X` — negative risk flag
- `GET /fee-rate?token_id=X` — base fee rate (in bps)
- `GET /book?token_id=X` — full orderbook
- `GET /books` — batch orderbooks
- `GET /prices-history` — historical prices

### Markets (public, L0)
- `GET /markets` — full market list (paginated with `next_cursor`)
- `GET /markets/{condition_id}` — single market by condition_id
- `GET /simplified-markets` — simplified market list
- `GET /sampling-markets` — sampling markets
- `GET /sampling-simplified-markets` — sampling simplified markets

### Orders (L2)
- `POST /order` — post single order
- `POST /orders` — post multiple orders
- `GET /data/order/{order_id}` — get order by ID
- `GET /data/orders` — list user's orders
- `DELETE /order` — cancel single order
- `DELETE /orders` — cancel multiple orders
- `DELETE /cancel-all` — cancel all orders
- `DELETE /cancel-market-orders` — cancel by market/asset

### Trades (L2)
- `GET /data/trades` — user's trade history

### Account (L2)
- `GET /balance-allowance` — balance and allowance info
- `POST /balance-allowance/update` — update balance/allowance
- `GET /notifications` — user notifications
- `DELETE /notifications` — drop notifications

### Scoring
- `GET /order-scoring` — check if order is scoring (earning rewards)
- `GET /orders-scoring` — batch scoring check

### Heartbeat
- `POST /v1/heartbeats` — keep-alive; if no heartbeat within **10 seconds**, all orders are auto-cancelled

### Live Activity
- `GET /live-activity/events/{condition_id}` — market trade events

### Rewards
- `GET /rewards/user`, `/rewards/user/total`, `/rewards/user/percentages`, `/rewards/user/markets`
- `GET /rewards/markets/current`, `/rewards/markets/{id}`

### RFQ (Request for Quote)
- `POST /rfq/request` — create RFQ request
- `DELETE /rfq/request` — cancel RFQ request
- `GET /rfq/data/requests` — list RFQ requests
- `POST /rfq/quote` — create quote
- `DELETE /rfq/quote` — cancel quote
- `GET /rfq/data/requester/quotes`, `/rfq/data/quoter/quotes` — list quotes
- `GET /rfq/data/best-quote` — best quote
- `POST /rfq/request/accept` — accept RFQ request
- `POST /rfq/quote/approve` — approve quote
- `GET /rfq/config` — RFQ configuration

### Builder
- `GET /builder/trades` — trades originated by builder

---

## 6. Order Types

| Type | Description |
|------|-------------|
| **GTC** | Good-Till-Cancelled. Default for limit orders. Stays on the book until filled or cancelled. |
| **GTD** | Good-Till-Date. Time-bounded limit order; expires at specified time. |
| **FOK** | Fill-or-Kill. Used for market orders. Must fill entirely and immediately, or the entire order is rejected. |
| **FAK** | Fill-and-Kill. Fills as much as possible immediately; unfilled remainder is cancelled (partial fill OK). |

**Limit order params**: `token_id`, `price` (0.00-1.00), `size` (shares), `side` (BUY/SELL)
**Market order params**: `token_id`, `amount` (dollar amount), `side`, `order_type` (FOK)
**Post options**: `post_only` flag available (maker-only, rejected if would cross)

---

## 7. Tick Sizes

Valid tick sizes: `"0.1"`, `"0.01"`, `"0.001"`, `"0.0001"`

Each market has a specific tick size retrievable via `GET /tick-size?token_id=X`. Prices must be rounded to the market's tick size. The client caches tick sizes with a default TTL of 300 seconds.

---

## 8. Token Mechanics

- Each market has **two outcome tokens**: YES and NO (identified by separate `token_id` values)
- Prices range from **$0.00 to $1.00** per share
- YES price + NO price = $1.00 (approximately, minus spread)
- Collateral is **USDC** (6 decimals) on Polygon
- Outcome tokens are **Conditional Tokens (CTF ERC-1155)** at address `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`
- **Negative risk** markets use a separate exchange contract and adapter
- Token IDs are discovered via the Gamma Markets API (`GET https://gamma-api.polymarket.com/markets`) — the `clobTokenIds` field contains a JSON array with [YES_token_id, NO_token_id]
- **Token allowances** must be set for EOA/MetaMask wallets (approve USDC and CTF for the three exchange contracts). Email/Magic wallets handle this automatically.

---

## 9. Fee Structure

- Fees are per-token/per-market, retrieved via `GET /fee-rate?token_id=X`
- Returned in **basis points (bps)** — e.g., 200 = 2%
- Charged to **order makers on proceeds**
- Fee fields in trade records: `fee_rate_bps` and `feeUsdc`
- Exact fee schedule is server-side and may vary by market

---

## 10. WebSocket / Real-Time Feeds

The official CLOB clients (Python and TypeScript) do **not** include WebSocket functionality. The clients are purely REST-based.

However, the existing market-sensemaking project already uses WebSocket at:
- `wss://ws-subscriptions-clob.polymarket.com/ws/market`

This provides:
- `book` — full order book snapshot
- `price_change` — incremental level updates (size = NEW aggregate, NOT delta)
- `last_trade_price` — trade execution
- `tick_size_change` — tick adjustment at extreme prices

Real-time data can also be achieved via polling REST endpoints (orderbook, prices, trades).

The **heartbeat mechanism** (`POST /v1/heartbeats`) is a REST call that must be sent every 10 seconds to keep orders alive when using heartbeat mode.

---

## 11. Pagination

All list endpoints use cursor-based pagination:
- Pass `next_cursor` parameter (default: `"MA=="` which is base64 for "0")
- End sentinel: `"LTE="` (base64 for "-1") indicates no more pages

---

## 12. Gamma Markets API

Separate from the CLOB API. Base URL: `https://gamma-api.polymarket.com`
- `GET /markets` — returns market metadata including `condition_id`, `clobTokenIds`, question text, volume, etc.
- Used for **market discovery** — you get token IDs here, then trade via the CLOB API
- The CLOB API also has `/markets` and `/simplified-markets` endpoints that return similar data

---

## 13. Python Client

```bash
pip install py-clob-client    # requires Python 3.9+
```

### Basic Usage

```python
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType

# L0: Public data only
client = ClobClient("https://clob.polymarket.com")

# Get orderbook
book = client.get_order_book(token_id="0x123...")
print(book)

# Get midpoint
mid = client.get_midpoint(token_id="0x123...")

# L1: Create API credentials
client = ClobClient(
    "https://clob.polymarket.com",
    key="0xYOUR_PRIVATE_KEY",
    chain_id=137,
)
creds = client.create_or_derive_api_creds()

# L2: Trading
client = ClobClient(
    "https://clob.polymarket.com",
    key="0xYOUR_PRIVATE_KEY",
    chain_id=137,
    creds=creds,
)

# Place a limit order (GTC)
order = client.create_order(
    OrderArgs(
        token_id="0x123...",
        price=0.50,
        size=100,
        side="BUY",
    )
)
resp = client.post_order(order)
print(resp)

# Place a market order (FOK)
order = client.create_order(
    OrderArgs(
        token_id="0x123...",
        price=0.55,  # worst acceptable price
        size=100,
        side="BUY",
    ),
    OrderType.FOK,
)
resp = client.post_order(order)

# Cancel order
client.cancel(order_id="0xORDER_ID")

# Cancel all orders
client.cancel_all()

# Get trades
trades = client.get_trades()
```

---

## 14. Key Differences from Traditional Exchanges

### Prediction Market Specifics
1. **Binary outcomes**: Every market resolves to exactly $0 or $1 per share
2. **Complementary pairs**: YES + NO always sum to ~$1 (minus spread)
3. **Bounded prices**: All prices in [0, 1] range
4. **CTF on Polygon**: Uses ERC-1155 Conditional Token Framework, not traditional custody
5. **No margin/leverage**: Fully collateralized positions only
6. **Resolution risk**: Markets can resolve ambiguously or be voided
7. **Variable tick sizes**: Tick size changes at extreme prices (near 0 or 1)
8. **Heartbeat requirement**: Active trading requires 10-second heartbeat or orders auto-cancel
9. **Reward scoring**: Orders may earn maker rewards if they meet scoring criteria

### Trading Implications
- **Arbitrage**: Cross-book (YES vs 1-NO), cross-market (correlated events)
- **Market making**: Wide spreads in thin markets, but bounded risk
- **Information trading**: Prediction markets are primarily information-driven
- **Fee sensitivity**: 2% fees are significant for high-frequency strategies
- **Liquidity constraints**: Much thinner than traditional exchanges
