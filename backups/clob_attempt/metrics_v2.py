"""
Market Sensemaking Metrics v2.0
完整实现基于 Market Profile 的指标体系

使用 CLOB API 的 type 字段精确识别 aggressor
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

# ============================================================================
# 1. Consensus Band & Profile 类
# ============================================================================

def calculate_volume_profile(trades: List[Dict], tick_size: float = 0.01) -> Dict[float, float]:
    """
    计算 Volume-at-Price Profile
    
    Args:
        trades: 交易列表
        tick_size: 价格分箱大小
    
    Returns:
        {price_level: total_volume} 字典
    """
    profile = defaultdict(float)
    
    for trade in trades:
        try:
            price = float(trade.get('price', 0))
            size = float(trade.get('size', 0))
            
            # 价格分箱
            bin_price = round(price / tick_size) * tick_size
            bin_price = round(bin_price, 4)
            
            profile[bin_price] += size
            
        except (ValueError, TypeError):
            continue
    
    return dict(profile)


def calculate_consensus_band(
    profile: Dict[float, float],
    coverage: float = 0.70
) -> Tuple[float, float, float]:
    """
    计算 Consensus Band (共识带)
    
    定义：覆盖 X% 成交量的概率区间
    
    Args:
        profile: Volume-at-Price profile
        coverage: 覆盖百分比（默认 70%）
    
    Returns:
        (VAH, VAL, mid_probability)
        - VAH (Value Area High): 共识带上界
        - VAL (Value Area Low): 共识带下界  
        - mid_probability: 共识带中点
    """
    if not profile:
        return None, None, None
    
    # 按成交量排序
    sorted_bins = sorted(profile.items(), key=lambda x: x[1], reverse=True)
    total_volume = sum(profile.values())
    
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


def calculate_pomd(profile: Dict[float, float]) -> Optional[float]:
    """
    计算 POMD (Point of Max Disagreement)
    
    定义：最大分歧点 - 成交量最大的价格点
    意义：市场争议最激烈的概率点
    
    Args:
        profile: Volume-at-Price profile
    
    Returns:
        POMD 价格点
    """
    if not profile:
        return None
    
    pomd = max(profile.items(), key=lambda x: x[1])[0]
    return pomd


def identify_rejected_probabilities(
    profile: Dict[float, float],
    threshold_percentile: float = 0.10
) -> List[float]:
    """
    识别 Rejected Probabilities (被否定概率区)
    
    定义：成交量极低的价格区间（类似 single prints）
    意义：被市场快速否定/停留极短的区间
    
    Args:
        profile: Volume-at-Price profile
        threshold_percentile: 低于此百分位的视为 rejected
    
    Returns:
        被否定的价格点列表
    """
    if not profile:
        return []
    
    volumes = list(profile.values())
    threshold = statistics.quantiles(volumes, n=100)[int(threshold_percentile * 100)]
    
    rejected = [price for price, volume in profile.items() if volume < threshold]
    
    return rejected


# ============================================================================
# 2. 不确定性类
# ============================================================================

def calculate_ui(
    band_width: float,
    mid_probability: float
) -> Optional[float]:
    """
    计算 UI (Uncertainty Index)
    
    定义：UI = band_width / mid_probability
    
    意义：相同带宽，在不同价格位置的不确定性不同
    - 50% 附近的 10% 带宽 → 中等不确定性
    - 90% 附近的 10% 带宽 → 极度不确定（接近确定却分裂）
    
    Args:
        band_width: Consensus band 宽度
        mid_probability: 共识带中点
    
    Returns:
        UI 值
    """
    # 边界情况：价格极端位置不计算
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
    
    定义：ECR = (100 - price) / days_remaining
    意义：理论上"还剩多少要收敛"
    
    Args:
        current_price: 当前价格（百分比，0-100）
        days_remaining: 剩余天数
    
    Returns:
        ECR 值
    """
    if days_remaining < 1:
        return None
    
    # 价格极端位置不计算
    if current_price > 95 or current_price < 5:
        return None
    
    distance_to_certainty = min(current_price, 100 - current_price)
    ecr = distance_to_certainty / days_remaining
    
    return ecr


def calculate_acr(
    band_width_now: float,
    band_width_7d_ago: Optional[float],
    days: int = 7
) -> Optional[float]:
    """
    计算 ACR (Actual Convergence Rate)
    
    定义：ACR = (band_width_7d_ago - band_width_now) / 7
    意义：实际不确定性收窄速度
    
    Args:
        band_width_now: 当前带宽
        band_width_7d_ago: 7天前的带宽
        days: 时间间隔（天）
    
    Returns:
        ACR 值
    """
    if band_width_7d_ago is None:
        return None
    
    acr = (band_width_7d_ago - band_width_now) / days
    
    return acr


def calculate_cer(
    acr: Optional[float],
    ecr: Optional[float]
) -> Optional[float]:
    """
    计算 CER (Convergence Efficiency Ratio)
    
    定义：CER = ACR / ECR
    意义：市场收敛是否"健康/迟钝/阻塞"
    
    - CER > 1: 收敛快于预期（健康）
    - CER ≈ 1: 收敛符合预期
    - CER < 1: 收敛慢于预期（迟钝/阻塞）
    
    Args:
        acr: 实际收敛速度
        ecr: 期望收敛速度
    
    Returns:
        CER 值
    """
    if acr is None or ecr is None:
        return None
    
    if ecr == 0:
        return None
    
    cer = acr / ecr
    
    return cer


# ============================================================================
# 3. 信念强度类（使用 CLOB API 的 aggressor 数据）
# ============================================================================

def calculate_ar(trades: List[Dict]) -> Optional[float]:
    """
    计算 AR (Aggressive Ratio)
    
    定义：AR = aggressive_volume / total_volume
    意义：主动交易占比
    
    使用 CLOB API 的 'type' 字段：
    - type == 'TAKER' → aggressive (主动方)
    - type == 'MAKER' → passive (被动方)
    
    Args:
        trades: 交易列表（必须包含 'type' 字段）
    
    Returns:
        AR 值
    """
    if not trades:
        return None
    
    aggressive_volume = 0
    total_volume = 0
    
    for trade in trades:
        try:
            size = float(trade.get('size', 0))
            trade_type = trade.get('type', '')
            
            total_volume += size
            
            if trade_type == 'TAKER':
                aggressive_volume += size
                
        except (ValueError, TypeError):
            continue
    
    if total_volume == 0:
        return None
    
    ar = aggressive_volume / total_volume
    
    return ar


def calculate_volume_delta(trades: List[Dict]) -> Optional[float]:
    """
    计算 Volume Delta
    
    定义：delta = aggressive_buy - aggressive_sell
    意义：主动买卖的不平衡
    
    使用 CLOB API 数据：
    - type == 'TAKER' AND side == 'BUY' → aggressive buy
    - type == 'TAKER' AND side == 'SELL' → aggressive sell
    
    Args:
        trades: 交易列表（必须包含 'type' 和 'side' 字段）
    
    Returns:
        Volume Delta 值
    """
    if not trades:
        return None
    
    aggressive_buy = 0
    aggressive_sell = 0
    
    for trade in trades:
        try:
            size = float(trade.get('size', 0))
            trade_type = trade.get('type', '')
            side = trade.get('side', '')
            
            # 只统计主动方
            if trade_type == 'TAKER':
                if side == 'BUY':
                    aggressive_buy += size
                elif side == 'SELL':
                    aggressive_sell += size
                    
        except (ValueError, TypeError):
            continue
    
    delta = aggressive_buy - aggressive_sell
    
    return delta


def calculate_cs(
    ar: Optional[float],
    delta: Optional[float],
    total_volume: float
) -> Optional[float]:
    """
    计算 CS (Conviction Score)
    
    定义：CS = (AR * |delta|) / total_volume
    意义：共识是否"主动形成"
    
    - 高 CS = 强 AR + 大 delta = 主动形成的强信念
    - 低 CS = 弱 AR 或小 delta = 被动形成的弱共识
    
    Args:
        ar: Aggressive Ratio
        delta: Volume Delta  
        total_volume: 总成交量
    
    Returns:
        CS 值
    """
    if ar is None or delta is None:
        return None
    
    if total_volume == 0:
        return None
    
    cs = (ar * abs(delta)) / total_volume
    
    return cs


# ============================================================================
# 4. 状态判定
# ============================================================================

def determine_market_status(
    ui: Optional[float],
    cer: Optional[float],
    cs: Optional[float]
) -> str:
    """
    判定市场状态
    
    分类：
    - 🟢 Informed: 市场已形成稳定共识
    - 🟡 Fragmented: 市场理解分裂
    - 🔴 Noisy: 市场缺乏稳定认知结构
    
    Args:
        ui: Uncertainty Index
        cer: Convergence Efficiency Ratio
        cs: Conviction Score
    
    Returns:
        状态字符串
    """
    # 数据不足
    if ui is None and cer is None and cs is None:
        return "⚪ Unknown"
    
    # 🟢 Informed 条件（所有指标都良好）
    if (ui is not None and ui < 0.30) and \
       (cer is not None and cer >= 0.8) and \
       (cs is not None and cs >= 0.35):
        return "🟢 Informed"
    
    # 🔴 Noisy 条件（任一指标很差）
    if (ui is not None and ui >= 0.50) or \
       (cer is not None and cer < 0.4) or \
       (cs is not None and cs < 0.15):
        return "🔴 Noisy"
    
    # 🟡 Fragmented（其余情况）
    return "🟡 Fragmented"


# ============================================================================
# 5. 辅助函数
# ============================================================================

def filter_trades_by_time(trades: List[Dict], hours: int = 24) -> List[Dict]:
    """
    筛选指定时间内的交易
    
    Args:
        trades: 交易列表
        hours: 时间窗口（小时）
    
    Returns:
        过滤后的交易列表
    """
    cutoff = datetime.now() - timedelta(hours=hours)
    cutoff_ts = int(cutoff.timestamp())
    
    return [t for t in trades if t.get('timestamp', 0) >= cutoff_ts]


def calculate_band_width(VAH: Optional[float], VAL: Optional[float]) -> Optional[float]:
    """
    计算 band width
    
    Args:
        VAH: Value Area High
        VAL: Value Area Low
    
    Returns:
        Band Width
    """
    if VAH is None or VAL is None:
        return None
    
    return VAH - VAL


# ============================================================================
# 6. 完整的指标计算流程
# ============================================================================

def calculate_all_metrics(
    trades_all: List[Dict],
    trades_24h: List[Dict],
    current_price: float,
    days_remaining: int,
    band_width_7d_ago: Optional[float] = None
) -> Dict:
    """
    计算所有指标（一站式）
    
    Args:
        trades_all: 所有交易（用于 profile）
        trades_24h: 24h 交易（用于 AR/CS）
        current_price: 当前价格（0-1）
        days_remaining: 剩余天数
        band_width_7d_ago: 7天前的 band width
    
    Returns:
        包含所有指标的字典
    """
    metrics = {}
    
    # 1. Profile & Consensus Band
    profile = calculate_volume_profile(trades_all)
    VAH, VAL, mid_prob = calculate_consensus_band(profile)
    band_width = calculate_band_width(VAH, VAL)
    
    metrics['VAH'] = VAH
    metrics['VAL'] = VAL
    metrics['mid_probability'] = mid_prob
    metrics['band_width'] = band_width
    metrics['POMD'] = calculate_pomd(profile)
    metrics['rejected_probabilities'] = identify_rejected_probabilities(profile)
    
    # 2. 不确定性类
    metrics['UI'] = calculate_ui(band_width, mid_prob) if band_width and mid_prob else None
    
    current_price_pct = current_price * 100
    metrics['ECR'] = calculate_ecr(current_price_pct, days_remaining)
    metrics['ACR'] = calculate_acr(band_width, band_width_7d_ago)
    metrics['CER'] = calculate_cer(metrics['ACR'], metrics['ECR'])
    
    # 3. 信念强度类
    metrics['AR'] = calculate_ar(trades_24h)
    metrics['volume_delta'] = calculate_volume_delta(trades_24h)
    
    total_volume_24h = sum(t.get('size', 0) for t in trades_24h)
    metrics['CS'] = calculate_cs(metrics['AR'], metrics['volume_delta'], total_volume_24h)
    
    # 4. 状态判定
    metrics['status'] = determine_market_status(
        metrics['UI'],
        metrics['CER'],
        metrics['CS']
    )
    
    return metrics


# ============================================================================
# 7. 测试代码
# ============================================================================

if __name__ == "__main__":
    print("🧪 Testing Metrics v2.0\n")
    
    # 模拟交易数据
    test_trades = [
        {'type': 'TAKER', 'side': 'BUY', 'price': 0.65, 'size': 100, 'timestamp': int(datetime.now().timestamp())},
        {'type': 'MAKER', 'side': 'SELL', 'price': 0.65, 'size': 100, 'timestamp': int(datetime.now().timestamp())},
        {'type': 'TAKER', 'side': 'BUY', 'price': 0.66, 'size': 150, 'timestamp': int(datetime.now().timestamp())},
        {'type': 'TAKER', 'side': 'SELL', 'price': 0.64, 'size': 80, 'timestamp': int(datetime.now().timestamp())},
        {'type': 'MAKER', 'side': 'BUY', 'price': 0.64, 'size': 80, 'timestamp': int(datetime.now().timestamp())},
    ]
    
    # 计算指标
    metrics = calculate_all_metrics(
        trades_all=test_trades,
        trades_24h=test_trades,
        current_price=0.65,
        days_remaining=30,
        band_width_7d_ago=0.15
    )
    
    print("📊 Calculated Metrics:")
    print("="*50)
    
    for key, value in metrics.items():
        if key != 'rejected_probabilities':
            if isinstance(value, float):
                print(f"{key:<20}: {value:.4f}")
            else:
                print(f"{key:<20}: {value}")
    
    print("\n✅ Metrics v2.0 test completed!")
