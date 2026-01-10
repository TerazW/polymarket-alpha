"""
Polymarket API module.
Supports:
- 12 official primary categories
- Multi-category support (a market can belong to multiple categories)
- Fetch markets by category
- Fetch all active markets
- Fetch trade data
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
        
        # Polymarket official 12 primary categories (ordered by priority).
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
        Fetch markets by official categories (supports multi-category).

        Strategy:
        1. Iterate each primary category (using tag_slug)
        2. Fetch all markets in that category
        3. Merge and deduplicate (a market can appear in multiple categories)
        4. Record all categories into the categories list
        5. Assign a primary category by priority

        Args:
            min_volume_24h: minimum 24h volume
            max_markets_per_category: per-category market limit
            total_limit: overall market limit

        Returns:
            List[Dict]: market list with:
                - category: primary category
                - categories: all categories
        """
        all_markets = {}  # {condition_id: market_data}
        market_categories = defaultdict(list)  # {condition_id: [categories]}
        
        print("\nFetching markets by official categories...")
        print(f"   Min volume: ${min_volume_24h}")
        print(f"   Categories: {len(self.main_categories)}\n")
        
        for tag_slug, category_name in self.main_categories:
            try:
                print(f"{category_name}...")
                
                markets = self._get_markets_by_tag_slug(
                    tag_slug,
                    min_volume_24h=min_volume_24h,
                    limit=max_markets_per_category
                )
                
                print(f"   Found {len(markets)} markets")
                
                for market in markets:
                    condition_id = market['condition_id']
                    
                    # Record all categories for this market.
                    if category_name not in market_categories[condition_id]:
                        market_categories[condition_id].append(category_name)
                    
                    # Save market data if not already present.
                    if condition_id not in all_markets:
                        all_markets[condition_id] = market
                
                time.sleep(0.3)  # Avoid rate limiting.
                
            except Exception as e:
                print(f"   Error: {e}")
                continue
        
        # Assign categories.
        print("\nAssigning categories...")
        for condition_id, categories in market_categories.items():
            # Save all categories.
            all_markets[condition_id]['categories'] = categories
            
            # Assign primary category by priority.
            for tag_slug, category_name in self.main_categories:
                if category_name in categories:
                    all_markets[condition_id]['category'] = category_name
                    break
        
        markets_list = list(all_markets.values())
        
        # Sort by volume.
        markets_list.sort(key=lambda x: x['volume_24h'], reverse=True)
        
        # Apply total limit.
        if total_limit:
            markets_list = markets_list[:total_limit]
        
        print(f"\nTotal unique markets: {len(markets_list)}")
        
        # Category distribution (primary).
        cat_count = defaultdict(int)
        for m in markets_list:
            cat_count[m['category']] += 1
        
        print(f"\nCategory distribution (primary):")
        for cat, count in sorted(cat_count.items(), key=lambda x: x[1], reverse=True):
            print(f"  {cat}: {count}")
        
        # Multi-category stats.
        multi_cat_count = sum(1 for m in markets_list if len(m.get('categories', [])) > 1)
        if multi_cat_count > 0:
            print(f"\nMarkets with multiple categories: {multi_cat_count}")
        
        return markets_list
    
    def get_all_markets_from_events(
        self,
        min_volume_24h: float = 100,
        max_events: int = None
    ) -> List[Dict]:
        """
        Fetch all active markets from the Events API (no categories).

        Used by sync_incremental.py.

        Args:
            min_volume_24h: minimum 24h volume
            max_events: max number of events (None = all)

        Returns:
            List[Dict]: market list
        """
        markets = []
        offset = 0
        page_size = 100
        events_fetched = 0
        
        print("\nFetching all markets from Events API...")
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

                # Extract markets from events.
                for event in events:
                    if 'markets' in event and event['markets']:
                        # Get event info for all markets in this event.
                        evt_id = event.get('id')
                        evt_title = event.get('title')

                        for market_raw in event['markets']:
                            # Check volume.
                            volume = float(market_raw.get('volume24hr', 0))
                            if volume < min_volume_24h:
                                continue

                            # Extract market data with event info.
                            market = self._extract_market_from_event(market_raw, event_id=evt_id, event_title=evt_title)
                            if market:
                                markets.append(market)

                # Stop if event limit reached.
                if max_events and events_fetched >= max_events:
                    break
                
                # Stop on last page.
                if len(events) < page_size:
                    break
                
                offset += page_size
                
                # Progress output.
                if offset % 500 == 0:
                    print(f"   Processed {events_fetched} events, found {len(markets)} markets...")
                
                time.sleep(0.2)  # Rate limit
                
            except Exception as e:
                print(f"   Error at offset {offset}: {e}")
                break
        
        # Deduplicate by condition_id.
        unique_markets = {}
        for m in markets:
            cid = m['condition_id']
            if cid not in unique_markets:
                unique_markets[cid] = m
            elif m['volume_24h'] > unique_markets[cid]['volume_24h']:
                unique_markets[cid] = m
        
        markets_list = list(unique_markets.values())
        markets_list.sort(key=lambda x: x['volume_24h'], reverse=True)
        
        print(f"\nTotal: {events_fetched} events -> {len(markets_list)} unique markets")
        
        return markets_list
    
    def _get_markets_by_tag_slug(
        self,
        tag_slug: str,
        min_volume_24h: float = 0,
        limit: int = None
    ) -> List[Dict]:
        """
        Fetch markets by tag_slug.

        Args:
            tag_slug: category slug (e.g., 'politics', 'crypto')
            min_volume_24h: minimum 24h volume
            limit: maximum number of markets

        Returns:
            List[Dict]: market list
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

                # Extract markets from events.
                for event in events:
                    if 'markets' in event and event['markets']:
                        # Get event info for all markets in this event.
                        evt_id = event.get('id')
                        evt_title = event.get('title')

                        for market_raw in event['markets']:
                            # Check volume.
                            volume = float(market_raw.get('volume24hr', 0))
                            if volume < min_volume_24h:
                                continue

                            # Extract market data with event info.
                            market = self._extract_market_from_event(market_raw, event_id=evt_id, event_title=evt_title)
                            if market:
                                markets.append(market)

                # Stop if limit reached.
                if limit and len(markets) >= limit:
                    markets = markets[:limit]
                    break
                
                # Stop on last page.
                if len(events) < page_size:
                    break
                
                offset += page_size
                
            except Exception as e:
                print(f"      Error at offset {offset}: {e}")
                break
        
        return markets
    
    def _extract_market_from_event(self, market: Dict, event_id: str = None, event_title: str = None) -> Optional[Dict]:
        """Extract standard fields from an event market."""
        try:
            condition_id = market.get('conditionId', '')
            if not condition_id:
                return None

            # token_id - extract both YES and NO tokens
            clob_token_ids_raw = market.get('clobTokenIds', '')
            token_id = None
            yes_token_id = None
            no_token_id = None

            if isinstance(clob_token_ids_raw, str) and clob_token_ids_raw:
                try:
                    clob_token_ids = json.loads(clob_token_ids_raw)
                    if isinstance(clob_token_ids, list):
                        if len(clob_token_ids) >= 1:
                            yes_token_id = clob_token_ids[0]
                            token_id = yes_token_id
                        if len(clob_token_ids) >= 2:
                            no_token_id = clob_token_ids[1]
                except json.JSONDecodeError:
                    pass
            elif isinstance(clob_token_ids_raw, list):
                if len(clob_token_ids_raw) >= 1:
                    yes_token_id = clob_token_ids_raw[0]
                    token_id = yes_token_id
                if len(clob_token_ids_raw) >= 2:
                    no_token_id = clob_token_ids_raw[1]

            if not token_id:
                token_id = condition_id
            if not yes_token_id:
                yes_token_id = condition_id
            if not no_token_id:
                no_token_id = condition_id
            
            # Price.
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
                'yes_token_id': yes_token_id,
                'no_token_id': no_token_id,
                'question': market.get('question', 'Unknown'),
                'slug': market.get('slug', ''),
                'description': market.get('description', ''),
                'price': price,
                'volume_24h': volume_24h,
                'liquidity': liquidity,
                'end_date': market.get('endDateIso', None),
                'created_at': market.get('createdAt', None),
                'active': market.get('active', True),
                'closed': market.get('closed', False),
                'category': 'Other',  # Overridden later.
                'categories': [],     # Filled later.
                'event_id': event_id,
                'event_title': event_title,
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
        """Fetch public trades (Data API)."""
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
            print(f"Error fetching trades: {e}")
            return []
    
    def get_trades_for_market(
        self, 
        condition_id: str, 
        limit: int = 5000
    ) -> List[Dict]:
        """Fetch trades for a specific market."""
        return self.get_trades(limit=limit, market=condition_id)
    
    def get_orderbook(self, token_id: str) -> Optional[Dict]:
        """Fetch order book (CLOB API)."""
        try:
            response = requests.get(
                f"{self.clob_api}/book",
                params={"token_id": token_id},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching book for {token_id}: {e}")
            return None


# Tests
if __name__ == "__main__":
    print("Testing PolymarketAPI...\n")
    print("=" * 60)
    
    api = PolymarketAPI()
    
    # Show primary categories.
    print(f"\nMain categories ({len(api.main_categories)}):")
    for i, (slug, name) in enumerate(api.main_categories, 1):
        print(f"   {i}. {slug} -> {name}")
    
    # Test get_markets_by_categories.
    print("\n" + "=" * 60)
    print("Test: get_markets_by_categories")
    print("=" * 60)
    
    markets = api.get_markets_by_categories(
        min_volume_24h=100,
        total_limit=100
    )
    
    print(f"\nGot {len(markets)} markets")
    
    # Sample multi-category markets.
    multi_cat_markets = [m for m in markets if len(m.get('categories', [])) > 1]
    if multi_cat_markets:
        print("\nSample multi-category markets:")
        for m in multi_cat_markets[:5]:
            print(f"   - {m['question'][:40]}...")
            print(f"     Primary: {m['category']}")
            print(f"     All: {m['categories']}")
    
    # Test get_all_markets_from_events.
    print("\n" + "=" * 60)
    print("Test: get_all_markets_from_events")
    print("=" * 60)
    
    markets2 = api.get_all_markets_from_events(
        min_volume_24h=100,
        max_events=50
    )
    
    print(f"\nGot {len(markets2)} markets")
    
    print("\n" + "=" * 60)
    print("All tests completed!")
