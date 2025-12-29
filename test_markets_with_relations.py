# test_markets_with_relations.py
import requests

# 使用 include_tag 参数获取完整数据
response = requests.get(
    "https://gamma-api.polymarket.com/markets",
    params={
        'limit': 3,
        'closed': 'false',
        'include_tag': 'true',  # ← 关键参数
        'related_tags': 'true'
    },
    timeout=30
)

if response.status_code == 200:
    markets = response.json()
    
    print(f"获取到 {len(markets)} 个市场\n")
    
    for i, market in enumerate(markets, 1):
        print(f"{'='*60}")
        print(f"Market {i}: {market.get('question', 'Unknown')[:50]}...")
        print(f"{'='*60}")
        
        # 检查所有可能包含分类信息的字段
        print(f"category 字段: {market.get('category', 'NOT FOUND')}")
        
        # categories 数组
        if 'categories' in market and market['categories']:
            print(f"\n✅ categories 数组找到:")
            for cat in market['categories']:
                print(f"  - label: {cat.get('label', 'N/A')}")
                print(f"    slug: {cat.get('slug', 'N/A')}")
        else:
            print(f"\n❌ categories 数组: 空或不存在")
        
        # tags 数组
        if 'tags' in market and market['tags']:
            print(f"\n✅ tags 数组找到:")
            for tag in market['tags']:
                print(f"  - label: {tag.get('label', 'N/A')}")
                print(f"    slug: {tag.get('slug', 'N/A')}")
        else:
            print(f"\n❌ tags 数组: 空或不存在")
        
        # events 数组（反向关联）
        if 'events' in market and market['events']:
            print(f"\n✅ events 数组找到:")
            for event in market['events']:
                print(f"  - title: {event.get('title', 'N/A')[:40]}...")
                print(f"    category: {event.get('category', 'NOT FOUND')}")
                print(f"    subcategory: {event.get('subcategory', 'NOT FOUND')}")
        else:
            print(f"\n❌ events 数组: 空或不存在")
        
        print()
else:
    print(f"请求失败: {response.status_code}")