"""
Belief Reaction System - POC
A Human Belief Reaction Sensing System for Event-Driven Markets.

"看存在没意义，看反应才有意义"
"Observing existence is meaningless; observing REACTION is everything."
"""

from .models import (
    ReactionType, BeliefState, PriceLevel, TradeEvent,
    ShockEvent, ReactionEvent, ReactionMetrics, BeliefStateChange,
    STATE_INDICATORS
)
from .config import *
from .shock_detector import ShockDetector
from .reaction_classifier import ReactionClassifier, ReactionObserver
from .belief_state import BeliefStateMachine, BeliefStateEngine
from .reaction_engine import ReactionEngine, OrderBookState

__all__ = [
    # Models
    'ReactionType', 'BeliefState', 'PriceLevel', 'TradeEvent',
    'ShockEvent', 'ReactionEvent', 'ReactionMetrics', 'BeliefStateChange',
    'STATE_INDICATORS',
    # Core components
    'ShockDetector', 'ReactionClassifier', 'ReactionObserver',
    'BeliefStateMachine', 'BeliefStateEngine',
    'ReactionEngine', 'OrderBookState',
]
