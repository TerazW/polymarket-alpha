"""
调试脚本：检查 sync.py 中的 token_id 值
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.polymarket_api import PolymarketAPI

api = PolymarketAPI()
print("Fetching markets...")
markets = api.get_markets(limit=200, min_volume_24h=100)

if markets:
    extracted = api.extract_market_data(markets)
    extracted.sort(key=lambda x: x['volume_24h'], reverse=True)
    extracted = extracted[:10]
    
    print(f"\n找到 {len(extracted)} 个市场\n")
    print("=" * 80)
    
    for i, market in enumerate(extracted, 1):
        token_id = market.get('token_id')
        condition_id = market.get('condition_id')
        question = market.get('question', '')[:60]
        
        print(f"[{i}] {question}")
        print(f"    token_id: {token_id}")
        print(f"    condition_id: {condition_id}")
        print(f"    token_id type: {type(token_id)}")
        print(f"    token_id repr: {repr(token_id)}")
        print()
else:
    print("❌ No markets fetched")
    