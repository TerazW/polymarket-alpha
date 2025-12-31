"""
Market Sensemaking 指标计算 - 完整版 v3
路线 B：WebSocket + Data API 版本（带 aggressor）

优化：
- AR 改成 Directional AR = |delta| / total_volume
- AR 和 CS 语义统一（CS = AR，避免重复）
- 更清晰的指标定义

=== 可用指标 ===

1. 共识带和 Profile 相关
   ✅ Consensus Band (VAH/VAL) - 覆盖70%成交量的概率区间
   ✅ Band Width - 带宽 (VAH - VAL)
   ✅ POMD - 最大分歧点
   ✅ Rejected Probabilities - 被否定概率区

2. 不确定性类
   ✅ UI - Uncertainty Index
   ✅ ECR - Expected Convergence Rate
   ✅ ACR - Actual Convergence Rate
   ✅ CER - Convergence Efficiency Ratio

3. 信念强度类 - ✅ UNLOCKED
   ✅ AR (Directional) - 方向性强度 |delta| / total
   ✅ Volume Delta - 主动买卖差额
   ✅ CS - Conviction Score (= AR，统一定义)
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict


# ============================================================================
# 1. 共识带和 Profile 相关
# ============================================================================

def calculate_histogram(trades: List[Dict], tick_size: float = 0.01) -> Dict[float, float]:
    """
    将成交数据转换为价格直方图 (Volume-at-Price Profile)
    
    Args:
        trades: 交易列表，每个交易需要有 'price' 和 'size' 字段
        tick_size: 价格分箱大小（默认 0.01 = 1%）
    
    Returns:
        {price_level: total_volume} 字典
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
    
    定义：覆盖 X% 成交量权重的概率区间
    
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
    """计算 Band Width (带宽)"""
    VAH, VAL, _ = calculate_consensus_band(histogram, coverage)
    
    if VAH is None or VAL is None:
        return None
    
    return VAH - VAL


def calculate_pomd(histogram: Dict[float, float]) -> Optional[float]:
    """计算 POMD (Point of Max Disagreement)"""
    if not histogram:
        return None
    
    pomd = max(histogram.items(), key=lambda x: x[1])[0]
    return pomd


def calculate_rejected_probabilities(
    histogram: Dict[float, float],
    threshold_percentile: float = 0.10
) -> List[float]:
    """计算 Rejected Probabilities (被否定概率区)"""
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


def get_volume_profile_summary(histogram: Dict[float, float]) -> Dict:
    """获取 Volume Profile 的完整摘要"""
    VAH, VAL, mid_prob = calculate_consensus_band(histogram)
    band_width = get_band_width(histogram)
    pomd = calculate_pomd(histogram)
    rejected = calculate_rejected_probabilities(histogram)
    
    return {
        'VAH': VAH,
        'VAL': VAL,
        'mid_probability': mid_prob,
        'band_width': band_width,
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
    计算 UI (Uncertainty Index)
    
    定义：UI = band_width / mid_probability
    """
    VAH, VAL, mid_probability = calculate_consensus_band(histogram)
    
    if VAH is None or VAL is None or mid_probability is None:
        return None
    
    band_width = VAH - VAL
    
    if mid_probability < 0.10 or mid_probability > 0.90:
        return None
    
    if mid_probability == 0:
        return None
    
    return band_width / mid_probability


def calculate_ecr(
    current_price: float,
    days_remaining: int
) -> Optional[float]:
    """
    计算 ECR (Expected Convergence Rate)
    
    定义：ECR = distance_to_certainty / days_remaining
    """
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
    """
    计算 ACR (Actual Convergence Rate)
    
    定义：ACR = (band_width_7d_ago - band_width_now) / days
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
    计算 CER (Convergence Efficiency Ratio)
    
    定义：CER = ACR / ECR
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
    """获取所有不确定性指标的摘要"""
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
# 3. 信念强度类 - ✅ UNLOCKED (WebSocket 提供 aggressor 数据)
# ============================================================================

def calculate_ar(
    aggressive_buy: float,
    aggressive_sell: float,
    total_volume: float
) -> Optional[float]:
    """
    ✅ Directional AR (方向性 Aggressive Ratio)
    
    定义：AR = |delta| / total_volume
    
    意义：
    - 0 = 买卖完全对冲，无方向性
    - 1 = 完全单边，强方向性
    
    注意：这和传统的 AR（主动成交占比）不同！
    传统 AR 在预测市场恒等于 1（所有成交都是 taker 触发）。
    我们用 Directional AR 来表示"方向性强度"，更有信息量。
    
    Args:
        aggressive_buy: 主动买入量
        aggressive_sell: 主动卖出量
        total_volume: 总成交量
    
    Returns:
        AR 值（0-1）
    """
    if total_volume <= 0:
        return None
    
    delta = abs(aggressive_buy - aggressive_sell)
    ar = delta / total_volume
    
    return min(ar, 1.0)


def calculate_volume_delta(
    aggressive_buy: float,
    aggressive_sell: float
) -> Optional[float]:
    """
    ✅ Volume Delta
    
    定义：Delta = aggressive_buy - aggressive_sell
    
    意义：
    - Delta > 0 → 主动买入占优（看涨压力）
    - Delta < 0 → 主动卖出占优（看跌压力）
    - |Delta| 大 → 单边力量强
    
    Args:
        aggressive_buy: 主动买入量
        aggressive_sell: 主动卖出量
    
    Returns:
        Volume Delta（可正可负）
    """
    return aggressive_buy - aggressive_sell


def calculate_cs(
    aggressive_buy: float,
    aggressive_sell: float,
    total_volume: float
) -> Optional[float]:
    """
    ✅ CS (Conviction Score) = Directional AR
    
    定义：CS = |delta| / total_volume
    
    注意：CS 和 Directional AR 是同一个值！
    保留 CS 是为了语义清晰：
    - AR 强调"方向性"（order flow 视角）
    - CS 强调"信念强度"（market microstructure 视角）
    
    解读：
    - CS > 0.5 → 强单边信念（一边倒）
    - CS 0.2-0.5 → 中等信念（有方向偏好）
    - CS < 0.2 → 弱信念（买卖均衡，犹豫不决）
    
    Args:
        aggressive_buy: 主动买入量
        aggressive_sell: 主动卖出量
        total_volume: 总成交量
    
    Returns:
        CS 值（0-1）
    """
    # CS = AR（统一定义）
    return calculate_ar(aggressive_buy, aggressive_sell, total_volume)


def get_conviction_metrics(
    aggressive_buy: float,
    aggressive_sell: float,
    total_volume: float
) -> Dict:
    """
    获取所有信念强度指标
    
    Args:
        aggressive_buy: 主动买入量（来自 WebSocket）
        aggressive_sell: 主动卖出量（来自 WebSocket）
        total_volume: 总成交量
    
    Returns:
        包含 AR, Volume Delta, CS, direction 的字典
    """
    delta = calculate_volume_delta(aggressive_buy, aggressive_sell)
    ar = calculate_ar(aggressive_buy, aggressive_sell, total_volume)
    
    # 方向判定
    if delta is not None:
        if delta > total_volume * 0.1:  # delta > 10% of volume
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
        'CS': ar,  # CS = AR
        'aggressive_buy': aggressive_buy,
        'aggressive_sell': aggressive_sell,
        'total_volume': total_volume,
        'direction': direction
    }


# ============================================================================
# 4. 状态判定 - 使用 CS
# ============================================================================

def determine_status(
    ui: Optional[float],
    cer: Optional[float],
    cs: Optional[float] = None
) -> str:
    """
    判定市场状态
    
    分类逻辑：
    - 🟢 Informed: 低不确定性 + 健康收敛 + 强信念
      - UI < 0.30 AND CER >= 0.8 AND (CS >= 0.35 OR CS is None)
    
    - 🔴 Noisy: 高不确定性 或 收敛阻塞 或 极弱信念
      - UI >= 0.50 OR CER < 0.4 OR CS < 0.15
    
    - 🟡 Fragmented: 其余情况
    
    - ⚪ Unknown: 数据不足
    """
    # 数据不足
    if ui is None and cer is None:
        return "⚪ Unknown"
    
    # 🔴 Noisy（任一指标很差）
    if (ui is not None and ui >= 0.50):
        return "🔴 Noisy"
    if (cer is not None and cer < 0.4):
        return "🔴 Noisy"
    if (cs is not None and cs < 0.15):
        return "🔴 Noisy"
    
    # 🟢 Informed（所有可用指标都好）
    ui_good = (ui is not None and ui < 0.30)
    cer_good = (cer is not None and cer >= 0.8)
    cs_good = (cs is None or cs >= 0.35)
    
    if ui_good and cer_good and cs_good:
        return "🟢 Informed"
    
    # 🟡 Fragmented
    return "🟡 Fragmented"


def get_status_explanation(status: str) -> str:
    """获取状态的中文解释"""
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
    # WebSocket aggressor 数据（可选）
    aggressive_buy: Optional[float] = None,
    aggressive_sell: Optional[float] = None,
    ws_total_volume: Optional[float] = None
) -> Dict:
    """
    一站式计算所有指标
    
    Args:
        trades_all: 所有交易（用于 profile，来自 Data API）
        trades_24h: 24h 交易
        current_price: 当前价格 (0-1)
        days_remaining: 剩余天数
        band_width_7d_ago: 7天前的 band width
        aggressive_buy: 主动买入量（来自 WebSocket）
        aggressive_sell: 主动卖出量（来自 WebSocket）
        ws_total_volume: WebSocket 统计的总成交量
    
    Returns:
        包含所有指标的字典
    """
    # 计算 histogram
    histogram = calculate_histogram(trades_all)
    
    # Profile 相关
    VAH, VAL, mid_prob = calculate_consensus_band(histogram)
    band_width = get_band_width(histogram)
    pomd = calculate_pomd(histogram)
    rejected = calculate_rejected_probabilities(histogram)
    
    # 不确定性相关
    ui = calculate_ui(histogram)
    ecr = calculate_ecr(current_price, days_remaining)
    acr = calculate_acr(band_width, band_width_7d_ago)
    cer = calculate_cer(band_width, band_width_7d_ago, current_price, days_remaining)
    
    # 信念强度（来自 WebSocket）
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
        # Profile 相关
        'VAH': VAH,
        'VAL': VAL,
        'mid_probability': mid_prob,
        'band_width': band_width,
        'POMD': pomd,
        'rejected_probabilities': rejected,
        
        # 不确定性相关
        'UI': ui,
        'ECR': ecr,
        'ACR': acr,
        'CER': cer,
        
        # 信念强度
        'AR': ar,  # Directional AR
        'volume_delta': volume_delta,
        'CS': cs,  # = AR
        
        # 状态
        'status': status,
        'status_explanation': get_status_explanation(status),
        
        # 元数据
        'total_trades': len(trades_all),
        'trades_24h_count': len(trades_24h),
        'band_width_7d_ago': band_width_7d_ago,
        'has_aggressor_data': aggressive_buy is not None
    }


# ============================================================================
# 6. 测试代码
# ============================================================================

if __name__ == "__main__":
    print("🧪 Testing Metrics v3 (Directional AR)\n")
    print("=" * 60)
    
    # 模拟交易数据
    test_trades = [
        {'price': 0.62, 'size': 50, 'timestamp': int(datetime.now().timestamp())},
        {'price': 0.63, 'size': 80, 'timestamp': int(datetime.now().timestamp())},
        {'price': 0.64, 'size': 120, 'timestamp': int(datetime.now().timestamp())},
        {'price': 0.65, 'size': 200, 'timestamp': int(datetime.now().timestamp())},
        {'price': 0.66, 'size': 150, 'timestamp': int(datetime.now().timestamp())},
        {'price': 0.67, 'size': 90, 'timestamp': int(datetime.now().timestamp())},
        {'price': 0.68, 'size': 60, 'timestamp': int(datetime.now().timestamp())},
    ]
    
    # 模拟 WebSocket aggressor 数据
    # 场景：强 bullish（买入远大于卖出）
    agg_buy = 700.0
    agg_sell = 200.0
    
    print(f"📊 Test scenario: Aggressive Buy={agg_buy}, Sell={agg_sell}")
    print(f"   Expected: Strong bullish signal\n")
    
    metrics = calculate_all_metrics(
        trades_all=test_trades,
        trades_24h=test_trades,
        current_price=0.65,
        days_remaining=30,
        band_width_7d_ago=0.12,
        aggressive_buy=agg_buy,
        aggressive_sell=agg_sell
    )
    
    print("📈 Results:")
    print("-" * 40)
    print(f"  AR (Directional): {metrics['AR']:.4f}" if metrics['AR'] else "  AR: N/A")
    print(f"  Volume Delta:     {metrics['volume_delta']:.2f}" if metrics['volume_delta'] is not None else "  Delta: N/A")
    print(f"  CS:               {metrics['CS']:.4f}" if metrics['CS'] else "  CS: N/A")
    print(f"  Status:           {metrics['status']}")
    
    # AR 应该 = |700-200| / 900 = 500/900 ≈ 0.556
    expected_ar = abs(agg_buy - agg_sell) / (agg_buy + agg_sell)
    print(f"\n✅ Expected AR: {expected_ar:.4f}")
    print(f"   AR = |delta| / total = |{agg_buy}-{agg_sell}| / {agg_buy+agg_sell}")
    
    print("\n" + "=" * 60)
    
    # 场景 2：弱信念（买卖均衡）
    print("\n📊 Test scenario 2: Balanced (weak conviction)")
    agg_buy2 = 500.0
    agg_sell2 = 480.0
    
    metrics2 = calculate_all_metrics(
        trades_all=test_trades,
        trades_24h=test_trades,
        current_price=0.65,
        days_remaining=30,
        band_width_7d_ago=0.12,
        aggressive_buy=agg_buy2,
        aggressive_sell=agg_sell2
    )
    
    print(f"  AR: {metrics2['AR']:.4f}" if metrics2['AR'] else "  AR: N/A")
    print(f"  Delta: {metrics2['volume_delta']:.2f}")
    print(f"  CS: {metrics2['CS']:.4f}" if metrics2['CS'] else "  CS: N/A")
    print(f"  Status: {metrics2['status']}")
    
    # AR 应该很低 = |500-480| / 980 = 20/980 ≈ 0.02
    expected_ar2 = abs(agg_buy2 - agg_sell2) / (agg_buy2 + agg_sell2)
    print(f"  Expected AR: {expected_ar2:.4f} (very low = weak conviction)")
    
    print("\n" + "=" * 60)
    print("✅ Tests completed!")