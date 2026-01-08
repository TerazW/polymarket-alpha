"""
System Module (v5.31)

Provides unified system management:
- SystemStartupManager: Coordinates all service startup/shutdown
- ServiceHealth: Aggregated health status
"""

from .startup import (
    SystemStartupManager,
    ServiceStatus,
    SystemHealth,
)

__all__ = [
    'SystemStartupManager',
    'ServiceStatus',
    'SystemHealth',
]
