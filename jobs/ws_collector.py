"""
WebSocket Trades 收集器
后台服务：收集实时 trades 数据（带 aggressor）并写入数据库

用途：
1. 实时收集 Polymarket WebSocket trades
2. 聚合计算 AR / Volume Delta / CS
3. 定期写入数据库
4. 供 sync.py 使用

运行方式：
    python jobs/ws_collector.py --markets 100

部署方式（Render）：
    作为 Background Worker 运行
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional

# 添加项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from sqlalchemy import text
from utils.db import get_session, init_db
from utils.polymarket_api import PolymarketAPI
from utils.polymarket_ws import PolymarketWebSocket, TradeAggregator


class WSTradeCollector:
    """
    WebSocket Trades 收集器
    
    功能：
    1. 获取活跃市场列表
    2. 订阅 WebSocket
    3. 收集 trades（带 aggressor side）
    4. 定期聚合并写入数据库
    """
    
    def __init__(
        self,
        max_markets: int = 100,
        flush_interval: int = 60,  # 每 60 秒写入一次
        verbose: bool = True
    ):
        self.max_markets = max_markets
        self.flush_interval = flush_interval
        self.verbose = verbose
        
        self.api = PolymarketAPI()
        self.aggregator = TradeAggregator()
        self.ws: Optional[PolymarketWebSocket] = None
        
        # {token_id: market_info}
        self.markets: Dict[str, Dict] = {}
        
        # 统计
        self.stats = {
            'started_at': None,
            'total_trades': 0,
            'total_flushes': 0,
            'last_flush': None
        }
    
    def _log(self, message: str):
        if self.verbose:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp}] {message}")
    
    def load_markets(self) -> List[str]:
        """
        获取活跃市场的 token IDs
        
        Returns:
            token_ids 列表
        """
        self._log(f"📡 Loading top {self.max_markets} markets...")
        
        markets = self.api.get_markets_by_categories(
            min_volume_24h=1000,  # 只订阅高活跃度市场
            total_limit=self.max_markets
        )
        
        token_ids = []
        for m in markets:
            token_id = m.get('token_id')
            if token_id:
                token_ids.append(token_id)
                self.markets[token_id] = m
        
        self._log(f"✅ Loaded {len(token_ids)} markets")
        return token_ids
    
    def on_trade(self, trade: Dict):
        """收到 trade 时的回调"""
        self.aggregator.add_trade(trade)
        self.stats['total_trades'] += 1
        
        if self.verbose and self.stats['total_trades'] % 500 == 0:
            self._log(f"📊 Total trades: {self.stats['total_trades']}")
    
    def flush_to_db(self):
        """
        将聚合数据写入数据库
        """
        session = get_session()
        
        try:
            now = datetime.now()
            today = now.date()
            
            # 获取过去 1 小时的数据
            since_ms = int((now - timedelta(hours=1)).timestamp() * 1000)
            
            records_written = 0
            
            for token_id, market in self.markets.items():
                # 获取聚合统计
                stats = self.aggregator.get_aggressor_stats(
                    asset_id=token_id,
                    since_ms=since_ms
                )
                
                if stats['trade_count'] == 0:
                    continue
                
                # 写入 ws_trades_hourly 表
                session.execute(text("""
                    INSERT INTO ws_trades_hourly 
                    (token_id, hour, aggressive_buy, aggressive_sell, 
                     volume_delta, total_volume, trade_count, created_at)
                    VALUES 
                    (:tid, :hour, :agg_buy, :agg_sell, 
                     :delta, :total, :count, :now)
                    ON CONFLICT (token_id, hour) DO UPDATE SET
                        aggressive_buy = ws_trades_hourly.aggressive_buy + EXCLUDED.aggressive_buy,
                        aggressive_sell = ws_trades_hourly.aggressive_sell + EXCLUDED.aggressive_sell,
                        volume_delta = ws_trades_hourly.volume_delta + EXCLUDED.volume_delta,
                        total_volume = ws_trades_hourly.total_volume + EXCLUDED.total_volume,
                        trade_count = ws_trades_hourly.trade_count + EXCLUDED.trade_count
                """), {
                    'tid': token_id,
                    'hour': now.replace(minute=0, second=0, microsecond=0),
                    'agg_buy': stats['aggressive_buy_volume'],
                    'agg_sell': stats['aggressive_sell_volume'],
                    'delta': stats['volume_delta'],
                    'total': stats['total_volume'],
                    'count': stats['trade_count'],
                    'now': now
                })
                
                records_written += 1
            
            session.commit()
            
            # 清空聚合器
            self.aggregator.clear()
            
            self.stats['total_flushes'] += 1
            self.stats['last_flush'] = now
            
            self._log(f"💾 Flushed {records_written} records to database")
            
        except Exception as e:
            session.rollback()
            self._log(f"❌ Flush error: {e}")
        finally:
            session.close()
    
    def run(self):
        """
        启动收集器（阻塞）
        """
        self._log("🚀 Starting WebSocket Trade Collector")
        self.stats['started_at'] = datetime.now()
        
        # 1. 加载市场
        token_ids = self.load_markets()
        
        if not token_ids:
            self._log("❌ No markets to subscribe")
            return
        
        # 2. 确保数据库表存在
        self._ensure_tables()
        
        # 3. 创建 WebSocket
        self.ws = PolymarketWebSocket(
            asset_ids=token_ids,
            on_trade=self.on_trade,
            verbose=False  # WS 本身不打印日志
        )
        
        # 4. 启动 WebSocket（后台）
        ws_thread = self.ws.run_async()
        
        self._log(f"📡 WebSocket connected, monitoring {len(token_ids)} markets")
        self._log(f"⏰ Flush interval: {self.flush_interval} seconds")
        
        # 5. 定期 flush 循环
        try:
            while True:
                time.sleep(self.flush_interval)
                self.flush_to_db()
                
        except KeyboardInterrupt:
            self._log("👋 Stopping...")
        finally:
            if self.ws:
                self.ws.stop()
            self._print_stats()
    
    def _ensure_tables(self):
        """确保数据库表存在"""
        session = get_session()
        try:
            # ws_trades_hourly 表 - 按小时聚合的 aggressor 数据
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS ws_trades_hourly (
                    id SERIAL PRIMARY KEY,
                    token_id VARCHAR(100),
                    hour TIMESTAMP,
                    aggressive_buy DECIMAL(20,8) DEFAULT 0,
                    aggressive_sell DECIMAL(20,8) DEFAULT 0,
                    volume_delta DECIMAL(20,8) DEFAULT 0,
                    total_volume DECIMAL(20,8) DEFAULT 0,
                    trade_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(token_id, hour)
                )
            """))
            
            # 创建索引
            session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_ws_trades_token_hour 
                ON ws_trades_hourly(token_id, hour)
            """))
            
            session.commit()
            self._log("✅ Database tables ready")
            
        except Exception as e:
            self._log(f"⚠️ Table creation warning: {e}")
            session.rollback()
        finally:
            session.close()
    
    def _print_stats(self):
        """打印统计信息"""
        print("\n" + "=" * 60)
        print("📊 Collector Statistics")
        print("=" * 60)
        for k, v in self.stats.items():
            print(f"  {k}: {v}")
        
        if self.ws:
            ws_stats = self.ws.get_stats()
            print("\n📡 WebSocket Statistics:")
            for k, v in ws_stats.items():
                print(f"  {k}: {v}")


def get_aggressor_stats_from_db(
    session,
    token_id: str,
    hours: int = 24
) -> Dict:
    """
    从数据库获取 aggressor 统计
    
    Args:
        session: 数据库会话
        token_id: token ID
        hours: 过去多少小时
    
    Returns:
        聚合统计
    """
    try:
        query = text("""
            SELECT 
                SUM(aggressive_buy) as agg_buy,
                SUM(aggressive_sell) as agg_sell,
                SUM(volume_delta) as delta,
                SUM(total_volume) as total,
                SUM(trade_count) as count
            FROM ws_trades_hourly
            WHERE token_id = :tid
            AND hour >= NOW() - INTERVAL ':hours hours'
        """.replace(':hours', str(hours)))
        
        result = session.execute(query, {'tid': token_id}).fetchone()
        
        if result and result[4] and result[4] > 0:
            return {
                'aggressive_buy_volume': float(result[0] or 0),
                'aggressive_sell_volume': float(result[1] or 0),
                'volume_delta': float(result[2] or 0),
                'total_volume': float(result[3] or 0),
                'trade_count': int(result[4] or 0),
                'has_data': True
            }
        
    except Exception as e:
        print(f"⚠️ Error getting aggressor stats: {e}")
    
    return {
        'aggressive_buy_volume': 0,
        'aggressive_sell_volume': 0,
        'volume_delta': 0,
        'total_volume': 0,
        'trade_count': 0,
        'has_data': False
    }


def calculate_cs_from_aggressor(
    aggressive_buy: float,
    aggressive_sell: float,
    total_volume: float
) -> Optional[float]:
    """
    从 aggressor 数据计算 CS
    
    CS = (AR × |delta|) / total_volume
    
    在预测市场：
    - AR ≈ 1（所有 trades 都是 taker 触发）
    - delta = aggressive_buy - aggressive_sell
    
    简化公式：
    CS = |delta| / total_volume
    
    意义：
    - CS 高 → 单边压倒性主动成交，强信念
    - CS 低 → 买卖双方主动成交均衡，弱信念
    """
    if total_volume <= 0:
        return None
    
    delta = abs(aggressive_buy - aggressive_sell)
    cs = delta / total_volume
    
    # CS 范围 [0, 1]
    return min(cs, 1.0)


# ============================================================================
# 命令行入口
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='WebSocket Trade Collector')
    parser.add_argument('--markets', type=int, default=100,
                       help='Number of markets to monitor (default: 100)')
    parser.add_argument('--interval', type=int, default=60,
                       help='Flush interval in seconds (default: 60)')
    parser.add_argument('--quiet', action='store_true',
                       help='Reduce logging')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🌐 Polymarket WebSocket Trade Collector")
    print("=" * 60)
    print(f"Markets: {args.markets}")
    print(f"Flush interval: {args.interval}s")
    print("=" * 60)
    
    # 初始化数据库
    init_db()
    
    # 启动收集器
    collector = WSTradeCollector(
        max_markets=args.markets,
        flush_interval=args.interval,
        verbose=not args.quiet
    )
    
    collector.run()