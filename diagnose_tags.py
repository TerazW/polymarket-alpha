# diagnose_tags.py
from utils.polymarket_api import PolymarketAPI

api = PolymarketAPI()

# 获取一些市场
markets = api.get_markets_with_tags(limit=100, max_markets=50)

# 统计 tags
tag_counts = {}
for market in markets:
    for tag in market.get('tags', []):
        tag_counts[tag] = tag_counts.get(tag, 0) + 1

# 显示最常见的 tags
print("最常见的 Tags（前 30）：\n")
sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
for i, (tag, count) in enumerate(sorted_tags[:30], 1):
    print(f"{i}. {tag}: {count}")

# 显示被分类为 Other 的市场
print("\n\n被分类为 'Other' 的市场示例：\n")
for market in markets[:10]:
    if market['category'] == 'Other':
        print(f"Question: {market['question'][:50]}...")
        print(f"Tags: {', '.join(market['tags'][:5])}")
        print(f"Category: {market['category']}\n")