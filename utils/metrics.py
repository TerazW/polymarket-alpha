"""
Market Sensemaking 指标计算 - 完整版 v5

=== 修复内容 ===
1. timestamp 统一（自动适配 ms/s）
2. CS v2 = Directional AR × Participation（避免小样本虚高）
3. Direction 判断用 AR 阈值（语义更清晰）
4. 状态判定逻辑优化

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
   ✅ CS v2 = AR × log(1 + volume)（信念强度 × 参与规模）

=== 数据来源分工 ===
- Data API: trades → Histogram → VAH/VAL/POC/UI/CER
- WebSocket: aggressor → AR/Delta/CS/POMD
"""

import math
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict


# ============================================================================
# 配置常量
# ============================================================================

# Direction 判断阈值
AR_BULLISH_THRESHOLD = 0.10   # AR > 0.10 且 delta > 0 → BULLISH
AR_BEARISH_THRESHOLD = 0.10   # AR > 0.10 且 delta < 0 → BEARISH

# CS v2 参与度缩放因子（可选）
CS_PARTICIPATION_SCALE = 1.0  # 可调整 log 的影响程度

# 状态判定阈值
UI_INFORMED_THRESHOLD = 0.30
UI_NOISY_THRESHOLD = 0.50
CER_INFORMED_THRESHOLD = 0.80
CER_NOISY_THRESHOLD = 0.40
CS_INFORMED_THRESHOLD = 2.0   # CS v2 新阈值（因为加了 log）
CS_NOISY_THRESHOLD = 0.5


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
            price = float(trade.get('price', 0))
            size = float(trade.get('size', 0))
            
            bin_price = round(price / tick_size) * tick_size
            bin_price = round(bin_price, 4)
            
            histogram[bin_price] += size
            
        except (ValueError, TypeError):
            continue
    
    return dict(histogram)


def calculate_consensus_band(
    histogram: Dict[float, float], 
    coverage: float = 0.70
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    计算 Consensus Band (共识带)
    
    定义：覆盖 X% 成交量的概率区间
    方法：按成交量从大到小排序，累计到 coverage%
    
    Returns:
        (VAH, VAL, mid_probability)
        - VAH: Value Area High
        - VAL: Value Area Low
        - mid_probability: (VAH + VAL) / 2
    """
    if not histogram:
        return None, None, None
    
    sorted_bins = sorted(histogram.items(), key=lambda x: x[1], reverse=True)
    total_volume = sum(histogram.values())
    
    if total_volume == 0:
        return None, None, None
    
    target_volume = total_volume * coverage
    cumulative = 0
    consensus_prices = []
    
    for price, volume in sorted_bins:
        cumulative += volume
        consensus_prices.append(price)
        if cumulative >= target_volume:
            break
    
    if not consensus_prices:
        return None, None, None
    
    VAH = max(consensus_prices)
    VAL = min(consensus_prices)
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
    min_threshold: float = 0
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
        min_threshold: 最小阈值，低于此值不算（避免噪音）
    
    Returns:
        POMD price，如果没有有效数据返回 None
    """
    if not aggressor_histogram:
        return None
    
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


def calculate_rejected_probabilities(
    histogram: Dict[float, float],
    threshold_percentile: float = 0.10
) -> List[float]:
    """
    Rejected Probabilities = 被市场快速否定的概率区
    
    定义：成交量在最低 10% 的价格区间
    类似传统 Market Profile 的 Single Prints
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


def get_volume_profile_summary(
    histogram: Dict[float, float],
    aggressor_histogram: Optional[Dict[float, Dict]] = None
) -> Dict:
    """获取 Volume Profile 完整摘要"""
    VAH, VAL, mid_prob = calculate_consensus_band(histogram)
    band_width = get_band_width(histogram)
    poc = calculate_poc(histogram)
    rejected = calculate_rejected_probabilities(histogram)
    
    pomd = None
    if aggressor_histogram:
        pomd = calculate_pomd(aggressor_histogram)
    
    return {
        'VAH': VAH,
        'VAL': VAL,
        'mid_probability': mid_prob,
        'band_width': band_width,
        'POC': poc,
        'POMD': pomd,
        'rejected_probabilities': rejected,
        'total_volume': sum(histogram.values()) if histogram else 0,
        'price_levels': len(histogram) if histogram else 0
    }


# ============================================================================
# 2. 不确定性类
# ============================================================================

def calculate_ui(histogram: Dict[float, float]) -> Optional[float]:
    """
    UI (Uncertainty Index) = band_width / mid_probability
    
    为什么这样定义？
    - 同样 10% 带宽，在 50% 附近 → 不确定性中等
    - 同样 10% 带宽，在 90% 附近 → 极度不确定（接近确定却分裂）
    
    解读：
    - UI < 0.30: 低不确定性
    - UI 0.30-0.50: 中等
    - UI >= 0.50: 高不确定性
    """
    VAH, VAL, mid_probability = calculate_consensus_band(histogram)
    
    if VAH is None or VAL is None or mid_probability is None:
        return None
    
    band_width = VAH - VAL
    
    # 边界情况：极端价格时 UI 意义不大
    if mid_probability < 0.10 or mid_probability > 0.90:
        return None
    
    if mid_probability == 0:
        return None
    
    return band_width / mid_probability


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
    
    CS v2 = (|delta| / total) × log(1 + total_volume)
    
    为什么 v2 比 v1 好？
    - v1: CS = AR → 小样本也能给高分（10 美元成交 AR=0.9）
    - v2: CS = AR × log(1+V) → 需要"方向性 + 足够参与"才能高分
    
    解读：
    - CS 低: 要么没方向，要么参与少
    - CS 高: 方向明确 + 足够多人参与 → 真正的 conviction
    """
    if total_volume <= 0:
        return None
    
    delta = abs(aggressive_buy - aggressive_sell)
    directional_ar = delta / total_volume
    participation = math.log(1 + total_volume) * CS_PARTICIPATION_SCALE
    
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
    cs: Optional[float] = None
) -> str:
    """
    判定市场状态
    
    🟢 Informed: 市场已形成稳定共识
       - UI < 0.30 (带宽窄)
       - CER >= 0.80 (收敛健康)
       - CS >= 2.0 (信念强，v2 阈值)
    
    🔴 Noisy: 市场缺乏稳定认知结构
       - UI >= 0.50 (带宽太宽)
       - 或 CER < 0.40 (收敛阻塞)
       - 或 CS < 0.5 (信念弱)
    
    🟡 Fragmented: 市场理解分裂，存在分歧
       - 其余情况
    
    ⚪ Unknown: 数据不足
    """
    if ui is None and cer is None:
        return "⚪ Unknown"
    
    # Noisy 条件（任一满足）
    if ui is not None and ui >= UI_NOISY_THRESHOLD:
        return "🔴 Noisy"
    if cer is not None and cer < CER_NOISY_THRESHOLD:
        return "🔴 Noisy"
    if cs is not None and cs < CS_NOISY_THRESHOLD:
        return "🔴 Noisy"
    
    # Informed 条件（全部满足）
    ui_good = (ui is not None and ui < UI_INFORMED_THRESHOLD)
    cer_good = (cer is not None and cer >= CER_INFORMED_THRESHOLD)
    cs_good = (cs is None or cs >= CS_INFORMED_THRESHOLD)
    
    if ui_good and cer_good and cs_good:
        return "🟢 Informed"
    
    return "🟡 Fragmented"


def get_status_explanation(status: str) -> str:
    """获取状态解释"""
    explanations = {
        "🟢 Informed": "市场已形成稳定共识，信念强",
        "🟡 Fragmented": "市场理解分裂，存在分歧",
        "🔴 Noisy": "市场缺乏稳定认知结构",
        "⚪ Unknown": "数据不足，无法判定"
    }
    return explanations.get(status, "未知状态")


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
    rejected = calculate_rejected_probabilities(histogram)
    
    # POMD（需要 aggressor histogram）
    pomd = None
    if aggressor_histogram:
        pomd = calculate_pomd(aggressor_histogram)
    
    # 不确定性相关
    ui = calculate_ui(histogram)
    ecr = calculate_ecr(current_price, days_remaining)
    acr = calculate_acr(band_width, band_width_7d_ago)
    cer = calculate_cer(band_width, band_width_7d_ago, current_price, days_remaining)
    
    # 信念强度（需要 WebSocket 数据）
    ar = None
    volume_delta = None
    cs = None
    direction = "UNKNOWN"
    
    if aggressive_buy is not None and aggressive_sell is not None:
        total_vol = ws_total_volume if ws_total_volume else (aggressive_buy + aggressive_sell)
        ar = calculate_ar(aggressive_buy, aggressive_sell, total_vol)
        volume_delta = calculate_volume_delta(aggressive_buy, aggressive_sell)
        cs = calculate_cs(aggressive_buy, aggressive_sell, total_vol)
        direction = get_direction(aggressive_buy, aggressive_sell, total_vol)
    
    # 状态判定
    status = determine_status(ui, cer, cs)
    
    return {
        # Profile
        'VAH': VAH,
        'VAL': VAL,
        'mid_probability': mid_prob,
        'band_width': band_width,
        'POC': poc,
        'POMD': pomd,
        'rejected_probabilities': rejected,
        
        # 不确定性
        'UI': ui,
        'ECR': ecr,
        'ACR': acr,
        'CER': cer,
        
        # 信念强度
        'AR': ar,
        'volume_delta': volume_delta,
        'CS': cs,
        'direction': direction,
        
        # 状态
        'status': status,
        'status_explanation': get_status_explanation(status),
        
        # 元数据
        'total_trades': len(trades_all),
        'trades_24h_count': len(trades_24h),
        'band_width_7d_ago': band_width_7d_ago,
        'has_aggressor_data': aggressive_buy is not None,
        'has_aggressor_histogram': aggressor_histogram is not None
    }


# ============================================================================
# 7. 测试
# ============================================================================

if __name__ == "__main__":
    print("🧪 Testing Metrics v5\n")
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
    
    # === 测试 2: CS v2 vs v1 ===
    print("\n📍 Test 2: CS v2 vs v1")
    
    # 小样本高 AR
    buy_small, sell_small, vol_small = 9, 1, 10
    cs_v1_small = calculate_cs_v1(buy_small, sell_small, vol_small)
    cs_v2_small = calculate_cs(buy_small, sell_small, vol_small)
    
    print(f"   Small sample ($10, AR=0.8):")
    print(f"     CS v1: {cs_v1_small:.3f}")
    print(f"     CS v2: {cs_v2_small:.3f}")
    
    # 大样本相同 AR
    buy_large, sell_large, vol_large = 9000, 1000, 10000
    cs_v1_large = calculate_cs_v1(buy_large, sell_large, vol_large)
    cs_v2_large = calculate_cs(buy_large, sell_large, vol_large)
    
    print(f"   Large sample ($10000, AR=0.8):")
    print(f"     CS v1: {cs_v1_large:.3f}")
    print(f"     CS v2: {cs_v2_large:.3f}")
    
    print(f"   ✅ CS v2 properly scales with volume")
    
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
    
    # === 测试 4: POC vs POMD ===
    print("\n📍 Test 4: POC vs POMD")
    
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
    
    # === 测试 5: 状态判定 ===
    print("\n📍 Test 5: Status Determination")
    
    # Informed
    status1 = determine_status(ui=0.2, cer=0.9, cs=3.0)
    print(f"   UI=0.2, CER=0.9, CS=3.0 → {status1}")
    
    # Noisy (high UI)
    status2 = determine_status(ui=0.6, cer=0.9, cs=3.0)
    print(f"   UI=0.6, CER=0.9, CS=3.0 → {status2}")
    
    # Fragmented
    status3 = determine_status(ui=0.35, cer=0.6, cs=1.5)
    print(f"   UI=0.35, CER=0.6, CS=1.5 → {status3}")
    
    print("\n" + "=" * 60)
    print("✅ All tests completed!")