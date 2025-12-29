# check_side_meaning.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.polymarket_api import PolymarketAPI
from collections import Counter

def analyze_side_field():
    api = PolymarketAPI()
    
    print("\n" + "="*70)
    print("🔬 Analyzing 'side' Field Meaning")
    print("="*70)
    
    # 获取一个高交易量市场
    print("\n📡 Fetching high-volume market...")
    markets = api.get_markets_by_categories(
        min_volume_24h=50000,
        total_limit=1
    )
    
    if not markets:
        print("❌ No markets found")
        return
    
    market = markets[0]
    condition_id = market['condition_id']
    current_price = market['price']
    
    print(f"✅ Market: {market['question'][:60]}...")
    print(f"   Current Price: {current_price*100:.1f}%")
    print(f"   Volume: ${market['volume_24h']:,.0f}")
    
    # 获取最近的交易
    print(f"\n📊 Fetching recent trades...")
    trades = api.get_trades_for_market(condition_id, limit=500)
    
    if not trades:
        print("❌ No trades found")
        return
    
    print(f"✅ Got {len(trades)} trades\n")
    
    # 分析 side 分布
    print("="*70)
    print("📊 Side Distribution Analysis:")
    print("="*70)
    
    side_counter = Counter()
    buy_prices = []
    sell_prices = []
    
    for trade in trades:
        side = trade.get('side', 'UNKNOWN')
        price = float(trade.get('price', 0))
        
        side_counter[side] += 1
        
        if side == 'BUY':
            buy_prices.append(price)
        elif side == 'SELL':
            sell_prices.append(price)
    
    print(f"\nSide counts:")
    for side, count in side_counter.most_common():
        pct = count / len(trades) * 100
        print(f"  {side:<10}: {count:>4} ({pct:>5.1f}%)")
    
    # 价格分析
    if buy_prices and sell_prices:
        avg_buy_price = sum(buy_prices) / len(buy_prices)
        avg_sell_price = sum(sell_prices) / len(sell_prices)
        
        print(f"\n" + "="*70)
        print("💡 Price Pattern Analysis:")
        print("="*70)
        print(f"  Current market price: {current_price:.4f}")
        print(f"  Average BUY price:    {avg_buy_price:.4f}")
        print(f"  Average SELL price:   {avg_sell_price:.4f}")
        print(f"  Difference:           {avg_buy_price - avg_sell_price:.4f}")
        
        print(f"\n" + "="*70)
        print("🎯 Interpretation:")
        print("="*70)
        
        if abs(avg_buy_price - avg_sell_price) < 0.01:
            print("  ✅ Avg BUY ≈ Avg SELL")
            print("     → 'side' likely means AGGRESSOR direction (taker)")
            print("     → This is what we need for AR/CS calculation!")
            interpretation = "AGGRESSOR"
        else:
            print("  ⚠️  Avg BUY ≠ Avg SELL significantly")
            print("     → 'side' might mean order book side")
            print("     → Need further investigation")
            interpretation = "UNCLEAR"
    else:
        print("\n⚠️  Not enough data for price analysis")
        interpretation = "INSUFFICIENT_DATA"
    
    # 显示最近几笔交易
    print(f"\n" + "="*70)
    print("📋 Recent Trades Sample (last 10):")
    print("="*70)
    print(f"{'Time':<20} {'Side':<6} {'Price':<8} {'Size':<10}")
    print("-"*70)
    
    from datetime import datetime
    
    for trade in trades[:10]:
        ts = datetime.fromtimestamp(trade['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
        side = trade.get('side', 'N/A')
        price = float(trade.get('price', 0))
        size = float(trade.get('size', 0))
        
        print(f"{ts:<20} {side:<6} {price:<8.4f} ${size:<10.2f}")
    
    return interpretation

if __name__ == "__main__":
    interpretation = analyze_side_field()
    
    print("\n" + "="*70)
    print("🎯 CONCLUSION:")
    print("="*70)
    
    if interpretation == "AGGRESSOR":
        print("✅ The 'side' field represents AGGRESSOR (taker) direction")
        print("✅ We can directly use it for AR and CS calculation")
        print("\n💡 Next step: Implement the new metrics system")
    elif interpretation == "UNCLEAR":
        print("⚠️  The 'side' field meaning is unclear")
        print("⚠️  We may need alternative methods")
        print("\n💡 Options:")
        print("   1. Check Polymarket API documentation")
        print("   2. Use price deviation as proxy for aggressor")
    else:
        print("⚠️  Insufficient data for analysis")
        print("💡 Try running on a higher-volume market")
    
    print("="*70)