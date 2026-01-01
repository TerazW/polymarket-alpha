"""
Phase Histogram 数据操作

提供 phase_histogram 表的读写函数
用于存储每个 Phase 的完整 histogram 数据，支持 Market Profile Evolution 可视化
"""

from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict
from sqlalchemy import text


def create_phase_histogram_table(session) -> bool:
    """创建 phase_histogram 表"""
    try:
        # 检测数据库类型
        from utils.db import IS_POSTGRES
        
        if IS_POSTGRES:
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS phase_histogram (
                    id SERIAL PRIMARY KEY,
                    token_id VARCHAR(100) NOT NULL,
                    phase_number INTEGER NOT NULL,
                    price_bin DECIMAL(10,4) NOT NULL,
                    volume DECIMAL(20,8) DEFAULT 0,
                    aggressive_buy DECIMAL(20,8) DEFAULT 0,
                    aggressive_sell DECIMAL(20,8) DEFAULT 0,
                    trade_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(token_id, phase_number, price_bin)
                )
            """))
            
            session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_phase_histogram_token_phase 
                ON phase_histogram(token_id, phase_number)
            """))
        else:
            # SQLite
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS phase_histogram (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id VARCHAR(100) NOT NULL,
                    phase_number INTEGER NOT NULL,
                    price_bin DECIMAL(10,4) NOT NULL,
                    volume DECIMAL(20,8) DEFAULT 0,
                    aggressive_buy DECIMAL(20,8) DEFAULT 0,
                    aggressive_sell DECIMAL(20,8) DEFAULT 0,
                    trade_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(token_id, phase_number, price_bin)
                )
            """))
            
            session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_phase_histogram_token_phase 
                ON phase_histogram(token_id, phase_number)
            """))
        
        session.commit()
        print("✅ phase_histogram table created")
        return True
        
    except Exception as e:
        session.rollback()
        print(f"⚠️ Error creating phase_histogram table: {e}")
        return False


def save_phase_histogram(
    session,
    token_id: str,
    phase_number: int,
    histogram: Dict[float, Dict],
    clear_existing: bool = True
) -> int:
    """
    保存 Phase 的 histogram 到数据库
    
    Args:
        session: 数据库会话
        token_id: 市场 token ID
        phase_number: Phase 编号 (1-4)
        histogram: {price_bin: {'volume': x, 'buy': y, 'sell': z, 'count': n}}
        clear_existing: 是否清除该 phase 的旧数据
    
    Returns:
        保存的记录数
    """
    if not histogram:
        return 0
    
    try:
        # 清除旧数据
        if clear_existing:
            session.execute(text("""
                DELETE FROM phase_histogram 
                WHERE token_id = :token_id AND phase_number = :phase_number
            """), {"token_id": token_id, "phase_number": phase_number})
        
        # 插入新数据
        saved = 0
        for price_bin, data in histogram.items():
            # 支持多种字段名
            volume = data.get('volume', 0) or data.get('total', 0)
            buy = data.get('aggressive_buy', 0) or data.get('buy', 0)
            sell = data.get('aggressive_sell', 0) or data.get('sell', 0)
            count = data.get('trade_count', 0) or data.get('count', 0)
            
            # 如果 volume 为 0，用 buy + sell
            if volume == 0:
                volume = buy + sell
            
            # 跳过空数据
            if volume == 0 and buy == 0 and sell == 0:
                continue
            
            session.execute(text("""
                INSERT INTO phase_histogram 
                (token_id, phase_number, price_bin, volume, aggressive_buy, aggressive_sell, trade_count)
                VALUES (:token_id, :phase_number, :price_bin, :volume, :buy, :sell, :count)
            """), {
                "token_id": token_id,
                "phase_number": phase_number,
                "price_bin": float(price_bin),
                "volume": float(volume),
                "buy": float(buy),
                "sell": float(sell),
                "count": int(count)
            })
            saved += 1
        
        session.commit()
        return saved
        
    except Exception as e:
        session.rollback()
        print(f"Error saving phase histogram: {e}")
        return 0


def get_phase_histogram(
    session,
    token_id: str,
    phase_number: int
) -> Dict[float, Dict]:
    """
    获取单个 Phase 的 histogram
    
    Returns:
        {price_bin: {'volume': x, 'buy': y, 'sell': z}}
    """
    try:
        result = session.execute(text("""
            SELECT price_bin, volume, aggressive_buy, aggressive_sell, trade_count
            FROM phase_histogram
            WHERE token_id = :token_id AND phase_number = :phase_number
            ORDER BY price_bin
        """), {"token_id": token_id, "phase_number": phase_number}).fetchall()
        
        histogram = {}
        for row in result:
            price_bin = float(row[0])
            histogram[price_bin] = {
                'volume': float(row[1] or 0),
                'buy': float(row[2] or 0),
                'sell': float(row[3] or 0),
                'count': int(row[4] or 0)
            }
        
        return histogram
    except Exception as e:
        print(f"Error getting phase histogram: {e}")
        return {}


def get_all_phase_histograms(
    session,
    token_id: str
) -> Dict[int, Dict[float, Dict]]:
    """
    获取所有 Phase 的 histogram
    
    Returns:
        {phase_number: {price_bin: {'volume': x, 'buy': y, 'sell': z}}}
    """
    try:
        result = session.execute(text("""
            SELECT phase_number, price_bin, volume, aggressive_buy, aggressive_sell, trade_count
            FROM phase_histogram
            WHERE token_id = :token_id
            ORDER BY phase_number, price_bin
        """), {"token_id": token_id}).fetchall()
        
        histograms = defaultdict(dict)
        for row in result:
            phase_num = int(row[0])
            price_bin = float(row[1])
            histograms[phase_num][price_bin] = {
                'volume': float(row[2] or 0),
                'buy': float(row[3] or 0),
                'sell': float(row[4] or 0),
                'count': int(row[5] or 0)
            }
        
        return dict(histograms)
    except Exception as e:
        print(f"Error getting all phase histograms: {e}")
        return {}


def aggregate_trades_to_phase_histogram(
    trades: List[Dict],
    tick_size: float = 0.01
) -> Dict[float, Dict]:
    """
    将交易列表聚合为 histogram 格式
    
    Args:
        trades: 交易列表，每个交易需要 price, size, side
        tick_size: 价格分档大小
    
    Returns:
        {price_bin: {'volume': x, 'buy': y, 'sell': z, 'count': n}}
    """
    histogram = defaultdict(lambda: {
        'volume': 0.0,
        'buy': 0.0,
        'sell': 0.0,
        'count': 0
    })
    
    for trade in trades:
        try:
            # 获取 price，处理 tuple 类型
            price = trade.get('price', 0)
            if isinstance(price, tuple):
                price = price[0] if price else 0
            price = float(price)
            
            # 获取 size，处理 tuple 类型
            size = trade.get('size', 0)
            if isinstance(size, tuple):
                size = size[0] if size else 0
            size = float(size)
            
            # 获取 side，处理 tuple 类型
            side = trade.get('side', '')
            if isinstance(side, tuple):
                side = side[0] if side else ''
            side = str(side).upper()
            
            # 价格分档
            bin_price = round(price / tick_size) * tick_size
            bin_price = round(bin_price, 4)
            
            histogram[bin_price]['volume'] += size
            histogram[bin_price]['count'] += 1
            
            if side == 'BUY':
                histogram[bin_price]['buy'] += size
            elif side == 'SELL':
                histogram[bin_price]['sell'] += size
            else:
                # 没有 side 信息，平均分配
                histogram[bin_price]['buy'] += size / 2
                histogram[bin_price]['sell'] += size / 2
                
        except (ValueError, TypeError):
            continue
    
    return dict(histogram)