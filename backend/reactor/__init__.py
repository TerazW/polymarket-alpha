"""
Belief Reaction System - Backend Reactor Module (v5.26)

Integrates POC reactor logic into the backend API layer.

Components:
- ReactorService: Async service for FastAPI integration
- BeliefMachineService: Belief state machine management
- AlertGenerator: Alert generation (existing)

The actual reactor logic lives in /poc/ - this module provides:
- Thread-safe wrappers
- Async interfaces for FastAPI
- Database persistence
- API response formatting
"""

from .alert_generator import AlertGenerator
from .service import ReactorService, BeliefMachineService
from .core import ReactorWrapper

__all__ = [
    'AlertGenerator',
    'ReactorService',
    'BeliefMachineService',
    'ReactorWrapper',
]
