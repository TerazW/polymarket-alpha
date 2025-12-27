"""
完整版指标计算（使用 Data API 的逐笔成交）
"""
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict

def calculate_histogram(trades: List[Dict], tick_size: float = 0.01) -> Dict[float, float]:
    """
    将成交数据转换为价格直方图
    
    注意：Data API 的 price 是 0-1，不需要转换
    """
    histogram = defaultdict(float)
    
    for trade in trades:
        try:
            price = float(trade.get('price', 0))
            size = float(trade.get('size', 0))
            
            # 分箱（price 已经是 0-1）
            bin_price = round(price / tick_size) * tick_size
            bin_price = round(bin_price, 4)
            
            histogram[bin_price] += size
            
        except (ValueError, TypeError):
            continue
    
    return dict(histogram)

def calculate_ui(histogram: Dict[float, float]) -> Optional[float]:
    """
    计算 Uncertainty Index
    UI = Consensus Band Width / Mid Probability
    """
    if not histogram:
        return None
    
    sorted_bins = sorted(histogram.items(), key=lambda x: x[1], reverse=True)
    total_volume = sum(histogram.values())
    
    if total_volume == 0:
        return None
    
    # 70% 成交量区间
    target_volume = total_volume * 0.70
    cumulative = 0
    consensus_band_prices = []
    
    for price, volume in sorted_bins:
        cumulative += volume
        consensus_band_prices.append(price)
        if cumulative >= target_volume:
            break
    
    if not consensus_band_prices:
        return None
    
    va_high = max(consensus_band_prices)
    va_low = min(consensus_band_prices)
    band_width = va_high - va_low
    mid_probability = (va_high + va_low) / 2
    
    # 边界情况
    if mid_probability < 0.10 or mid_probability > 0.90:
        return None
    
    ui = band_width / mid_probability if mid_probability > 0 else None
    
    return ui

def calculate_cs(trades: List[Dict]) -> Optional[float]:
    """
    计算 Conviction Score
    基于 buy/sell 方向性
    """
    if not trades:
        return None
    
    buy_volume = 0
    sell_volume = 0
    
    for trade in trades:
        try:
            size = float(trade.get('size', 0))
            side = trade.get('side', '')
            
            if side == 'BUY':
                buy_volume += size
            elif side == 'SELL':
                sell_volume += size
                
        except (ValueError, TypeError):
            continue
    
    total_volume = buy_volume + sell_volume
    
    if total_volume == 0:
        return None
    
    # 单边性强度
    volume_delta = abs(buy_volume - sell_volume)
    cs = volume_delta / total_volume
    
    return cs

def calculate_cer(
    band_width_now: float,
    band_width_7d_ago: Optional[float],
    current_price: float,
    days_remaining: int
) -> Optional[float]:
    """
    计算 Convergence Health
    CER = Actual Convergence Rate / Expected Convergence Rate
    """
    if days_remaining < 3:
        return None
    if current_price > 0.95 or current_price < 0.05:
        return None
    if band_width_7d_ago is None:
        return None
    
    # Expected rate
    distance_to_certainty = min(current_price, 1 - current_price)
    ecr = distance_to_certainty / days_remaining
    
    # Actual rate
    acr = (band_width_7d_ago - band_width_now) / 7
    
    # CER
    cer = acr / ecr if ecr > 0 else None
    
    return cer

def determine_status(
    ui: Optional[float],
    cer: Optional[float],
    cs: Optional[float]
) -> str:
    """判定市场状态"""
    if ui is None and cer is None and cs is None:
        return "⚪ Unknown"
    
    # 🔴 Noisy
    if (ui is not None and ui >= 0.50) or \
       (cer is not None and cer < 0.4) or \
       (cs is not None and cs < 0.15):
        return "🔴 Noisy"
    
    # 🟢 Informed
    if (ui is not None and ui < 0.30) and \
       (cer is not None and cer >= 0.8) and \
       (cs is not None and cs >= 0.35):
        return "🟢 Informed"
    
    # 🟡 Fragmented
    return "🟡 Fragmented"

def filter_trades_by_time(trades: List[Dict], hours: int = 24) -> List[Dict]:
    """
    筛选指定时间内的成交
    
    注意：timestamp 是秒（不是毫秒）
    """
    cutoff = datetime.now() - timedelta(hours=hours)
    cutoff_ts = int(cutoff.timestamp())  # 秒时间戳
    
    return [t for t in trades if t.get('timestamp', 0) >= cutoff_ts]

def get_band_width(histogram: dict) -> Optional[float]:
    """从直方图计算 band width"""
    if not histogram:
        return None
    
    sorted_bins = sorted(histogram.items(), key=lambda x: x[1], reverse=True)
    total_volume = sum(histogram.values())
    
    if total_volume == 0:
        return None
    
    target = total_volume * 0.70
    cumulative = 0
    prices = []
    
    for price, volume in sorted_bins:
        cumulative += volume
        prices.append(price)
        if cumulative >= target:
            break
    
    if prices:
        return max(prices) - min(prices)
    return None