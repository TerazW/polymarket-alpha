import requests

print("Testing Gamma API for open markets...\n")

# 获取大量市场
response = requests.get(
    'https://gamma-api.polymarket.com/markets',
    params={'limit': 2000},
    timeout=30
)
data = response.json()

# 统计
open_markets = [m for m in data if not m.get('closed', True)]
closed_markets = [m for m in data if m.get('closed', True)]

print(f"Total markets fetched: {len(data)}")
print(f"Open markets: {len(open_markets)}")
print(f"Closed markets: {len(closed_markets)}")

# 显示开放市场
if open_markets:
    # 按成交量排序
    open_markets.sort(key=lambda x: float(x.get('volume24hr', 0)), reverse=True)
    
    print(f"\nTop 5 open markets by volume:")
    for i, m in enumerate(open_markets[:5], 1):
        vol = float(m.get('volume24hr', 0))
        print(f"\n{i}. {m.get('question', 'N/A')[:60]}...")
        print(f"   Volume 24h: ${vol:,.2f}")
        print(f"   Closed: {m.get('closed', False)}")
        print(f"   End date: {m.get('endDateIso', 'N/A')}")
else:
    print("\n❌ No open markets found in first 2000!")

print("\n✅ Test completed!")