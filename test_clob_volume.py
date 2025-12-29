"""
测试 CLOB API - 查找高交易量市场
"""

import os
from dotenv import load_dotenv
load_dotenv()

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import TradeParams
import time

def test_high_volume():
    print("="*70)
    print("🔍 Finding High-Volume Markets")
    print("="*70)
    
    # 初始化
    client = ClobClient(
        "https://clob.polymarket.com",
        key=os.getenv("PRIVATE_KEY"),
        chain_id=137
    )
    
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    
    print("\n📊 Fetching markets...")
    
    # 收集所有市场
    all_markets = []
    next_cursor = None
    
    for page in range(5):  # 获取前5页
        try:
            if next_cursor:
                result = client.get_markets(next_cursor=next_cursor)
            else:
                result = client.get_markets()
            
            markets = result.get('data', [])
            all_markets.extend(markets)
            
            next_cursor = result.get('next_cursor')
            
            print(f"   Page {page + 1}: {len(markets)} markets (total: {len(all_markets)})")
            
            if not next_cursor:
                break
                
        except Exception as e:
            print(f"   Error: {e}")
            break
    
    # 按交易量排序
    print(f"\n🔢 Sorting {len(all_markets)} markets by volume...")
    
    sorted_markets = sorted(
        all_markets,
        key=lambda m: m.get('volume', 0) + m.get('volume_24hr', 0),
        reverse=True
    )
    
    # 显示前20个
    print(f"\n📈 Top 20 markets by volume:")
    print(f"{'Rank':<6}{'Volume':<15}{'24h Vol':<15}{'Question'}")
    print("-" * 70)
    
    for i, market in enumerate(sorted_markets[:20], 1):
        volume = market.get('volume', 0)
        volume_24h = market.get('volume_24hr', 0)
        question = market.get('question', 'N/A')[:40]
        
        print(f"{i:<6}${volume:<14,.0f}${volume_24h:<14,.0f}{question}...")
    
    # 测试第一个有交易量的市场
    print(f"\n🧪 Testing trades for top market...")
    
    top_market = sorted_markets[0]
    print(f"\n   Question: {top_market.get('question')}")
    print(f"   Condition ID: {top_market.get('condition_id')}")
    print(f"   Volume: ${top_market.get('volume', 0):,.2f}")
    
    # 获取交易
    condition_id = top_market.get('condition_id')
    now = int(time.time())
    after = now - (24 * 3600)
    
    try:
        params = TradeParams(market=condition_id, after=after)
        trades = client.get_trades(params=params)
        
        print(f"\n   ✅ Got {len(trades)} trades in last 24h")
        
        if trades:
            trade = trades[0]
            print(f"\n   📝 Sample trade:")
            print(f"      Side: {trade.get('side')}")
            print(f"      Price: {trade.get('price')}")
            print(f"      Size: {trade.get('size')}")
            print(f"      Maker orders: {len(trade.get('maker_orders', []))}")
            
            return True
        else:
            print(f"   ⚠️  No trades found")
            return False
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "="*70)

if __name__ == "__main__":
    test_high_volume()