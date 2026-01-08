"""
Radar Module - Market surveillance dashboard support

v5.20: Add explainability system
"""

from .explain import (
    # Core types
    Language,
    TrendDirection,
    ExplainFactor,
    Factor,
    CounterfactualCondition,
    StateExplanation,
    # Main functions
    generate_explanation,
    explain_single_event,
    generate_radar_tooltip,
    # Constants
    STATE_HEADLINES,
    FACTOR_DESCRIPTIONS,
)

__all__ = [
    # Types
    'Language',
    'TrendDirection',
    'ExplainFactor',
    'Factor',
    'CounterfactualCondition',
    'StateExplanation',
    # Functions
    'generate_explanation',
    'explain_single_event',
    'generate_radar_tooltip',
    # Constants
    'STATE_HEADLINES',
    'FACTOR_DESCRIPTIONS',
]
