"""
Belief Reaction System - Configuration v3
Based on Spec 1 & Spec 2 deterministic definitions + ChatGPT audit fixes.

核心改进:
1. Shock 分母改成 baseline_size (500ms 中位数)
2. 加绝对阈值 MIN_ABS_VOL
3. 双窗口: FAST + SLOW
4. 领先事件参数
5. [v3] refill_ratio 防爆: DROP_MIN 门槛
6. [v3] vacuum 双阈值: 相对 + 绝对
7. [v3] CHASE/SWEEP 持续性检查
8. [v3] 时间桶采样 (250ms)
9. [v3] GRADUAL_THINNING 事件
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
# REACTION CLASSIFICATION THRESHOLDS (Spec 1 v1 规则 + v3 修复)
# =============================================================================

# [v3] DROP_MIN 门槛: 只有 drop >= 15% 才计算 refill_ratio，否则归为 NO_IMPACT
# 防止分母爆炸: refill_ratio = (max-min)/(baseline-min)
DROP_MIN_THRESHOLD = 0.15            # drop_ratio >= 15% 才有意义

# VACUUM: 流动性完全消失
VACUUM_DURATION_THRESHOLD_MS = 3000  # 真空持续时间阈值 (3s)
VACUUM_MIN_SIZE_RATIO = 0.05         # [v3] 相对阈值: min_size <= 5% of baseline
VACUUM_ABS_THRESHOLD = 10            # [v3] 绝对阈值: min_size <= 10 (防薄盘误触发)
VACUUM_REFILL_RATIO = 0.2            # refill_ratio < 20% 才算 VACUUM

# SWEEP: 多档被扫 / 快速重定价
SWEEP_DROP_RATIO = 0.5               # drop_ratio >= 50%
SWEEP_SHIFT_TICKS = 2                # shift >= 2 ticks

# CHASE: 迁移但未必深度塌陷
CHASE_SHIFT_TICKS = 1                # shift >= 1 tick

# [v3] CHASE/SWEEP 持续性检查: 防止短暂抖动误判
PRICE_SHIFT_PERSIST_MS = 500         # best 价格迁移必须持续 >= 500ms
PRICE_SHIFT_REVERT_TOLERANCE_MS = 200  # 期间回撤不超过 200ms

# PULL: 撤退
PULL_DROP_RATIO = 0.6                # drop_ratio >= 60%
PULL_REFILL_RATIO = 0.3              # refill_ratio < 30%

# HOLD: 坚守/快速补回
HOLD_REFILL_THRESHOLD = 0.8          # Refill ratio >= 80%
HOLD_TIME_THRESHOLD_MS = 5000        # Time to refill <= 5s
HOLD_REFILL_ALPHA = 0.8              # 补回到 80% of baseline

# DELAYED: 默认 (其余情况)

# =============================================================================
# LEADING EVENTS PARAMETERS (领先事件 - Phase 2 + v3)
# =============================================================================

# PRE_SHOCK_PULL: 无成交撤退
# [v3] trade_volume_nearby 口径明确：
#   成交量阈值 = max(SMALL_TRADE_RATIO * baseline, SMALL_TRADE_ABS)
#   如果附近成交量 < 阈值，则认为是"无成交撤退"
PRE_SHOCK_PULL_WINDOW_MS = 3000      # 3 seconds
PRE_SHOCK_PULL_DROP_FROM = 0.8       # 从 >= 80% baseline 降到
PRE_SHOCK_PULL_DROP_TO = 0.2         # <= 20% baseline
PRE_SHOCK_SMALL_TRADE_RATIO = 0.05   # 相对阈值: 成交量 < 5% baseline
PRE_SHOCK_SMALL_TRADE_ABS = 50       # 绝对阈值: 成交量 < 50

# DEPTH_COLLAPSE: 多价位同步塌陷
DEPTH_COLLAPSE_WINDOW_MS = 5000      # 5 seconds
DEPTH_COLLAPSE_TICKS = 5             # ±5 ticks 范围
DEPTH_COLLAPSE_MIN_LEVELS = 3        # >= 3 个价位
DEPTH_COLLAPSE_DROP_RATIO = 0.6      # drop >= 60%
DEPTH_COLLAPSE_TIME_STD_MS = 1000    # 时间标准差 < 1s (同步性)

# [v3] GRADUAL_THINNING: 渐进撤退 (慢慢撤离)
# 在 GRADUAL_THINNING_WINDOW 内，best±N ticks 的总深度下降 >= X%，且没有明显成交驱动
GRADUAL_THINNING_WINDOW_MS = 60000   # 60 seconds
GRADUAL_THINNING_TICKS = 5           # ±5 ticks 范围
GRADUAL_THINNING_DROP_RATIO = 0.4    # 总深度下降 >= 40%
GRADUAL_THINNING_TRADE_RATIO = 0.1   # 成交驱动占比 < 10%

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
TIMESERIES_SAMPLE_MS = 1000          # Database sampling interval (legacy)

# [v3] 时间桶采样: 严格按时间桶保存，不按消息条数
TIME_BUCKET_MS = 250                 # 250ms 时间桶
TIME_BUCKET_TOLERANCE_MS = 50        # 允许误差 ±50ms

# =============================================================================
# DATA RETENTION POLICIES (v3)
# =============================================================================
RETENTION_RAW_EVENTS_DAYS = 7        # raw_events 保留 7 天 (用于 debug/回放)
RETENTION_BOOK_BINS_250MS_DAYS = 14  # book_bins 250ms 保留 14 天
RETENTION_BOOK_BINS_1S_DAYS = 90     # book_bins 1s 保留 90 天 (降采样)
RETENTION_EVENTS_DAYS = 365          # shock/reaction/leading/belief 保留 1 年
