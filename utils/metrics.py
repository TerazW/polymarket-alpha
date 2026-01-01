"""
Market Sensemaking 指标计算 - 完整版 v5.3

=== v5.3 更新 ===
1. edge_zone flag: 极端概率市场标记而非返回 None
2. Noisy 判定加 volume 门槛: 防止误伤冷市场
3. V0 配置化: 支持环境变量设置
4. impulse_tag: EMERGING/ABSORPTION/EXHAUSTION 独立标签

=== 可用指标 ===

1. 共识带和 Profile 相关
   ✅ Consensus Band (VAH/VAL) - 覆盖 70% 成交量的概率区间
   ✅ Band Width = VAH - VAL
   ✅ POC - Point of Control（成交量最大的价格）
   ✅ POMD - Point of Max Disagreement（拉锯最激烈的价格）
   ✅ Rejected Probabilities（被市场快速否定的概率区）

2. 不确定性类
   ✅ UI = band_width / mid_probability
   ✅ ECR = distance_to_certainty / days_remaining（理论收敛速度）
   ✅ ACR = (bw_7d_ago - bw_now) / 7（实际收敛速度）
   ✅ CER = ACR / ECR（收敛效率）

3. 信念强度类
   ✅ AR (Directional) = |delta| / total（方向性强度）
   ✅ Volume Delta = buy - sell（方向）
   ✅ CS v2 = AR × log(1 + volume/V0)（信念强度 × 参与规模）

4. 状态分类
   ✅ status: Informed / Fragmented / Noisy（结构状态）
   ✅ impulse_tag: EMERGING / ABSORPTION / EXHAUSTION（提示标签）
   ✅ edge_zone: True/False（是否接近确定）

=== 数据来源分工 ===
- Data API: trades → Histogram → VAH/VAL/POC/UI/CER
- WebSocket: aggressor → AR/Delta/CS/POMD
"""

import math
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict


# ============================================================================
# 配置常量（支持环境变量覆盖）
# ============================================================================

# Direction 判断阈值
AR_BULLISH_THRESHOLD = 0.10   # AR > 0.10 且 delta > 0 → BULLISH
AR_BEARISH_THRESHOLD = 0.10   # AR > 0.10 且 delta < 0 → BEARISH

# CS v2 归一化基准（可通过环境变量配置）
# V0 建议用历史数据 P50-P70 标定
CS_VOLUME_BASELINE = float(os.getenv('CS_VOLUME_BASELINE', '1000.0'))

# POMD 最小阈值
POMD_MIN_THRESHOLD_RATIO = 0.02  # 至少占总量 2% 才算有效争议点
POMD_MIN_ABSOLUTE = 10.0         # 绝对最小值

# 状态判定阈值
UI_INFORMED_THRESHOLD = 0.30
UI_NOISY_THRESHOLD = 0.50
CER_INFORMED_THRESHOLD = 0.80
CER_NOISY_THRESHOLD = 0.40
CS_NOISY_THRESHOLD = 0.3   # CS 很低 = 没有方向性参与

# Noisy 判定的 volume 门槛（防止误伤冷市场）
NOISY_MIN_VOLUME = float(os.getenv('NOISY_MIN_VOLUME', '100.0'))

# Edge Zone 阈值（接近确定的市场）
EDGE_ZONE_LOW = 0.10   # mid_prob < 10%
EDGE_ZONE_HIGH = 0.90  # mid_prob > 90%

# Impulse Tag 阈值
IMPULSE_EMERGING_UI = 0.35
IMPULSE_EMERGING_CS = 0.45
IMPULSE_EMERGING_CER = 0.5
IMPULSE_ABSORPTION_CS_MIN = 0.25
IMPULSE_ABSORPTION_CS_MAX = 0.45
IMPULSE_ABSORPTION_PRICE_EPSILON = 0.02  # POMD 与 price 差距
IMPULSE_EXHAUSTION_CS = 0.7
IMPULSE_EXHAUSTION_UI = 0.2


# ============================================================================
# 1. 共识带和 Profile 相关
# ============================================================================

def calculate_histogram(trades: List[Dict], tick_size: float = 0.01) -> Dict[float, float]:
    """
    将成交数据转换为价格直方图 (Volume-at-Price)
    
    注意：这是总量直方图，不区分 buy/sell
    用于 VAH/VAL/POC 计算
    """
    histogram = defaultdict(float)
    
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
    计算 Consensus Band (共识带) - Market Profile Value Area 算法
    
    正确算法（围绕 POC 连续扩展）：
    1. 找到 POC（成交量最大的 bin）
    2. 从 POC 向两侧扩展
    3. 每次选"成交量更大的那一侧"的相邻 bin
    4. 直到覆盖目标成交量
    
    这样 VAH/VAL 才是真正"连贯"的 value area，不会把中间没成交的价格也算进去。
    
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
    
    # 按价格排序
    sorted_prices = sorted(histogram.keys())
    if len(sorted_prices) == 0:
        return None, None, None
    
    # 找 POC
    poc_price = max(histogram.keys(), key=lambda p: histogram[p])
    poc_idx = sorted_prices.index(poc_price)
    
    # 从 POC 开始扩展
    target_volume = total_volume * coverage
    cumulative = histogram[poc_price]
    
    low_idx = poc_idx
    high_idx = poc_idx
    
    # 向两侧扩展直到达到目标
    while cumulative < target_volume:
        # 检查两侧是否还有空间
        can_go_low = low_idx > 0
        can_go_high = high_idx < len(sorted_prices) - 1
        
        if not can_go_low and not can_go_high:
            break
        
        # 计算两侧下一个 bin 的成交量
        low_volume = histogram[sorted_prices[low_idx - 1]] if can_go_low else 0
        high_volume = histogram[sorted_prices[high_idx + 1]] if can_go_high else 0
        
        # 选择成交量更大的那一侧扩展
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
    
    用途：衡量不确定性强弱
    - BW 大 → 认知分散
    - BW 小 → 共识集中
    """
    VAH, VAL, _ = calculate_consensus_band(histogram, coverage)
    if VAH is None or VAL is None:
        return None
    return VAH - VAL


def calculate_poc(histogram: Dict[float, float]) -> Optional[float]:
    """
    POC (Point of Control) = 交易集中点
    
    定义：成交量最大的 price bin
    意义：流动性中心，大家都在这里成交
    
    注意：POC ≠ 争议，只是"交易集中"
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
    POMD (Point of Max Disagreement) = 拉锯最激烈点
    
    定义：min(aggressive_buy, aggressive_sell) 最大的 price bin
    意义：双方都在主动打，而且势均力敌
    
    POC vs POMD:
    - POC: 成交量最大（可能是单边推进）
    - POMD: 双边拉锯最激烈（真正的争议点）
    
    Args:
        aggressor_histogram: {price: {'buy': x, 'sell': y, ...}}
        min_threshold: 最小阈值，None 时自动计算
        total_volume: 总成交量，用于计算动态阈值
    
    Returns:
        POMD price，如果没有有效数据返回 None
    """
    if not aggressor_histogram:
        return None
    
    # 计算动态阈值
    if min_threshold is None:
        if total_volume and total_volume > 0:
            # 至少占总量 2%
            min_threshold = max(
                total_volume * POMD_MIN_THRESHOLD_RATIO,
                POMD_MIN_ABSOLUTE
            )
        else:
            # 如果没有总量信息，用绝对最小值
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
    计算 Tail（被拒绝价格区）- Market Profile 风格
    
    定义：
    - Upper Tail: 高于 VAH 的价格区（卖方拒绝区）
    - Lower Tail: 低于 VAL 的价格区（买方拒绝区）
    
    意义：
    - 价格快速扫过然后被拒绝
    - 表示市场强烈不认可这些价格
    - 类似传统 Market Profile 的 Single Prints
    
    Args:
        histogram: 价格直方图
        vah: Value Area High
        val: Value Area Low
        min_tail_bins: 最少几个 bin 才算 tail
    
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
    Rejected Probabilities = 被市场快速否定的概率区（旧版本，保留兼容）
    
    注意：推荐使用 calculate_tails()，它基于 VAH/VAL 更准确
    
    定义：成交量在最低 10% 的价格区间
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
    获取完整的 Market Profile 数据（用于可视化）
    
    Returns:
        {
            'histogram': {price: volume},
            'poc': float,
            'vah': float,
            'val': float,
            'band_width': float,
            'upper_tail': [prices],
            'lower_tail': [prices],
            'pomd': float (如果有 aggressor 数据),
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
    """获取 Volume Profile 完整摘要"""
    VAH, VAL, mid_prob = calculate_consensus_band(histogram)
    band_width = get_band_width(histogram)
    poc = calculate_poc(histogram)
    tails = calculate_tails(histogram, VAH, VAL)
    rejected = calculate_rejected_probabilities(histogram)  # 保留旧版兼容
    
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
        'rejected_probabilities': rejected,  # 旧版兼容
        'total_volume': sum(histogram.values()) if histogram else 0,
        'price_levels': len(histogram) if histogram else 0
    }


# ============================================================================
# 2. 不确定性类
# ============================================================================

def calculate_ui(histogram: Dict[float, float]) -> Tuple[Optional[float], bool]:
    """
    UI (Uncertainty Index) = band_width / mid_probability
    
    为什么这样定义？
    - 同样 10% 带宽，在 50% 附近 → 不确定性中等
    - 同样 10% 带宽，在 90% 附近 → 极度不确定（接近确定却分裂）
    
    Returns:
        (ui_value, edge_zone)
        - ui_value: UI 值，极端概率时为 None
        - edge_zone: True 如果 mid_prob < 10% 或 > 90%（接近确定）
    
    解读：
    - UI < 0.30: 低不确定性
    - UI 0.30-0.50: 中等
    - UI >= 0.50: 高不确定性
    - edge_zone=True: 市场接近确定，UI 意义有限
    """
    VAH, VAL, mid_probability = calculate_consensus_band(histogram)
    
    if VAH is None or VAL is None or mid_probability is None:
        return None, False
    
    band_width = VAH - VAL
    
    # 边界情况：极端价格时标记 edge_zone
    if mid_probability < EDGE_ZONE_LOW or mid_probability > EDGE_ZONE_HIGH:
        return None, True  # UI=None 但 edge_zone=True
    
    if mid_probability == 0:
        return None, False
    
    return band_width / mid_probability, False


def calculate_ui_simple(histogram: Dict[float, float]) -> Optional[float]:
    """
    简化版 UI（兼容旧代码）
    只返回 UI 值，不返回 edge_zone
    """
    ui, _ = calculate_ui(histogram)
    return ui


def calculate_ecr(current_price: float, days_remaining: int) -> Optional[float]:
    """
    ECR (Expected Convergence Rate) = distance_to_certainty / days_remaining
    
    意义：理论上"还剩多少要收敛"
    - 市场最终会收敛到 0 或 100
    - distance = min(price, 1-price)
    """
    if days_remaining < 1:
        return None
    
    # 极端价格时不计算
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
    
    意义：实际不确定性收窄速度
    - ACR > 0: 带宽在收窄（共识在形成）
    - ACR < 0: 带宽在扩大（分歧在加剧）
    - ACR ≈ 0: 带宽稳定
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
    
    意义：市场收敛是否"健康/迟钝/阻塞"
    - CER > 1.0: 收敛比预期快 ✅
    - CER ≈ 0.8-1.0: 正常收敛
    - CER < 0.5: 收敛阻塞 ⚠️
    - CER < 0: 在发散（反向）
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
    """获取所有不确定性指标"""
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
# 3. 信念强度类
# ============================================================================

def calculate_ar(
    aggressive_buy: float,
    aggressive_sell: float,
    total_volume: float
) -> Optional[float]:
    """
    AR (Directional Aggressive Ratio) = |delta| / total_volume
    
    为什么用 Directional AR 而不是传统 AR？
    - 传统 AR = aggressive / total ≈ 1（在预测市场几乎所有成交都是 aggressive）
    - Directional AR = |buy - sell| / total → 衡量方向性强度
    
    解读：
    - 0 = 买卖均衡，无方向（双边拉锯）
    - 1 = 完全单边，强方向（单边推进）
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
    
    意义：方向
    - delta > 0: 买方主导
    - delta < 0: 卖方主导
    - delta ≈ 0: 均衡
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
    
    为什么用 V0 归一化？
    - 原始 log(1+V) 的阈值会随 volume 单位变化而漂移
    - log(1 + V/V0) 使阈值跨市场稳定可比
    - V0 = 1000 意味着 $1000 成交量时 participation ≈ 0.69
    
    解读：
    - CS 低: 要么没方向，要么参与少
    - CS 高: 方向明确 + 足够多人参与 → 真正的 conviction
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
    CS v1 (旧版) = Directional AR
    
    保留供对比，不推荐使用
    """
    return calculate_ar(aggressive_buy, aggressive_sell, total_volume)


def get_direction(
    aggressive_buy: float,
    aggressive_sell: float,
    total_volume: float
) -> str:
    """
    判断方向（用 AR 阈值）
    
    规则：
    - AR > threshold 且 delta > 0 → BULLISH
    - AR > threshold 且 delta < 0 → BEARISH
    - 否则 → NEUTRAL
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
    """获取所有信念强度指标"""
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
# 4. 状态判定
# ============================================================================

def determine_status(
    ui: Optional[float],
    cer: Optional[float],
    cs: Optional[float] = None,
    total_volume: Optional[float] = None,
    edge_zone: bool = False
) -> str:
    """
    判定市场状态
    
    🟢 Informed: 市场已形成稳定共识
       - UI < 0.30 (带宽窄)
       - CER >= 0.80 (收敛健康)
       - 注意：不要求 CS 高！已形成共识的市场可能很"平静"
    
    🔴 Noisy: 市场缺乏稳定认知结构
       - UI >= 0.50 (带宽太宽)
       - 或 CER < 0.40 (收敛阻塞)
       - 或 CS < 0.3 且 volume > 门槛 (有足够成交但没方向)
    
    🟡 Fragmented: 市场理解分裂，存在分歧
       - 其余情况
    
    ⚪ Unknown: 数据不足
    
    🔵 Late-stage: edge_zone=True（接近确定）
    
    设计原则：
    - Informed = 已稳定，不是"正在形成共识"
    - CS 高 = 有人在主动推动，可能是事件驱动或共识形成中
    - 因此 Informed 不要求 CS 高
    - Noisy 判定需要足够成交量，避免误伤冷市场
    """
    # Edge Zone 优先判定（接近确定的市场）
    if edge_zone:
        return "🔵 Late-stage"
    
    if ui is None and cer is None:
        return "⚪ Unknown"
    
    # Noisy 条件（任一满足）
    if ui is not None and ui >= UI_NOISY_THRESHOLD:
        return "🔴 Noisy"
    if cer is not None and cer < CER_NOISY_THRESHOLD:
        return "🔴 Noisy"
    
    # CS 很低 = 没有方向性参与
    # 但必须有足够成交量才判定为 Noisy（防止误伤冷市场）
    if cs is not None and cs < CS_NOISY_THRESHOLD:
        volume_sufficient = (total_volume is None) or (total_volume >= NOISY_MIN_VOLUME)
        if volume_sufficient:
            return "🔴 Noisy"
    
    # Informed 条件（UI + CER 都满足，不看 CS）
    ui_good = (ui is not None and ui < UI_INFORMED_THRESHOLD)
    cer_good = (cer is not None and cer >= CER_INFORMED_THRESHOLD)
    
    if ui_good and cer_good:
        return "🟢 Informed"
    
    return "🟡 Fragmented"


def get_status_explanation(status: str) -> str:
    """获取状态解释"""
    explanations = {
        "🟢 Informed": "市场已形成稳定共识，信念强",
        "🟡 Fragmented": "市场理解分裂，存在分歧",
        "🔴 Noisy": "市场缺乏稳定认知结构",
        "🔵 Late-stage": "市场接近确定，已进入末期",
        "⚪ Unknown": "数据不足，无法判定"
    }
    return explanations.get(status, "未知状态")


def determine_impulse_tag(
    ui: Optional[float],
    cer: Optional[float],
    cs: Optional[float],
    pomd: Optional[float],
    current_price: Optional[float]
) -> Optional[str]:
    """
    判定 Impulse Tag（独立于 status 的提示标签）
    
    ⚡ EMERGING: 共识正在形成
       - UI 高（分歧大）+ CS 高（方向明确）+ CER 不差
       - 这是最强的"早期共识"信号
    
    🔄 ABSORPTION: 关键位置拉锯
       - POMD ≈ current_price（双方在当前价位对抗）
       - CS 中等（有对抗但方向未定）
       - Regime 转换的前夜
    
    💨 EXHAUSTION: 末期动能
       - CS 很高 + UI 很低
       - 看起来"所有人都同意"但结构已给不出新信息
       - 风险警告信号
    
    Returns:
        str or None: "EMERGING" / "ABSORPTION" / "EXHAUSTION" / None
    """
    # EMERGING: 共识正在形成（最强 edge）
    if (ui is not None and ui >= IMPULSE_EMERGING_UI and
        cs is not None and cs >= IMPULSE_EMERGING_CS and
        cer is not None and cer >= IMPULSE_EMERGING_CER):
        return "⚡ EMERGING"
    
    # ABSORPTION: 关键位置拉锯
    if (pomd is not None and current_price is not None and
        cs is not None and 
        IMPULSE_ABSORPTION_CS_MIN <= cs <= IMPULSE_ABSORPTION_CS_MAX):
        if abs(pomd - current_price) < IMPULSE_ABSORPTION_PRICE_EPSILON:
            return "🔄 ABSORPTION"
    
    # EXHAUSTION: 末期动能（风险警告）
    if (cs is not None and cs >= IMPULSE_EXHAUSTION_CS and
        ui is not None and ui < IMPULSE_EXHAUSTION_UI):
        return "💨 EXHAUSTION"
    
    return None


def get_impulse_explanation(impulse_tag: Optional[str]) -> str:
    """获取 impulse tag 解释"""
    if impulse_tag is None:
        return ""
    
    explanations = {
        "⚡ EMERGING": "共识正在形成 - 订单流开始单边，早期参与机会",
        "🔄 ABSORPTION": "关键位置拉锯 - 双方在当前价位对抗，突破即信号",
        "💨 EXHAUSTION": "末期动能警告 - 看似共识但结构已饱和，风险高"
    }
    return explanations.get(impulse_tag, "")


# ============================================================================
# 5. 辅助函数
# ============================================================================

def normalize_timestamp(ts) -> int:
    """
    统一 timestamp 到毫秒
    
    自动适配：
    - 如果 ts < 1e12 → 认为是秒，转成毫秒
    - 如果 ts >= 1e12 → 认为已经是毫秒
    """
    if ts is None:
        return 0
    
    try:
        ts = int(ts)
        if ts < 1e12:
            # 秒 → 毫秒
            return ts * 1000
        else:
            # 已经是毫秒
            return ts
    except (ValueError, TypeError):
        return 0


def filter_trades_by_time(trades: List[Dict], hours: int = 24) -> List[Dict]:
    """
    筛选指定时间内的成交
    
    ⚠️ v5 修复：自动适配 ms/s timestamp
    """
    cutoff = datetime.now() - timedelta(hours=hours)
    cutoff_ms = int(cutoff.timestamp() * 1000)  # 统一用毫秒
    
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
    筛选指定时间范围内的成交
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
# 6. 一站式计算
# ============================================================================

def calculate_all_metrics(
    trades_all: List[Dict],
    trades_24h: List[Dict],
    current_price: float,
    days_remaining: int,
    band_width_7d_ago: Optional[float] = None,
    # WebSocket aggressor 数据
    aggressive_buy: Optional[float] = None,
    aggressive_sell: Optional[float] = None,
    ws_total_volume: Optional[float] = None,
    # WebSocket price bin 数据（用于 POMD）
    aggressor_histogram: Optional[Dict[float, Dict]] = None
) -> Dict:
    """
    一站式计算所有指标
    
    数据分工：
    - Data API trades_all → Histogram → VAH/VAL/POC/UI/CER
    - WebSocket → AR/Delta/CS/POMD
    
    Args:
        trades_all: Data API 交易（用于 profile/VAH/VAL/POC）
        trades_24h: 24h 交易（用于统计）
        current_price: 当前价格
        days_remaining: 剩余天数
        band_width_7d_ago: 7天前带宽（用于 ACR/CER）
        aggressive_buy: 主动买入量（WebSocket）
        aggressive_sell: 主动卖出量（WebSocket）
        ws_total_volume: WebSocket 总量
        aggressor_histogram: {price: {'buy': x, 'sell': y}}（WebSocket，用于 POMD）
    """
    # 计算 histogram（Data API）
    histogram = calculate_histogram(trades_all)
    
    # Profile 相关
    VAH, VAL, mid_prob = calculate_consensus_band(histogram)
    band_width = get_band_width(histogram)
    poc = calculate_poc(histogram)
    tails = calculate_tails(histogram, VAH, VAL)
    rejected = calculate_rejected_probabilities(histogram)  # 旧版兼容
    
    # POMD（需要 aggressor histogram + 动态阈值）
    pomd = None
    if aggressor_histogram:
        # 计算 aggressor histogram 总量用于动态阈值
        ws_vol = sum(
            d.get('buy', 0) + d.get('sell', 0) 
            for d in aggressor_histogram.values()
        )
        pomd = calculate_pomd(aggressor_histogram, total_volume=ws_vol)
    
    # 不确定性相关（使用新的返回格式）
    ui, edge_zone = calculate_ui(histogram)
    ecr = calculate_ecr(current_price, days_remaining)
    acr = calculate_acr(band_width, band_width_7d_ago)
    cer = calculate_cer(band_width, band_width_7d_ago, current_price, days_remaining)
    
    # 信念强度（需要 WebSocket 数据）
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
    
    # 状态判定（包含 volume 门槛和 edge_zone）
    status = determine_status(ui, cer, cs, total_vol, edge_zone)
    
    # Impulse Tag（独立提示标签）
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
        'rejected_probabilities': rejected,  # 旧版兼容
        
        # 不确定性
        'UI': ui,
        'ECR': ecr,
        'ACR': acr,
        'CER': cer,
        'edge_zone': edge_zone,
        
        # 信念强度
        'AR': ar,
        'volume_delta': volume_delta,
        'CS': cs,
        'direction': direction,
        
        # 状态
        'status': status,
        'status_explanation': get_status_explanation(status),
        'impulse_tag': impulse_tag,
        'impulse_explanation': get_impulse_explanation(impulse_tag),
        
        # 元数据
        'total_trades': len(trades_all),
        'trades_24h_count': len(trades_24h),
        'band_width_7d_ago': band_width_7d_ago,
        'has_aggressor_data': aggressive_buy is not None,
        'has_aggressor_histogram': aggressor_histogram is not None,
        'histogram': histogram,  # 用于可视化
    }


# ============================================================================
# 7. 测试
# ============================================================================

if __name__ == "__main__":
    print("🧪 Testing Metrics v5.3\n")
    print("=" * 60)
    
    # === 测试 1: timestamp 统一 ===
    print("\n📍 Test 1: Timestamp Normalization")
    
    # 模拟不同格式的 timestamp
    ts_seconds = 1704067200      # 2024-01-01 00:00:00 (秒)
    ts_millis = 1704067200000    # 2024-01-01 00:00:00 (毫秒)
    
    norm_s = normalize_timestamp(ts_seconds)
    norm_m = normalize_timestamp(ts_millis)
    
    print(f"   Input (seconds): {ts_seconds} → {norm_s}")
    print(f"   Input (millis):  {ts_millis} → {norm_m}")
    print(f"   ✅ Both normalized to same value: {norm_s == norm_m}")
    
    # === 测试 2: CS v2 vs v1 (with V0 normalization) ===
    print("\n📍 Test 2: CS v2 with V0 Normalization")
    
    # 小样本高 AR
    buy_small, sell_small, vol_small = 9, 1, 10
    cs_v1_small = calculate_cs_v1(buy_small, sell_small, vol_small)
    cs_v2_small = calculate_cs(buy_small, sell_small, vol_small)
    
    print(f"   Small sample ($10, AR=0.8):")
    print(f"     CS v1: {cs_v1_small:.3f}")
    print(f"     CS v2: {cs_v2_small:.4f} (V0={CS_VOLUME_BASELINE})")
    
    # 中样本
    buy_med, sell_med, vol_med = 900, 100, 1000
    cs_v1_med = calculate_cs_v1(buy_med, sell_med, vol_med)
    cs_v2_med = calculate_cs(buy_med, sell_med, vol_med)
    
    print(f"   Medium sample ($1000, AR=0.8):")
    print(f"     CS v1: {cs_v1_med:.3f}")
    print(f"     CS v2: {cs_v2_med:.4f}")
    
    # 大样本相同 AR
    buy_large, sell_large, vol_large = 9000, 1000, 10000
    cs_v1_large = calculate_cs_v1(buy_large, sell_large, vol_large)
    cs_v2_large = calculate_cs(buy_large, sell_large, vol_large)
    
    print(f"   Large sample ($10000, AR=0.8):")
    print(f"     CS v1: {cs_v1_large:.3f}")
    print(f"     CS v2: {cs_v2_large:.4f}")
    
    print(f"   ✅ CS v2 with V0 normalization: threshold stable across markets")
    
    # === 测试 3: Direction 判断 ===
    print("\n📍 Test 3: Direction (using AR threshold)")
    
    # BULLISH: AR > 0.1, delta > 0
    dir_bull = get_direction(60, 40, 100)
    print(f"   Buy=60, Sell=40, Total=100 → {dir_bull}")
    
    # BEARISH: AR > 0.1, delta < 0
    dir_bear = get_direction(40, 60, 100)
    print(f"   Buy=40, Sell=60, Total=100 → {dir_bear}")
    
    # NEUTRAL: AR < 0.1
    dir_neut = get_direction(52, 48, 100)
    print(f"   Buy=52, Sell=48, Total=100 → {dir_neut}")
    
    # === 测试 4: Consensus Band (围绕 POC 连续扩展) ===
    print("\n📍 Test 4: Consensus Band (POC-centered continuous expansion)")
    
    # 模拟一个有 tail 的市场
    test_trades_full = [
        {'price': 0.58, 'size': 10},   # Lower tail
        {'price': 0.59, 'size': 15},   # Lower tail
        {'price': 0.60, 'size': 50},   # VAL 附近
        {'price': 0.61, 'size': 80},   
        {'price': 0.62, 'size': 120},  
        {'price': 0.63, 'size': 180},  
        {'price': 0.64, 'size': 250},  # POC
        {'price': 0.65, 'size': 200},  
        {'price': 0.66, 'size': 150},  
        {'price': 0.67, 'size': 100},  # VAH 附近
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
    print(f"   ✅ Value Area is continuous around POC")
    
    # === 测试 5: POC vs POMD ===
    print("\n📍 Test 5: POC vs POMD")
    
    test_trades = [
        {'price': 0.64, 'size': 120},
        {'price': 0.65, 'size': 200},  # 最大成交 → POC
        {'price': 0.66, 'size': 150},
    ]
    
    aggressor_histogram = {
        0.64: {'buy': 55, 'sell': 65},   # min_side = 55 ← 双边最均衡！
        0.65: {'buy': 180, 'sell': 20},  # min_side = 20（单边推进）
        0.66: {'buy': 100, 'sell': 50},  # min_side = 50
    }
    
    histogram = calculate_histogram(test_trades)
    poc = calculate_poc(histogram)
    pomd = calculate_pomd(aggressor_histogram)
    
    print(f"   POC (最大成交): {poc}")
    print(f"   POMD (最大争议): {pomd}")
    print(f"   ✅ POC ≠ POMD: 最大成交点不是最大争议点")
    
    # === 测试 6: 状态判定 (v5.3: 包含 volume 门槛和 edge_zone) ===
    print("\n📍 Test 6: Status Determination (v5.3)")
    
    # Informed: UI 低 + CER 高，不管 CS
    status1 = determine_status(ui=0.2, cer=0.9, cs=0.5)
    print(f"   UI=0.2, CER=0.9, CS=0.5 → {status1}")
    
    # Informed: 没有 CS 数据也能判定
    status2 = determine_status(ui=0.2, cer=0.9, cs=None)
    print(f"   UI=0.2, CER=0.9, CS=None → {status2}")
    
    # Noisy (high UI)
    status3 = determine_status(ui=0.6, cer=0.9, cs=1.0)
    print(f"   UI=0.6, CER=0.9, CS=1.0 → {status3}")
    
    # Noisy (low CS + sufficient volume)
    status4 = determine_status(ui=0.3, cer=0.5, cs=0.1, total_volume=500)
    print(f"   UI=0.3, CER=0.5, CS=0.1, vol=500 → {status4}")
    
    # NOT Noisy (low CS but cold market - volume too low)
    status4b = determine_status(ui=0.3, cer=0.5, cs=0.1, total_volume=50)
    print(f"   UI=0.3, CER=0.5, CS=0.1, vol=50 → {status4b} (cold market protected)")
    
    # Late-stage (edge_zone)
    status5 = determine_status(ui=None, cer=0.9, cs=0.5, edge_zone=True)
    print(f"   edge_zone=True → {status5}")
    
    # Fragmented
    status6 = determine_status(ui=0.35, cer=0.6, cs=0.8)
    print(f"   UI=0.35, CER=0.6, CS=0.8 → {status6}")
    
    # === 测试 7: Impulse Tag ===
    print("\n📍 Test 7: Impulse Tag (v5.3)")
    
    # EMERGING: 高 UI + 高 CS + OK CER
    impulse1 = determine_impulse_tag(ui=0.4, cer=0.6, cs=0.5, pomd=None, current_price=0.65)
    print(f"   UI=0.4, CS=0.5, CER=0.6 → {impulse1}")
    
    # ABSORPTION: POMD ≈ price + 中等 CS
    impulse2 = determine_impulse_tag(ui=0.35, cer=0.5, cs=0.35, pomd=0.65, current_price=0.66)
    print(f"   POMD≈price, CS=0.35 → {impulse2}")
    
    # EXHAUSTION: 高 CS + 低 UI
    impulse3 = determine_impulse_tag(ui=0.15, cer=0.9, cs=0.8, pomd=None, current_price=0.85)
    print(f"   UI=0.15, CS=0.8 → {impulse3}")
    
    # None: 不满足任何条件
    impulse4 = determine_impulse_tag(ui=0.3, cer=0.5, cs=0.4, pomd=None, current_price=0.65)
    print(f"   UI=0.3, CS=0.4 → {impulse4}")
    
    # === 测试 8: UI with edge_zone ===
    print("\n📍 Test 8: UI with edge_zone flag")
    
    # 正常市场
    test_normal = [{'price': 0.5, 'size': 100}, {'price': 0.55, 'size': 100}]
    ui_norm, edge_norm = calculate_ui(calculate_histogram(test_normal))
    ui_str = f"{ui_norm:.3f}" if ui_norm is not None else "None"
    print(f"   Normal market (50%): UI={ui_str}, edge_zone={edge_norm}")
    
    # 极端市场（接近确定）
    test_edge = [{'price': 0.92, 'size': 100}, {'price': 0.95, 'size': 100}]
    ui_edge, edge_flag = calculate_ui(calculate_histogram(test_edge))
    print(f"   Edge market (95%): UI={ui_edge}, edge_zone={edge_flag}")
    
    print("\n" + "=" * 60)
    print("✅ All v5.3 tests completed!")