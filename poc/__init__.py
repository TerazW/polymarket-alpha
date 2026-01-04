"""
Belief Reaction System - POC
A Human Belief Reaction Sensing System for Event-Driven Markets.

"看存在没意义，看反应才有意义"
"Observing existence is meaningless; observing REACTION is everything."
"""

from .models import (
    ReactionType, BeliefState, PriceLevel, TradeEvent,
    ShockEvent, ReactionEvent, ReactionMetrics, BeliefStateChange,
    LeadingEvent, LeadingEventType, WindowType, AnchorLevel,
    STATE_INDICATORS, REACTION_INDICATORS
)
from .config import *
from .shock_detector import ShockDetector
from .reaction_classifier import ReactionClassifier, ReactionObserver
from .belief_state import BeliefStateMachine, BeliefStateEngine
from .reaction_engine import ReactionEngine, OrderBookState
from .leading_events import LeadingEventDetector
from .belief_state_machine import BeliefStateMachine as BeliefStateMachineV2
from .alert_system import AlertSystem, Alert, AlertType, AlertPriority

# v4.1: Collector/Reactor decoupling
from .event_bus import EventBus, RawEvent, EventType as RawEventType, InMemoryEventBus, create_event_bus
from .collector import DataCollector, ConnectionState
from .reactor import Reactor

__all__ = [
    # Models
    'ReactionType', 'BeliefState', 'PriceLevel', 'TradeEvent',
    'ShockEvent', 'ReactionEvent', 'ReactionMetrics', 'BeliefStateChange',
    'LeadingEvent', 'LeadingEventType', 'WindowType', 'AnchorLevel',
    'STATE_INDICATORS', 'REACTION_INDICATORS',
    # Core components (v3)
    'ShockDetector', 'ReactionClassifier', 'ReactionObserver',
    'BeliefStateMachine', 'BeliefStateEngine',
    'ReactionEngine', 'OrderBookState',
    # v4: Leading events + State machine v2
    'LeadingEventDetector',
    'BeliefStateMachineV2',
    # v4: Alert system
    'AlertSystem', 'Alert', 'AlertType', 'AlertPriority',
    # v4.1: Collector/Reactor decoupling
    'EventBus', 'RawEvent', 'RawEventType', 'InMemoryEventBus', 'create_event_bus',
    'DataCollector', 'ConnectionState',
    'Reactor',
]
