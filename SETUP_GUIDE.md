# 🚀 Market Sensemaking v2.0 - Setup Guide

## 📋 Overview

This guide will help you upgrade to the new **Metrics v2.0 system**, which uses the **Polymarket CLOB API** to get accurate **aggressor (taker/maker)** data for precise market analysis.

---

## 🎯 What's New in v2.0

### **Improved Data Quality**
- ✅ **Precise aggressor identification** using CLOB API's `type` field
- ✅ **All your original metrics** implemented exactly as designed
- ✅ **No compromises** on indicator definitions

### **New Metrics System**
1. **Consensus Band & Profile**
   - Consensus Band (70% volume coverage)
   - Band Width (VAH - VAL)
   - POMD (Point of Max Disagreement)
   - Rejected Probabilities

2. **Uncertainty Metrics**
   - UI (Uncertainty Index)
   - ECR (Expected Convergence Rate)
   - ACR (Actual Convergence Rate)
   - CER (Convergence Efficiency Ratio)

3. **Conviction Metrics** (Now with accurate aggressor data!)
   - AR (Aggressive Ratio)
   - Volume Delta
   - CS (Conviction Score)

---

## 🔧 Setup Steps

### **Step 1: Install Dependencies**

```bash
pip install eth-account web3
```

### **Step 2: Generate API Wallet**

Run the wallet setup tool:

```bash
python setup_wallet.py
```

**Choose option 1** to generate a new wallet. The script will:
- Create a new Polygon wallet
- Display the private key
- Optionally auto-write to `.env` file

**Important Notes:**
- ✅ This wallet is **only for API authentication**
- ✅ **No funds required**
- ✅ Keep the private key secure
- ✅ Already in `.gitignore` (safe from Git)

### **Step 3: Configure Environment**

If you didn't auto-write in Step 2, manually update `.env`:

```bash
# Copy from template
cp .env.example .env

# Edit .env and set:
PRIVATE_KEY=0x... (your wallet private key)
DATABASE_URL=postgresql://... (your Render PostgreSQL URL)
```

### **Step 4: Test CLOB API Connection**

```bash
python polymarket_clob_api.py
```

**Expected output:**
```
[CLOB Client] Initialized for address: 0x...
[CLOB Client] Initializing API credentials...
✅ API credentials created successfully!
   API Key: abcd1234...

🧪 Testing trade data fetch...
   📊 Fetching CLOB trades (last 1h)...
   ✅ Got 150 trades (with maker/taker info)

✅ Successfully fetched 150 trades!

📊 Sample trades:
1. TAKER | BUY  | Price: 0.650 | Size: $100.00
2. MAKER | SELL | Price: 0.650 | Size: $100.00
3. TAKER | BUY  | Price: 0.655 | Size: $150.00
...
```

**Troubleshooting:**
- If you see **"Failed to create API key"**: Try using nonce=1 or 2
- If you see **"API key may already exist"**: The script will auto-derive it
- Check that `PRIVATE_KEY` is set correctly in `.env`

### **Step 5: Migrate Database**

Add new metric columns to your database:

```bash
python migrate_database.py
```

**Expected output:**
```
📊 Database Migration - Metrics v2.0
🔍 Checking current schema...
   Found 10 existing columns

📝 Need to add 9 new columns:
   - vah
   - val
   - mid_probability
   - band_width
   - pomd
   - ar
   - volume_delta
   - ecr
   - acr

🚀 Executing migration...
   ✅ Added column: vah
   ✅ Added column: val
   ...

✅ Migration completed successfully!
```

### **Step 6: Test Metrics Calculation**

```bash
python metrics_v2.py
```

**Expected output:**
```
🧪 Testing Metrics v2.0

📊 Calculated Metrics:
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
status              : 🟡 Fragmented

✅ Metrics v2.0 test completed!
```

---

## 🎯 Usage

### **Using the New System**

The new system is backward compatible but with **much better data**.

#### **Option 1: Update Existing sync.py**

Replace your `polymarket_api.get_trades_for_market()` calls with:

```python
from polymarket_clob_api import PolymarketCLOBClient

# Initialize CLOB client
clob_client = PolymarketCLOBClient(os.getenv("PRIVATE_KEY"))
clob_client.initialize_api_credentials()

# Get trades (now with type field!)
trades = clob_client.get_trades_for_market(condition_id, hours=24)

# trades now contain:
# - type: 'TAKER' (aggressor) or 'MAKER' (passive)
# - side: 'BUY' or 'SELL'
# - price, size, timestamp
```

#### **Option 2: Use New metrics_v2.py**

```python
from metrics_v2 import calculate_all_metrics

# Calculate all metrics at once
metrics = calculate_all_metrics(
    trades_all=trades_all,      # All trades (for profile)
    trades_24h=trades_24h,       # 24h trades (for AR/CS)
    current_price=0.65,          # Current price (0-1)
    days_remaining=30,           # Days to resolution
    band_width_7d_ago=0.15       # 7d ago band width (optional)
)

# Access metrics
print(f"UI: {metrics['UI']}")
print(f"CER: {metrics['CER']}")
print(f"CS: {metrics['CS']}")
print(f"Status: {metrics['status']}")
```

---

## 📊 Metric Definitions Reference

### **Consensus Band & Profile**

**Consensus Band**
- Definition: 覆盖 70% 成交量的概率区间
- VAH (Value Area High): 共识带上界
- VAL (Value Area Low): 共识带下界

**Band Width**
- Formula: `BW = VAH - VAL`
- Interpretation:
  - Large BW → Widespread disagreement
  - Small BW → Concentrated consensus

**POMD (Point of Max Disagreement)**
- Definition: 成交量最大的价格点
- Interpretation: 争议最激烈的概率点

### **Uncertainty Metrics**

**UI (Uncertainty Index)**
- Formula: `UI = band_width / mid_probability`
- Interpretation:
  - Same 10% band at 50% → Moderate uncertainty
  - Same 10% band at 90% → Extreme uncertainty

**CER (Convergence Efficiency Ratio)**
- Formula: `CER = ACR / ECR`
  - ECR = (100 - price) / days_remaining
  - ACR = (band_width_7d_ago - band_width_now) / 7
- Interpretation:
  - CER > 1: Converging faster than expected (Healthy)
  - CER ≈ 1: Converging as expected
  - CER < 1: Converging slower than expected (Sluggish)

### **Conviction Metrics**

**AR (Aggressive Ratio)**
- Formula: `AR = aggressive_volume / total_volume`
- Uses: CLOB API's `type` field
- Interpretation: Proportion of active trading

**Volume Delta**
- Formula: `Delta = aggressive_buy - aggressive_sell`
- Uses: `type == 'TAKER'` trades only
- Interpretation: Directional imbalance in aggressive trading

**CS (Conviction Score)**
- Formula: `CS = (AR * |delta|) / total_volume`
- Interpretation:
  - High CS: Strong active directional conviction
  - Low CS: Weak passive consensus

---

## 🔍 Troubleshooting

### **CLOB API Issues**

**Problem: "Failed to create API key"**
- Solution: Try different nonce values (0, 1, 2)
- Run: `python setup_wallet.py` → Option 2 → Verify wallet

**Problem: "API credentials not initialized"**
- Solution: Call `client.initialize_api_credentials()` first
- Or run the test script: `python polymarket_clob_api.py`

**Problem: "Invalid private key"**
- Solution: Check `.env` file
- Ensure `PRIVATE_KEY` starts with `0x`
- Must be 66 characters (0x + 64 hex)

### **Database Issues**

**Problem: "Column already exists"**
- This is normal if re-running migration
- Script automatically handles this

**Problem: Migration fails**
- Check `DATABASE_URL` is correct
- Ensure PostgreSQL is accessible
- Try manual migration (see `migrate_database.py`)

**Rollback Migration:**
```bash
python migrate_database.py --rollback
```
⚠️ **Warning:** This deletes all v2 metrics data!

---

## 📈 Next Steps

### **1. Update Your Sync Script**

Integrate CLOB API into your sync workflow:

```python
# In sync.py or sync_incremental.py

from polymarket_clob_api import PolymarketCLOBClient
from metrics_v2 import calculate_all_metrics

# Initialize once
clob_client = PolymarketCLOBClient(os.getenv("PRIVATE_KEY"))
clob_client.initialize_api_credentials()

# For each market
for market in markets:
    # Get trades with aggressor info
    trades = clob_client.get_trades_for_market(
        market['condition_id'],
        hours=24
    )
    
    # Calculate new metrics
    metrics = calculate_all_metrics(
        trades_all=trades,
        trades_24h=trades,
        current_price=market['price'],
        days_remaining=market['days_remaining'],
        band_width_7d_ago=get_7d_band_width(market['token_id'])
    )
    
    # Save to database (include new fields)
    save_metrics_v2(market['token_id'], metrics)
```

### **2. Build Market Detail Pages**

Now that you have accurate metrics, you can:
- Show Consensus Band Evolution over time
- Display aggressor flow (TAKER vs MAKER)
- Visualize POMD and rejected probabilities
- Create conviction strength indicators

### **3. Set Up Daily Automation**

Schedule daily syncs to build history:

```bash
# Run daily at 2 AM
0 2 * * * cd /path/to/project && python sync_v2.py
```

After 7 days, CER calculations will work fully!

---

## 🎉 You're All Set!

Your Market Sensemaking system now has:
- ✅ Accurate aggressor identification
- ✅ Professional-grade metrics
- ✅ Complete Market Profile analysis
- ✅ Foundation for advanced features

**Questions?** Check the code comments or reach out!

---

## 📚 Resources

- **Polymarket CLOB Docs**: https://docs.polymarket.com/developers/CLOB/
- **Metrics Definitions**: See `metrics_v2.py` docstrings
- **Database Schema**: See `migrate_database.py`

---

**Version**: 2.0.0  
**Date**: December 2024  
**Author**: Market Sensemaking Team
