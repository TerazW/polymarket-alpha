# test_tag_slug_limit.py
import requests

tag_slug = 'sports'
offset = 0
total_events = 0
total_markets = 0

print(f"测试 {tag_slug} 能获取多少市场...\n")

for page in range(10):  # 测试 10 页
    response = requests.get(
        "https://gamma-api.polymarket.com/events",
        params={
            'tag_slug': tag_slug,
            'limit': 100,
            'offset': offset,
            'closed': 'false'
        },
        timeout=30
    )
    
    if response.status_code == 200:
        events = response.json()
        
        if not events:
            print(f"页 {page + 1}: 无数据，停止")
            break
        
        # 统计 markets
        markets_count = sum(len(e.get('markets', [])) for e in events)
        total_events += len(events)
        total_markets += markets_count
        
        print(f"页 {page + 1}: {len(events)} events, {markets_count} markets (累计: {total_markets})")
        
        if len(events) < 100:
            print(f"\n最后一页")
            break
        
        offset += 100
    else:
        print(f"错误: {response.status_code}")
        break

print(f"\n总计: {total_events} events, {total_markets} markets")
