"""
Polymarket API 模块
支持：
- 12 个官方主分类
- 多分类支持（一个市场可属于多个分类）
- 按分类获取市场
- 获取所有活跃市场
- 获取交易数据
"""

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
        
        # ✅ Polymarket 官方 12 个主分类（按优先级排序，从图片左到右）
        self.main_categories = [
            ('politics', 'Politics'),
            ('sports', 'Sports'),
            ('crypto', 'Crypto'),
            ('finance', 'Finance'),
            ('geopolitics', 'Geopolitics'),
            ('earnings', 'Earnings'),
            ('tech', 'Tech'),
            ('culture', 'Culture'),
            ('world', 'World'),
            ('economy', 'Economy'),
            ('elections', 'Elections'),
            ('mentions', 'Mentions'),
        ]
    
    def get_markets_by_categories(
        self,
        min_volume_24h: float = 100,
        max_markets_per_category: int = None,
        total_limit: int = None
    ) -> List[Dict]:
        """
        ✅ 按官方分类获取市场（支持多分类）
        
        策略：
        1. 遍历每个主分类（使用 tag_slug）
        2. 获取该分类下的所有市场
        3. 合并去重（同一市场可能在多个分类）
        4. 记录所有分类到 categories 列表
        5. 优先级分配主分类到 category 字段
        
        Args:
            min_volume_24h: 最小 24h 成交量
            max_markets_per_category: 每个分类最多获取多少市场
            total_limit: 总共最多获取多少市场
        
        Returns:
            List[Dict]: 市场列表，每个市场包含：
                - category: 主分类（优先级最高的）
                - categories: 所有分类列表
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
                    if category_name not in market_categories[condition_id]:
                        market_categories[condition_id].append(category_name)
                    
                    # 保存市场数据（如果还没有）
                    if condition_id not in all_markets:
                        all_markets[condition_id] = market
                
                time.sleep(0.3)  # 避免 rate limit
                
            except Exception as e:
                print(f"   ❌ Error: {e}")
                continue
        
        # 分配分类
        print(f"\n🔄 Assigning categories...")
        for condition_id, categories in market_categories.items():
            # 保存所有分类
            all_markets[condition_id]['categories'] = categories
            
            # 分配主分类（优先级最高的）
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
        
        # 统计分类分布（按主分类）
        cat_count = defaultdict(int)
        for m in markets_list:
            cat_count[m['category']] += 1
        
        print(f"\nCategory distribution (primary):")
        for cat, count in sorted(cat_count.items(), key=lambda x: x[1], reverse=True):
            print(f"  {cat}: {count}")
        
        # 统计多分类情况
        multi_cat_count = sum(1 for m in markets_list if len(m.get('categories', [])) > 1)
        if multi_cat_count > 0:
            print(f"\n📊 Markets with multiple categories: {multi_cat_count}")
        
        return markets_list
    
    def get_all_markets_from_events(
        self,
        min_volume_24h: float = 100,
        max_events: int = None
    ) -> List[Dict]:
        """
        ✅ 从 Events API 获取所有活跃市场（不按分类）
        
        用于 sync_incremental.py 的增量同步
        
        Args:
            min_volume_24h: 最小 24h 成交量
            max_events: 最多获取多少个 events（None = 全部）
        
        Returns:
            List[Dict]: 市场列表
        """
        markets = []
        offset = 0
        page_size = 100
        events_fetched = 0
        
        print(f"\n📡 Fetching all markets from Events API...")
        print(f"   Min volume: ${min_volume_24h}")
        print(f"   Max events: {max_events or 'unlimited'}\n")
        
        while True:
            try:
                response = requests.get(
                    f"{self.gamma_api}/events",
                    params={
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
                
                events_fetched += len(events)
                
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
                
                # 检查是否达到 event 限制
                if max_events and events_fetched >= max_events:
                    break
                
                # 检查是否最后一页
                if len(events) < page_size:
                    break
                
                offset += page_size
                
                # 进度显示
                if offset % 500 == 0:
                    print(f"   Processed {events_fetched} events, found {len(markets)} markets...")
                
                time.sleep(0.2)  # Rate limit
                
            except Exception as e:
                print(f"   ❌ Error at offset {offset}: {e}")
                break
        
        # 去重（基于 condition_id）
        unique_markets = {}
        for m in markets:
            cid = m['condition_id']
            if cid not in unique_markets:
                unique_markets[cid] = m
            elif m['volume_24h'] > unique_markets[cid]['volume_24h']:
                unique_markets[cid] = m
        
        markets_list = list(unique_markets.values())
        markets_list.sort(key=lambda x: x['volume_24h'], reverse=True)
        
        print(f"\n✅ Total: {events_fetched} events → {len(markets_list)} unique markets")
        
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
                'created_at': market.get('createdAt', None),
                'active': market.get('active', True),
                'closed': market.get('closed', False),
                'category': 'Other',  # 会被后续覆盖
                'categories': [],     # 会被后续填充
            }
            
        except Exception as e:
            return None
    
    # ===== Trades API =====
    
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
    print("🧪 Testing PolymarketAPI...\n")
    print("=" * 60)
    
    api = PolymarketAPI()
    
    # 显示主分类
    print(f"\n📂 Main categories ({len(api.main_categories)}):")
    for i, (slug, name) in enumerate(api.main_categories, 1):
        print(f"   {i}. {slug} → {name}")
    
    # 测试 get_markets_by_categories
    print("\n" + "=" * 60)
    print("📊 Test: get_markets_by_categories")
    print("=" * 60)
    
    markets = api.get_markets_by_categories(
        min_volume_24h=100,
        total_limit=100
    )
    
    print(f"\n✅ Got {len(markets)} markets")
    
    # 显示多分类示例
    multi_cat_markets = [m for m in markets if len(m.get('categories', [])) > 1]
    if multi_cat_markets:
        print(f"\n📊 Sample multi-category markets:")
        for m in multi_cat_markets[:5]:
            print(f"   - {m['question'][:40]}...")
            print(f"     Primary: {m['category']}")
            print(f"     All: {m['categories']}")
    
    # 测试 get_all_markets_from_events
    print("\n" + "=" * 60)
    print("📊 Test: get_all_markets_from_events")
    print("=" * 60)
    
    markets2 = api.get_all_markets_from_events(
        min_volume_24h=100,
        max_events=50
    )
    
    print(f"\n✅ Got {len(markets2)} markets")
    
    print("\n" + "=" * 60)
    print("✅ All tests completed!")