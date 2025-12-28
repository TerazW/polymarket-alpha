import sys
sys.path.insert(0, '.')

from utils.polymarket_api import PolymarketAPI

api = PolymarketAPI()

# 获取少量市场
print("Fetching markets...")
markets = api.get_all_markets_from_events(min_volume_24h=100, max_events=1)

print(f"\nGot {len(markets)} markets after extraction")

if not markets:
    print("\n❌ Extraction failed completely")
    print("\nLet's check raw data...")
    
    # 直接获取原始数据
    import requests
    response = requests.get(
        'https://gamma-api.polymarket.com/events',
        params={'limit': 1, 'closed': 'false'}
    )
    events = response.json()
    
    if events and 'markets' in events[0]:
        market = events[0]['markets'][0]
        print("\nFirst market raw data:")
        import json
        print(json.dumps(market, indent=2)[:1000])
        
        print("\n\nKey fields:")
        print(f"conditionId: {market.get('conditionId')}")
        print(f"clobTokenIds: {market.get('clobTokenIds')}")
        print(f"volume24hr: {market.get('volume24hr')}")
        print(f"question: {market.get('question')}")
        
        # 尝试手动提取
        print("\n\nTrying manual extraction...")
        try:
            extracted = api.extract_market_data([market])
            if extracted:
                print("✅ Manual extraction worked!")
                print(json.dumps(extracted[0], indent=2))
            else:
                print("❌ Manual extraction also failed")
        except Exception as e:
            print(f"❌ Exception: {e}")
            import traceback
            traceback.print_exc()
else:
    print("\n✅ Extraction worked!")
    print("\nFirst market:")
    import json
    print(json.dumps(markets[0], indent=2))

