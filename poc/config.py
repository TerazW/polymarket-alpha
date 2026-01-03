"""
Belief Reaction System - Configuration
All tunable parameters in one place.
"""

# =============================================================================
# SHOCK DETECTION PARAMETERS
# =============================================================================
SHOCK_TIME_WINDOW_MS = 2000        # Window for shock volume calculation
SHOCK_VOLUME_THRESHOLD = 0.35      # % of level size to trigger shock
SHOCK_CONSECUTIVE_TRADES = 3       # Consecutive trades at same price

# =============================================================================
# REACTION CLASSIFICATION PARAMETERS
# =============================================================================
REACTION_WINDOW_MS = 20000         # Observation window after shock (20s)
REACTION_SAMPLE_INTERVAL_MS = 500  # Sample every 500ms

# Reaction type thresholds
HOLD_REFILL_THRESHOLD = 0.8        # Refill ratio for HOLD classification
HOLD_TIME_THRESHOLD_MS = 5000      # Time to refill for HOLD (5s)
VACUUM_THRESHOLD = 0.05            # Max liquidity ratio for VACUUM
PULL_THRESHOLD = 0.1               # Max liquidity ratio for PULL

# =============================================================================
# BELIEF STATE ENGINE PARAMETERS
# =============================================================================
KEY_LEVELS_COUNT = 5               # Number of key levels to track
KEY_LEVELS_LOOKBACK_HOURS = 24     # History for key level identification
STATE_REACTION_WINDOW = 10         # Recent reactions to consider for state

# =============================================================================
# WEBSOCKET PARAMETERS
# =============================================================================
WS_ENDPOINT = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
WS_PING_INTERVAL = 10              # Send PING every 10 seconds

# =============================================================================
# DATABASE PARAMETERS
# =============================================================================
TIMESERIES_SAMPLE_MS = 1000        # Database sampling interval
