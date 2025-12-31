"""
WebSocket Trades 收集器 (v2 - 优化版)
后台服务：收集实时 trades 数据（带 aggressor）并写入数据库

优化点：
1. 使用 last_flush_ts 而非 now-1h（避免丢数据）
2. 使用增量计数器（内存效率）
3. 按小时桶聚合写入

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
from utils.db import get_session, init_db, DATABASE_URL
from utils.polymarket_api import PolymarketAPI
from utils.polymarket_ws import PolymarketWebSocket


class WSTradeCollector:
    """
    WebSocket Trades 收集器 (v2 - 优化版)
    
    功能：
    1. 获取活跃市场列表
    2. 订阅 WebSocket
    3. 收集 trades（带 aggressor side）
    4. 使用 last_flush_ts 追踪，避免丢数据
    5. 定期聚合并写入数据库
    """
    
    def __init__(
        self,
        max_markets: int = 100,
        flush_interval: int = 60,
        verbose: bool = True
    ):
        self.max_markets = max_markets
        self.flush_interval = flush_interval
        self.verbose = verbose
        
        self.api = PolymarketAPI()
        self.ws: Optional[PolymarketWebSocket] = None
        
        # {token_id: market_info}
        self.markets: Dict[str, Dict] = {}
        
        # 统计
        self.stats = {
            'started_at': None,
            'total_flushes': 0,
            'total_records_written': 0,
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
        """
        将聚合数据写入数据库
        
        优化：
        - 使用 aggregator 的 last_flush_ts 追踪
        - flush 完成后才清空并更新时间戳
        - 避免数据丢失
        """
        if not self.ws:
            return
        
        session = get_session()
        aggregator = self.ws.get_aggregator()
        
        try:
            now = datetime.now()
            
            # 获取自上次 flush 以来的所有统计
            all_stats = aggregator.get_stats_since_last_flush()
            
            if not all_stats:
                self._log("📭 No new trades to flush")
                return
            
            records_written = 0
            current_hour = now.replace(minute=0, second=0, microsecond=0)
            
            for token_id, stats in all_stats.items():
                if stats['trade_count'] == 0:
                    continue
                
                try:
                    # 写入 ws_trades_hourly 表
                    # 使用 UPSERT：同一小时内累加
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
                        'hour': current_hour,
                        'agg_buy': stats['aggressive_buy'],
                        'agg_sell': stats['aggressive_sell'],
                        'delta': stats['volume_delta'],
                        'total': stats['total_volume'],
                        'count': stats['trade_count'],
                        'now': now
                    })
                    
                    records_written += 1
                    
                except Exception as e:
                    self._log(f"  ⚠️ Error writing {token_id[:20]}...: {e}")
                    continue
            
            session.commit()
            
            # 成功后才清空聚合器并更新 flush 时间
            aggregator.clear_and_update_flush_time()
            
            self.stats['total_flushes'] += 1
            self.stats['total_records_written'] += records_written
            self.stats['last_flush'] = now
            
            self._log(f"💾 Flushed {records_written} records | Total: {self.stats['total_records_written']}")
            
        except Exception as e:
            session.rollback()
            self.stats['flush_errors'] += 1
            self._log(f"❌ Flush error: {e}")
        finally:
            session.close()
    
    def run(self):
        """启动收集器（阻塞）"""
        self._log("🚀 Starting WebSocket Trade Collector v2")
        self._log(f"   Database: {DATABASE_URL[:50]}...")
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
            verbose=False
        )
        
        # 4. 启动 WebSocket（后台）
        ws_thread = self.ws.run_async()
        
        self._log(f"📡 WebSocket connected, monitoring {len(token_ids)} markets")
        self._log(f"⏰ Flush interval: {self.flush_interval} seconds")
        self._log(f"🔄 Using last_flush_ts tracking (no data loss)")
        
        # 5. 定期 flush 循环
        try:
            while True:
                time.sleep(self.flush_interval)
                self.flush_to_db()
                
                # 打印状态
                if self.ws:
                    ws_stats = self.ws.get_stats()
                    self._log(f"📊 WS: {ws_stats['trades_received']} trades | {ws_stats['assets_count']} assets active")
                
        except KeyboardInterrupt:
            self._log("👋 Stopping...")
        finally:
            # 最后一次 flush
            self._log("💾 Final flush...")
            self.flush_to_db()
            
            if self.ws:
                self.ws.stop()
            self._print_stats()
    
    def _ensure_tables(self):
        """确保数据库表存在"""
        session = get_session()
        try:
            # 检测数据库类型
            is_sqlite = 'sqlite' in DATABASE_URL.lower()
            
            if is_sqlite:
                # SQLite 语法
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(token_id, hour)
                    )
                """))
            else:
                # PostgreSQL 语法
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
            
            # 创建索引（两者语法相同）
            try:
                session.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_ws_trades_token_hour 
                    ON ws_trades_hourly(token_id, hour)
                """))
            except:
                pass  # 索引可能已存在
            
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
        
        # 运行时长
        if self.stats['started_at']:
            duration = datetime.now() - self.stats['started_at']
            print(f"\n⏱️ Total runtime: {duration}")


# ============================================================================
# 辅助函数：供 sync.py 使用
# ============================================================================

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
        {
            'aggressive_buy': float,
            'aggressive_sell': float,
            'total_volume': float,
            'volume_delta': float,
            'directional_ar': float,  # |delta| / total
            'trade_count': int,
            'has_data': bool
        }
    """
    try:
        # PostgreSQL 语法
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
            
            # Directional AR = |delta| / total
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
        # 表可能不存在或其他错误
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


# ============================================================================
# 命令行入口
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='WebSocket Trade Collector v2')
    parser.add_argument('--markets', type=int, default=100,
                       help='Number of markets to monitor (default: 100)')
    parser.add_argument('--interval', type=int, default=60,
                       help='Flush interval in seconds (default: 60)')
    parser.add_argument('--quiet', action='store_true',
                       help='Reduce logging')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🌐 Polymarket WebSocket Trade Collector v2")
    print("=" * 60)
    print(f"Markets: {args.markets}")
    print(f"Flush interval: {args.interval}s")
    print(f"Optimizations: last_flush_ts tracking, incremental counters")
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