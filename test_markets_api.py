# test_markets_api.py
import requests

# 直接调用 Markets API（不是 Events API）
response = requests.get(
    "https://gamma-api.polymarket.com/markets",
    params={
        'limit': 5,
        'closed': 'false'
    },
    timeout=30
)

if response.status_code == 200:
    markets = response.json()
    
    print(f"获取到 {len(markets)} 个市场\n")
    
    for i, market in enumerate(markets[:5], 1):
        print(f"=== Market {i} ===")
        print(f"Question: {market.get('question', 'Unknown')[:60]}...")
        print(f"category: {market.get('category', 'NOT FOUND')}")
        print(f"volume24hr: {market.get('volume24hr', 0)}")
        
        # 检查 categories 数组
        if 'categories' in market and market['categories']:
            print(f"categories 数组:")
            for cat in market['categories']:
                print(f"  - {cat.get('label', 'N/A')}")
        
        # 检查 tags 数组
        if 'tags' in market and market['tags']:
            print(f"tags 数组:")
            for tag in market['tags']:
                print(f"  - {tag.get('label', 'N/A')}")
        
        print()
else:
    print(f"请求失败: {response.status_code}")