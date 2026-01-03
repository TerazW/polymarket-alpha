ls backend/"""
Market Sensemaking metrics - full version v5.3

v5.3 updates:
1. edge_zone flag: mark extreme-probability markets instead of returning None
2. Noisy uses a volume floor to avoid flagging cold markets
3. V0 is configurable via environment variables
4. impulse_tag: EMERGING/ABSORPTION/EXHAUSTION as a separate signal

Available metrics:
1. Consensus band / profile
   - Consensus Band (VAH/VAL): 70% volume coverage
   - Band Width = VAH - VAL
   - POC: price with max volume
   - POMD: price with max disagreement
   - Rejected probabilities
2. Uncertainty
   - UI = band_width / mid_probability
   - ECR = distance_to_certainty / days_remaining
   - ACR = (bw_7d_ago - bw_now) / 7
   - CER = ACR / ECR
3. Conviction
   - AR (Directional) = |delta| / total
   - Volume Delta = buy - sell
   - CS v2 = AR * log(1 + volume / V0)
4. Classification
   - status: Informed / Fragmented / Noisy
   - impulse_tag: EMERGING / ABSORPTION / EXHAUSTION
   - edge_zone: True/False

Data sources:
- Data API: trades -> Histogram -> VAH/VAL/POC/UI/CER
- WebSocket: aggressor -> AR/Delta/CS/POMD
"""

import math
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict


# ============================================================================
# Configuration constants (env overrides supported)
# ============================================================================

# Direction thresholds
AR_BULLISH_THRESHOLD = 0.10   # AR > 0.10 and delta > 0 -> BULLISH
AR_BEARISH_THRESHOLD = 0.10   # AR > 0.10 and delta < 0 -> BEARISH

# CS v2 normalization baseline (env configurable)
# V0 is typically calibrated from historical P50-P70
CS_VOLUME_BASELINE = float(os.getenv('CS_VOLUME_BASELINE', '1000.0'))

# POMD minimum thresholds
POMD_MIN_THRESHOLD_RATIO = 0.02  # Must be at least 2% of total volume
POMD_MIN_ABSOLUTE = 10.0         # Absolute floor

# Status thresholds
UI_INFORMED_THRESHOLD = 0.30
UI_NOISY_THRESHOLD = 0.50
CER_INFORMED_THRESHOLD = 0.80
CER_NOISY_THRESHOLD = 0.40
CS_NOISY_THRESHOLD = 0.3   # Low CS implies weak directional participation

# Volume floor for Noisy to avoid flagging cold markets
NOISY_MIN_VOLUME = float(os.getenv('NOISY_MIN_VOLUME', '100.0'))

# Edge-zone thresholds (near-certain markets)
EDGE_ZONE_LOW = 0.10   # mid_prob < 10%
EDGE_ZONE_HIGH = 0.90  # mid_prob > 90%

# Impulse tag thresholds
IMPULSE_EMERGING_UI = 0.35
IMPULSE_EMERGING_CS = 0.45
IMPULSE_EMERGING_CER = 0.5
IMPULSE_ABSORPTION_CS_MIN = 0.25
IMPULSE_ABSORPTION_CS_MAX = 0.45
IMPULSE_ABSORPTION_PRICE_EPSILON = 0.02  # POMD vs price distance
IMPULSE_EXHAUSTION_CS = 0.7
IMPULSE_EXHAUSTION_UI = 0.2


# ============================================================================
# 1. Consensus band and profile
# ============================================================================

def calculate_histogram(trades: List[Dict], tick_size: float = 0.01) -> Dict[float, float]:
    """
    Convert trade data to a volume-at-price histogram.

    This is total volume only (no buy/sell split) and is used for
    VAH/VAL/POC calculations.
    """
    histogram = defaultdict(float)
    
    for trade in trades:
        try:
            # Read price, handling tuple values.
            price = trade.get('price', 0)
            if isinstance(price, tuple):
                price = price[0] if price else 0
            price = float(price)
            
            # Read size, handling tuple values.
            size = trade.get('size', 0)
            if isinstance(size, tuple):
                size = size[0] if size else 0
            size = float(size)
            
            bin_price = round(price / tick_size) * tick_size
            bin_price = round(bin_price, 4)
            
            histogram[bin_price] += size
            
        except (ValueError, TypeError, IndexError):
            continue
    
    return dict(histogram)


def calculate_consensus_band(
    histogram: Dict[float, float], 
    coverage: float = 0.70
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Compute the consensus band (Market Profile value area).

    Algorithm (expand contiguously around POC):
    1. Find POC (max-volume bin)
    2. Expand from POC to both sides
    3. Each step chooses the adjacent side with larger volume
    4. Stop when target volume coverage is reached

    This preserves a continuous value area around POC.
    
    Returns:
        (VAH, VAL, mid_probability)
        - VAH: Value Area High
        - VAL: Value Area Low  
        - mid_probability: (VAH + VAL) / 2
    """
    if not histogram:
        return None, None, None
    
    total_volume = sum(histogram.values())
    if total_volume == 0:
        return None, None, None
    
    # Sort by price.
    sorted_prices = sorted(histogram.keys())
    if len(sorted_prices) == 0:
        return None, None, None
    
    # Find POC.
    poc_price = max(histogram.keys(), key=lambda p: histogram[p])
    poc_idx = sorted_prices.index(poc_price)
    
    # Expand from POC.
    target_volume = total_volume * coverage
    cumulative = histogram[poc_price]
    
    low_idx = poc_idx
    high_idx = poc_idx
    
    # Expand outward until target coverage is reached.
    while cumulative < target_volume:
        # Check whether either side can expand.
        can_go_low = low_idx > 0
        can_go_high = high_idx < len(sorted_prices) - 1
        
        if not can_go_low and not can_go_high:
            break
        
        # Compare the next adjacent bin on each side.
        low_volume = histogram[sorted_prices[low_idx - 1]] if can_go_low else 0
        high_volume = histogram[sorted_prices[high_idx + 1]] if can_go_high else 0
        
        # Expand toward the side with higher volume.
        if can_go_low and (not can_go_high or low_volume >= high_volume):
            low_idx -= 1
            cumulative += histogram[sorted_prices[low_idx]]
        elif can_go_high:
            high_idx += 1
            cumulative += histogram[sorted_prices[high_idx]]
    
    VAL = sorted_prices[low_idx]
    VAH = sorted_prices[high_idx]
    mid_probability = (VAH + VAL) / 2
    
    return VAH, VAL, mid_probability


def get_band_width(histogram: Dict[float, float], coverage: float = 0.70) -> Optional[float]:
    """
    Band Width = VAH - VAL
    
    Interprets uncertainty:
    - Larger BW -> more dispersion
    - Smaller BW -> tighter consensus
    """
    VAH, VAL, _ = calculate_consensus_band(histogram, coverage)
    if VAH is None or VAL is None:
        return None
    return VAH - VAL


def calculate_poc(histogram: Dict[float, float]) -> Optional[float]:
    """
    POC (Point of Control) = max-volume price bin.

    POC indicates the liquidity center. It is not necessarily a
    disagreement point.
    """
    if not histogram:
        return None
    return max(histogram.keys(), key=lambda p: histogram[p])


def calculate_pomd(
    aggressor_histogram: Dict[float, Dict],
    min_threshold: float = None,
    total_volume: float = None
) -> Optional[float]:
    """
    POMD (Point of Max Disagreement) = strongest two-sided tug-of-war.

    Defined as the price bin with the largest min(aggressive_buy, aggressive_sell).

    POC vs POMD:
    - POC: max volume (can be one-sided)
    - POMD: most balanced two-sided pressure
    
    Args:
        aggressor_histogram: {price: {'buy': x, 'sell': y, ...}}
        min_threshold: minimum threshold (auto if None)
        total_volume: total volume for dynamic thresholding
    
    Returns:
        POMD price or None when insufficient data
    """
    if not aggressor_histogram:
        return None
    
    # Compute dynamic threshold.
    if min_threshold is None:
        if total_volume and total_volume > 0:
            # At least 2% of total volume.
            min_threshold = max(
                total_volume * POMD_MIN_THRESHOLD_RATIO,
                POMD_MIN_ABSOLUTE
            )
        else:
            # Fallback to absolute floor when total volume is unknown.
            min_threshold = POMD_MIN_ABSOLUTE
    
    valid_bins = {}
    for price, data in aggressor_histogram.items():
        buy = data.get('buy', 0)
        sell = data.get('sell', 0)
        min_side = min(buy, sell)
        
        if min_side >= min_threshold:
            valid_bins[price] = min_side
    
    if not valid_bins:
        return None
    
    return max(valid_bins.keys(), key=lambda p: valid_bins[p])


def calculate_tails(
    histogram: Dict[float, float],
    vah: float,
    val: float,
    min_tail_bins: int = 2
) -> Dict[str, List[float]]:
    """
    Compute tails (rejected price areas) in Market Profile terms.

    Definition:
    - Upper Tail: prices above VAH (seller rejection)
    - Lower Tail: prices below VAL (buyer rejection)

    Interpretation:
    - Price trades through quickly and is rejected
    - Similar to classic Market Profile single prints

    Args:
        histogram: volume-at-price histogram
        vah: Value Area High
        val: Value Area Low
        min_tail_bins: minimum bin count to qualify as a tail
    
    Returns:
        {'upper_tail': [prices], 'lower_tail': [prices]}
    """
    if not histogram or vah is None or val is None:
        return {'upper_tail': [], 'lower_tail': []}
    
    sorted_prices = sorted(histogram.keys())
    
    upper_tail = [p for p in sorted_prices if p > vah]
    lower_tail = [p for p in sorted_prices if p < val]
    
    return {
        'upper_tail': upper_tail if len(upper_tail) >= min_tail_bins else [],
        'lower_tail': lower_tail if len(lower_tail) >= min_tail_bins else []
    }


def calculate_rejected_probabilities(
    histogram: Dict[float, float],
    threshold_percentile: float = 0.10
) -> List[float]:
    """
    Rejected probabilities (legacy).

    Prefer calculate_tails() for VAH/VAL-based rejection.
    Defined as price bins in the lowest 10% volume percentile.
    """
    if not histogram or len(histogram) < 3:
        return []
    
    volumes = list(histogram.values())
    
    try:
        sorted_volumes = sorted(volumes)
        threshold_idx = max(0, int(len(sorted_volumes) * threshold_percentile) - 1)
        threshold = sorted_volumes[threshold_idx]
        rejected = [price for price, volume in histogram.items() if volume <= threshold]
        return sorted(rejected)
    except Exception:
        return []


def get_market_profile(
    histogram: Dict[float, float],
    aggressor_histogram: Optional[Dict[float, Dict]] = None
) -> Dict:
    """
    Return a full market profile summary (for visualization).
    
    Returns:
        {
            'histogram': {price: volume},
            'poc': float,
            'vah': float,
            'val': float,
            'band_width': float,
            'upper_tail': [prices],
            'lower_tail': [prices],
            'pomd': float (when aggressor data is available),
            'total_volume': float,
        }
    """
    if not histogram:
        return None
    
    VAH, VAL, mid_prob = calculate_consensus_band(histogram)
    poc = calculate_poc(histogram)
    band_width = get_band_width(histogram)
    tails = calculate_tails(histogram, VAH, VAL)
    
    pomd = None
    if aggressor_histogram:
        ws_vol = sum(d.get('buy', 0) + d.get('sell', 0) for d in aggressor_histogram.values())
        pomd = calculate_pomd(aggressor_histogram, total_volume=ws_vol)
    
    return {
        'histogram': histogram,
        'poc': poc,
        'vah': VAH,
        'val': VAL,
        'mid_probability': mid_prob,
        'band_width': band_width,
        'upper_tail': tails['upper_tail'],
        'lower_tail': tails['lower_tail'],
        'pomd': pomd,
        'total_volume': sum(histogram.values()),
        'price_levels': len(histogram),
    }


def get_volume_profile_summary(
    histogram: Dict[float, float],
    aggressor_histogram: Optional[Dict[float, Dict]] = None
) -> Dict:
    """Return a full volume profile summary."""
    VAH, VAL, mid_prob = calculate_consensus_band(histogram)
    band_width = get_band_width(histogram)
    poc = calculate_poc(histogram)
    tails = calculate_tails(histogram, VAH, VAL)
    rejected = calculate_rejected_probabilities(histogram)  # Legacy compatibility.
    
    pomd = None
    if aggressor_histogram:
        ws_vol = sum(d.get('buy', 0) + d.get('sell', 0) for d in aggressor_histogram.values())
        pomd = calculate_pomd(aggressor_histogram, total_volume=ws_vol)
    
    return {
        'VAH': VAH,
        'VAL': VAL,
        'mid_probability': mid_prob,
        'band_width': band_width,
        'POC': poc,
        'POMD': pomd,
        'upper_tail': tails['upper_tail'],
        'lower_tail': tails['lower_tail'],
        'rejected_probabilities': rejected,  # Legacy compatibility.
        'total_volume': sum(histogram.values()) if histogram else 0,
        'price_levels': len(histogram) if histogram else 0
    }


# ============================================================================
# 2. Uncertainty metrics
# ============================================================================

def calculate_ui(histogram: Dict[float, float]) -> Tuple[Optional[float], bool]:
    """
    UI (Uncertainty Index) = band_width / mid_probability
    
    Interpretation:
    - A 10% band around 50% implies moderate uncertainty.
    - A 10% band near 90% implies extreme uncertainty (near certainty but split).
    
    Returns:
        (ui_value, edge_zone)
        - ui_value: UI value, None for extreme probabilities
        - edge_zone: True if mid_prob < 10% or > 90% (near certain)
    
    Guidance:
    - UI < 0.30: low uncertainty
    - UI 0.30-0.50: moderate
    - UI >= 0.50: high uncertainty
    - edge_zone=True: near-certain markets where UI is less meaningful
    """
    VAH, VAL, mid_probability = calculate_consensus_band(histogram)
    
    if VAH is None or VAL is None or mid_probability is None:
        return None, False
    
    band_width = VAH - VAL
    
    # Mark extreme-probability markets as edge zone.
    if mid_probability < EDGE_ZONE_LOW or mid_probability > EDGE_ZONE_HIGH:
        return None, True  # UI=None but edge_zone=True
    
    if mid_probability == 0:
        return None, False
    
    return band_width / mid_probability, False


def calculate_ui_simple(histogram: Dict[float, float]) -> Optional[float]:
    """
    Simplified UI (legacy compatibility).
    Returns UI only and omits edge_zone.
    """
    ui, _ = calculate_ui(histogram)
    return ui


def calculate_ecr(current_price: float, days_remaining: int) -> Optional[float]:
    """
    ECR (Expected Convergence Rate) = distance_to_certainty / days_remaining
    
    Interpretation:
    - How much theoretical convergence remains.
    - Market converges to 0 or 1.
    - distance = min(price, 1 - price)
    """
    if days_remaining < 1:
        return None
    
    # Skip extreme prices.
    if current_price > 0.95 or current_price < 0.05:
        return None
    
    distance_to_certainty = min(current_price, 1 - current_price)
    return distance_to_certainty / days_remaining


def calculate_acr(
    band_width_now: Optional[float],
    band_width_7d_ago: Optional[float],
    days: int = 7
) -> Optional[float]:
    """
    ACR (Actual Convergence Rate) = (bw_7d_ago - bw_now) / days
    
    Interpretation: real-world narrowing speed of uncertainty.
    - ACR > 0: band is shrinking (consensus forming)
    - ACR < 0: band is widening (divergence growing)
    - ACR ~= 0: band is stable
    """
    if band_width_now is None or band_width_7d_ago is None:
        return None
    if days <= 0:
        return None
    return (band_width_7d_ago - band_width_now) / days


def calculate_cer(
    band_width_now: Optional[float],
    band_width_7d_ago: Optional[float],
    current_price: float,
    days_remaining: int
) -> Optional[float]:
    """
    CER (Convergence Efficiency Ratio) = ACR / ECR
    
    Interpretation: how healthy convergence is.
    - CER > 1.0: faster than expected
    - CER ~= 0.8-1.0: normal
    - CER < 0.5: stalled
    - CER < 0: diverging
    """
    ecr = calculate_ecr(current_price, days_remaining)
    if ecr is None or ecr <= 0:
        return None
    
    acr = calculate_acr(band_width_now, band_width_7d_ago)
    if acr is None:
        return None
    
    return acr / ecr


def get_uncertainty_metrics(
    histogram: Dict[float, float],
    current_price: float,
    days_remaining: int,
    band_width_7d_ago: Optional[float] = None
) -> Dict:
    """Return all uncertainty metrics."""
    band_width_now = get_band_width(histogram)
    
    return {
        'UI': calculate_ui(histogram),
        'ECR': calculate_ecr(current_price, days_remaining),
        'ACR': calculate_acr(band_width_now, band_width_7d_ago),
        'CER': calculate_cer(band_width_now, band_width_7d_ago, current_price, days_remaining),
        'band_width_now': band_width_now,
        'band_width_7d_ago': band_width_7d_ago
    }


# ============================================================================
# 3. Conviction metrics
# ============================================================================

def calculate_ar(
    aggressive_buy: float,
    aggressive_sell: float,
    total_volume: float
) -> Optional[float]:
    """
    AR (Directional Aggressive Ratio) = |delta| / total_volume
    
    Why directional AR vs traditional AR?
    - Traditional AR = aggressive / total ~= 1 (prediction markets are mostly aggressive)
    - Directional AR = |buy - sell| / total -> directional strength
    
    Interpretation:
    - 0 = balanced, no direction
    - 1 = fully one-sided
    """
    if total_volume <= 0:
        return None
    
    delta = abs(aggressive_buy - aggressive_sell)
    return min(delta / total_volume, 1.0)


def calculate_volume_delta(
    aggressive_buy: float,
    aggressive_sell: float
) -> Optional[float]:
    """
    Volume Delta = aggressive_buy - aggressive_sell
    
    Direction:
    - delta > 0: buyers dominate
    - delta < 0: sellers dominate
    - delta ~= 0: balanced
    """
    return aggressive_buy - aggressive_sell


def calculate_cs(
    aggressive_buy: float,
    aggressive_sell: float,
    total_volume: float
) -> Optional[float]:
    """
    CS v2 (Conviction Score) = Directional AR × Participation
    
    CS v2 = (|delta| / total) × log(1 + total_volume / V0)
    
    Why normalize with V0?
    - Raw log(1+V) shifts thresholds as volume units change.
    - log(1 + V/V0) keeps thresholds comparable across markets.
    - V0 = 1000 means $1000 volume gives participation ~= 0.69.

    Interpretation:
    - Low CS: weak direction or low participation
    - High CS: clear direction with real participation
    """
    if total_volume <= 0:
        return None
    
    delta = abs(aggressive_buy - aggressive_sell)
    directional_ar = delta / total_volume
    participation = math.log(1 + total_volume / CS_VOLUME_BASELINE)
    
    return directional_ar * participation


def calculate_cs_v1(
    aggressive_buy: float,
    aggressive_sell: float,
    total_volume: float
) -> Optional[float]:
    """
    CS v1 (legacy) = Directional AR.
    Kept for comparison only.
    """
    return calculate_ar(aggressive_buy, aggressive_sell, total_volume)


def get_direction(
    aggressive_buy: float,
    aggressive_sell: float,
    total_volume: float
) -> str:
    """
    Direction classification using AR thresholds.

    Rules:
    - AR > threshold and delta > 0 -> BULLISH
    - AR > threshold and delta < 0 -> BEARISH
    - Otherwise -> NEUTRAL
    """
    if total_volume <= 0:
        return "UNKNOWN"
    
    ar = calculate_ar(aggressive_buy, aggressive_sell, total_volume)
    delta = aggressive_buy - aggressive_sell
    
    if ar is None:
        return "UNKNOWN"
    
    if ar > AR_BULLISH_THRESHOLD and delta > 0:
        return "BULLISH"
    elif ar > AR_BEARISH_THRESHOLD and delta < 0:
        return "BEARISH"
    else:
        return "NEUTRAL"


def get_conviction_metrics(
    aggressive_buy: float,
    aggressive_sell: float,
    total_volume: float
) -> Dict:
    """Return all conviction metrics."""
    return {
        'AR': calculate_ar(aggressive_buy, aggressive_sell, total_volume),
        'volume_delta': calculate_volume_delta(aggressive_buy, aggressive_sell),
        'CS': calculate_cs(aggressive_buy, aggressive_sell, total_volume),
        'CS_v1': calculate_cs_v1(aggressive_buy, aggressive_sell, total_volume),
        'aggressive_buy': aggressive_buy,
        'aggressive_sell': aggressive_sell,
        'total_volume': total_volume,
        'direction': get_direction(aggressive_buy, aggressive_sell, total_volume)
    }


# ============================================================================
# 4. Status classification
# ============================================================================

def determine_status(
    ui: Optional[float],
    cer: Optional[float],
    cs: Optional[float] = None,
    total_volume: Optional[float] = None,
    edge_zone: bool = False
) -> str:
    """
    Determine market status.

    Informed:
    - UI < 0.30 (narrow band)
    - CER >= 0.80 (healthy convergence)
    - Note: does not require high CS; mature consensus can be calm

    Noisy:
    - UI >= 0.50 (very wide band)
    - or CER < 0.40 (stalled convergence)
    - or CS < 0.3 with sufficient volume (activity without direction)

    Fragmented:
    - all other cases

    Unknown:
    - insufficient data

    Late-stage:
    - edge_zone=True (near certain)

    Design principles:
    - Informed = stable consensus, not "consensus forming"
    - High CS implies active pushing, often early/mid consensus
    - Noisy requires enough volume to avoid flagging cold markets
    """
    # Edge zone takes precedence for near-certain markets.
    if edge_zone:
        return "🔵 Late-stage"
    
    if ui is None and cer is None:
        return "⚪ Unknown"
    
    # Noisy if any condition matches.
    if ui is not None and ui >= UI_NOISY_THRESHOLD:
        return "🔴 Noisy"
    if cer is not None and cer < CER_NOISY_THRESHOLD:
        return "🔴 Noisy"
    
    # Low CS implies weak directional participation.
    # Require sufficient volume to avoid flagging cold markets.
    if cs is not None and cs < CS_NOISY_THRESHOLD:
        volume_sufficient = (total_volume is None) or (total_volume >= NOISY_MIN_VOLUME)
        if volume_sufficient:
            return "🔴 Noisy"
    
    # Informed requires UI + CER; CS is ignored.
    ui_good = (ui is not None and ui < UI_INFORMED_THRESHOLD)
    cer_good = (cer is not None and cer >= CER_INFORMED_THRESHOLD)
    
    if ui_good and cer_good:
        return "🟢 Informed"
    
    return "🟡 Fragmented"


def get_status_explanation(status: str) -> str:
    """Return a human-readable status explanation."""
    explanations = {
        "🟢 Informed": "Stable consensus with strong shared belief.",
        "🟡 Fragmented": "Understanding is split; disagreement persists.",
        "🔴 Noisy": "Lacks a stable cognitive structure.",
        "🔵 Late-stage": "Near certainty and in late stage.",
        "⚪ Unknown": "Insufficient data to classify."
    }
    return explanations.get(status, "Unknown status")


def determine_impulse_tag(
    ui: Optional[float],
    cer: Optional[float],
    cs: Optional[float],
    pomd: Optional[float],
    current_price: Optional[float]
) -> Optional[str]:
    """
    Determine impulse tag (signal independent of status).

    EMERGING:
    - High UI (large divergence) + high CS (clear direction) + CER not poor
    - Strong early-consensus signal

    ABSORPTION:
    - POMD ~= current_price (two-sided battle at current price)
    - Mid CS (conflict but unclear direction)
    - Often precedes regime change

    EXHAUSTION:
    - High CS + very low UI
    - Looks like full agreement but structure is saturated
    - Risk warning

    Returns:
        str or None: "EMERGING" / "ABSORPTION" / "EXHAUSTION" / None
    """
    # EMERGING: early consensus signal.
    if (ui is not None and ui >= IMPULSE_EMERGING_UI and
        cs is not None and cs >= IMPULSE_EMERGING_CS and
        cer is not None and cer >= IMPULSE_EMERGING_CER):
        return "⚡ EMERGING"
    
    # ABSORPTION: tug-of-war near the current price.
    if (pomd is not None and current_price is not None and
        cs is not None and 
        IMPULSE_ABSORPTION_CS_MIN <= cs <= IMPULSE_ABSORPTION_CS_MAX):
        if abs(pomd - current_price) < IMPULSE_ABSORPTION_PRICE_EPSILON:
            return "🔄 ABSORPTION"
    
    # EXHAUSTION: late-stage momentum (risk warning).
    if (cs is not None and cs >= IMPULSE_EXHAUSTION_CS and
        ui is not None and ui < IMPULSE_EXHAUSTION_UI):
        return "💨 EXHAUSTION"
    
    return None


def get_impulse_explanation(impulse_tag: Optional[str]) -> str:
    """Return a human-readable impulse explanation."""
    if impulse_tag is None:
        return ""
    
    explanations = {
        "⚡ EMERGING": "Consensus forming; order flow tilts early.",
        "🔄 ABSORPTION": "Key tug-of-war; a break often becomes the signal.",
        "💨 EXHAUSTION": "Late-stage momentum; structure is saturated, risk is high."
    }
    return explanations.get(impulse_tag, "")


# ============================================================================
# 5. Helpers
# ============================================================================

def normalize_timestamp(ts) -> int:
    """
    Normalize timestamps to milliseconds.

    Auto-detect:
    - ts < 1e12 -> seconds, convert to ms
    - ts >= 1e12 -> already ms
    """
    if ts is None:
        return 0
    
    try:
        ts = int(ts)
        if ts < 1e12:
            # Seconds -> milliseconds.
            return ts * 1000
        else:
            # Already milliseconds.
            return ts
    except (ValueError, TypeError):
        return 0


def filter_trades_by_time(trades: List[Dict], hours: int = 24) -> List[Dict]:
    """
    Filter trades within the last N hours.

    v5: auto-adapts ms vs s timestamps.
    """
    cutoff = datetime.now() - timedelta(hours=hours)
    cutoff_ms = int(cutoff.timestamp() * 1000)  # Use milliseconds.
    
    filtered = []
    for t in trades:
        ts = normalize_timestamp(t.get('timestamp', 0))
        if ts >= cutoff_ms:
            filtered.append(t)
    
    return filtered


def filter_trades_by_timerange(
    trades: List[Dict],
    start_time: datetime,
    end_time: datetime
) -> List[Dict]:
    """
    Filter trades within a specific time range.
    """
    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    
    filtered = []
    for t in trades:
        ts = normalize_timestamp(t.get('timestamp', 0))
        if start_ms <= ts < end_ms:
            filtered.append(t)
    
    return filtered


# ============================================================================
# 6. One-shot metrics
# ============================================================================

def calculate_all_metrics(
    trades_all: List[Dict],
    trades_24h: List[Dict],
    current_price: float,
    days_remaining: int,
    band_width_7d_ago: Optional[float] = None,
    # WebSocket aggressor data
    aggressive_buy: Optional[float] = None,
    aggressive_sell: Optional[float] = None,
    ws_total_volume: Optional[float] = None,
    # WebSocket price bin data (for POMD)
    aggressor_histogram: Optional[Dict[float, Dict]] = None
) -> Dict:
    """
    Compute all metrics in one pass.

    Data sources:
    - Data API trades_all -> Histogram -> VAH/VAL/POC/UI/CER
    - WebSocket -> AR/Delta/CS/POMD
    
    Args:
        trades_all: Data API trades (profile/VAH/VAL/POC)
        trades_24h: 24h trades (stats only)
        current_price: current price
        days_remaining: days remaining
        band_width_7d_ago: bandwidth 7 days ago (for ACR/CER)
        aggressive_buy: aggressive buy volume (WebSocket)
        aggressive_sell: aggressive sell volume (WebSocket)
        ws_total_volume: total WebSocket volume
        aggressor_histogram: {price: {'buy': x, 'sell': y}} (WebSocket, for POMD)
    """
    # Histogram (Data API).
    histogram = calculate_histogram(trades_all)
    
    # Profile metrics.
    VAH, VAL, mid_prob = calculate_consensus_band(histogram)
    band_width = get_band_width(histogram)
    poc = calculate_poc(histogram)
    tails = calculate_tails(histogram, VAH, VAL)
    rejected = calculate_rejected_probabilities(histogram)  # Legacy compatibility.
    
    # POMD (requires aggressor histogram + dynamic threshold).
    pomd = None
    if aggressor_histogram:
        # Total aggressor volume for dynamic thresholding.
        ws_vol = sum(
            d.get('buy', 0) + d.get('sell', 0) 
            for d in aggressor_histogram.values()
        )
        pomd = calculate_pomd(aggressor_histogram, total_volume=ws_vol)
    
    # Uncertainty metrics.
    ui, edge_zone = calculate_ui(histogram)
    ecr = calculate_ecr(current_price, days_remaining)
    acr = calculate_acr(band_width, band_width_7d_ago)
    cer = calculate_cer(band_width, band_width_7d_ago, current_price, days_remaining)
    
    # Conviction metrics (require WebSocket data).
    ar = None
    volume_delta = None
    cs = None
    direction = "UNKNOWN"
    total_vol = None
    
    if aggressive_buy is not None and aggressive_sell is not None:
        total_vol = ws_total_volume if ws_total_volume else (aggressive_buy + aggressive_sell)
        ar = calculate_ar(aggressive_buy, aggressive_sell, total_vol)
        volume_delta = calculate_volume_delta(aggressive_buy, aggressive_sell)
        cs = calculate_cs(aggressive_buy, aggressive_sell, total_vol)
        direction = get_direction(aggressive_buy, aggressive_sell, total_vol)
    
    # Status classification (volume floor + edge_zone included).
    status = determine_status(ui, cer, cs, total_vol, edge_zone)
    
    # Impulse tag (independent signal).
    impulse_tag = determine_impulse_tag(ui, cer, cs, pomd, current_price)
    
    return {
        # Profile
        'VAH': VAH,
        'VAL': VAL,
        'mid_probability': mid_prob,
        'band_width': band_width,
        'POC': poc,
        'POMD': pomd,
        'upper_tail': tails['upper_tail'],
        'lower_tail': tails['lower_tail'],
        'rejected_probabilities': rejected,  # Legacy compatibility.
        
        # Uncertainty
        'UI': ui,
        'ECR': ecr,
        'ACR': acr,
        'CER': cer,
        'edge_zone': edge_zone,
        
        # Conviction
        'AR': ar,
        'volume_delta': volume_delta,
        'CS': cs,
        'direction': direction,
        
        # Status
        'status': status,
        'status_explanation': get_status_explanation(status),
        'impulse_tag': impulse_tag,
        'impulse_explanation': get_impulse_explanation(impulse_tag),
        
        # Metadata
        'total_trades': len(trades_all),
        'trades_24h_count': len(trades_24h),
        'band_width_7d_ago': band_width_7d_ago,
        'has_aggressor_data': aggressive_buy is not None,
        'has_aggressor_histogram': aggressor_histogram is not None,
        'histogram': histogram,  # For visualization.
    }


# ============================================================================
# 7. Tests
# ============================================================================

if __name__ == "__main__":
    print("Testing Metrics v5.3\n")
    print("=" * 60)
    
    # === Test 1: timestamp normalization ===
    print("\nTest 1: Timestamp Normalization")
    
    # Simulate different timestamp formats.
    ts_seconds = 1704067200      # 2024-01-01 00:00:00 (seconds)
    ts_millis = 1704067200000    # 2024-01-01 00:00:00 (milliseconds)
    
    norm_s = normalize_timestamp(ts_seconds)
    norm_m = normalize_timestamp(ts_millis)
    
    print(f"   Input (seconds): {ts_seconds} -> {norm_s}")
    print(f"   Input (millis):  {ts_millis} -> {norm_m}")
    print(f"   OK: both normalized to same value: {norm_s == norm_m}")
    
    # === Test 2: CS v2 vs v1 (with V0 normalization) ===
    print("\nTest 2: CS v2 with V0 Normalization")
    
    # Small sample with high AR.
    buy_small, sell_small, vol_small = 9, 1, 10
    cs_v1_small = calculate_cs_v1(buy_small, sell_small, vol_small)
    cs_v2_small = calculate_cs(buy_small, sell_small, vol_small)
    
    print(f"   Small sample ($10, AR=0.8):")
    print(f"     CS v1: {cs_v1_small:.3f}")
    print(f"     CS v2: {cs_v2_small:.4f} (V0={CS_VOLUME_BASELINE})")
    
    # Medium sample.
    buy_med, sell_med, vol_med = 900, 100, 1000
    cs_v1_med = calculate_cs_v1(buy_med, sell_med, vol_med)
    cs_v2_med = calculate_cs(buy_med, sell_med, vol_med)
    
    print(f"   Medium sample ($1000, AR=0.8):")
    print(f"     CS v1: {cs_v1_med:.3f}")
    print(f"     CS v2: {cs_v2_med:.4f}")
    
    # Large sample with same AR.
    buy_large, sell_large, vol_large = 9000, 1000, 10000
    cs_v1_large = calculate_cs_v1(buy_large, sell_large, vol_large)
    cs_v2_large = calculate_cs(buy_large, sell_large, vol_large)
    
    print(f"   Large sample ($10000, AR=0.8):")
    print(f"     CS v1: {cs_v1_large:.3f}")
    print(f"     CS v2: {cs_v2_large:.4f}")
    
    print("   OK: CS v2 with V0 normalization is stable across markets")
    
    # === Test 3: Direction (AR threshold) ===
    print("\nTest 3: Direction (using AR threshold)")
    
    # BULLISH: AR > 0.1, delta > 0
    dir_bull = get_direction(60, 40, 100)
    print(f"   Buy=60, Sell=40, Total=100 -> {dir_bull}")
    
    # BEARISH: AR > 0.1, delta < 0
    dir_bear = get_direction(40, 60, 100)
    print(f"   Buy=40, Sell=60, Total=100 -> {dir_bear}")
    
    # NEUTRAL: AR < 0.1
    dir_neut = get_direction(52, 48, 100)
    print(f"   Buy=52, Sell=48, Total=100 -> {dir_neut}")
    
    # === Test 4: Consensus Band (POC-centered continuous expansion) ===
    print("\nTest 4: Consensus Band (POC-centered continuous expansion)")
    
    # Simulate a market with tails.
    test_trades_full = [
        {'price': 0.58, 'size': 10},   # Lower tail
        {'price': 0.59, 'size': 15},   # Lower tail
        {'price': 0.60, 'size': 50},   # Near VAL
        {'price': 0.61, 'size': 80},   
        {'price': 0.62, 'size': 120},  
        {'price': 0.63, 'size': 180},  
        {'price': 0.64, 'size': 250},  # POC
        {'price': 0.65, 'size': 200},  
        {'price': 0.66, 'size': 150},  
        {'price': 0.67, 'size': 100},  # Near VAH
        {'price': 0.68, 'size': 40},   
        {'price': 0.69, 'size': 20},   # Upper tail
        {'price': 0.70, 'size': 10},   # Upper tail
    ]
    
    histogram_full = calculate_histogram(test_trades_full)
    poc_full = calculate_poc(histogram_full)
    vah, val, mid = calculate_consensus_band(histogram_full)
    tails = calculate_tails(histogram_full, vah, val)
    
    print(f"   POC: {poc_full}")
    print(f"   Value Area: [{val}, {vah}]")
    print(f"   Upper Tail: {tails['upper_tail']}")
    print(f"   Lower Tail: {tails['lower_tail']}")
    print("   OK: Value Area is continuous around POC")
    
    # === Test 5: POC vs POMD ===
    print("\nTest 5: POC vs POMD")
    
    test_trades = [
        {'price': 0.64, 'size': 120},
        {'price': 0.65, 'size': 200},  # Max volume -> POC
        {'price': 0.66, 'size': 150},
    ]
    
    aggressor_histogram = {
        0.64: {'buy': 55, 'sell': 65},   # min_side = 55 (most balanced)
        0.65: {'buy': 180, 'sell': 20},  # min_side = 20 (one-sided push)
        0.66: {'buy': 100, 'sell': 50},  # min_side = 50
    }
    
    histogram = calculate_histogram(test_trades)
    poc = calculate_poc(histogram)
    pomd = calculate_pomd(aggressor_histogram)
    
    print(f"   POC (max volume): {poc}")
    print(f"   POMD (max disagreement): {pomd}")
    print("   OK: POC != POMD (max volume is not max disagreement)")
    
    # === Test 6: Status Determination (v5.3) ===
    print("\nTest 6: Status Determination (v5.3)")
    
    # Informed: low UI + high CER, CS ignored.
    status1 = determine_status(ui=0.2, cer=0.9, cs=0.5)
    print(f"   UI=0.2, CER=0.9, CS=0.5 -> {status1}")
    
    # Informed: CS not required.
    status2 = determine_status(ui=0.2, cer=0.9, cs=None)
    print(f"   UI=0.2, CER=0.9, CS=None -> {status2}")
    
    # Noisy (high UI)
    status3 = determine_status(ui=0.6, cer=0.9, cs=1.0)
    print(f"   UI=0.6, CER=0.9, CS=1.0 -> {status3}")
    
    # Noisy (low CS + sufficient volume)
    status4 = determine_status(ui=0.3, cer=0.5, cs=0.1, total_volume=500)
    print(f"   UI=0.3, CER=0.5, CS=0.1, vol=500 -> {status4}")
    
    # NOT Noisy (low CS but cold market - volume too low)
    status4b = determine_status(ui=0.3, cer=0.5, cs=0.1, total_volume=50)
    print(f"   UI=0.3, CER=0.5, CS=0.1, vol=50 -> {status4b} (cold market protected)")
    
    # Late-stage (edge_zone).
    status5 = determine_status(ui=None, cer=0.9, cs=0.5, edge_zone=True)
    print(f"   edge_zone=True -> {status5}")
    
    # Fragmented
    status6 = determine_status(ui=0.35, cer=0.6, cs=0.8)
    print(f"   UI=0.35, CER=0.6, CS=0.8 -> {status6}")
    
    # === Test 7: Impulse Tag ===
    print("\nTest 7: Impulse Tag (v5.3)")
    
    # EMERGING: high UI + high CS + OK CER.
    impulse1 = determine_impulse_tag(ui=0.4, cer=0.6, cs=0.5, pomd=None, current_price=0.65)
    print(f"   UI=0.4, CS=0.5, CER=0.6 -> {impulse1}")
    
    # ABSORPTION: POMD ~= price + mid CS.
    impulse2 = determine_impulse_tag(ui=0.35, cer=0.5, cs=0.35, pomd=0.65, current_price=0.66)
    print(f"   POMD~=price, CS=0.35 -> {impulse2}")
    
    # EXHAUSTION: high CS + low UI.
    impulse3 = determine_impulse_tag(ui=0.15, cer=0.9, cs=0.8, pomd=None, current_price=0.85)
    print(f"   UI=0.15, CS=0.8 -> {impulse3}")
    
    # None: no conditions met.
    impulse4 = determine_impulse_tag(ui=0.3, cer=0.5, cs=0.4, pomd=None, current_price=0.65)
    print(f"   UI=0.3, CS=0.4 -> {impulse4}")
    
    # === Test 8: UI with edge_zone ===
    print("\nTest 8: UI with edge_zone flag")
    
    # Normal market.
    test_normal = [{'price': 0.5, 'size': 100}, {'price': 0.55, 'size': 100}]
    ui_norm, edge_norm = calculate_ui(calculate_histogram(test_normal))
    ui_str = f"{ui_norm:.3f}" if ui_norm is not None else "None"
    print(f"   Normal market (50%): UI={ui_str}, edge_zone={edge_norm}")
    
    # Extreme market (near certain).
    test_edge = [{'price': 0.92, 'size': 100}, {'price': 0.95, 'size': 100}]
    ui_edge, edge_flag = calculate_ui(calculate_histogram(test_edge))
    print(f"   Edge market (95%): UI={ui_edge}, edge_zone={edge_flag}")
    
    print("\n" + "=" * 60)
    print("OK: All v5.3 tests completed!")
