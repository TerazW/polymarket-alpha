"""
WebSocket Trades 收集器 (v3 - Price Bin 版)
后台服务：收集实时 trades 并按 price bin 存储 buy/sell

新功能：
1. 存储 price bin 级别的 aggressive buy/sell
2. 支持 POC 和 POMD 计算
3. last_flush_ts 追踪避免丢数据

运行方式：
    python jobs/ws_collector.py --markets 100

部署方式（Render）：
    作为 Background Worker 运行
"""

import os
import sys
import time
import argparse
from datetime import datetime
from typing import Dict, List, Optional

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from sqlalchemy import text
from utils.db import get_session, init_db, DATABASE_URL
from utils.polymarket_api import PolymarketAPI
from utils.polymarket_ws import PolymarketWebSocket


class WSTradeCollector:
    """
    WebSocket Trades 收集器 (v3 - Price Bin 版)
    """
    
    def __init__(
        self,
        max_markets: int = 100,
        flush_interval: int = 60,
        tick_size: float = 0.01,
        verbose: bool = True
    ):
        self.max_markets = max_markets
        self.flush_interval = flush_interval
        self.tick_size = tick_size
        self.verbose = verbose
        
        self.api = PolymarketAPI()
        self.ws: Optional[PolymarketWebSocket] = None
        
        self.markets: Dict[str, Dict] = {}
        
        self.stats = {
            'started_at': None,
            'total_flushes': 0,
            'total_asset_records': 0,
            'total_bin_records': 0,
            'last_flush': None,
            'flush_errors': 0
        }
    
    def _log(self, message: str):
        if self.verbose:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp}] {message}")
    
    def load_markets(self) -> List[str]:
        """获取活跃市场的 token IDs"""
        self._log(f"📡 Loading top {self.max_markets} markets...")
        
        markets = self.api.get_markets_by_categories(
            min_volume_24h=1000,
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
    
    def flush_to_db(self):
        """将聚合数据写入数据库"""
        if not self.ws:
            return
        
        session = get_session()
        aggregator = self.ws.get_aggregator()
        
        try:
            now = datetime.now()
            current_hour = now.replace(minute=0, second=0, microsecond=0)
            
            # 获取所有 asset 统计
            all_stats = aggregator.get_all_stats()
            
            # 获取所有 price bins
            all_bins = aggregator.get_all_price_bins()
            
            if not all_stats:
                self._log("📭 No new trades to flush")
                return
            
            asset_records = 0
            bin_records = 0
            
            for token_id, stats in all_stats.items():
                if stats['trade_count'] == 0:
                    continue
                
                try:
                    # 1. 写入 ws_trades_hourly（asset 级别汇总）
                    session.execute(text("""
                        INSERT INTO ws_trades_hourly 
                        (token_id, hour, aggressive_buy, aggressive_sell, 
                         volume_delta, total_volume, trade_count, 
                         poc, pomd, created_at)
                        VALUES 
                        (:tid, :hour, :agg_buy, :agg_sell, 
                         :delta, :total, :count,
                         :poc, :pomd, :now)
                        ON CONFLICT (token_id, hour) DO UPDATE SET
                            aggressive_buy = ws_trades_hourly.aggressive_buy + EXCLUDED.aggressive_buy,
                            aggressive_sell = ws_trades_hourly.aggressive_sell + EXCLUDED.aggressive_sell,
                            volume_delta = ws_trades_hourly.volume_delta + EXCLUDED.volume_delta,
                            total_volume = ws_trades_hourly.total_volume + EXCLUDED.total_volume,
                            trade_count = ws_trades_hourly.trade_count + EXCLUDED.trade_count,
                            poc = EXCLUDED.poc,
                            pomd = EXCLUDED.pomd
                    """), {
                        'tid': token_id,
                        'hour': current_hour,
                        'agg_buy': stats['aggressive_buy'],
                        'agg_sell': stats['aggressive_sell'],
                        'delta': stats['volume_delta'],
                        'total': stats['total_volume'],
                        'count': stats['trade_count'],
                        'poc': stats.get('poc'),
                        'pomd': stats.get('pomd'),
                        'now': now
                    })
                    asset_records += 1
                    
                    # 2. 写入 ws_price_bins（price bin 级别明细）
                    if token_id in all_bins:
                        for price_bin, bin_data in all_bins[token_id].items():
                            if bin_data['count'] == 0:
                                continue
                            
                            session.execute(text("""
                                INSERT INTO ws_price_bins
                                (token_id, hour, price_bin, aggressive_buy, aggressive_sell, trade_count)
                                VALUES
                                (:tid, :hour, :price, :buy, :sell, :count)
                                ON CONFLICT (token_id, hour, price_bin) DO UPDATE SET
                                    aggressive_buy = ws_price_bins.aggressive_buy + EXCLUDED.aggressive_buy,
                                    aggressive_sell = ws_price_bins.aggressive_sell + EXCLUDED.aggressive_sell,
                                    trade_count = ws_price_bins.trade_count + EXCLUDED.trade_count
                            """), {
                                'tid': token_id,
                                'hour': current_hour,
                                'price': price_bin,
                                'buy': bin_data['buy'],
                                'sell': bin_data['sell'],
                                'count': bin_data['count']
                            })
                            bin_records += 1
                    
                except Exception as e:
                    self._log(f"  ⚠️ Error writing {token_id[:20]}...: {e}")
                    continue
            
            session.commit()
            
            # 成功后清空聚合器
            aggregator.clear_and_update_flush_time()
            
            self.stats['total_flushes'] += 1
            self.stats['total_asset_records'] += asset_records
            self.stats['total_bin_records'] += bin_records
            self.stats['last_flush'] = now
            
            self._log(f"💾 Flushed: {asset_records} assets, {bin_records} price bins")
            
        except Exception as e:
            session.rollback()
            self.stats['flush_errors'] += 1
            self._log(f"❌ Flush error: {e}")
        finally:
            session.close()
    
    def run(self):
        """启动收集器"""
        self._log("🚀 Starting WebSocket Trade Collector v3 (Price Bin)")
        self._log(f"   Database: {DATABASE_URL[:50]}...")
        self._log(f"   Tick size: {self.tick_size}")
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
            tick_size=self.tick_size,
            verbose=False
        )
        
        # 4. 启动 WebSocket
        ws_thread = self.ws.run_async()
        
        self._log(f"📡 WebSocket connected, monitoring {len(token_ids)} markets")
        self._log(f"⏰ Flush interval: {self.flush_interval}s")
        
        # 5. 定期 flush 循环
        try:
            while True:
                time.sleep(self.flush_interval)
                self.flush_to_db()
                
                if self.ws:
                    ws_stats = self.ws.get_stats()
                    self._log(f"📊 WS: {ws_stats['trades_received']} trades | {ws_stats['total_price_bins']} bins")
                
        except KeyboardInterrupt:
            self._log("👋 Stopping...")
        finally:
            self._log("💾 Final flush...")
            self.flush_to_db()
            
            if self.ws:
                self.ws.stop()
            self._print_stats()
    
    def _ensure_tables(self):
        """确保数据库表存在"""
        session = get_session()
        try:
            is_sqlite = 'sqlite' in DATABASE_URL.lower()
            
            # 1. ws_trades_hourly 表（添加 poc, pomd 字段）
            if is_sqlite:
                session.execute(text("""
                    CREATE TABLE IF NOT EXISTS ws_trades_hourly (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        token_id VARCHAR(100),
                        hour TIMESTAMP,
                        aggressive_buy DECIMAL(20,8) DEFAULT 0,
                        aggressive_sell DECIMAL(20,8) DEFAULT 0,
                        volume_delta DECIMAL(20,8) DEFAULT 0,
                        total_volume DECIMAL(20,8) DEFAULT 0,
                        trade_count INTEGER DEFAULT 0,
                        poc DECIMAL(10,4),
                        pomd DECIMAL(10,4),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(token_id, hour)
                    )
                """))
            else:
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
                        poc DECIMAL(10,4),
                        pomd DECIMAL(10,4),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(token_id, hour)
                    )
                """))
                
                # 添加 poc, pomd 字段（如果不存在）
                try:
                    session.execute(text("ALTER TABLE ws_trades_hourly ADD COLUMN IF NOT EXISTS poc DECIMAL(10,4)"))
                    session.execute(text("ALTER TABLE ws_trades_hourly ADD COLUMN IF NOT EXISTS pomd DECIMAL(10,4)"))
                except:
                    pass
            
            # 2. ws_price_bins 表（新表）
            if is_sqlite:
                session.execute(text("""
                    CREATE TABLE IF NOT EXISTS ws_price_bins (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        token_id VARCHAR(100),
                        hour TIMESTAMP,
                        price_bin DECIMAL(10,4),
                        aggressive_buy DECIMAL(20,8) DEFAULT 0,
                        aggressive_sell DECIMAL(20,8) DEFAULT 0,
                        trade_count INTEGER DEFAULT 0,
                        UNIQUE(token_id, hour, price_bin)
                    )
                """))
            else:
                session.execute(text("""
                    CREATE TABLE IF NOT EXISTS ws_price_bins (
                        id SERIAL PRIMARY KEY,
                        token_id VARCHAR(100),
                        hour TIMESTAMP,
                        price_bin DECIMAL(10,4),
                        aggressive_buy DECIMAL(20,8) DEFAULT 0,
                        aggressive_sell DECIMAL(20,8) DEFAULT 0,
                        trade_count INTEGER DEFAULT 0,
                        UNIQUE(token_id, hour, price_bin)
                    )
                """))
            
            # 创建索引
            try:
                session.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_ws_trades_token_hour 
                    ON ws_trades_hourly(token_id, hour)
                """))
                session.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_ws_bins_token_hour 
                    ON ws_price_bins(token_id, hour)
                """))
            except:
                pass
            
            session.commit()
            self._log("✅ Database tables ready (ws_trades_hourly + ws_price_bins)")
            
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
        
        if self.stats['started_at']:
            duration = datetime.now() - self.stats['started_at']
            print(f"\n⏱️ Total runtime: {duration}")


# ============================================================================
# 辅助函数：供 sync.py 使用
# ============================================================================

def get_aggressor_stats_from_db(session, token_id: str, hours: int = 24) -> Dict:
    """从数据库获取 aggressor 统计（包含 POC/POMD）"""
    try:
        query = text("""
            SELECT 
                COALESCE(SUM(aggressive_buy), 0) as agg_buy,
                COALESCE(SUM(aggressive_sell), 0) as agg_sell,
                COALESCE(SUM(total_volume), 0) as total,
                COALESCE(SUM(trade_count), 0) as count
            FROM ws_trades_hourly
            WHERE token_id = :tid
            AND hour >= (NOW() - INTERVAL '24 hours')
        """)
        
        result = session.execute(query, {'tid': token_id}).fetchone()
        
        if result and result[3] > 0:
            agg_buy = float(result[0])
            agg_sell = float(result[1])
            total = float(result[2])
            delta = agg_buy - agg_sell
            directional_ar = abs(delta) / total if total > 0 else None
            
            return {
                'aggressive_buy': agg_buy,
                'aggressive_sell': agg_sell,
                'total_volume': total,
                'volume_delta': delta,
                'directional_ar': directional_ar,
                'trade_count': int(result[3]),
                'has_data': True
            }
        
    except Exception as e:
        pass
    
    return {
        'aggressive_buy': 0,
        'aggressive_sell': 0,
        'total_volume': 0,
        'volume_delta': 0,
        'directional_ar': None,
        'trade_count': 0,
        'has_data': False
    }


def get_price_bins_from_db(session, token_id: str, hours: int = 24) -> Dict[float, Dict]:
    """
    从数据库获取 price bin 级别的 buy/sell 数据
    
    Returns:
        {price_bin: {'buy': x, 'sell': y, 'total': z, 'min_side': w}}
    """
    try:
        query = text("""
            SELECT 
                price_bin,
                SUM(aggressive_buy) as buy,
                SUM(aggressive_sell) as sell,
                SUM(trade_count) as count
            FROM ws_price_bins
            WHERE token_id = :tid
            AND hour >= (NOW() - INTERVAL '24 hours')
            GROUP BY price_bin
        """)
        
        results = session.execute(query, {'tid': token_id}).fetchall()
        
        bins = {}
        for row in results:
            price = float(row[0])
            buy = float(row[1])
            sell = float(row[2])
            bins[price] = {
                'buy': buy,
                'sell': sell,
                'total': buy + sell,
                'delta': buy - sell,
                'min_side': min(buy, sell),
                'count': int(row[3])
            }
        
        return bins
        
    except Exception as e:
        return {}


def calculate_poc_from_db(session, token_id: str, hours: int = 24) -> Optional[float]:
    """从数据库计算 POC（成交量最大的 price bin）"""
    bins = get_price_bins_from_db(session, token_id, hours)
    if not bins:
        return None
    return max(bins.keys(), key=lambda p: bins[p]['total'])


def calculate_pomd_from_db(session, token_id: str, hours: int = 24, min_threshold: float = 0) -> Optional[float]:
    """
    从数据库计算 POMD（min(buy, sell) 最大的 price bin）
    
    Args:
        min_threshold: 最小阈值，低于此值不算
    """
    bins = get_price_bins_from_db(session, token_id, hours)
    if not bins:
        return None
    
    valid_bins = {p: d for p, d in bins.items() if d['min_side'] >= min_threshold}
    if not valid_bins:
        return None
    
    return max(valid_bins.keys(), key=lambda p: valid_bins[p]['min_side'])


# ============================================================================
# 命令行入口
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='WebSocket Trade Collector v3')
    parser.add_argument('--markets', type=int, default=100,
                       help='Number of markets to monitor (default: 100)')
    parser.add_argument('--interval', type=int, default=60,
                       help='Flush interval in seconds (default: 60)')
    parser.add_argument('--tick-size', type=float, default=0.01,
                       help='Price bin tick size (default: 0.01)')
    parser.add_argument('--quiet', action='store_true',
                       help='Reduce logging')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🌐 Polymarket WebSocket Trade Collector v3 (Price Bin)")
    print("=" * 60)
    print(f"Markets: {args.markets}")
    print(f"Flush interval: {args.interval}s")
    print(f"Tick size: {args.tick_size}")
    print("=" * 60)
    
    init_db()
    
    collector = WSTradeCollector(
        max_markets=args.markets,
        flush_interval=args.interval,
        tick_size=args.tick_size,
        verbose=not args.quiet
    )
    
    collector.run()