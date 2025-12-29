# test_api_pagination.py
import sys
sys.path.insert(0, 'C:/Projects/market-sensemaking')

from utils.polymarket_api import PolymarketAPI

api = PolymarketAPI()

print("测试 Sports 分类的分页...\n")

# 测试单个分类
markets = api._get_markets_by_tag_slug(
    tag_slug='sports',
    min_volume_24h=100,
    limit=None  # 不限制
)

print(f"\n✅ 获取到 {len(markets)} 个市场")

if markets:
    volumes = [m['volume_24h'] for m in markets]
    print(f"Volume 范围: ${min(volumes):,.0f} - ${max(volumes):,.0f}")
    print(f"\n前 5 个市场:")
    for i, m in enumerate(markets[:5], 1):
        print(f"  {i}. {m['question'][:50]}... (${m['volume_24h']:,.0f})")