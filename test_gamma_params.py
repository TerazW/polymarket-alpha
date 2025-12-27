import requests

print("Testing different Gamma API parameters...\n")

# 测试 1: 默认参数
print("1️⃣ Test 1: Default (limit=500)")
response = requests.get(
    'https://gamma-api.polymarket.com/markets',
    params={'limit': 500},
    timeout=30
)
data = response.json()
open_count = len([m for m in data if not m.get('closed', True)])
print(f"   Total: {len(data)}, Open: {open_count}\n")

# 测试 2: 添加 active 参数
print("2️⃣ Test 2: With active=true")
response = requests.get(
    'https://gamma-api.polymarket.com/markets',
    params={'limit': 500, 'active': 'true'},
    timeout=30
)
data = response.json()
open_count = len([m for m in data if not m.get('closed', True)])
print(f"   Total: {len(data)}, Open: {open_count}\n")

# 测试 3: 添加 closed 参数
print("3️⃣ Test 3: With closed=false")
response = requests.get(
    'https://gamma-api.polymarket.com/markets',
    params={'limit': 500, 'closed': 'false'},
    timeout=30
)
data = response.json()
open_count = len([m for m in data if not m.get('closed', True)])
print(f"   Total: {len(data)}, Open: {open_count}")

if open_count > 0:
    print(f"\n✅ Found {open_count} open markets!")
    # 显示前 3 个
    open_markets = [m for m in data if not m.get('closed', True)]
    open_markets.sort(key=lambda x: float(x.get('volume24hr', 0)), reverse=True)
    
    for i, m in enumerate(open_markets[:3], 1):
        print(f"\n{i}. {m.get('question', 'N/A')[:60]}...")
        print(f"   Volume: ${float(m.get('volume24hr', 0)):,.2f}")
else:
    print("\n❌ Still no open markets found")

print("\n✅ Test completed!")
