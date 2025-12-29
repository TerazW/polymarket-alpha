from utils.polymarket_api import PolymarketAPI
import requests

api = PolymarketAPI()

# 获取一个有 tags 的市场
response = requests.get(
    f"{api.gamma_api}/events",
    params={'limit': 5, 'closed': 'false'},
    timeout=30
)

if response.status_code == 200:
    events = response.json()
    for event in events:
        if 'markets' in event and event['markets']:
            market = event['markets'][0]
            
            print(f"\n市场: {market.get('question', 'Unknown')[:60]}...")
            
            # 检查可能的分类字段
            print(f"  groupItemTitle: {market.get('groupItemTitle', 'N/A')}")
            print(f"  slug: {market.get('slug', 'N/A')}")
            
            # 检查 tags（如果有）
            if 'tags' in market:
                print(f"  tags: {market['tags']}")
            
            # 检查 events（反向关联）
            if 'events' in market:
                print(f"  events: {market['events']}")
                
            break