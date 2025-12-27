import requests

response = requests.get(
    "https://gamma-api.polymarket.com/markets",
    params={"limit": 10},
    timeout=15
)

markets = response.json()

print(f"Total markets: {len(markets)}\n")

for i, m in enumerate(markets[:5], 1):
    print(f"{i}. {m.get('question', 'N/A')[:60]}...")
    print(f"   active: {m.get('active')}")
    print(f"   closed: {m.get('closed')}")
    print(f"   volume24hr: {m.get('volume24hr')}")
    print(f"   endDateIso: {m.get('endDateIso')}")
    print()