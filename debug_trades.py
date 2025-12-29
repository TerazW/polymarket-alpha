"""
调试：查看 Data API 返回的交易数据结构
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.polymarket_api import PolymarketAPI

# Bears vs 49ers
CONDITION_ID = "0x52c934257bd7d014c8dcd5833fee69597027d14c9c47c791f6be6e286e59cef7"

def main():
    print("=" * 70)
    print("Debugging Data API trades response")
    print("=" * 70)
    
    api = PolymarketAPI()
    
    print(f"\n📊 Fetching trades for market: {CONDITION_ID[:20]}...")
    trades = api.get_trades_for_market(CONDITION_ID, limit=10)
    
    print(f"\n✅ Got {len(trades)} trades")
    
    if trades:
        print(f"\n🔍 Sample trade structure:")
        trade = trades[0]
        print(f"\nAll fields: {list(trade.keys())}")
        
        print(f"\n📋 Trade details:")
        for key, value in trade.items():
            print(f"  {key}: {value}")
        
        # 检查是否有 taker/maker 标识
        print(f"\n🎯 Looking for taker/maker identification...")
        
        potential_fields = ['type', 'role', 'aggressor', 'isTaker', 'isMaker', 
                           'takerOnly', 'maker', 'taker', 'orderType']
        
        found_fields = {k: trade.get(k) for k in potential_fields if k in trade}
        
        if found_fields:
            print(f"  ✅ Found potential fields: {found_fields}")
        else:
            print(f"  ⚠️  No explicit taker/maker field found")
        
        # 检查前 5 笔交易的模式
        print(f"\n📊 Analyzing first 5 trades...")
        for i, t in enumerate(trades[:5], 1):
            print(f"  {i}. side={t.get('side')}, size={t.get('size')}, "
                  f"price={t.get('price')}, timestamp={t.get('timestamp')}")
    else:
        print(f"\n⚠️  No trades returned")
        print(f"\n💡 Trying with explicit parameters...")
        
        # 尝试不带 market 参数
        trades_all = api.get_trades(limit=10)
        print(f"   Without market filter: {len(trades_all)} trades")

if __name__ == "__main__":
    main()