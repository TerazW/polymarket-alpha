# test_tag_slug_approach.py
import requests

def get_markets_by_tag_slug(tag_slug, limit=10):
    """通过 tag slug 获取市场"""
    response = requests.get(
        "https://gamma-api.polymarket.com/events",
        params={
            'tag_slug': tag_slug,
            'limit': limit,
            'closed': 'false'
        },
        timeout=30
    )
    
    if response.status_code == 200:
        events = response.json()
        markets = []
        for event in events:
            if 'markets' in event:
                for market in event['markets']:
                    markets.append({
                        'question': market.get('question', 'Unknown'),
                        'volume24hr': market.get('volume24hr', 0),
                        'category': tag_slug.capitalize()  # ← 直接设置分类
                    })
        return markets
    return []

# 测试
categories = ['politics', 'sports', 'crypto', 'finance', 'business']

for cat in categories:
    markets = get_markets_by_tag_slug(cat, limit=2)
    print(f"\n{cat.upper()}:")
    for m in markets[:2]:
        print(f"  - {m['question'][:60]}...")
        print(f"    Category: {m['category']}, Volume: ${m['volume24hr']:,.0f}")