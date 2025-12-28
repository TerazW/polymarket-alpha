import requests
import json
import time
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
        获取市场列表（传统方法，仅用于后向兼容）
        
        注意：此方法最多返回 500 个市场，且 offset 不起作用
        建议使用 get_all_markets_from_events() 获取完整市场列表
        
        Args:
            limit: 返回数量（最大 500）
            min_volume_24h: 最小 24h 成交量
        """
        try:
            response = requests.get(
                f"{self.gamma_api}/markets",
                params={
                    'limit': min(limit, 500),
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
            
            print(f"   Found {len(filtered)} markets with volume > ${min_volume_24h}")
            
            # 按成交量排序
            filtered.sort(key=lambda x: float(x.get('volume24hr', 0)), reverse=True)
            
            return filtered[:limit]
            
        except Exception as e:
            print(f"❌ Error fetching markets: {e}")
            return []
    
    def get_all_markets_from_events(
        self, 
        min_volume_24h: float = 100,
        max_events: int = None
    ) -> List[Dict]:
        """
        通过 Events API 获取所有市场（推荐方法）
        
        优势：
        - 可以获取所有市场（2920+）
        - 支持完整分页
        - 自动去重
        
        Args:
            min_volume_24h: 最小 24h 成交量
            max_events: 最多处理多少个 events（None = 全部）
        
        Returns:
            List[Dict]: 市场列表
        """
        all_markets = {}  # 用字典去重 {conditionId: market}
        offset = 0
        limit = 500  # 每页 500 个 events
        events_processed = 0
        
        print(f"\n📡 Fetching all markets via Events API...")
        print(f"   Min volume: ${min_volume_24h}")
        
        while True:
            try:
                response = requests.get(
                    f"{self.gamma_api}/events",
                    params={
                        'limit': limit,
                        'offset': offset,
                        'closed': 'false',
                        'order': 'id',
                        'ascending': 'false'
                    },
                    timeout=30
                )
                response.raise_for_status()
                events = response.json()
                
                if not events:
                    print(f"   No more events found at offset {offset}")
                    break
                
                # 从每个 event 提取 markets
                markets_in_batch = 0
                for event in events:
                    if 'markets' in event and isinstance(event['markets'], list):
                        for market in event['markets']:
                            condition_id = market.get('conditionId')
                            if condition_id and condition_id not in all_markets:
                                all_markets[condition_id] = market
                                markets_in_batch += 1
                
                events_processed += len(events)
                
                print(f"   Batch {offset//limit + 1}: {len(events)} events, "
                      f"{markets_in_batch} new markets, "
                      f"total unique: {len(all_markets)}")
                
                # 检查是否达到最大 events 限制
                if max_events and events_processed >= max_events:
                    print(f"   Reached max_events limit: {max_events}")
                    break
                
                # 检查是否是最后一页
                if len(events) < limit:
                    print(f"   Last page reached (got {len(events)} < {limit})")
                    break
                
                offset += limit
                time.sleep(0.2)  # 避免 rate limit (125 req/10s)
                
            except Exception as e:
                print(f"❌ Error at offset {offset}: {e}")
                break
        
        # 转换回列表
        markets_list = list(all_markets.values())
        
        print(f"\n✅ Total unique markets fetched: {len(markets_list)}")
        
        # 过滤交易量
        filtered = [
            m for m in markets_list
            if float(m.get('volume24hr', 0)) >= min_volume_24h
        ]
        
        print(f"   After volume filter (>${min_volume_24h}): {len(filtered)}")
        
        # 按成交量排序
        filtered.sort(key=lambda x: float(x.get('volume24hr', 0)), reverse=True)

        extracted = self.extract_market_data(filtered)
        
        return extracted
    
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
                
                # 处理 clobTokenIds 可能是字符串或数组
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
    
    print("="*70)
    print("Test 1: Traditional get_markets (limited to 500)")
    print("="*70)
    markets_old = api.get_markets(limit=10, min_volume_24h=100)
    print(f"✅ Got {len(markets_old)} markets\n")
    
    print("="*70)
    print("Test 2: New get_all_markets_from_events (unlimited)")
    print("="*70)
    markets_new = api.get_all_markets_from_events(
        min_volume_24h=100,
        max_events=1000  # 测试用，限制前 1000 个 events
    )
    print(f"\n✅ Got {len(markets_new)} markets\n")
    
    if markets_new:
        print("Top 5 markets by volume:")
        for i, m in enumerate(markets_new[:5], 1):
            print(f"{i}. {m['question'][:60]}...")
            print(f"   Price: {m['price']:.2%} | Volume: ${m['volume_24h']:,.0f}")
            print()
    
    print("✅ All tests completed!")
