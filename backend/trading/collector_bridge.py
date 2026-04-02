"""
Collector Bridge - Connects existing collector data flow to trading engine

The existing collector (backend/collector/main.py) receives WebSocket data
from Polymarket and processes it through the POC reactor pipeline.

This bridge hooks into that data flow and feeds it to the trading orchestrator's
alpha models, without modifying the existing collector code.

Integration points:
1. on_trade() callback -> feeds into Hawkes, VPIN
2. on_book() callback  -> feeds into OFI, depth imbalance, HMM, BOCPD
3. on_reaction/state_change callbacks -> feeds belief state into signals
"""

import logging
from typing import Optional, Dict
from decimal import Decimal

from backend.trading.trader import TradingOrchestrator, TradingConfig

logger = logging.getLogger(__name__)


class CollectorBridge:
    """
    Bridge between existing collector and trading engine.

    Usage:
        # In collector initialization
        bridge = CollectorBridge()
        bridge.start()

        # In collector's on_trade callback
        bridge.on_trade(token_id, timestamp, price, size, side)

        # In collector's on_book callback
        bridge.on_book_snapshot(token_id, timestamp, bids, asks)
    """

    def __init__(self, config: Optional[TradingConfig] = None):
        self.config = config or TradingConfig(paper_mode=True)
        self.trader = TradingOrchestrator(config=self.config)
        self._started = False

    async def start(self):
        """Start the trading engine."""
        if not self._started:
            await self.trader.start()
            self._started = True
            logger.info("CollectorBridge started - trading engine active")

    async def stop(self):
        """Stop the trading engine."""
        if self._started:
            await self.trader.stop()
            self._started = False

    def on_trade(
        self,
        token_id: str,
        timestamp_ms: int,
        price: float,
        size: float,
        side: str,
    ):
        """
        Called when collector processes a trade event.

        Maps to collector's existing on_trade / on_last_trade_price handler.
        """
        if not self._started:
            return

        ts_seconds = timestamp_ms / 1000.0

        # Convert Decimal price if needed
        if isinstance(price, Decimal):
            price = float(price)

        self.trader.on_trade(
            token_id=token_id,
            timestamp=ts_seconds,
            price=price,
            size=size,
            side=side,
        )

    def on_book_snapshot(
        self,
        token_id: str,
        timestamp_ms: int,
        bids: list,
        asks: list,
    ):
        """
        Called when collector processes a book snapshot.

        Args:
            bids: [(price, size), ...] sorted by price descending
            asks: [(price, size), ...] sorted by price ascending
        """
        if not self._started:
            return

        if not bids or not asks:
            return

        ts_seconds = timestamp_ms / 1000.0

        # Extract best bid/ask
        best_bid_price = float(bids[0][0]) if isinstance(bids[0][0], Decimal) else bids[0][0]
        best_bid_size = float(bids[0][1])
        best_ask_price = float(asks[0][0]) if isinstance(asks[0][0], Decimal) else asks[0][0]
        best_ask_size = float(asks[0][1])

        # Multi-level depth
        bid_levels = [
            (float(p) if isinstance(p, Decimal) else p, float(s))
            for p, s in bids[:10]
        ]
        ask_levels = [
            (float(p) if isinstance(p, Decimal) else p, float(s))
            for p, s in asks[:10]
        ]

        self.trader.on_book_update(
            token_id=token_id,
            timestamp=ts_seconds,
            bid_price=best_bid_price,
            ask_price=best_ask_price,
            bid_size=best_bid_size,
            ask_size=best_ask_size,
            bid_levels=bid_levels,
            ask_levels=ask_levels,
        )

    def on_belief_state_change(self, token_id: str, new_state: str):
        """Called when reactor detects a belief state change."""
        if not self._started:
            return
        self.trader.on_belief_state_change(token_id, new_state)

    def on_reaction(self, token_id: str, reaction_type: str, window_type: str):
        """
        Called when reactor classifies a reaction.

        Reactions feed into the belief state signal. The more severe the
        reaction (VACUUM, SWEEP, PULL), the more it shifts belief_state_signal.
        """
        # The belief state machine already processes reactions into state changes.
        # This callback is for logging/additional signal processing.
        if not self._started:
            return

        logger.debug(
            f"Reaction: {token_id[:8]}... {reaction_type} ({window_type})"
        )

    def on_market_resolution(self, token_id: str, outcome: int):
        """Called when a market resolves (YES=1, NO=0)."""
        if not self._started:
            return
        self.trader.on_market_resolution(token_id, outcome)

    def get_status(self) -> Dict:
        """Get trading system status."""
        return self.trader.get_status()
