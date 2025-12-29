"""
测试 Polymarket Data API 的 takerOnly 参数
验证是否能区分 taker 和 maker 交易
"""
import requests
import json

# Bears vs 49ers 市场的 condition_id
CONDITION_ID = "0x52c934257bd7d014c8dcd5833fee69597027d14c9c47c791f6be6e286e59cef7"

def test_data_api():
    """测试 Data API"""
    
    print("=" * 70)
    print("Testing Polymarket Data API - takerOnly parameter")
    print("=" * 70)
    
    # Test 1: takerOnly=true (default)
    print("\n1️⃣ Test with takerOnly=true (只获取 taker 交易)")
    url_taker = f"https://data-api.polymarket.com/trades?market={CONDITION_ID}&takerOnly=true&limit=5"
    
    try:
        response = requests.get(url_taker)
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Got {len(data)} trades")
            
            if data:
                print(f"\n   Sample trade:")
                trade = data[0]
                print(f"   - Side: {trade.get('side')}")
                print(f"   - Size: {trade.get('size')}")
                print(f"   - Price: {trade.get('price')}")
                print(f"   - Timestamp: {trade.get('timestamp')}")
                print(f"   - Transaction: {trade.get('transactionHash', 'N/A')}")
                print(f"\n   All keys: {list(trade.keys())}")
        else:
            print(f"   ❌ Error: {response.text}")
    except Exception as e:
        print(f"   ❌ Exception: {e}")
    
    # Test 2: takerOnly=false (获取所有交易)
    print("\n2️⃣ Test with takerOnly=false (获取所有交易)")
    url_all = f"https://data-api.polymarket.com/trades?market={CONDITION_ID}&takerOnly=false&limit=5"
    
    try:
        response = requests.get(url_all)
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Got {len(data)} trades")
            
            if data:
                print(f"\n   Sample trade:")
                trade = data[0]
                print(f"   - Side: {trade.get('side')}")
                print(f"   - Size: {trade.get('size')}")
                print(f"   - Price: {trade.get('price')}")
                print(f"   - Timestamp: {trade.get('timestamp')}")
                print(f"   - Transaction: {trade.get('transactionHash', 'N/A')}")
                print(f"\n   All keys: {list(trade.keys())}")
                
                # 检查是否有标识 taker/maker 的字段
                print(f"\n   🔍 Looking for taker/maker identification...")
                has_role_field = any(key in trade for key in ['role', 'type', 'aggressor', 'isTaker', 'isMaker'])
                if has_role_field:
                    print(f"   ✅ Found role identification!")
                else:
                    print(f"   ⚠️  No explicit taker/maker field found")
        else:
            print(f"   ❌ Error: {response.text}")
    except Exception as e:
        print(f"   ❌ Exception: {e}")
    
    # Test 3: Compare counts
    print("\n3️⃣ Comparing trade counts")
    try:
        resp_taker = requests.get(f"https://data-api.polymarket.com/trades?market={CONDITION_ID}&takerOnly=true&limit=100")
        resp_all = requests.get(f"https://data-api.polymarket.com/trades?market={CONDITION_ID}&takerOnly=false&limit=100")
        
        if resp_taker.status_code == 200 and resp_all.status_code == 200:
            taker_count = len(resp_taker.json())
            all_count = len(resp_all.json())
            
            print(f"   Taker only: {taker_count} trades")
            print(f"   All trades: {all_count} trades")
            print(f"   Difference: {all_count - taker_count} trades")
            
            if all_count > taker_count:
                print(f"\n   ✅ takerOnly=false 返回更多交易！")
                print(f"   💡 这意味着额外的 {all_count - taker_count} 笔是 MAKER 交易")
            elif all_count == taker_count:
                print(f"\n   ⚠️  两个参数返回相同数量的交易")
                print(f"   💡 可能所有交易都标记为 taker，或参数无效")
    except Exception as e:
        print(f"   ❌ Exception: {e}")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    test_data_api()
    