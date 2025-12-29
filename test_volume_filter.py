# test_volume_filter.py
import requests

tag_slug = 'sports'
min_volume = 100
total_markets = 0
filtered_markets = 0

print(f"测试 {tag_slug} 有多少市场 volume >= ${min_volume}...\n")

for page in range(5):  # 测试 5 页
    response = requests.get(
        "https://gamma-api.polymarket.com/events",
        params={
            'tag_slug': tag_slug,
            'limit': 100,
            'offset': page * 100,
            'closed': 'false'
        },
        timeout=30
    )
    
    if response.status_code == 200:
        events = response.json()
        
        if not events:
            break
        
        for event in events:
            if 'markets' in event and event['markets']:
                for market in event['markets']:
                    total_markets += 1
                    volume = float(market.get('volume24hr', 0))
                    if volume >= min_volume:
                        filtered_markets += 1
        
        print(f"页 {page + 1}: 总共 {total_markets} markets, 其中 {filtered_markets} >= ${min_volume}")

print(f"\n最终: {filtered_markets}/{total_markets} 市场符合 volume >= ${min_volume}")
print(f"过滤率: {(total_markets - filtered_markets) / total_markets * 100:.1f}% 被过滤")