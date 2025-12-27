import requests
import json
from typing import List, Dict, Optional

# Polymarket APIs
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

class PolymarketAPI:
    def __init__(self):
        self.gamma_api = GAMMA_API
        self.clob_api = CLOB_API
        self.data_api = DATA_API
    
    def get_markets(self, limit: int = 100, min_volume_24h: float = 100) -> List[Dict]:
        """
        获取市场列表（Gamma API）
        
        Args:
            limit: 返回数量
            min_volume_24h: 最小 24h 成交量
        """
        try:
            # 使用 closed=false 获取开放市场
            response = requests.get(
                f"{self.gamma_api}/markets",
                params={
                    'limit': min(limit * 3, 500),
                    'closed': 'false'
                },
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            if not isinstance(data, list):
                return []
            
            # 过滤有成交量的市场
            filtered = [
                m for m in data 
                if float(m.get('volume24hr', 0)) >= min_volume_24h
            ]
            
            print(f"   Found {len(filtered)} markets with volume > ${min_volume_24h} (from {len(data)} open markets)")
            
            # 按成交量排序
            filtered.sort(key=lambda x: float(x.get('volume24hr', 0)), reverse=True)
            
            return filtered[:limit]
            
        except Exception as e:
            print(f"❌ Error fetching markets: {e}")
            return []
    
    def get_trades(
        self, 
        limit: int = 1000,
        offset: int = 0,
        market: Optional[str] = None,
        side: Optional[str] = None
    ) -> List[Dict]:
        """获取公共成交数据（Data API）"""
        try:
            params = {
                "limit": min(limit, 10000),
                "offset": offset
            }
            
            if market:
                params["market"] = market
            
            if side:
                params["side"] = side
            
            response = requests.get(
                f"{self.data_api}/trades",
                params=params,
                timeout=30
            )
            response.raise_for_status()
            trades = response.json()
            
            return trades if isinstance(trades, list) else []
            
        except Exception as e:
            print(f"❌ Error fetching trades: {e}")
            return []
    
    def get_trades_for_market(
        self, 
        condition_id: str, 
        limit: int = 5000
    ) -> List[Dict]:
        """获取特定市场的成交数据"""
        return self.get_trades(limit=limit, market=condition_id)
    
    def get_orderbook(self, token_id: str) -> Optional[Dict]:
        """获取订单簿（CLOB API）"""
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
                condition_id = market.get('conditionId', '')
                clob_token_ids_raw = market.get('clobTokenIds', [])
                
                if not condition_id or not clob_token_ids_raw:
                    continue
                
                # 🔧 修复：处理 clobTokenIds 可能是字符串或数组
                if isinstance(clob_token_ids_raw, str):
                    try:
                        clob_token_ids = json.loads(clob_token_ids_raw)
                    except:
                        clob_token_ids = []
                else:
                    clob_token_ids = clob_token_ids_raw
                
                token_id = clob_token_ids[0] if clob_token_ids else ''
                if not token_id:
                    continue
                
                # 价格处理
                outcome_prices_raw = market.get('outcomePrices', '["0.5", "0.5"]')
                
                if isinstance(outcome_prices_raw, str):
                    try:
                        outcome_prices = json.loads(outcome_prices_raw)
                    except:
                        outcome_prices = ["0.5", "0.5"]
                else:
                    outcome_prices = outcome_prices_raw
                
                try:
                    price = float(outcome_prices[0]) if outcome_prices else 0.5
                except (ValueError, IndexError, TypeError):
                    price = 0.5
                
                data = {
                    'condition_id': condition_id,
                    'token_id': token_id,
                    'question': market.get('question', 'Unknown'),
                    'description': market.get('description', ''),
                    'price': price,
                    'volume_24h': float(market.get('volume24hr', 0)),
                    'liquidity': float(market.get('liquidityNum', 0)),
                    'end_date': market.get('endDateIso', None),
                    'active': market.get('active', True),
                    'closed': market.get('closed', False),
                    'category': 'Other'
                }
                
                extracted.append(data)
                
            except Exception as e:
                continue
        
        return extracted

# 测试
if __name__ == "__main__":
    print("🧪 Testing Polymarket APIs...\n")
    
    api = PolymarketAPI()
    
    print("Testing GET /markets (open markets, volume > $100)...")
    markets_list = api.get_markets(limit=10, min_volume_24h=100)
    
    if markets_list:
        print(f"✅ Success!\n")
        
        extracted = api.extract_market_data(markets_list)
        print(f"✅ Extracted {len(extracted)} markets\n")
        
        if extracted:
            print("Top 3 markets:")
            for i, m in enumerate(extracted[:3], 1):
                print(f"{i}. {m['question'][:60]}...")
                print(f"   Price: {m['price']:.2%}")
                print(f"   Volume: ${m['volume_24h']:,.0f}")
                print()
    
    print("✅ All tests completed!")