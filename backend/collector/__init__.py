"""
Belief Reaction System - Backend Collector Module (v5.29)

Integrates POC DataCollector into the backend, connecting it to ReactorService.

Components:
- CollectorService: Manages WebSocket data collection
- IntegratedCollectorReactor: Combined collector + reactor service

Usage:
    from backend.collector import CollectorService

    collector = CollectorService(token_ids=['token1', 'token2'])
    await collector.start()
    # ... data flows automatically to reactor
    await collector.stop()
"""

from .service import CollectorService, IntegratedCollectorReactor
from poc.collector import ConnectionState

__all__ = ['CollectorService', 'IntegratedCollectorReactor', 'ConnectionState']
