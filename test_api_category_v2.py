# test_api_category_v2.py
from utils.polymarket_api import PolymarketAPI
import requests

api = PolymarketAPI()

print("=" * 60)
print("测试 1: 直接从 Events API 获取原始数据")
print("=" * 60)

# 直接调用 Events API，不经过任何处理
response = requests.get(
    f"{api.gamma_api}/events",
    params={'limit': 1, 'closed': 'false'},
    timeout=30
)

if response.status_code == 200:
    events = response.json()
    if events:
        event = events[0]
        print(f"\nEvent 标题: {event.get('title', 'Unknown')}")
        print(f"Event category: {event.get('category', 'NOT FOUND')}")
        print(f"Event subcategory: {event.get('subcategory', 'NOT FOUND')}")
        
        if 'markets' in event and event['markets']:
            market = event['markets'][0]
            print(f"\n--- Market 信息 ---")
            print(f"Market question: {market.get('question', 'Unknown')}")
            print(f"Market category: {market.get('category', 'NOT FOUND')}")
            print(f"Market volume24hr: {market.get('volume24hr', 0)}")
            
            print(f"\n--- Market 所有字段 ---")
            for key in sorted(market.keys()):
                value = market.get(key)
                if len(str(value)) < 100:  # 只显示短字段
                    print(f"  {key}: {value}")

print("\n" + "=" * 60)
print("测试 2: 检查我们的 extract_market_data")
print("=" * 60)

# 测试不带 volume filter
markets = api.get_all_markets_from_events(
    min_volume_24h=0,  # ← 改成 0
    max_events=1
)

if markets:
    market = markets[0]
    print(f"\n提取后的市场数据:")
    print(f"Question: {market.get('question', 'Unknown')}")
    print(f"Category: {market.get('category', 'NOT FOUND')}")
    print(f"Volume 24h: {market.get('volume_24h', 0)}")
else:
    print("extract_market_data 返回空！")