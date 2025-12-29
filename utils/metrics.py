"""
Market Sensemaking 指标计算 - 完整版
路线 A：Data API 版本（无 aggressor）

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

=== 锁定指标（需要 aggressor 数据）===
   🔒 AR - Aggressive Ratio
   🔒 Volume Delta
   🔒 CS - Conviction Score
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import statistics


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
    
    注意：Data API 的 price 是 0-1，不需要转换
    """
    histogram = defaultdict(float)
    
    for trade in trades:
        try:
            price = float(trade.get('price', 0))
            size = float(trade.get('size', 0))
            
            # 价格分箱
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
    
    Args:
        histogram: Volume-at-Price profile
        coverage: 覆盖百分比（默认 70%）
    
    Returns:
        (VAH, VAL, mid_probability)
        - VAH (Value Area High): 共识带上界
        - VAL (Value Area Low): 共识带下界  
        - mid_probability: 共识带中点 (VAH + VAL) / 2
    """
    if not histogram:
        return None, None, None
    
    # 按成交量排序（从大到小）
    sorted_bins = sorted(histogram.items(), key=lambda x: x[1], reverse=True)
    total_volume = sum(histogram.values())
    
    if total_volume == 0:
        return None, None, None
    
    # 累积到目标覆盖率
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
    计算 Band Width (带宽)
    
    定义：band_width = VAH - VAL
    用途：不确定性强弱
    - BW 大 → 认知分散
    - BW 小 → 共识集中
    
    Args:
        histogram: Volume-at-Price profile
        coverage: 覆盖百分比（默认 70%）
    
    Returns:
        Band Width (0-1 范围)
    """
    VAH, VAL, _ = calculate_consensus_band(histogram, coverage)
    
    if VAH is None or VAL is None:
        return None
    
    return VAH - VAL


def calculate_pomd(histogram: Dict[float, float]) -> Optional[float]:
    """
    计算 POMD (Point of Max Disagreement)
    
    定义：最大分歧点 - 成交量最大的价格点
    意义：市场争议最激烈的概率点
    
    Args:
        histogram: Volume-at-Price profile
    
    Returns:
        POMD 价格点 (0-1 范围)
    """
    if not histogram:
        return None
    
    pomd = max(histogram.items(), key=lambda x: x[1])[0]
    return pomd


def calculate_rejected_probabilities(
    histogram: Dict[float, float],
    threshold_percentile: float = 0.10
) -> List[float]:
    """
    计算 Rejected Probabilities (被否定概率区)
    
    定义：成交量极低的价格区间（类似 Market Profile 的 single prints）
    意义：被市场快速否定/停留极短的区间
    
    Args:
        histogram: Volume-at-Price profile
        threshold_percentile: 低于此百分位的视为 rejected（默认 10%）
    
    Returns:
        被否定的价格点列表
    """
    if not histogram or len(histogram) < 3:
        return []
    
    volumes = list(histogram.values())
    
    try:
        # 计算阈值（第 10 百分位）
        sorted_volumes = sorted(volumes)
        threshold_idx = max(0, int(len(sorted_volumes) * threshold_percentile) - 1)
        threshold = sorted_volumes[threshold_idx]
        
        # 找出低于阈值的价格点
        rejected = [price for price, volume in histogram.items() if volume <= threshold]
        
        return sorted(rejected)
    except Exception:
        return []


def get_volume_profile_summary(histogram: Dict[float, float]) -> Dict:
    """
    获取 Volume Profile 的完整摘要
    
    Returns:
        包含所有 Profile 相关指标的字典
    """
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
    
    意义：同样带宽，在不同价格位置的不确定性不同
    - 50% 附近的 10% 带宽 → UI = 0.2，中等不确定性
    - 90% 附近的 10% 带宽 → UI = 0.11，但实际是极度不确定（接近确定却分裂）
    
    注意：这个公式在高概率区域会低估不确定性，
    但在中等概率区域是合理的度量
    
    Args:
        histogram: Volume-at-Price profile
    
    Returns:
        UI 值（越高越不确定）
    """
    VAH, VAL, mid_probability = calculate_consensus_band(histogram)
    
    if VAH is None or VAL is None or mid_probability is None:
        return None
    
    band_width = VAH - VAL
    
    # 边界情况：价格极端位置不计算（避免除以接近0的数）
    if mid_probability < 0.10 or mid_probability > 0.90:
        return None
    
    if mid_probability == 0:
        return None
    
    ui = band_width / mid_probability
    
    return ui


def calculate_ecr(
    current_price: float,
    days_remaining: int
) -> Optional[float]:
    """
    计算 ECR (Expected Convergence Rate)
    
    定义：ECR = distance_to_certainty / days_remaining
    意义：理论上"还剩多少要收敛"，即期望的每日收敛速度
    
    Args:
        current_price: 当前价格 (0-1 范围)
        days_remaining: 剩余天数
    
    Returns:
        ECR 值（每天期望收敛的概率距离）
    """
    if days_remaining < 1:
        return None
    
    # 价格极端位置不计算
    if current_price > 0.95 or current_price < 0.05:
        return None
    
    # 到确定性的距离（取较近的一端）
    distance_to_certainty = min(current_price, 1 - current_price)
    
    ecr = distance_to_certainty / days_remaining
    
    return ecr


def calculate_acr(
    band_width_now: Optional[float],
    band_width_7d_ago: Optional[float],
    days: int = 7
) -> Optional[float]:
    """
    计算 ACR (Actual Convergence Rate)
    
    定义：ACR = (band_width_7d_ago - band_width_now) / days
    意义：实际不确定性收窄速度
    
    - ACR > 0：共识在收敛（好）
    - ACR < 0：共识在发散（可能有新信息冲击）
    - ACR ≈ 0：停滞
    
    Args:
        band_width_now: 当前带宽
        band_width_7d_ago: 7天前的带宽
        days: 时间间隔（默认 7 天）
    
    Returns:
        ACR 值（每天实际收敛的带宽）
    """
    if band_width_now is None or band_width_7d_ago is None:
        return None
    
    if days <= 0:
        return None
    
    acr = (band_width_7d_ago - band_width_now) / days
    
    return acr


def calculate_cer(
    band_width_now: Optional[float],
    band_width_7d_ago: Optional[float],
    current_price: float,
    days_remaining: int
) -> Optional[float]:
    """
    计算 CER (Convergence Efficiency Ratio)
    
    定义：CER = ACR / ECR
    意义：市场收敛是否"健康/迟钝/阻塞"
    
    - CER > 1.0：收敛快于预期（非常健康，市场快速形成共识）
    - CER ≈ 0.8-1.0：正常收敛
    - CER < 0.5：收敛迟钝（可能有持续分歧）
    - CER < 0：发散（新信息导致不确定性增加）
    
    Args:
        band_width_now: 当前带宽
        band_width_7d_ago: 7天前的带宽
        current_price: 当前价格 (0-1 范围)
        days_remaining: 剩余天数
    
    Returns:
        CER 值
    """
    # 计算 ECR
    ecr = calculate_ecr(current_price, days_remaining)
    if ecr is None or ecr <= 0:
        return None
    
    # 计算 ACR
    acr = calculate_acr(band_width_now, band_width_7d_ago)
    if acr is None:
        return None
    
    # CER
    cer = acr / ecr
    
    return cer


def get_uncertainty_metrics(
    histogram: Dict[float, float],
    current_price: float,
    days_remaining: int,
    band_width_7d_ago: Optional[float] = None
) -> Dict:
    """
    获取所有不确定性指标的摘要
    
    Returns:
        包含 UI, ECR, ACR, CER 的字典
    """
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
# 3. 信念强度类 - 🔒 LOCKED (需要 aggressor 数据)
# ============================================================================

def calculate_ar(trades: List[Dict]) -> Optional[float]:
    """
    🔒 LOCKED: 需要 aggressor (TAKER/MAKER) 数据
    
    AR (Aggressive Ratio) = aggressive_volume / total_volume
    
    意义：主动交易占比
    - AR 高 → 市场参与者主动出击，信念强
    - AR 低 → 被动挂单成交为主
    """
    return None  # Data API 没有 aggressor 信息


def calculate_volume_delta(trades: List[Dict]) -> Optional[float]:
    """
    🔒 LOCKED: 需要 aggressor (TAKER/MAKER) 数据
    
    Volume Delta = aggressive_buy - aggressive_sell
    
    意义：主动买卖的不平衡
    - Delta > 0 → 主动买入占优
    - Delta < 0 → 主动卖出占优
    """
    return None  # Data API 没有 aggressor 信息


def calculate_cs(trades: List[Dict]) -> Optional[float]:
    """
    🔒 LOCKED: 需要 aggressor (TAKER/MAKER) 数据
    
    CS (Conviction Score) = (AR * |delta|) / total_volume
    
    意义：共识是否"主动形成"
    - 高 CS = 强 AR + 大 delta = 主动形成的强信念
    - 低 CS = 弱 AR 或小 delta = 被动形成的弱共识
    
    注意：旧版本用 BUY/SELL side 计算是不准确的，
    真正的 CS 需要知道谁是 taker (主动方)
    """
    return None  # Data API 没有 aggressor 信息


# ============================================================================
# 4. 状态判定
# ============================================================================

def determine_status(
    ui: Optional[float],
    cer: Optional[float],
    cs: Optional[float] = None  # 路线 A 下始终为 None
) -> str:
    """
    判定市场状态
    
    路线 A (无 aggressor)：只用 UI + CER 判断
    
    分类逻辑：
    - 🟢 Informed: 低不确定性 (UI < 0.30) + 健康收敛 (CER >= 0.8)
    - 🔴 Noisy: 高不确定性 (UI >= 0.50) 或 收敛阻塞 (CER < 0.4)
    - 🟡 Fragmented: 其余情况
    - ⚪ Unknown: 数据不足
    
    Args:
        ui: Uncertainty Index
        cer: Convergence Efficiency Ratio
        cs: Conviction Score (路线 A 下为 None)
    
    Returns:
        状态字符串
    """
    # 数据不足
    if ui is None and cer is None:
        return "⚪ Unknown"
    
    # 🔴 Noisy（任一指标很差）
    if (ui is not None and ui >= 0.50) or \
       (cer is not None and cer < 0.4):
        return "🔴 Noisy"
    
    # 🟢 Informed（两个指标都良好）
    if (ui is not None and ui < 0.30) and \
       (cer is not None and cer >= 0.8):
        return "🟢 Informed"
    
    # 🟡 Fragmented（其余情况）
    return "🟡 Fragmented"


def get_status_explanation(status: str) -> str:
    """
    获取状态的中文解释
    """
    explanations = {
        "🟢 Informed": "市场已形成稳定共识",
        "🟡 Fragmented": "市场理解分裂，存在分歧",
        "🔴 Noisy": "市场缺乏稳定认知结构",
        "⚪ Unknown": "数据不足，无法判定"
    }
    return explanations.get(status, "未知状态")


# ============================================================================
# 5. 辅助函数
# ============================================================================

def filter_trades_by_time(trades: List[Dict], hours: int = 24) -> List[Dict]:
    """
    筛选指定时间内的成交
    
    Args:
        trades: 交易列表
        hours: 时间窗口（小时）
    
    Returns:
        过滤后的交易列表
    
    注意：Data API 的 timestamp 是秒（不是毫秒）
    """
    cutoff = datetime.now() - timedelta(hours=hours)
    cutoff_ts = int(cutoff.timestamp())
    
    return [t for t in trades if t.get('timestamp', 0) >= cutoff_ts]


def calculate_all_metrics(
    trades_all: List[Dict],
    trades_24h: List[Dict],
    current_price: float,
    days_remaining: int,
    band_width_7d_ago: Optional[float] = None
) -> Dict:
    """
    一站式计算所有指标
    
    Args:
        trades_all: 所有交易（用于 profile）
        trades_24h: 24h 交易（用于近期活动分析）
        current_price: 当前价格 (0-1)
        days_remaining: 剩余天数
        band_width_7d_ago: 7天前的 band width
    
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
    
    # 信念强度（锁定）
    ar = calculate_ar(trades_24h)
    volume_delta = calculate_volume_delta(trades_24h)
    cs = calculate_cs(trades_24h)
    
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
        
        # 信念强度（锁定）
        'AR': ar,  # None
        'volume_delta': volume_delta,  # None
        'CS': cs,  # None
        
        # 状态
        'status': status,
        'status_explanation': get_status_explanation(status),
        
        # 元数据
        'total_trades': len(trades_all),
        'trades_24h_count': len(trades_24h),
        'band_width_7d_ago': band_width_7d_ago
    }


# ============================================================================
# 6. 测试代码
# ============================================================================

if __name__ == "__main__":
    print("🧪 Testing Metrics (Complete Version)\n")
    print("=" * 60)
    
    # 模拟交易数据
    test_trades = [
        {'price': 0.62, 'size': 50, 'timestamp': int(datetime.now().timestamp())},
        {'price': 0.63, 'size': 80, 'timestamp': int(datetime.now().timestamp())},
        {'price': 0.64, 'size': 120, 'timestamp': int(datetime.now().timestamp())},
        {'price': 0.65, 'size': 200, 'timestamp': int(datetime.now().timestamp())},  # 最大成交
        {'price': 0.66, 'size': 150, 'timestamp': int(datetime.now().timestamp())},
        {'price': 0.67, 'size': 90, 'timestamp': int(datetime.now().timestamp())},
        {'price': 0.68, 'size': 60, 'timestamp': int(datetime.now().timestamp())},
        {'price': 0.70, 'size': 20, 'timestamp': int(datetime.now().timestamp())},  # 低成交
        {'price': 0.55, 'size': 15, 'timestamp': int(datetime.now().timestamp())},  # 低成交
    ]
    
    # 计算所有指标
    metrics = calculate_all_metrics(
        trades_all=test_trades,
        trades_24h=test_trades,
        current_price=0.65,
        days_remaining=30,
        band_width_7d_ago=0.12  # 假设7天前带宽是 12%
    )
    
    print("\n📊 1. Profile 相关指标")
    print("-" * 40)
    print(f"  VAH (共识带上界):     {metrics['VAH']:.4f}" if metrics['VAH'] else "  VAH: N/A")
    print(f"  VAL (共识带下界):     {metrics['VAL']:.4f}" if metrics['VAL'] else "  VAL: N/A")
    print(f"  Mid Probability:      {metrics['mid_probability']:.4f}" if metrics['mid_probability'] else "  Mid Prob: N/A")
    print(f"  Band Width (带宽):    {metrics['band_width']:.4f}" if metrics['band_width'] else "  Band Width: N/A")
    print(f"  POMD (最大分歧点):    {metrics['POMD']:.4f}" if metrics['POMD'] else "  POMD: N/A")
    print(f"  Rejected Probs:       {metrics['rejected_probabilities']}")
    
    print("\n📈 2. 不确定性指标")
    print("-" * 40)
    print(f"  UI (不确定性指数):    {metrics['UI']:.4f}" if metrics['UI'] else "  UI: N/A")
    print(f"  ECR (期望收敛率):     {metrics['ECR']:.6f}" if metrics['ECR'] else "  ECR: N/A")
    print(f"  ACR (实际收敛率):     {metrics['ACR']:.6f}" if metrics['ACR'] else "  ACR: N/A")
    print(f"  CER (收敛效率比):     {metrics['CER']:.4f}" if metrics['CER'] else "  CER: N/A")
    
    print("\n🔒 3. 信念强度指标 (Locked)")
    print("-" * 40)
    print(f"  AR:                   {metrics['AR']} (需要 aggressor 数据)")
    print(f"  Volume Delta:         {metrics['volume_delta']} (需要 aggressor 数据)")
    print(f"  CS:                   {metrics['CS']} (需要 aggressor 数据)")
    
    print("\n📍 4. 状态判定")
    print("-" * 40)
    print(f"  Status: {metrics['status']}")
    print(f"  解释: {metrics['status_explanation']}")
    
    print("\n" + "=" * 60)
    print("✅ Metrics test completed!")