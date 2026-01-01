"""
Market Lifecycle Phases - 生命周期阶段分析 v2

功能：
1. 固定时间切片（25% 生命周期 × 4 段）
2. 成交量门槛检查（不达标标记为 insufficient）
3. 每个阶段独立计算 Band/POC/POMD/UI/CER/AR/CS

设计原则：
- 边界固定：基于时间，历史不会改变
- 诚实展示：数据不足就标记，不强行画
- 质量保证：达标的 phase 才有可靠的 profile

数据来源：
- Data API trades → Band/POC/UI/CER
- WebSocket → POMD/AR/CS（如果有）
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from sqlalchemy import text

from utils.metrics import (
    calculate_histogram,
    calculate_consensus_band,
    get_band_width,
    calculate_poc,
    calculate_pomd,
    calculate_ui,
    calculate_ecr,
    calculate_acr,
    calculate_cer,
    calculate_ar,
    calculate_volume_delta,
    calculate_cs,
    determine_status,
)


# ============================================================================
# 配置
# ============================================================================

@dataclass
class PhaseConfig:
    """Phase 配置"""
    phase_number: int  # 1, 2, 3, 4
    start_pct: float   # 0, 0.25, 0.5, 0.75
    end_pct: float     # 0.25, 0.5, 0.75, 1.0


# 4 个 phases，各 25%
PHASES = [
    PhaseConfig(1, 0.00, 0.25),
    PhaseConfig(2, 0.25, 0.50),
    PhaseConfig(3, 0.50, 0.75),
    PhaseConfig(4, 0.75, 1.00),
]

# 门槛配置
MIN_TRADES_THRESHOLD = 30      # 最少交易笔数
MIN_VOLUME_THRESHOLD = 500     # 最少成交量（美元）


# ============================================================================
# Phase 计算
# ============================================================================

def calculate_phase_dates(
    created_at: datetime,
    end_date: datetime
) -> List[Tuple[int, datetime, datetime]]:
    """
    计算每个 phase 的起止日期
    
    Args:
        created_at: 市场创建时间
        end_date: 市场结算时间
    
    Returns:
        [(phase_number, start_date, end_date), ...]
    """
    total_duration = end_date - created_at
    
    phases = []
    for p in PHASES:
        phase_start = created_at + total_duration * p.start_pct
        phase_end = created_at + total_duration * p.end_pct
        phases.append((p.phase_number, phase_start, phase_end))
    
    return phases


def get_current_phase(
    created_at: datetime,
    end_date: datetime,
    now: Optional[datetime] = None
) -> Optional[int]:
    """
    获取当前处于第几个 phase
    
    Returns:
        phase_number (1-4) 或 None（已结算或未开始）
    """
    if now is None:
        now = datetime.now()
    
    if now >= end_date:
        return None  # 已结算
    
    if now < created_at:
        return None  # 还没开始
    
    total_duration = (end_date - created_at).total_seconds()
    elapsed = (now - created_at).total_seconds()
    progress = elapsed / total_duration
    
    for p in PHASES:
        if p.start_pct <= progress < p.end_pct:
            return p.phase_number
    
    return 4  # 最后阶段


def get_lifecycle_progress(
    created_at: datetime,
    end_date: datetime,
    now: Optional[datetime] = None
) -> float:
    """
    获取生命周期进度（0.0 ~ 1.0）
    """
    if now is None:
        now = datetime.now()
    
    if now <= created_at:
        return 0.0
    if now >= end_date:
        return 1.0
    
    total = (end_date - created_at).total_seconds()
    elapsed = (now - created_at).total_seconds()
    return elapsed / total


def filter_trades_by_phase(
    trades: List[Dict],
    phase_start: datetime,
    phase_end: datetime
) -> List[Dict]:
    """
    筛选某个 phase 内的 trades
    
    Args:
        trades: 交易列表
        phase_start: phase 开始时间
        phase_end: phase 结束时间
    """
    start_ts = int(phase_start.timestamp())
    end_ts = int(phase_end.timestamp())
    
    filtered = []
    for t in trades:
        ts = t.get('timestamp', 0)
        
        # 处理各种 timestamp 格式
        if ts is None:
            continue
        
        try:
            # 如果是 tuple，取第一个元素
            if isinstance(ts, tuple):
                ts = ts[0] if ts else 0
            
            # 如果是字符串，转换为数字
            if isinstance(ts, str):
                ts = float(ts)
            
            # 如果是毫秒，转换为秒
            if ts > 1e12:
                ts = ts / 1000
            
            ts = int(ts)
            
            if start_ts <= ts < end_ts:
                filtered.append(t)
                
        except (ValueError, TypeError, IndexError):
            continue
    
    return filtered


def check_phase_validity(
    trades: List[Dict],
    min_trades: int = MIN_TRADES_THRESHOLD,
    min_volume: float = MIN_VOLUME_THRESHOLD
) -> Tuple[bool, str]:
    """
    检查 phase 是否满足门槛
    
    Args:
        trades: 该 phase 内的交易
        min_trades: 最少交易笔数
        min_volume: 最少成交量
    
    Returns:
        (is_valid, reason)
    """
    if not trades:
        return False, "no_trades"
    
    trade_count = len(trades)
    
    # 计算 total_volume，处理 tuple 类型
    total_volume = 0.0
    for t in trades:
        size = t.get('size', 0)
        if isinstance(size, tuple):
            size = size[0] if size else 0
        try:
            total_volume += float(size)
        except (ValueError, TypeError):
            pass
    
    if trade_count < min_trades:
        return False, f"insufficient_trades ({trade_count} < {min_trades})"
    
    if total_volume < min_volume:
        return False, f"insufficient_volume (${total_volume:.0f} < ${min_volume})"
    
    return True, "valid"


# ============================================================================
# 指标计算
# ============================================================================

def calculate_phase_metrics(
    trades: List[Dict],
    current_price: float,
    days_remaining: int,
    previous_band_width: Optional[float] = None,
    # WebSocket aggressor 数据（可选）
    aggressor_histogram: Optional[Dict[float, Dict]] = None,
    aggressive_buy: Optional[float] = None,
    aggressive_sell: Optional[float] = None,
    # 门槛配置
    min_trades: int = MIN_TRADES_THRESHOLD,
    min_volume: float = MIN_VOLUME_THRESHOLD,
) -> Dict:
    """
    计算某个 phase 的所有指标
    
    Args:
        trades: 该 phase 内的 trades（Data API）
        current_price: 当前/阶段结束价格
        days_remaining: 该阶段结束时剩余天数
        previous_band_width: 上一阶段的 band width（用于 ACR）
        aggressor_histogram: WebSocket price bins（可选，用于 POMD）
        aggressive_buy/sell: WebSocket aggressor 汇总（可选，用于 AR/CS）
        min_trades: 最少交易笔数门槛
        min_volume: 最少成交量门槛
    
    Returns:
        包含所有指标的字典，含 is_valid 和 validity_reason
    """
    # 检查门槛
    is_valid, validity_reason = check_phase_validity(trades, min_trades, min_volume)
    
    trade_count = len(trades) if trades else 0
    
    # 计算 total_volume，处理 tuple 类型
    total_volume = 0.0
    if trades:
        for t in trades:
            size = t.get('size', 0)
            if isinstance(size, tuple):
                size = size[0] if size else 0
            try:
                total_volume += float(size)
            except (ValueError, TypeError):
                pass
    
    # 基础返回结构
    result = {
        'has_data': trade_count > 0,
        'is_valid': is_valid,
        'validity_reason': validity_reason,
        'trade_count': trade_count,
        'total_volume': total_volume,
        'price_at_end': current_price,
    }
    
    # 如果没有交易，直接返回
    if not trades:
        return result
    
    # 计算 histogram
    histogram = calculate_histogram(trades)
    
    if not histogram:
        result['validity_reason'] = "no_histogram"
        result['is_valid'] = False
        return result
    
    # Profile
    VAH, VAL, mid_prob = calculate_consensus_band(histogram)
    band_width = get_band_width(histogram)
    poc = calculate_poc(histogram)
    
    # POMD（需要 aggressor histogram）
    pomd = None
    if aggressor_histogram:
        pomd = calculate_pomd(aggressor_histogram)
    
    # Uncertainty - 注意 calculate_ui 返回 (ui_value, edge_zone) 元组
    ui, edge_zone = calculate_ui(histogram)
    ecr = calculate_ecr(current_price, days_remaining) if days_remaining > 0 else None
    acr = calculate_acr(band_width, previous_band_width) if previous_band_width else None
    cer = calculate_cer(band_width, previous_band_width, current_price, days_remaining) if previous_band_width and days_remaining > 0 else None
    
    # Conviction（需要 WebSocket 数据）
    ar = None
    cs = None
    volume_delta = None
    
    if aggressive_buy is not None and aggressive_sell is not None:
        total_vol = aggressive_buy + aggressive_sell
        if total_vol > 0:
            ar = calculate_ar(aggressive_buy, aggressive_sell, total_vol)
            cs = calculate_cs(aggressive_buy, aggressive_sell, total_vol)
            volume_delta = calculate_volume_delta(aggressive_buy, aggressive_sell)
    
    # 状态 - 传入 edge_zone 参数
    status = determine_status(ui, cer, cs, total_volume=total_volume, edge_zone=edge_zone)
    
    # 更新结果
    result.update({
        # Profile
        'va_high': VAH,
        'va_low': VAL,
        'band_width': band_width,
        'poc': poc,
        'pomd': pomd,
        
        # Uncertainty
        'ui': ui,
        'ecr': ecr,
        'acr': acr,
        'cer': cer,
        
        # Conviction
        'ar': ar,
        'cs': cs,
        'volume_delta': volume_delta,
        
        # Status
        'status': status,
    })
    
    return result


# ============================================================================
# 数据库操作
# ============================================================================

def save_phase_metrics(
    session,
    token_id: str,
    phase_number: int,
    phase_start: datetime,
    phase_end: datetime,
    metrics: Dict
) -> bool:
    """
    保存 phase 指标到数据库
    """
    try:
        session.execute(text("""
            INSERT INTO lifecycle_phases
            (token_id, phase_number, phase_start, phase_end,
             is_valid, validity_reason,
             va_high, va_low, band_width, poc, pomd,
             ui, ecr, acr, cer,
             ar, cs, volume_delta,
             status, total_volume, trade_count, price_at_end,
             created_at)
            VALUES
            (:tid, :phase, :start, :end,
             :valid, :reason,
             :vah, :val, :bw, :poc, :pomd,
             :ui, :ecr, :acr, :cer,
             :ar, :cs, :vdelta,
             :status, :vol, :count, :price,
             :now)
            ON CONFLICT (token_id, phase_number) DO UPDATE SET
                phase_start = EXCLUDED.phase_start,
                phase_end = EXCLUDED.phase_end,
                is_valid = EXCLUDED.is_valid,
                validity_reason = EXCLUDED.validity_reason,
                va_high = EXCLUDED.va_high,
                va_low = EXCLUDED.va_low,
                band_width = EXCLUDED.band_width,
                poc = EXCLUDED.poc,
                pomd = EXCLUDED.pomd,
                ui = EXCLUDED.ui,
                ecr = EXCLUDED.ecr,
                acr = EXCLUDED.acr,
                cer = EXCLUDED.cer,
                ar = EXCLUDED.ar,
                cs = EXCLUDED.cs,
                volume_delta = EXCLUDED.volume_delta,
                status = EXCLUDED.status,
                total_volume = EXCLUDED.total_volume,
                trade_count = EXCLUDED.trade_count,
                price_at_end = EXCLUDED.price_at_end
        """), {
            'tid': token_id,
            'phase': phase_number,
            'start': phase_start,
            'end': phase_end,
            'valid': metrics.get('is_valid', False),
            'reason': metrics.get('validity_reason', 'unknown'),
            'vah': metrics.get('va_high'),
            'val': metrics.get('va_low'),
            'bw': metrics.get('band_width'),
            'poc': metrics.get('poc'),
            'pomd': metrics.get('pomd'),
            'ui': metrics.get('ui'),
            'ecr': metrics.get('ecr'),
            'acr': metrics.get('acr'),
            'cer': metrics.get('cer'),
            'ar': metrics.get('ar'),
            'cs': metrics.get('cs'),
            'vdelta': metrics.get('volume_delta'),
            'status': metrics.get('status'),
            'vol': metrics.get('total_volume'),
            'count': metrics.get('trade_count'),
            'price': metrics.get('price_at_end'),
            'now': datetime.now()
        })
        
        session.commit()
        return True
        
    except Exception as e:
        session.rollback()
        print(f"  ⚠️ Error saving phase {phase_number}: {e}")
        return False


def get_phase_metrics(session, token_id: str, phase_number: int) -> Optional[Dict]:
    """
    从数据库获取某个 phase 的指标
    """
    try:
        result = session.execute(text("""
            SELECT 
                phase_number, phase_start, phase_end,
                is_valid, validity_reason,
                va_high, va_low, band_width, poc, pomd,
                ui, ecr, acr, cer,
                ar, cs, volume_delta,
                status, total_volume, trade_count, price_at_end
            FROM lifecycle_phases
            WHERE token_id = :tid AND phase_number = :phase
        """), {'tid': token_id, 'phase': phase_number}).fetchone()
        
        if result:
            return {
                'phase_number': result[0],
                'phase_start': result[1],
                'phase_end': result[2],
                'is_valid': result[3] if result[3] is not None else False,
                'validity_reason': result[4] or 'unknown',
                'va_high': float(result[5]) if result[5] else None,
                'va_low': float(result[6]) if result[6] else None,
                'band_width': float(result[7]) if result[7] else None,
                'poc': float(result[8]) if result[8] else None,
                'pomd': float(result[9]) if result[9] else None,
                'ui': float(result[10]) if result[10] else None,
                'ecr': float(result[11]) if result[11] else None,
                'acr': float(result[12]) if result[12] else None,
                'cer': float(result[13]) if result[13] else None,
                'ar': float(result[14]) if result[14] else None,
                'cs': float(result[15]) if result[15] else None,
                'volume_delta': float(result[16]) if result[16] else None,
                'status': result[17],
                'total_volume': float(result[18]) if result[18] else None,
                'trade_count': int(result[19]) if result[19] else 0,
                'price_at_end': float(result[20]) if result[20] else None,
            }
        
    except Exception as e:
        print(f"  ⚠️ Error getting phase {phase_number}: {e}")
    
    return None


def get_all_phases(session, token_id: str) -> List[Dict]:
    """
    获取某个市场的所有 phases
    """
    phases = []
    for p in PHASES:
        phase_data = get_phase_metrics(session, token_id, p.phase_number)
        if phase_data:
            phases.append(phase_data)
    return phases


def get_band_evolution(session, token_id: str) -> List[Dict]:
    """
    获取 Band 演变数据（用于可视化）
    
    Returns:
        [{phase, va_high, va_low, band_width, poc, pomd, is_valid}, ...]
    """
    phases = get_all_phases(session, token_id)
    
    return [
        {
            'phase': p['phase_number'],
            'phase_start': p['phase_start'],
            'phase_end': p['phase_end'],
            'va_high': p['va_high'],
            'va_low': p['va_low'],
            'band_width': p['band_width'],
            'poc': p['poc'],
            'pomd': p['pomd'],
            'is_valid': p['is_valid'],
            'validity_reason': p['validity_reason'],
            'trade_count': p['trade_count'],
        }
        for p in phases
    ]


def create_lifecycle_table(session):
    """创建 lifecycle_phases 表（兼容 PostgreSQL / SQLite）"""
    from utils.db import IS_POSTGRES
    try:
        if IS_POSTGRES:
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS lifecycle_phases (
                    id SERIAL PRIMARY KEY,
                    token_id VARCHAR(100),
                    phase_number INTEGER,
                    phase_start TIMESTAMP,
                    phase_end TIMESTAMP,
                    
                    is_valid BOOLEAN DEFAULT FALSE,
                    validity_reason VARCHAR(100),
                    
                    va_high DECIMAL(10,4),
                    va_low DECIMAL(10,4),
                    band_width DECIMAL(10,4),
                    poc DECIMAL(10,4),
                    pomd DECIMAL(10,4),
                    
                    ui DECIMAL(10,4),
                    ecr DECIMAL(10,6),
                    acr DECIMAL(10,6),
                    cer DECIMAL(10,4),
                    
                    ar DECIMAL(10,4),
                    cs DECIMAL(10,4),
                    volume_delta DECIMAL(20,8),
                    
                    status VARCHAR(50),
                    total_volume DECIMAL(20,8),
                    trade_count INTEGER,
                    price_at_end DECIMAL(10,4),
                    
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    UNIQUE(token_id, phase_number)
                )
            """))
        else:
            # SQLite
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS lifecycle_phases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id TEXT,
                    phase_number INTEGER,
                    phase_start TIMESTAMP,
                    phase_end TIMESTAMP,
                    
                    is_valid BOOLEAN DEFAULT 0,
                    validity_reason TEXT,
                    
                    va_high REAL,
                    va_low REAL,
                    band_width REAL,
                    poc REAL,
                    pomd REAL,
                    
                    ui REAL,
                    ecr REAL,
                    acr REAL,
                    cer REAL,
                    
                    ar REAL,
                    cs REAL,
                    volume_delta REAL,
                    
                    status TEXT,
                    total_volume REAL,
                    trade_count INTEGER,
                    price_at_end REAL,
                    
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    UNIQUE(token_id, phase_number)
                )
            """))
        
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_lifecycle_token
            ON lifecycle_phases(token_id)
        """))
        
        session.commit()
        print("✅ Created lifecycle_phases table")
        return True
        
    except Exception as e:
        session.rollback()
        print(f"⚠️ Error creating table: {e}")
        return False


def _sqlite_has_column(session, table: str, col: str) -> bool:
    """检查 SQLite 表是否有某列"""
    try:
        rows = session.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return any(r[1] == col for r in rows)
    except:
        return False


def migrate_lifecycle_table(session):
    """迁移：添加 is_valid 和 validity_reason 字段（兼容 PostgreSQL / SQLite）"""
    from utils.db import IS_POSTGRES
    try:
        if IS_POSTGRES:
            session.execute(text("""
                ALTER TABLE lifecycle_phases 
                ADD COLUMN IF NOT EXISTS is_valid BOOLEAN DEFAULT FALSE
            """))
            session.execute(text("""
                ALTER TABLE lifecycle_phases 
                ADD COLUMN IF NOT EXISTS validity_reason VARCHAR(100)
            """))
        else:
            # SQLite：用 PRAGMA 检查再加
            if not _sqlite_has_column(session, "lifecycle_phases", "is_valid"):
                session.execute(text("ALTER TABLE lifecycle_phases ADD COLUMN is_valid BOOLEAN DEFAULT 0"))
            if not _sqlite_has_column(session, "lifecycle_phases", "validity_reason"):
                session.execute(text("ALTER TABLE lifecycle_phases ADD COLUMN validity_reason TEXT"))
        
        session.commit()
        print("✅ Migrated lifecycle_phases table")
        return True
    except Exception as e:
        session.rollback()
        print(f"⚠️ Migration error: {e}")
        return False


# ============================================================================
# 测试
# ============================================================================

if __name__ == "__main__":
    print("🧪 Testing Lifecycle Phases v2\n")
    print("=" * 60)
    
    # 模拟市场：100 天生命周期
    created_at = datetime(2024, 1, 1)
    end_date = datetime(2024, 4, 10)  # 100 天后
    
    print(f"Market: {created_at.date()} → {end_date.date()}")
    print(f"Duration: {(end_date - created_at).days} days\n")
    
    # 计算 phases
    phases = calculate_phase_dates(created_at, end_date)
    
    print("📅 Phases:")
    for phase_num, start, end in phases:
        days = (end - start).days
        print(f"  Phase {phase_num}: {start.date()} → {end.date()} ({days} days)")
    
    # 测试门槛检查
    print("\n🔍 Validity Check Tests:")
    
    # 足够的交易
    trades_enough = [{'size': 100, 'price': 0.5, 'timestamp': 0}] * 50
    valid, reason = check_phase_validity(trades_enough)
    print(f"  50 trades, $5000: {valid} ({reason})")
    
    # 交易不足
    trades_few = [{'size': 100, 'price': 0.5, 'timestamp': 0}] * 10
    valid, reason = check_phase_validity(trades_few)
    print(f"  10 trades, $1000: {valid} ({reason})")
    
    # 空交易
    valid, reason = check_phase_validity([])
    print(f"  0 trades: {valid} ({reason})")
    
    print("\n" + "=" * 60)
    print("✅ Tests completed!")