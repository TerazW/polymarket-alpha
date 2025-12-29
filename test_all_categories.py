import sys
sys.path.insert(0, 'C:/Projects/market-sensemaking')

from utils.polymarket_api import PolymarketAPI

api = PolymarketAPI()

print("测试获取所有分类...\n")

markets = api.get_markets_by_categories(
    min_volume_24h=100,
    max_markets_per_category=None,  # 不限制每个分类
    total_limit=None  # 不限制总数
)

print(f"\n✅ 最终获取 {len(markets)} 个唯一市场")

# 统计每个分类
from collections import Counter
cats = Counter(m['category'] for m in markets)

print("\n分类分布:")
for cat, count in cats.most_common():
    print(f"  {cat}: {count}")