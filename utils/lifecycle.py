"""
Market Lifecycle Phases - lifecycle analysis v2.

Features:
1. Fixed time slices (25% of lifecycle x 4 phases)
2. Volume thresholds (insufficient if below)
3. Per-phase metrics: Band/POC/POMD/UI/CER/AR/CS

Design principles:
- Fixed boundaries: time-based, history does not shift
- Honest output: mark insufficient data instead of forcing a chart
- Quality guardrail: only valid phases have reliable profiles

Data sources:
- Data API trades -> Band/POC/UI/CER
- WebSocket -> POMD/AR/CS (when available)
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
# Configuration
# ============================================================================

@dataclass
class PhaseConfig:
    """Phase configuration."""
    phase_number: int  # 1, 2, 3, 4
    start_pct: float   # 0, 0.25, 0.5, 0.75
    end_pct: float     # 0.25, 0.5, 0.75, 1.0


# 4 phases, each 25%
PHASES = [
    PhaseConfig(1, 0.00, 0.25),
    PhaseConfig(2, 0.25, 0.50),
    PhaseConfig(3, 0.50, 0.75),
    PhaseConfig(4, 0.75, 1.00),
]

# Thresholds
MIN_TRADES_THRESHOLD = 30      # Minimum trade count
MIN_VOLUME_THRESHOLD = 500     # Minimum volume (USD)


# ============================================================================
# Phase calculations
# ============================================================================

def calculate_phase_dates(
    created_at: datetime,
    end_date: datetime
) -> List[Tuple[int, datetime, datetime]]:
    """
    Compute start/end dates for each phase.

    Args:
        created_at: market creation time
        end_date: market end time

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
    Get current phase number.

    Returns:
        phase_number (1-4) or None (ended or not started)
    """
    if now is None:
        now = datetime.now()
    
    if now >= end_date:
        return None  # Ended
    
    if now < created_at:
        return None  # Not started
    
    total_duration = (end_date - created_at).total_seconds()
    elapsed = (now - created_at).total_seconds()
    progress = elapsed / total_duration
    
    for p in PHASES:
        if p.start_pct <= progress < p.end_pct:
            return p.phase_number
    
    return 4  # Final phase


def get_lifecycle_progress(
    created_at: datetime,
    end_date: datetime,
    now: Optional[datetime] = None
) -> float:
    """Get lifecycle progress (0.0 ~ 1.0)."""
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
    Filter trades within a phase.

    Args:
        trades: trade list
        phase_start: phase start time
        phase_end: phase end time
    """
    start_ts = int(phase_start.timestamp())
    end_ts = int(phase_end.timestamp())
    
    filtered = []
    for t in trades:
        ts = t.get('timestamp', 0)
        
        # Handle various timestamp formats.
        if ts is None:
            continue
        
        try:
            # If tuple, take first element.
            if isinstance(ts, tuple):
                ts = ts[0] if ts else 0
            
            # If string, convert to number.
            if isinstance(ts, str):
                ts = float(ts)
            
            # If milliseconds, convert to seconds.
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
    Check whether a phase meets thresholds.

    Args:
        trades: trades within the phase
        min_trades: minimum trade count
        min_volume: minimum volume

    Returns:
        (is_valid, reason)
    """
    if not trades:
        return False, "no_trades"
    
    trade_count = len(trades)
    
    # Compute total_volume, handling tuple sizes.
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
# Metrics
# ============================================================================

def calculate_phase_metrics(
    trades: List[Dict],
    current_price: float,
    days_remaining: int,
    previous_band_width: Optional[float] = None,
    # WebSocket aggressor data (optional)
    aggressor_histogram: Optional[Dict[float, Dict]] = None,
    aggressive_buy: Optional[float] = None,
    aggressive_sell: Optional[float] = None,
    # Thresholds
    min_trades: int = MIN_TRADES_THRESHOLD,
    min_volume: float = MIN_VOLUME_THRESHOLD,
) -> Dict:
    """
    Compute all metrics for a phase.

    Args:
        trades: phase trades (Data API)
        current_price: current/end price for the phase
        days_remaining: days remaining at phase end
        previous_band_width: prior phase band width (for ACR)
        aggressor_histogram: WebSocket price bins (optional, for POMD)
        aggressive_buy/sell: WebSocket aggressor totals (optional, for AR/CS)
        min_trades: minimum trade count
        min_volume: minimum volume

    Returns:
        Dict of metrics including is_valid and validity_reason
    """
    # Check thresholds.
    is_valid, validity_reason = check_phase_validity(trades, min_trades, min_volume)
    
    trade_count = len(trades) if trades else 0
    
    # Compute total_volume, handling tuple sizes.
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
    
    # Base result structure.
    result = {
        'has_data': trade_count > 0,
        'is_valid': is_valid,
        'validity_reason': validity_reason,
        'trade_count': trade_count,
        'total_volume': total_volume,
        'price_at_end': current_price,
    }
    
    # No trades -> return early.
    if not trades:
        return result
    
    # Compute histogram.
    histogram = calculate_histogram(trades)
    
    if not histogram:
        result['validity_reason'] = "no_histogram"
        result['is_valid'] = False
        return result
    
    # Profile
    VAH, VAL, mid_prob = calculate_consensus_band(histogram)
    band_width = get_band_width(histogram)
    poc = calculate_poc(histogram)
    
    # POMD (requires aggressor histogram).
    pomd = None
    if aggressor_histogram:
        pomd = calculate_pomd(aggressor_histogram)
    
    # Uncertainty - calculate_ui returns (ui_value, edge_zone).
    ui, edge_zone = calculate_ui(histogram)
    ecr = calculate_ecr(current_price, days_remaining) if days_remaining > 0 else None
    acr = calculate_acr(band_width, previous_band_width) if previous_band_width else None
    cer = calculate_cer(band_width, previous_band_width, current_price, days_remaining) if previous_band_width and days_remaining > 0 else None
    
    # Conviction (requires WebSocket data).
    ar = None
    cs = None
    volume_delta = None
    
    if aggressive_buy is not None and aggressive_sell is not None:
        total_vol = aggressive_buy + aggressive_sell
        if total_vol > 0:
            ar = calculate_ar(aggressive_buy, aggressive_sell, total_vol)
            cs = calculate_cs(aggressive_buy, aggressive_sell, total_vol)
            volume_delta = calculate_volume_delta(aggressive_buy, aggressive_sell)
    
    # Status (pass edge_zone).
    status = determine_status(ui, cer, cs, total_volume=total_volume, edge_zone=edge_zone)
    
    # Update result.
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
# Database operations
# ============================================================================

def save_phase_metrics(
    session,
    token_id: str,
    phase_number: int,
    phase_start: datetime,
    phase_end: datetime,
    metrics: Dict
) -> bool:
    """Save phase metrics to the database."""
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
        print(f"  Error saving phase {phase_number}: {e}")
        return False


def get_phase_metrics(session, token_id: str, phase_number: int) -> Optional[Dict]:
    """Fetch metrics for a phase from the database."""
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
        print(f"  Error getting phase {phase_number}: {e}")
    
    return None


def get_all_phases(session, token_id: str) -> List[Dict]:
    """Get all phases for a market."""
    phases = []
    for p in PHASES:
        phase_data = get_phase_metrics(session, token_id, p.phase_number)
        if phase_data:
            phases.append(phase_data)
    return phases


def get_band_evolution(session, token_id: str) -> List[Dict]:
    """
    Get band evolution data (for visualization).

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
    """Create lifecycle_phases table (PostgreSQL / SQLite)."""
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
        print("Created lifecycle_phases table")
        return True
        
    except Exception as e:
        session.rollback()
        print(f"Error creating table: {e}")
        return False


def _sqlite_has_column(session, table: str, col: str) -> bool:
    """Check whether a SQLite table has a column."""
    try:
        rows = session.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return any(r[1] == col for r in rows)
    except:
        return False


def migrate_lifecycle_table(session):
    """Migration: add is_valid and validity_reason (PostgreSQL / SQLite)."""
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
            # SQLite: check with PRAGMA before altering.
            if not _sqlite_has_column(session, "lifecycle_phases", "is_valid"):
                session.execute(text("ALTER TABLE lifecycle_phases ADD COLUMN is_valid BOOLEAN DEFAULT 0"))
            if not _sqlite_has_column(session, "lifecycle_phases", "validity_reason"):
                session.execute(text("ALTER TABLE lifecycle_phases ADD COLUMN validity_reason TEXT"))
        
        session.commit()
        print("Migrated lifecycle_phases table")
        return True
    except Exception as e:
        session.rollback()
        print(f"Migration error: {e}")
        return False


# ============================================================================
# Tests
# ============================================================================

if __name__ == "__main__":
    print("Testing Lifecycle Phases v2\n")
    print("=" * 60)
    
    # Simulate a 100-day market.
    created_at = datetime(2024, 1, 1)
    end_date = datetime(2024, 4, 10)  # 100 days later
    
    print(f"Market: {created_at.date()} -> {end_date.date()}")
    print(f"Duration: {(end_date - created_at).days} days\n")
    
    # Compute phases.
    phases = calculate_phase_dates(created_at, end_date)
    
    print("Phases:")
    for phase_num, start, end in phases:
        days = (end - start).days
        print(f"  Phase {phase_num}: {start.date()} -> {end.date()} ({days} days)")
    
    # Validity checks.
    print("\nValidity Check Tests:")
    
    # Sufficient trades.
    trades_enough = [{'size': 100, 'price': 0.5, 'timestamp': 0}] * 50
    valid, reason = check_phase_validity(trades_enough)
    print(f"  50 trades, $5000: {valid} ({reason})")
    
    # Insufficient trades.
    trades_few = [{'size': 100, 'price': 0.5, 'timestamp': 0}] * 10
    valid, reason = check_phase_validity(trades_few)
    print(f"  10 trades, $1000: {valid} ({reason})")
    
    # No trades.
    valid, reason = check_phase_validity([])
    print(f"  0 trades: {valid} ({reason})")
    
    print("\n" + "=" * 60)
    print("Tests completed!")
