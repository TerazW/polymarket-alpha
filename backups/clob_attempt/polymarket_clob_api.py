"""
Polymarket CLOB API 包装器 - 使用官方 SDK
"""

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import TradeParams
from typing import List, Dict, Optional
import time

class PolymarketCLOBClient:
    """基于官方 py-clob-client 的包装器"""
    
    def __init__(self, private_key: str, chain_id: int = 137):
        self.clob_endpoint = "https://clob.polymarket.com"
        self.chain_id = chain_id
        
        print(f"[CLOB Client] Initializing with official SDK...")
        
        # 使用官方客户端
        self.client = ClobClient(
            self.clob_endpoint,
            key=private_key,
            chain_id=chain_id
        )
        
        self.address = self.client.get_address()
        print(f"[CLOB Client] Initialized for address: {self.address}")
        
        self._api_creds_initialized = False
        
    def initialize_api_credentials(self, nonce: int = 0) -> bool:
        """初始化 API 凭证"""
        print(f"\n[CLOB Client] Initializing API credentials...")
        
        try:
            # 使用官方方法
            creds = self.client.create_or_derive_api_creds()
            
            if creds:
                self.client.set_api_creds(creds)
                self._api_creds_initialized = True
                
                # 保存属性以便外部访问
                self.api_key = creds.api_key
                self.api_secret = creds.api_secret
                self.api_passphrase = creds.api_passphrase
                
                print(f"✅ API credentials ready!")
                print(f"   API Key: {creds.api_key[:8]}...")
                
                return True
            else:
                print(f"❌ Failed to get API credentials")
                return False
                
        except Exception as e:
            print(f"❌ Error initializing API credentials: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_trades_for_market(
        self,
        condition_id: str,
        hours: int = 24,
        limit: int = 5000
    ) -> List[Dict]:
        """获取指定市场的交易"""
        if not self._api_creds_initialized:
            if not self.initialize_api_credentials():
                return []
        
        # 计算时间范围
        now = int(time.time())
        after = now - (hours * 3600)
        
        print(f"   📊 Fetching CLOB trades (last {hours}h)...")
        
        try:
            # 使用正确的 TradeParams 对象
            params = TradeParams(market=condition_id, after=after)
            
            # 调用官方 API
            trades_data = self.client.get_trades(params=params)
            
            if not trades_data:
                print(f"   ⚠️  API returned empty list")
                return []
            
            # 转换为我们需要的格式
            expanded_trades = []
            
            for trade in trades_data:
                # Taker trade
                taker_trade = {
                    'type': 'TAKER',
                    'side': trade['side'],
                    'price': float(trade['price']),
                    'size': float(trade['size']),
                    'timestamp': int(trade.get('match_time', 0)),
                    'market': trade['market'],
                    'trade_id': trade['id'],
                }
                expanded_trades.append(taker_trade)
                
                # Maker trades
                if 'maker_orders' in trade:
                    for maker_order in trade['maker_orders']:
                        maker_trade = {
                            'type': 'MAKER',
                            'side': maker_order['side'],
                            'price': float(maker_order['price']),
                            'size': float(maker_order.get('matched_amount', 0)),
                            'timestamp': int(trade.get('match_time', 0)),
                            'market': trade['market'],
                            'trade_id': trade['id'],
                        }
                        expanded_trades.append(maker_trade)
            
            print(f"   ✅ Got {len(expanded_trades)} trades (with maker/taker info)")
            
            return expanded_trades
            
        except Exception as e:
            print(f"   ❌ Error fetching trades: {e}")
            import traceback
            traceback.print_exc()
            return []