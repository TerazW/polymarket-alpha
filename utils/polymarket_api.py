import requests
import json
import time
from typing import List, Dict, Optional
from collections import defaultdict

# Polymarket APIs
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

class PolymarketAPI:
    def __init__(self):
        self.gamma_api = GAMMA_API
        self.clob_api = CLOB_API
        self.data_api = DATA_API
        
        # ✅ Polymarket 官方主分类（按优先级排序）
        self.main_categories = [
            ('politics', 'Politics'),
            ('crypto', 'Crypto'),
            ('sports', 'Sports'),
            ('finance', 'Finance'),
            ('business', 'Business'),
            ('economy', 'Economy'),
            ('tech', 'Tech'),
            ('science', 'Science & Tech'),
            ('geopolitics', 'Geopolitics'),
        ]
    
    def get_markets_by_categories(
        self,
        min_volume_24h: float = 100,
        max_markets_per_category: int = None,
        total_limit: int = None
    ) -> List[Dict]:
        """
        ✅ 新方法：按官方分类获取市场
        
        策略：
        1. 遍历每个主分类（使用 tag_slug）
        2. 获取该分类下的所有市场
        3. 合并去重（同一市场可能在多个分类）
        4. 优先级分配（如果重复，使用优先级最高的分类）
        
        Args:
            min_volume_24h: 最小 24h 成交量
            max_markets_per_category: 每个分类最多获取多少市场
            total_limit: 总共最多获取多少市场
        
        Returns:
            List[Dict]: 市场列表（带正确的 category）
        """
        all_markets = {}  # {condition_id: market_data}
        market_categories = defaultdict(list)  # {condition_id: [categories]}
        
        print(f"\n📡 Fetching markets by official categories...")
        print(f"   Min volume: ${min_volume_24h}")
        print(f"   Categories: {len(self.main_categories)}\n")
        
        for tag_slug, category_name in self.main_categories:
            try:
                print(f"📂 {category_name}...")
                
                markets = self._get_markets_by_tag_slug(
                    tag_slug,
                    min_volume_24h=min_volume_24h,
                    limit=max_markets_per_category
                )
                
                print(f"   Found {len(markets)} markets")
                
                for market in markets:
                    condition_id = market['condition_id']
                    
                    # 记录这个市场属于哪些分类
                    market_categories[condition_id].append(category_name)
                    
                    # 保存市场数据（如果还没有）
                    if condition_id not in all_markets:
                        market['category'] = category_name  # 暂时设置
                        all_markets[condition_id] = market
                
                time.sleep(0.3)  # 避免 rate limit
                
            except Exception as e:
                print(f"   ❌ Error: {e}")
                continue
        
        # 分配最终分类（使用优先级）
        print(f"\n🔄 Assigning final categories...")
        for condition_id, categories in market_categories.items():
            if len(categories) > 1:
                # 多个分类，使用优先级最高的
                for tag_slug, category_name in self.main_categories:
                    if category_name in categories:
                        all_markets[condition_id]['category'] = category_name
                        break
        
        markets_list = list(all_markets.values())
        
        # 按 volume 排序
        markets_list.sort(key=lambda x: x['volume_24h'], reverse=True)
        
        # 应用总数限制
        if total_limit:
            markets_list = markets_list[:total_limit]
        
        print(f"\n✅ Total unique markets: {len(markets_list)}")
        
        # 统计分类分布
        cat_count = defaultdict(int)
        for m in markets_list:
            cat_count[m['category']] += 1
        
        print(f"\nCategory distribution:")
        for cat, count in sorted(cat_count.items(), key=lambda x: x[1], reverse=True):
            print(f"  {cat}: {count}")
        
        return markets_list
    
    def _get_markets_by_tag_slug(
        self,
        tag_slug: str,
        min_volume_24h: float = 0,
        limit: int = None
    ) -> List[Dict]:
        """
        通过 tag_slug 获取市场
        
        Args:
            tag_slug: 分类 slug（如 'politics', 'crypto'）
            min_volume_24h: 最小 24h 成交量
            limit: 最多获取多少个市场
        
        Returns:
            List[Dict]: 市场列表
        """
        markets = []
        offset = 0
        page_size = 100
        
        while True:
            try:
                response = requests.get(
                    f"{self.gamma_api}/events",
                    params={
                        'tag_slug': tag_slug,
                        'limit': page_size,
                        'offset': offset,
                        'closed': 'false'
                    },
                    timeout=30
                )
                response.raise_for_status()
                events = response.json()
                
                if not events:
                    break
                
                # 从 events 提取 markets
                for event in events:
                    if 'markets' in event and event['markets']:
                        for market_raw in event['markets']:
                            # 检查 volume
                            volume = float(market_raw.get('volume24hr', 0))
                            if volume < min_volume_24h:
                                continue
                            
                            # 提取市场数据
                            market = self._extract_market_from_event(market_raw)
                            if market:
                                markets.append(market)
                
                # 检查是否达到限制
                if limit and len(markets) >= limit:
                    markets = markets[:limit]
                    break
                
                # 检查是否最后一页
                if len(events) < page_size:
                    break
                
                offset += page_size
                
            except Exception as e:
                print(f"      Error at offset {offset}: {e}")
                break
        
        return markets
    
    def _extract_market_from_event(self, market: Dict) -> Optional[Dict]:
        """从 event 中的 market 提取标准字段"""
        try:
            condition_id = market.get('conditionId', '')
            if not condition_id:
                return None
            
            # token_id
            clob_token_ids_raw = market.get('clobTokenIds', '')
            token_id = None
            
            if isinstance(clob_token_ids_raw, str) and clob_token_ids_raw:
                try:
                    clob_token_ids = json.loads(clob_token_ids_raw)
                    if isinstance(clob_token_ids, list) and clob_token_ids:
                        token_id = clob_token_ids[0]
                except json.JSONDecodeError:
                    pass
            elif isinstance(clob_token_ids_raw, list) and clob_token_ids_raw:
                token_id = clob_token_ids_raw[0]
            
            if not token_id:
                token_id = condition_id
            
            # 价格
            outcome_prices_raw = market.get('outcomePrices', '["0.5", "0.5"]')
            price = 0.5
            
            try:
                if isinstance(outcome_prices_raw, str):
                    outcome_prices = json.loads(outcome_prices_raw)
                else:
                    outcome_prices = outcome_prices_raw
                
                if isinstance(outcome_prices, list) and outcome_prices:
                    price = float(outcome_prices[0])
            except (json.JSONDecodeError, ValueError, IndexError, TypeError):
                pass
            
            # Volume
            volume_24h = 0.0
            try:
                volume_24h = float(market.get('volume24hr', 0))
            except (ValueError, TypeError):
                pass
            
            # Liquidity
            liquidity = 0.0
            try:
                liquidity = float(market.get('liquidityNum', 0))
            except (ValueError, TypeError):
                pass
            
            return {
                'condition_id': condition_id,
                'token_id': token_id,
                'question': market.get('question', 'Unknown'),
                'description': market.get('description', ''),
                'price': price,
                'volume_24h': volume_24h,
                'liquidity': liquidity,
                'end_date': market.get('endDateIso', None),
                'active': market.get('active', True),
                'closed': market.get('closed', False),
                'category': 'Other',  # 会被后续覆盖
                'tags': []  # 不需要了
            }
            
        except Exception as e:
            return None
    
    # ===== Trades API（保持不变）=====
    
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


# 测试
if __name__ == "__main__":
    print("🧪 Testing tag_slug approach...\n")
    
    api = PolymarketAPI()
    
    markets = api.get_markets_by_categories(
        min_volume_24h=100,
        max_markets_per_category=100,
        total_limit=500
    )
    
    print(f"\n✅ Got {len(markets)} total markets")
    
    # 显示示例
    print(f"\nSample markets:")
    for cat in ['Politics', 'Crypto', 'Sports']:
        cat_markets = [m for m in markets if m['category'] == cat]
        if cat_markets:
            print(f"\n{cat}:")
            for m in cat_markets[:3]:
                print(f"  - {m['question'][:50]}... (${m['volume_24h']:,.0f})")
