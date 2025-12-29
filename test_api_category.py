from utils.polymarket_api import PolymarketAPI

api = PolymarketAPI()

# 获取一个 event
print("测试 Events API...")
markets = api.get_all_markets_from_events(max_events=1)

if markets:
    market = markets[0]
    print(f"\n市场标题: {market.get('question', 'Unknown')}")
    print(f"Category 字段: {market.get('category', 'NOT FOUND')}")
    print(f"\n所有可用字段:")
    for key in sorted(market.keys()):
        print(f"  - {key}")
else:
    print("没有获取到市场数据！")