"""
对比不同的 API 调用方式
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.polymarket_api import PolymarketAPI
import requests

CONDITION_ID = "0x52c934257bd7d014c8dcd5833fee69597027d14c9c47c791f6be6e286e59cef7"
DATA_API = "https://data-api.polymarket.com"

def main():
    print("=" * 70)
    print("Comparing different API call methods")
    print("=" * 70)
    
    api = PolymarketAPI()
    
    # Method 1: 使用封装的方法
    print("\n1️⃣ Using api.get_trades_for_market()...")
    trades1 = api.get_trades_for_market(CONDITION_ID, limit=10)
    print(f"   Result: {len(trades1)} trades")
    
    # Method 2: 直接调用 Data API（不带 market 参数）
    print("\n2️⃣ Direct Data API call (no market filter)...")
    try:
        response = requests.get(f"{DATA_API}/trades", params={"limit": 10}, timeout=30)
        trades2 = response.json() if response.status_code == 200 else []
        print(f"   Result: {len(trades2)} trades")
        if trades2:
            print(f"   Sample market: {trades2[0].get('conditionId', 'N/A')[:20]}...")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Method 3: 尝试不同的参数名
    print("\n3️⃣ Trying different parameter names...")
    param_names = ['market', 'conditionId', 'condition_id', 'asset']
    
    for param_name in param_names:
        try:
            params = {"limit": 10, param_name: CONDITION_ID}
            response = requests.get(f"{DATA_API}/trades", params=params, timeout=10)
            if response.status_code == 200:
                trades = response.json()
                print(f"   {param_name}: {len(trades)} trades")
            else:
                print(f"   {param_name}: Status {response.status_code}")
        except Exception as e:
            print(f"   {param_name}: Error - {e}")
    
    # Method 4: 检查返回的所有交易是否包含这个市场
    print("\n4️⃣ Checking if recent trades include our market...")
    try:
        response = requests.get(f"{DATA_API}/trades", params={"limit": 100}, timeout=30)
        if response.status_code == 200:
            all_trades = response.json()
            market_trades = [t for t in all_trades if t.get('conditionId') == CONDITION_ID]
            print(f"   Found {len(market_trades)} trades for our market in recent 100 trades")
            
            # 统计最近交易的市场分布
            markets = {}
            for t in all_trades:
                cid = t.get('conditionId', 'unknown')[:20]
                markets[cid] = markets.get(cid, 0) + 1
            
            print(f"\n   Top markets in recent trades:")
            for cid, count in sorted(markets.items(), key=lambda x: x[1], reverse=True)[:5]:
                print(f"     {cid}...: {count} trades")
    except Exception as e:
        print(f"   Error: {e}")

if __name__ == "__main__":
    main()