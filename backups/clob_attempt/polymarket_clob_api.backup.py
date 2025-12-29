"""
Polymarket CLOB API 客户端（支持认证）
用于获取包含 maker/taker 信息的详细交易数据
"""

import requests
import time
import hmac
import hashlib
from typing import List, Dict, Optional
from datetime import datetime
from eth_account import Account
from eth_account.messages import encode_typed_data

class PolymarketCLOBClient:
    """
    Polymarket CLOB API 客户端
    
    功能：
    1. L1 认证（使用私钥）
    2. L2 认证（使用 API key）
    3. 获取包含 aggressor 信息的交易数据
    """
    
    def __init__(self, private_key: str, chain_id: int = 137):
        """
        初始化 CLOB 客户端
        
        Args:
            private_key: Polygon 钱包私钥（0x开头）
            chain_id: 链 ID（137 = Polygon Mainnet）
        """
        self.clob_endpoint = "https://clob.polymarket.com"
        self.chain_id = chain_id
        
        # 创建账户
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
        
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        
        print(f"[CLOB Client] Initialized for address: {self.address}")
        
        # API 凭证（延迟初始化）
        self.api_key = None
        self.api_secret = None
        self.api_passphrase = None
        self._api_creds_initialized = False
        
    def _create_l1_headers(self, timestamp: Optional[int] = None, nonce: int = 0) -> Dict[str, str]:
        """
        创建 L1 认证 headers（使用私钥签名）
        
        Args:
            timestamp: UNIX 时间戳（秒）
            nonce: Nonce（默认 0）
        
        Returns:
            包含 L1 认证信息的 headers
        """
        if timestamp is None:
            timestamp = int(time.time())
        
        # EIP-712 domain
        domain_data = {
            "name": "ClobAuthDomain",
            "version": "1",
            "chainId": self.chain_id,
        }
        
        # 消息类型定义（不包含 EIP712Domain）
        message_types = {
            "ClobAuth": [
                {"name": "address", "type": "address"},
                {"name": "timestamp", "type": "string"},
                {"name": "nonce", "type": "uint256"},
                {"name": "message", "type": "string"},
            ]
        }
        
        # 消息内容
        message_data = {
            "address": self.address,
            "timestamp": str(timestamp),
            "nonce": nonce,
            "message": "This message attests that I control the given wallet",
        }
        
        # 使用新版 API：encode_typed_data（不需要 primary_type）
        signable_message = encode_typed_data(
            domain_data=domain_data,
            message_types=message_types,
            message_data=message_data
        )
        
        # 签名
        signed_message = self.account.sign_message(signable_message)
        signature = signed_message.signature.hex()
        
        return {
            "POLY_ADDRESS": self.address,
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": str(timestamp),
            "POLY_NONCE": str(nonce),
        }
            
    def initialize_api_credentials(self, nonce: int = 0) -> bool:
        """
        初始化 API 凭证（首次使用时调用）
        
        Args:
            nonce: Nonce（默认 0，如果已存在凭证可以尝试其他值）
        
        Returns:
            是否成功初始化
        """
        print(f"\n[CLOB Client] Initializing API credentials...")
        
        try:
            # 创建 L1 headers
            headers = self._create_l1_headers(nonce=nonce)
            
            # 请求 API key
            response = requests.post(
                f"{self.clob_endpoint}/auth/api-key",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                creds = response.json()
                self.api_key = creds['apiKey']
                self.api_secret = creds['secret']
                self.api_passphrase = creds['passphrase']
                self._api_creds_initialized = True
                
                print(f"✅ API credentials created successfully!")
                print(f"   API Key: {self.api_key[:8]}...")
                
                return True
            
            elif response.status_code == 400:
                # API key 可能已存在，尝试 derive
                print("   API key may already exist, trying to derive...")
                return self._derive_api_credentials(nonce)
            
            else:
                print(f"❌ Failed to create API key: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
        
        except Exception as e:
            print(f"❌ Error initializing API credentials: {e}")
            return False
    
    def _derive_api_credentials(self, nonce: int = 0) -> bool:
        """
        从现有 nonce 派生 API 凭证
        
        Args:
            nonce: Nonce
        
        Returns:
            是否成功派生
        """
        try:
            headers = self._create_l1_headers(nonce=nonce)
            
            response = requests.get(
                f"{self.clob_endpoint}/auth/derive-api-key",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                creds = response.json()
                self.api_key = creds['apiKey']
                self.api_secret = creds['secret']
                self.api_passphrase = creds['passphrase']
                self._api_creds_initialized = True
                
                print(f"✅ API credentials derived successfully!")
                print(f"   API Key: {self.api_key[:8]}...")
                
                return True
            
            else:
                print(f"❌ Failed to derive API key: {response.status_code}")
                return False
        
        except Exception as e:
            print(f"❌ Error deriving API credentials: {e}")
            return False

    def _create_l2_headers(self, method: str, request_path: str) -> Dict[str, str]:
        """
        创建 L2 认证 headers（使用 API key）
        
        Args:
            method: HTTP 方法（GET, POST 等）
            request_path: 请求路径（包含查询参数）
        
        Returns:
            包含 L2 认证信息的 headers
        """
        timestamp = str(int(time.time()))
        
        # 构造签名消息
        message = timestamp + method + request_path
        
        # HMAC-SHA256 签名
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).digest().hex()
        
        return {
            "POLY_ADDRESS": self.address,
            "POLY_API_KEY": self.api_key,
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": timestamp,
            "POLY_PASSPHRASE": self.api_passphrase,
        }
    
    def get_trades(
        self, 
        market: str,
        limit: int = 1000,
        before: Optional[int] = None,
        after: Optional[int] = None
    ) -> List[Dict]:
        """
        获取市场的交易数据（包含 maker/taker 信息）
        
        Args:
            market: 市场 ID (condition_id)
            limit: 返回数量限制
            before: 时间戳之前的交易
            after: 时间戳之后的交易
        
        Returns:
            交易列表，每个交易包含 type 字段（TAKER/MAKER）
        """
        if not self._api_creds_initialized:
            print("⚠️  API credentials not initialized, initializing now...")
            if not self.initialize_api_credentials():
                print("❌ Failed to initialize API credentials")
                return []
        
        # 构建请求路径
        request_path = f"/data/trades?market={market}"
        
        # 添加可选参数
        params = []
        if before:
            params.append(f"before={before}")
        if after:
            params.append(f"after={after}")
        
        if params:
            request_path += "&" + "&".join(params)
        
        try:
            # 创建 L2 headers
            headers = self._create_l2_headers("GET", request_path)
            
            # 发送请求
            response = requests.get(
                f"{self.clob_endpoint}{request_path}",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                trades = response.json()
                
                # 展开 trades（每个 trade 可能有多个 maker_orders）
                expanded_trades = []
                
                for trade in trades:
                    # Taker trade
                    taker_trade = {
                        'type': 'TAKER',
                        'side': trade['side'],
                        'price': float(trade['price']),
                        'size': float(trade['size']),
                        'timestamp': int(trade['match_time']) if 'match_time' in trade else 0,
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
                                'size': float(maker_order['matched_amount']),
                                'timestamp': int(trade['match_time']) if 'match_time' in trade else 0,
                                'market': trade['market'],
                                'trade_id': trade['id'],
                            }
                            expanded_trades.append(maker_trade)
                
                return expanded_trades
            
            else:
                print(f"❌ Failed to get trades: {response.status_code}")
                print(f"   Response: {response.text[:200]}")
                return []
        
        except Exception as e:
            print(f"❌ Error getting trades: {e}")
            return []
    
    def get_trades_for_market(
        self,
        condition_id: str,
        hours: int = 24,
        limit: int = 5000
    ) -> List[Dict]:
        """
        获取指定市场在指定时间窗口内的所有交易
        
        Args:
            condition_id: 市场 condition ID
            hours: 时间窗口（小时）
            limit: 最大交易数量
        
        Returns:
            交易列表
        """
        # 计算时间范围
        now = int(time.time())
        after = now - (hours * 3600)
        
        print(f"   📊 Fetching CLOB trades (last {hours}h)...")
        
        trades = self.get_trades(
            market=condition_id,
            limit=limit,
            after=after
        )
        
        print(f"   ✅ Got {len(trades)} trades (with maker/taker info)")
        
        return trades


# 测试代码
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    private_key = os.getenv("PRIVATE_KEY")
    
    if not private_key:
        print("❌ PRIVATE_KEY not found in .env file")
        print("\n📝 To get started:")
        print("1. Create a new Polygon wallet (no funds needed)")
        print("2. Add PRIVATE_KEY=0x... to your .env file")
        print("3. Run this script again")
    else:
        print("🧪 Testing CLOB API Client...\n")
        
        # 初始化客户端
        client = PolymarketCLOBClient(private_key)
        
        # 初始化 API 凭证
        if client.initialize_api_credentials():
            # 测试获取交易数据
            print("\n🧪 Testing trade data fetch...")
            
            # 使用一个高交易量的市场测试
            test_market = "0x5543372edec0f4bd2a6d191a495b25dc69ed24f9c9d7018f"  # Bears vs 49ers
            
            trades = client.get_trades_for_market(test_market, hours=1, limit=100)
            
            if trades:
                print(f"\n✅ Successfully fetched {len(trades)} trades!")
                print("\n📊 Sample trades:")
                
                for i, trade in enumerate(trades[:5], 1):
                    print(f"\n{i}. {trade['type']:<6} | {trade['side']:<4} | "
                          f"Price: {trade['price']:.3f} | Size: ${trade['size']:.2f}")
                
                # 统计
                taker_count = sum(1 for t in trades if t['type'] == 'TAKER')
                maker_count = sum(1 for t in trades if t['type'] == 'MAKER')
                
                print(f"\n📈 Statistics:")
                print(f"   TAKER trades: {taker_count}")
                print(f"   MAKER trades: {maker_count}")
                print(f"   Total: {len(trades)}")
            
            print("\n✅ CLOB API Client test completed!")
        else:
            print("\n❌ Failed to initialize API credentials")
