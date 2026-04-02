"""
Collector Bridge - Connects existing collector data flow to trading engine

v6.1 FIX: Belief State is now the PRIMARY alpha signal, not just one of
many ensemble inputs. Reactions are forwarded with side information so
the signal layer can determine directionality.

Integration:
1. on_trade()              → Hawkes, VPIN (risk gates)
2. on_book_snapshot()      → OFI, depth imbalance, HMM, BOCPD (risk gates)
3. on_belief_state_change() → PRIMARY directional signal
4. on_reaction()            → Reaction side → directional context for belief state
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
        bridge = CollectorBridge()
        await bridge.start()

        # From collector callbacks:
        bridge.on_trade(token_id, timestamp, price, size, side)
        bridge.on_book_snapshot(token_id, timestamp, bids, asks)
        bridge.on_belief_state_change(token_id, new_state)
        bridge.on_reaction(token_id, reaction_type, window_type, side)
    """

    def __init__(self, config: Optional[TradingConfig] = None):
        self.config = config or TradingConfig(paper_mode=True)
        self.trader = TradingOrchestrator(config=self.config)
        self._started = False

    async def start(self):
        if not self._started:
            await self.trader.start()
            self._started = True
            logger.info("CollectorBridge started - trading engine active")

    async def stop(self):
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
        """Called when collector processes a trade event."""
        if not self._started:
            return

        ts_seconds = timestamp_ms / 1000.0
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
        """Called when collector processes a book snapshot."""
        if not self._started or not bids or not asks:
            return

        ts_seconds = timestamp_ms / 1000.0

        best_bid_price = float(bids[0][0]) if isinstance(bids[0][0], Decimal) else bids[0][0]
        best_bid_size = float(bids[0][1])
        best_ask_price = float(asks[0][0]) if isinstance(asks[0][0], Decimal) else asks[0][0]
        best_ask_size = float(asks[0][1])

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
        """
        Called when reactor detects a belief state change.

        This is the PRIMARY alpha signal. State transitions
        (especially toward CRACKING/BROKEN) indicate market dislocation.
        """
        if not self._started:
            return
        self.trader.on_belief_state_change(token_id, new_state)

    def on_reaction(
        self,
        token_id: str,
        reaction_type: str,
        window_type: str,
        side: str = "bid",
    ):
        """
        Called when reactor classifies a reaction.

        v6.1: Now forwards the SIDE information which is critical for
        determining directionality:
          - Reaction on bid side → bid liquidity collapsing → bearish
          - Reaction on ask side → ask liquidity collapsing → bullish

        This side info, combined with reaction severity, drives the
        belief state directional signal.
        """
        if not self._started:
            return

        self.trader.on_reaction(token_id, reaction_type, side)

        logger.debug(
            f"Reaction: {token_id[:8]}... {reaction_type} ({window_type}) "
            f"side={side}"
        )

    def on_market_resolution(self, token_id: str, outcome: int):
        """Called when a market resolves (YES=1, NO=0)."""
        if not self._started:
            return
        self.trader.on_market_resolution(token_id, outcome)

    def get_status(self) -> Dict:
        return self.trader.get_status()
