# Market Sensemaking v2.0 - Setup Guide

## Overview

This guide upgrades to the Metrics v2.0 system, which uses the Polymarket CLOB API
to fetch accurate aggressor (taker/maker) data for market analysis.

---

## What's New in v2.0

### Improved Data Quality
- Precise aggressor identification using the CLOB API `type` field
- All original metrics implemented exactly as designed
- No compromises on indicator definitions

### New Metrics System
1. Consensus Band and Profile
   - Consensus Band (70% volume coverage)
   - Band Width (VAH - VAL)
   - POMD (Point of Max Disagreement)
   - Rejected Probabilities

2. Uncertainty Metrics
   - UI (Uncertainty Index)
   - ECR (Expected Convergence Rate)
   - ACR (Actual Convergence Rate)
   - CER (Convergence Efficiency Ratio)

3. Conviction Metrics (now with aggressor data)
   - AR (Aggressive Ratio)
   - Volume Delta
   - CS (Conviction Score)

---

## Setup Steps

### Step 1: Install Dependencies

```bash
pip install eth-account web3
```

### Step 2: Generate API Wallet

Run the wallet setup tool:

```bash
python setup_wallet.py
```

Choose option 1 to generate a new wallet. The script will:
- Create a new Polygon wallet
- Display the private key
- Optionally write to `.env`

Important notes:
- This wallet is only for API authentication
- No funds required
- Keep the private key secure
- `.gitignore` already excludes `.env`

### Step 3: Configure Environment

If you did not auto-write in Step 2, update `.env` manually:

```bash
# Copy from template
cp .env.example .env

# Edit .env and set:
PRIVATE_KEY=0x... (your wallet private key)
DATABASE_URL=postgresql://... (your Render PostgreSQL URL)
```

### Step 4: Test CLOB API Connection

```bash
python polymarket_clob_api.py
```

Expected output:

```
[CLOB Client] Initialized for address: 0x...
[CLOB Client] Initializing API credentials...
OK. API credentials created successfully!
   API Key: abcd1234...

Testing trade data fetch...
   Fetching CLOB trades (last 1h)...
   Got 150 trades (with maker/taker info)

OK. Successfully fetched 150 trades!

Sample trades:
1. TAKER | BUY  | Price: 0.650 | Size: $100.00
2. MAKER | SELL | Price: 0.650 | Size: $100.00
3. TAKER | BUY  | Price: 0.655 | Size: $150.00
...
```

Troubleshooting:
- "Failed to create API key": try nonce 1 or 2
- "API key may already exist": script will auto-derive it
- Check `PRIVATE_KEY` in `.env`

### Step 5: Migrate Database

Add new metric columns to your database:

```bash
python migrate_database.py
```

Expected output:

```
Database Migration - Metrics v2.0
Checking current schema...
   Found 10 existing columns

Need to add 9 new columns:
   - vah
   - val
   - mid_probability
   - band_width
   - pomd
   - ar
   - volume_delta
   - ecr
   - acr

Executing migration...
   Added column: vah
   Added column: val
   ...

Migration completed successfully!
```

### Step 6: Test Metrics Calculation

```bash
python metrics_v2.py
```

Expected output:

```
Testing Metrics v2.0

Calculated Metrics:
==================================================
VAH                 : 0.6600
VAL                 : 0.6400
mid_probability     : 0.6500
band_width          : 0.0200
POMD                : 0.6500
UI                  : 0.0308
ECR                 : 1.1667
ACR                 : -0.0143
CER                 : -0.0122
AR                  : 0.6000
volume_delta        : 170.0000
CS                  : 0.1960
status              : Fragmented

Metrics v2.0 test completed!
```

---

## Usage

### Option 1: Update Existing sync.py

Replace your `polymarket_api.get_trades_for_market()` calls with:

```python
from polymarket_clob_api import PolymarketCLOBClient

# Initialize CLOB client
clob_client = PolymarketCLOBClient(os.getenv("PRIVATE_KEY"))
clob_client.initialize_api_credentials()

# Get trades (now with type field)
trades = clob_client.get_trades_for_market(condition_id, hours=24)

# trades now contain:
# - type: 'TAKER' (aggressor) or 'MAKER' (passive)
# - side: 'BUY' or 'SELL'
# - price, size, timestamp
```

### Option 2: Use New metrics_v2.py

```python
from metrics_v2 import calculate_all_metrics

metrics = calculate_all_metrics(
    trades_all=trades_all,      # All trades (profile)
    trades_24h=trades_24h,       # 24h trades (AR/CS)
    current_price=0.65,          # Current price (0-1)
    days_remaining=30,           # Days to resolution
    band_width_7d_ago=0.15       # 7d band width (optional)
)

print(f"UI: {metrics['UI']}")
print(f"CER: {metrics['CER']}")
print(f"CS: {metrics['CS']}")
print(f"Status: {metrics['status']}")
```

---

## Metric Definitions Reference

### Consensus Band and Profile

Consensus Band:
- Definition: 70% volume coverage interval
- VAH (Value Area High)
- VAL (Value Area Low)

Band Width:
- Formula: `BW = VAH - VAL`
- Interpretation:
  - Large BW -> widespread disagreement
  - Small BW -> concentrated consensus

POMD (Point of Max Disagreement):
- Definition: price with maximum disagreement
- Interpretation: most contested price level

### Uncertainty Metrics

UI (Uncertainty Index):
- Formula: `UI = band_width / mid_probability`
- Interpretation:
  - Same 10% band at 50% -> moderate uncertainty
  - Same 10% band at 90% -> extreme uncertainty

CER (Convergence Efficiency Ratio):
- Formula: `CER = ACR / ECR`
  - ECR = (100 - price) / days_remaining
  - ACR = (band_width_7d_ago - band_width_now) / 7
- Interpretation:
  - CER > 1: faster than expected (healthy)
  - CER ~= 1: as expected
  - CER < 1: slower than expected

### Conviction Metrics

AR (Aggressive Ratio):
- Formula: `AR = aggressive_volume / total_volume`
- Uses CLOB API `type` field
- Interpretation: proportion of active trading

Volume Delta:
- Formula: `Delta = aggressive_buy - aggressive_sell`
- Uses `type == 'TAKER'` trades only
- Interpretation: directional imbalance

CS (Conviction Score):
- Formula: `CS = (AR * |delta|) / total_volume`
- Interpretation:
  - High CS: strong directional conviction
  - Low CS: weak or passive consensus

---

## Troubleshooting

### CLOB API Issues

Problem: "Failed to create API key"
- Try different nonce values (0, 1, 2)
- Run `python setup_wallet.py`, choose Option 2, and verify wallet

Problem: "API credentials not initialized"
- Call `client.initialize_api_credentials()` first
- Or run `python polymarket_clob_api.py`

Problem: "Invalid private key"
- Check `.env`
- Ensure `PRIVATE_KEY` starts with `0x`
- Must be 66 characters (0x + 64 hex)

### Database Issues

Problem: "Column already exists"
- This is normal when re-running migration

Problem: Migration fails
- Check `DATABASE_URL`
- Ensure PostgreSQL is reachable
- Try manual migration (see `migrate_database.py`)

Rollback migration:

```bash
python migrate_database.py --rollback
```

Warning: This deletes all v2 metrics data.

---

## Next Steps

1. Update your sync script to use the CLOB API
2. Build market detail pages (consensus band evolution, aggressor flow)
3. Schedule daily syncs

Example daily cron:

```bash
0 2 * * * cd /path/to/project && python sync_v2.py
```

After 7 days, CER calculations will work fully.

---

## Resources

- Polymarket CLOB Docs: https://docs.polymarket.com/developers/CLOB/
- Metrics definitions: `metrics_v2.py` docstrings
- Database schema: `migrate_database.py`

---

Version: 2.0.0  
Date: December 2024  
Author: Market Sensemaking Team
