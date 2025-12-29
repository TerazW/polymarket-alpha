"""
测试 Gamma API 获取市场交易数据
"""
import requests

# Bears vs 49ers
CONDITION_ID = "0x52c934257bd7d014c8dcd5833fee69597027d14c9c47c791f6be6e286e59cef7"

def test_gamma_api():
    print("=" * 70)
    print("Testing Gamma API for market trades")
    print("=" * 70)
    
    # Gamma API endpoint (猜测)
    endpoints_to_try = [
        f"https://gamma-api.polymarket.com/trades?market={CONDITION_ID}",
        f"https://gamma-api.polymarket.com/trades?condition_id={CONDITION_ID}",
        f"https://gamma-api.polymarket.com/markets/{CONDITION_ID}/trades",
        f"https://clob.polymarket.com/trades?market={CONDITION_ID}",
    ]
    
    for i, url in enumerate(endpoints_to_try, 1):
        print(f"\n{i}. Testing: {url}")
        try:
            response = requests.get(url, timeout=5)
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    if isinstance(data, list):
                        print(f"   ✅ Got {len(data)} trades")
                        if data:
                            print(f"   Sample keys: {list(data[0].keys())[:5]}")
                    elif isinstance(data, dict):
                        print(f"   ✅ Got dict response")
                        print(f"   Keys: {list(data.keys())}")
                except:
                    print(f"   Response: {response.text[:200]}")
            else:
                print(f"   Response: {response.text[:200]}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    test_gamma_api()