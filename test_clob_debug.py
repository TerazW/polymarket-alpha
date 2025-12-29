"""
调试 CLOB API - 测试真实市场
"""

import os
import sys
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import TradeParams
import time

def test_clob_api():
    print("="*70)
    print("🔍 CLOB API Debug Test")
    print("="*70)
    
    # 初始化客户端
    private_key = os.getenv("PRIVATE_KEY")
    
    print("\n1️⃣ Initializing client...")
    client = ClobClient(
        "https://clob.polymarket.com",
        key=private_key,
        chain_id=137
    )
    
    print(f"   ✅ Address: {client.get_address()}")
    
    # 设置 API 凭证
    print("\n2️⃣ Setting up API credentials...")
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    print(f"   ✅ API Key: {creds.api_key[:8]}...")
    
    # 测试获取市场列表
    print("\n3️⃣ Fetching active markets...")
    try:
        markets = client.get_markets()
        print(f"   ✅ Got {len(markets.get('data', []))} markets")
        
        if markets.get('data'):
            # 找一个有交易量的市场
            print("\n   🔍 Looking for market with volume...")
            high_volume_market = None
            
            for market in markets['data'][:100]:  # 检查前100个
                volume = market.get('volume', 0)
                if volume > 1000:  # 至少$1000交易量
                    high_volume_market = market
                    break
            
            if not high_volume_market:
                print("   ⚠️  No high-volume market found in first 100, using first market")
                high_volume_market = markets['data'][0]
            
            # 测试这个市场
            print(f"\n   📊 Testing with market:")
            print(f"      Question: {high_volume_market.get('question', 'N/A')[:60]}...")
            print(f"      Condition ID: {high_volume_market.get('condition_id')}")
            print(f"      Volume: ${high_volume_market.get('volume', 0):,.2f}")
            print(f"      Volume 24h: ${high_volume_market.get('volume_24hr', 0):,.2f}")
            
            # 尝试获取交易数据
            print("\n4️⃣ Testing get_trades with condition_id...")
            
            condition_id = high_volume_market.get('condition_id')
            now = int(time.time())
            after = now - (24 * 3600)  # 24小时前
            
            print(f"      Market: {condition_id}")
            print(f"      After: {after} ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(after))})")
            
            try:
                params = TradeParams(market=condition_id, after=after)
                trades = client.get_trades(params=params)
                
                print(f"\n   ✅ Got {len(trades)} trades")
                
                if trades:
                    print(f"\n   📝 First trade sample:")
                    trade = trades[0]
                    print(f"      ID: {trade.get('id')}")
                    print(f"      Side: {trade.get('side')}")
                    print(f"      Price: {trade.get('price')}")
                    print(f"      Size: {trade.get('size')}")
                    print(f"      Match time: {trade.get('match_time')}")
                    print(f"      Maker orders: {len(trade.get('maker_orders', []))}")
                else:
                    print(f"   ⚠️  No trades in last 24h for this market")
                    
                    # 尝试更长时间范围
                    print(f"\n5️⃣ Trying longer time range (7 days)...")
                    after_7d = now - (7 * 24 * 3600)
                    params_7d = TradeParams(market=condition_id, after=after_7d)
                    trades_7d = client.get_trades(params=params_7d)
                    
                    print(f"   Got {len(trades_7d)} trades in last 7 days")
                    
                    if trades_7d:
                        trade = trades_7d[0]
                        print(f"\n   📝 Sample trade:")
                        print(f"      ID: {trade.get('id')}")
                        print(f"      Side: {trade.get('side')}")
                        print(f"      Price: {trade.get('price')}")
                        print(f"      Match time: {trade.get('match_time')}")
                        
            except Exception as e:
                print(f"   ❌ Error getting trades: {e}")
                import traceback
                traceback.print_exc()
                
    except Exception as e:
        print(f"   ❌ Error getting markets: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*70)
    print("🏁 Debug test complete")
    print("="*70)

if __name__ == "__main__":
    test_clob_api()