# check_trade_structure.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.polymarket_api import PolymarketAPI

def check_trade_data_structure():
    api = PolymarketAPI()
    
    print("\n" + "="*70)
    print("🔍 Checking Polymarket Trade Data Structure")
    print("="*70)
    
    # 获取一个高交易量市场的数据
    print("\n📡 Fetching sample market...")
    markets = api.get_markets_by_categories(
        min_volume_24h=10000,
        total_limit=1
    )
    
    if not markets:
        print("❌ No markets found")
        return
    
    market = markets[0]
    condition_id = market['condition_id']
    
    print(f"✅ Sample market: {market['question'][:60]}...")
    print(f"   Volume: ${market['volume_24h']:,.0f}")
    
    # 获取交易数据
    print(f"\n📊 Fetching trades...")
    trades = api.get_trades_for_market(condition_id, limit=10)
    
    if not trades:
        print("❌ No trades found")
        return
    
    print(f"✅ Got {len(trades)} trades\n")
    
    # 分析第一笔交易的结构
    print("="*70)
    print("📋 Sample Trade Structure:")
    print("="*70)
    
    sample = trades[0]
    for key, value in sample.items():
        value_str = str(value)[:50]
        print(f"  {key:<20}: {value_str}")
    
    # 检查关键字段
    print("\n" + "="*70)
    print("✅ Field Availability Check:")
    print("="*70)
    
    required_fields = {
        'price': 'Price data',
        'size': 'Trade size/volume',
        'timestamp': 'Time information',
        'side': 'Buy/Sell direction (CRITICAL)',
        'makerOrderId': 'Maker order ID (for aggressor detection)',
        'takerOrderId': 'Taker order ID (for aggressor detection)'
    }
    
    for field, description in required_fields.items():
        if field in sample:
            print(f"  ✅ {field:<20} - {description}")
        else:
            print(f"  ❌ {field:<20} - {description} [MISSING]")
    
    # 检查 side 字段的值
    if 'side' in sample:
        print("\n" + "="*70)
        print("📊 Side Field Analysis:")
        print("="*70)
        
        side_values = set()
        for trade in trades:
            if 'side' in trade:
                side_values.add(trade['side'])
        
        print(f"  Unique side values: {side_values}")
        
        if 'BUY' in side_values or 'SELL' in side_values:
            print("  ✅ Standard BUY/SELL format detected")
        else:
            print("  ⚠️  Non-standard format, need mapping")
    else:
        print("\n" + "="*70)
        print("⚠️  WARNING: No 'side' field found")
        print("="*70)
        print("  We'll need to infer aggressor from order IDs")
        print("  This is more complex but doable")
    
    return sample

if __name__ == "__main__":
    check_trade_data_structure()