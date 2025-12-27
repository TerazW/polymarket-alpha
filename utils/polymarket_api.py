import requests
from typing import List, Dict, Optional

# Polymarket APIs
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"  # 新增！

class PolymarketAPI:
    def __init__(self):
        self.gamma_api = GAMMA_API
        self.clob_api = CLOB_API
        self.data_api = DATA_API  # 新增！
    
    def get_markets(self, limit: int = 100) -> List[Dict]:
        """获取市场列表（Gamma API - 公开）"""
        try:
            response = requests.get(
                f"{self.gamma_api}/markets",
                params={
                    "limit": limit,
                    "active": True,
                    "closed": False
                },
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            print(f"❌ Error fetching markets: {e}")
            return []
    
    def get_trades(self, limit: int = 1000, condition_id: Optional[str] = None) -> List[Dict]:
        """
        获取公共成交数据（Data API - 公开，无需认证）
        
        Args:
            limit: 返回的成交数量（默认 100，最大可能更高）
            condition_id: 可选，筛选特定市场的成交
        
        Returns:
            成交列表，包含 price, size, timestamp, side 等
        """
        try:
            params = {"limit": limit}
            
            # 如果指定了 condition_id，可以筛选（需要确认 API 是否支持）
            # 从文档看暂时没看到 condition_id 参数，可能需要客户端过滤
            
            response = requests.get(
                f"{self.data_api}/trades",
                params=params,
                timeout=20
            )
            response.raise_for_status()
            trades = response.json()
            
            # 如果指定了 condition_id，在客户端过滤
            if condition_id:
                trades = [t for t in trades if t.get('conditionId') == condition_id]
            
            return trades
            
        except Exception as e:
            print(f"❌ Error fetching trades: {e}")
            return []
    
    def get_orderbook(self, token_id: str) -> Optional[Dict]:
        """获取订单簿（CLOB API - 公开）"""
        try:
            response = requests.get(
                f"{self.clob_api}/book",
                params={"token_id": token_id},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"❌ Error fetching book for {token_id}: {e}")
            return None
    
    def extract_market_data(self, markets: List[Dict]) -> List[Dict]:
        """从 Gamma API 数据中提取关键字段"""
        extracted = []
        
        for market in markets:
            try:
                tokens = market.get('tokens', [])
                if not tokens:
                    continue
                
                yes_token = tokens[0]
                
                data = {
                    'condition_id': market.get('condition_id', ''),
                    'token_id': yes_token.get('token_id', ''),
                    'question': market.get('question', 'Unknown'),
                    'description': market.get('description', ''),
                    'price': float(yes_token.get('price', 0.5)),
                    'volume_24h': float(market.get('volume24hr', 0)),
                    'liquidity': float(market.get('liquidity', 0)),
                    'end_date': market.get('end_date_iso', None),
                    'active': market.get('active', True),
                    'category': market.get('market', 'Other')
                }
                
                extracted.append(data)
                
            except Exception as e:
                print(f"⚠️  Error extracting market: {e}")
                continue
        
        return extracted

# 测试
if __name__ == "__main__":
    print("🧪 Testing Polymarket Data API...\n")
    
    api = PolymarketAPI()
    
    # 1. 测试获取公共成交
    print("1️⃣ Testing GET /trades (Data API)...")
    trades = api.get_trades(limit=10)
    
    if trades:
        print(f"   ✅ Fetched {len(trades)} trades")
        
        # 显示第一笔成交
        t = trades[0]
        print(f"\n   First trade:")
        print(f"   Condition ID: {t.get('conditionId', 'N/A')[:20]}...")
        print(f"   Side: {t.get('side', 'N/A')}")
        print(f"   Price: {t.get('price', 0)}")
        print(f"   Size: {t.get('size', 0)}")
        print(f"   Timestamp: {t.get('timestamp', 0)}")
        print(f"   Title: {t.get('title', 'N/A')[:50]}...")
        
        # 统计
        print(f"\n   📊 Statistics:")
        buy_count = sum(1 for t in trades if t.get('side') == 'BUY')
        sell_count = sum(1 for t in trades if t.get('side') == 'SELL')
        print(f"   BUY: {buy_count}, SELL: {sell_count}")
        
    else:
        print("   ❌ No trades fetched")
    
    # 2. 测试获取市场列表
    print(f"\n2️⃣ Testing GET /markets (Gamma API)...")
    markets = api.get_markets(limit=3)
    
    if markets:
        print(f"   ✅ Fetched {len(markets)} markets")
        extracted = api.extract_market_data(markets)
        
        if extracted:
            m = extracted[0]
            print(f"\n   First market:")
            print(f"   Question: {m['question'][:60]}...")
            print(f"   Condition ID: {m['condition_id']}")
            print(f"   Price: {m['price']:.2%}")
    
    print("\n✅ All tests completed!")