"""
Market Sensemaking 指标计算 - 完整版 v4
路线 B：WebSocket + Data API 版本

新功能：
- POC = 交易集中点（成交量最大）
- POMD = 拉锯最激烈点（min(buy, sell) 最大）
- AR = Directional AR = |delta| / total

=== 可用指标 ===

1. 共识带和 Profile 相关
   ✅ Consensus Band (VAH/VAL)
   ✅ Band Width
   ✅ POC - Point of Control（交易集中点）
   ✅ POMD - Point of Max Disagreement（拉锯点）
   ✅ Rejected Probabilities

2. 不确定性类
   ✅ UI - Uncertainty Index
   ✅ ECR - Expected Convergence Rate
   ✅ ACR - Actual Convergence Rate
   ✅ CER - Convergence Efficiency Ratio

3. 信念强度类
   ✅ AR (Directional) - 方向性强度
   ✅ Volume Delta
   ✅ CS - Conviction Score
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict


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
    
    Returns:
        (VAH, VAL, mid_probability)
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
    """计算 Band Width"""
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
    
    Args:
        aggressor_histogram: {price: {'buy': x, 'sell': y, ...}}
        min_threshold: 最小阈值，低于此值不算（避免噪音）
    
    Returns:
        POMD price，如果没有有效数据返回 None
    """
    if not aggressor_histogram:
        return None
    
    # 计算每个 price bin 的 min_side
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


def calculate_pomd_by_fight_score(
    aggressor_histogram: Dict[float, Dict]
) -> Optional[float]:
    """
    POMD (方案 A) = FightScore 最大的 price bin
    
    FightScore = volume × (1 - |delta|/volume)
    
    量大 + delta接近0 = 争议最大
    """
    if not aggressor_histogram:
        return None
    
    def fight_score(data):
        buy = data.get('buy', 0)
        sell = data.get('sell', 0)
        total = buy + sell
        if total <= 0:
            return 0
        delta = abs(buy - sell)
        balance = 1 - delta / (total + 1e-10)
        return total * balance
    
    return max(
        aggressor_histogram.keys(),
        key=lambda p: fight_score(aggressor_histogram[p])
    )


def calculate_rejected_probabilities(
    histogram: Dict[float, float],
    threshold_percentile: float = 0.10
) -> List[float]:
    """计算 Rejected Probabilities"""
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
    
    # POMD 需要 aggressor 数据
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
    """UI = band_width / mid_probability"""
    VAH, VAL, mid_probability = calculate_consensus_band(histogram)
    
    if VAH is None or VAL is None or mid_probability is None:
        return None
    
    band_width = VAH - VAL
    
    if mid_probability < 0.10 or mid_probability > 0.90:
        return None
    
    if mid_probability == 0:
        return None
    
    return band_width / mid_probability


def calculate_ecr(current_price: float, days_remaining: int) -> Optional[float]:
    """ECR = distance_to_certainty / days_remaining"""
    if days_remaining < 1:
        return None
    
    if current_price > 0.95 or current_price < 0.05:
        return None
    
    distance_to_certainty = min(current_price, 1 - current_price)
    return distance_to_certainty / days_remaining


def calculate_acr(
    band_width_now: Optional[float],
    band_width_7d_ago: Optional[float],
    days: int = 7
) -> Optional[float]:
    """ACR = (band_width_7d_ago - band_width_now) / days"""
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
    """CER = ACR / ECR"""
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
    Directional AR = |delta| / total_volume
    
    意义：方向性强度
    - 0 = 买卖均衡，无方向
    - 1 = 完全单边，强方向
    """
    if total_volume <= 0:
        return None
    
    delta = abs(aggressive_buy - aggressive_sell)
    return min(delta / total_volume, 1.0)


def calculate_volume_delta(
    aggressive_buy: float,
    aggressive_sell: float
) -> Optional[float]:
    """Volume Delta = buy - sell"""
    return aggressive_buy - aggressive_sell


def calculate_cs(
    aggressive_buy: float,
    aggressive_sell: float,
    total_volume: float
) -> Optional[float]:
    """CS = Directional AR（统一定义）"""
    return calculate_ar(aggressive_buy, aggressive_sell, total_volume)


def get_conviction_metrics(
    aggressive_buy: float,
    aggressive_sell: float,
    total_volume: float
) -> Dict:
    """获取所有信念强度指标"""
    delta = calculate_volume_delta(aggressive_buy, aggressive_sell)
    ar = calculate_ar(aggressive_buy, aggressive_sell, total_volume)
    
    if delta is not None:
        if delta > total_volume * 0.1:
            direction = "BULLISH"
        elif delta < -total_volume * 0.1:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"
    else:
        direction = "UNKNOWN"
    
    return {
        'AR': ar,
        'volume_delta': delta,
        'CS': ar,
        'aggressive_buy': aggressive_buy,
        'aggressive_sell': aggressive_sell,
        'total_volume': total_volume,
        'direction': direction
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
    
    - 🟢 Informed: UI < 0.30 AND CER >= 0.8 AND CS >= 0.35
    - 🔴 Noisy: UI >= 0.50 OR CER < 0.4 OR CS < 0.15
    - 🟡 Fragmented: 其余
    - ⚪ Unknown: 数据不足
    """
    if ui is None and cer is None:
        return "⚪ Unknown"
    
    if (ui is not None and ui >= 0.50):
        return "🔴 Noisy"
    if (cer is not None and cer < 0.4):
        return "🔴 Noisy"
    if (cs is not None and cs < 0.15):
        return "🔴 Noisy"
    
    ui_good = (ui is not None and ui < 0.30)
    cer_good = (cer is not None and cer >= 0.8)
    cs_good = (cs is None or cs >= 0.35)
    
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

def filter_trades_by_time(trades: List[Dict], hours: int = 24) -> List[Dict]:
    """筛选指定时间内的成交"""
    cutoff = datetime.now() - timedelta(hours=hours)
    cutoff_ts = int(cutoff.timestamp())
    return [t for t in trades if t.get('timestamp', 0) >= cutoff_ts]


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
    
    Args:
        trades_all: Data API 交易（用于 profile/VAH/VAL/POC）
        trades_24h: 24h 交易
        current_price: 当前价格
        days_remaining: 剩余天数
        band_width_7d_ago: 7天前带宽
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
    
    # 信念强度
    if aggressive_buy is not None and aggressive_sell is not None:
        total_vol = ws_total_volume if ws_total_volume else (aggressive_buy + aggressive_sell)
        ar = calculate_ar(aggressive_buy, aggressive_sell, total_vol)
        volume_delta = calculate_volume_delta(aggressive_buy, aggressive_sell)
        cs = calculate_cs(aggressive_buy, aggressive_sell, total_vol)
    else:
        ar = None
        volume_delta = None
        cs = None
    
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
# 6. 测试
# ============================================================================

if __name__ == "__main__":
    print("🧪 Testing Metrics v4 (POC + POMD)\n")
    print("=" * 60)
    
    # 模拟 Data API trades
    test_trades = [
        {'price': 0.62, 'size': 50},
        {'price': 0.63, 'size': 80},
        {'price': 0.64, 'size': 120},
        {'price': 0.65, 'size': 200},  # 最大成交 → POC
        {'price': 0.66, 'size': 150},
        {'price': 0.67, 'size': 90},
        {'price': 0.68, 'size': 60},
    ]
    
    # 模拟 WebSocket aggressor histogram
    # 0.65 虽然成交量大，但单边（buy >> sell）
    # 0.64 成交量小一些，但双边均衡（争议大）
    aggressor_histogram = {
        0.62: {'buy': 40, 'sell': 10},   # min_side = 10
        0.63: {'buy': 60, 'sell': 20},   # min_side = 20
        0.64: {'buy': 55, 'sell': 65},   # min_side = 55 ← 双边最均衡！
        0.65: {'buy': 180, 'sell': 20},  # min_side = 20（单边推进）
        0.66: {'buy': 100, 'sell': 50},  # min_side = 50
        0.67: {'buy': 30, 'sell': 60},   # min_side = 30
        0.68: {'buy': 20, 'sell': 40},   # min_side = 20
    }
    
    histogram = calculate_histogram(test_trades)
    poc = calculate_poc(histogram)
    pomd = calculate_pomd(aggressor_histogram)
    
    print("📊 Test Data:")
    print(f"   Total Volume Profile: 7 price bins")
    print(f"   Aggressor Histogram: 7 price bins with buy/sell")
    
    print(f"\n📈 Results:")
    print(f"   POC (交易集中点): {poc}")
    print(f"   POMD (拉锯点):    {pomd}")
    
    print(f"\n✅ Expected:")
    print(f"   POC = 0.65 (成交量最大)")
    print(f"   POMD = 0.64 (min(buy,sell) = 55 最大)")
    
    print(f"\n📖 解读:")
    print(f"   POC 0.65: 大家都在这里成交（流动性中心）")
    print(f"   POMD 0.64: 大家在这里吵得最凶（双边拉锯）")
    
    if poc != pomd:
        print(f"\n   ⚠️ POC ≠ POMD: 说明最大成交点不是最大争议点！")
        print(f"      0.65 成交量大但是单边推进（buy=180, sell=20）")
        print(f"      0.64 成交量小但双方势均力敌（buy=55, sell=65）")
    
    print("\n" + "=" * 60)
    print("✅ Tests completed!")