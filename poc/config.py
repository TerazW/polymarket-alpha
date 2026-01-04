"""
Belief Reaction System - Configuration v2
Based on Spec 1 & Spec 2 deterministic definitions.

核心改进:
1. Shock 分母改成 baseline_size (500ms 中位数)
2. 加绝对阈值 MIN_ABS_VOL
3. 双窗口: FAST + SLOW
4. 领先事件参数
"""

# =============================================================================
# SHOCK DETECTION PARAMETERS
# =============================================================================
SHOCK_TIME_WINDOW_MS = 2000        # Window for shock volume calculation (2s)
SHOCK_VOLUME_THRESHOLD = 0.35      # % of baseline_size to trigger shock

# Baseline calculation (用中位数而非单点值，避免被操纵)
BASELINE_WINDOW_START_MS = 500     # Start of baseline window (t0 - 500ms)
BASELINE_WINDOW_END_MS = 100       # End of baseline window (t0 - 100ms)

# Absolute minimum threshold (避免薄盘市场误触发)
MIN_ABS_VOL = 200                  # Minimum absolute trade volume for shock
MIN_ORDER_SIZE_MULTIPLIER = 5      # Alternative: MIN_ABS_VOL = 5 * min_order_size

# Consecutive trades trigger
SHOCK_CONSECUTIVE_TRADES = 3       # Consecutive trades at same price triggers shock

# =============================================================================
# REACTION WINDOW PARAMETERS (双窗口)
# =============================================================================
# FAST window: 检测"信息冲击型撤退/vacuum"
REACTION_FAST_WINDOW_MS = 8000     # 8 seconds

# SLOW window: 检测"慢补/再平衡"
REACTION_SLOW_WINDOW_MS = 30000    # 30 seconds

REACTION_SAMPLE_INTERVAL_MS = 250  # Sample every 250ms (关键窗口更密集)

# =============================================================================
# REACTION CLASSIFICATION THRESHOLDS (Spec 1 v1 规则)
# =============================================================================
# VACUUM: 流动性完全消失
VACUUM_DURATION_THRESHOLD_MS = 3000  # 真空持续时间阈值 (3s)
VACUUM_MIN_SIZE_RATIO = 0.02         # min_size <= 2% of baseline
VACUUM_REFILL_RATIO = 0.2            # refill_ratio < 20% 才算 VACUUM

# SWEEP: 多档被扫 / 快速重定价
SWEEP_DROP_RATIO = 0.5               # drop_ratio >= 50%
SWEEP_SHIFT_TICKS = 2                # shift >= 2 ticks

# CHASE: 迁移但未必深度塌陷
CHASE_SHIFT_TICKS = 1                # shift >= 1 tick

# PULL: 撤退
PULL_DROP_RATIO = 0.6                # drop_ratio >= 60%
PULL_REFILL_RATIO = 0.3              # refill_ratio < 30%

# HOLD: 坚守/快速补回
HOLD_REFILL_THRESHOLD = 0.8          # Refill ratio >= 80%
HOLD_TIME_THRESHOLD_MS = 5000        # Time to refill <= 5s
HOLD_REFILL_ALPHA = 0.8              # 补回到 80% of baseline

# DELAYED: 默认 (其余情况)

# =============================================================================
# LEADING EVENTS PARAMETERS (领先事件 - Phase 2)
# =============================================================================
# PRE_SHOCK_PULL: 无成交撤退
PRE_SHOCK_PULL_WINDOW_MS = 3000      # 3 seconds
PRE_SHOCK_PULL_DROP_FROM = 0.8       # 从 >= 80% baseline 降到
PRE_SHOCK_PULL_DROP_TO = 0.2         # <= 20% baseline
PRE_SHOCK_SMALL_TRADE_RATIO = 0.05   # 成交量 < 5% baseline
PRE_SHOCK_SMALL_TRADE_ABS = 50       # 或绝对值 < 50

# DEPTH_COLLAPSE: 多价位同步塌陷
DEPTH_COLLAPSE_WINDOW_MS = 5000      # 5 seconds
DEPTH_COLLAPSE_TICKS = 5             # ±5 ticks 范围
DEPTH_COLLAPSE_MIN_LEVELS = 3        # >= 3 个价位
DEPTH_COLLAPSE_DROP_RATIO = 0.6      # drop >= 60%
DEPTH_COLLAPSE_TIME_STD_MS = 1000    # 时间标准差 < 1s (同步性)

# =============================================================================
# ANCHOR LEVELS PARAMETERS (关键价位选择 - Phase 2)
# =============================================================================
ANCHOR_LOOKBACK_HOURS = 24           # 回看 24 小时
ANCHOR_PERSISTENCE_THETA = 0.5       # 持续时间计算阈值 (50% of peak)
ANCHOR_WEIGHT_PEAK = 1.0             # peak_size 权重
ANCHOR_WEIGHT_PERSISTENCE = 1.0      # persistence 权重
ANCHOR_TOP_K = 3                     # 每个 token 选 top 3

# =============================================================================
# BELIEF STATE MACHINE PARAMETERS (Phase 3)
# =============================================================================
STATE_WINDOW_MS = 30 * 60 * 1000     # 滚动窗口 30 分钟
STATE_HOLD_RATIO_STABLE = 0.7        # STABLE 需要 hold_ratio >= 70%

# =============================================================================
# WEBSOCKET PARAMETERS
# =============================================================================
WS_ENDPOINT = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
WS_PING_INTERVAL = 10                # Send PING every 10 seconds

# =============================================================================
# DATABASE PARAMETERS
# =============================================================================
TIMESERIES_SAMPLE_MS = 1000          # Database sampling interval
