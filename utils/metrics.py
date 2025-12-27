import pandas as pd
import numpy as np
from typing import Dict, List, Optional

def calculate_histogram(trades: List[Dict], tick_size: float = 0.01) -> Dict[float, float]:
    """
    将成交数据转换为价格直方图
    """
    histogram = {}
    
    for trade in trades:
        price = float(trade.get('price', 0))
        size = float(trade.get('size', 0))
        
        # 分箱
        bin_price = round(price / tick_size) * tick_size
        bin_price = round(bin_price, 4)
        
        histogram[bin_price] = histogram.get(bin_price, 0) + size
    
    return histogram

def calculate_ui(histogram: Dict[float, float]) -> Optional[float]:
    """
    计算 Uncertainty Index
    UI = Consensus Band Width / Mid Probability
    """
    if not histogram:
        return None
    
    # 按成交量排序
    sorted_bins = sorted(histogram.items(), key=lambda x: x[1], reverse=True)
    
    total_volume = sum(histogram.values())
    if total_volume == 0:
        return None
    
    # 找 70% 成交量区间
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
    
    # 边界情况处理
    if mid_probability < 0.10 or mid_probability > 0.90:
        return None
    
    ui = band_width / mid_probability if mid_probability > 0 else None
    
    return ui

def calculate_cer(
    band_width_now: float,
    band_width_7d_ago: float,
    current_price: float,
    days_remaining: int
) -> Optional[float]:
    """
    计算 Convergence Health (CER)
    CER = Actual Convergence Rate / Expected Convergence Rate
    """
    # 边界情况
    if days_remaining < 3:
        return None
    if current_price > 95 or current_price < 5:
        return None
    
    # Expected Convergence Rate
    ecr = (100 - current_price) / days_remaining
    
    # Actual Convergence Rate
    acr = (band_width_7d_ago - band_width_now) / 7
    
    # CER
    cer = acr / ecr if ecr > 0 else None
    
    return cer

def calculate_cs_simple(histogram: Dict[float, float], current_price: float) -> Optional[float]:
    """
    计算 Conviction Score (简化版)
    CS = |Above - Below| / Total
    """
    if not histogram:
        return None
    
    above = sum(v for p, v in histogram.items() if p > current_price)
    below = sum(v for p, v in histogram.items() if p < current_price)
    total = above + below
    
    if total == 0:
        return None
    
    cs = abs(above - below) / total
    
    return cs

def determine_status(ui: Optional[float], cer: Optional[float], cs: Optional[float]) -> str:
    """
    判定市场状态
    优先级：🔴 > 🟢 > 🟡
    """
    # 如果任何指标为 None，返回 Unknown
    if ui is None and cer is None and cs is None:
        return "⚪ Unknown"
    
    # 🔴 Noisy（最高优先级）
    if (ui is not None and ui >= 0.50) or \
       (cer is not None and cer < 0.4) or \
       (cs is not None and cs < 0.15):
        return "🔴 Noisy"
    
    # 🟢 Informed（必须全部满足）
    if (ui is not None and ui < 0.30) and \
       (cer is not None and cer >= 0.8) and \
       (cs is not None and cs >= 0.35):
        return "🟢 Informed"
    
    # 🟡 Fragmented（默认）
    return "🟡 Fragmented"

# 测试
if __name__ == "__main__":
    # 测试数据
    test_histogram = {
        0.45: 1000,
        0.46: 1500,
        0.47: 2000,
        0.48: 2500,
        0.49: 3000,
        0.50: 3500,
        0.51: 3000,
        0.52: 2500,
        0.53: 2000,
        0.54: 1500,
        0.55: 1000
    }
    
    ui = calculate_ui(test_histogram)
    print(f"UI: {ui:.4f}" if ui else "UI: None")
    
    cs = calculate_cs_simple(test_histogram, 0.50)
    print(f"CS: {cs:.4f}" if cs else "CS: None")
    
    status = determine_status(ui, 0.75, cs)
    print(f"Status: {status}")