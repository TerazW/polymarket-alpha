"""
Trading Orchestrator

The main trading loop that:
1. Receives real-time data from the collector
2. Feeds data into alpha models
3. Generates trading signals
4. Sizes positions via Kelly criterion
5. Passes through risk management
6. Executes approved trades

This is the entry point for the autonomous trading system.
"""

import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Set
from collections import deque

from backend.strategy.signals import SignalAggregator, MarketSignals
from backend.strategy.kelly import KellyPositionSizer, KellyConfig
from backend.strategy.risk_manager import RiskManager, RiskConfig, RiskLevel
from backend.execution.polymarket_client import (
    PolymarketExecutionClient,
    OrderRequest,
    OrderSide,
    OrderType,
)

logger = logging.getLogger(__name__)


@dataclass
class TradingConfig:
    """Trading system configuration."""
    # Trading intervals
    signal_interval_seconds: float = 10.0    # Generate signals every N seconds
    feedback_interval_seconds: float = 60.0  # Provide feedback to ensemble every N seconds

    # Trade triggers
    min_direction_strength: float = 0.15     # Minimum |direction| to consider trading
    min_edge: float = 0.02                   # Minimum edge to trade
    min_confidence: float = 0.55             # Minimum confidence

    # Execution
    paper_mode: bool = True                  # Paper trading by default
    max_slippage: float = 0.01              # Max acceptable slippage from signal price

    # Kelly
    kelly_config: KellyConfig = field(default_factory=KellyConfig)

    # Risk
    risk_config: RiskConfig = field(default_factory=RiskConfig)


@dataclass
class TradeRecord:
    """Record of an executed trade."""
    trade_id: str
    timestamp: float
    market_id: str
    side: str
    price: float
    size_usd: float
    quantity: float
    signals: Dict
    risk_check: Dict
    order_id: str = ""
    pnl: Optional[float] = None
    settled: bool = False


class TradingOrchestrator:
    """
    Main trading system orchestrator.

    Lifecycle:
        1. start() -> begins the trading loop
        2. on_book_update() / on_trade() -> receives data from collector
        3. _generate_and_execute() -> periodic signal generation + execution
        4. stop() -> graceful shutdown
    """

    def __init__(self, config: Optional[TradingConfig] = None):
        self.config = config or TradingConfig()

        # Core components
        self.signals = SignalAggregator()
        self.kelly = KellyPositionSizer(config=self.config.kelly_config)
        self.risk = RiskManager(config=self.config.risk_config)
        self.execution = PolymarketExecutionClient(paper_mode=self.config.paper_mode)

        # State
        self._running = False
        self._market_prices: Dict[str, float] = {}
        self._active_markets: Set[str] = set()
        self._trade_history: deque = deque(maxlen=10000)
        self._last_signal_time: float = 0.0
        self._last_feedback_time: float = 0.0
        self._signal_snapshots: Dict[str, deque] = {}  # For feedback

        # Statistics
        self._total_trades = 0
        self._total_pnl = 0.0
        self._winning_trades = 0

    async def start(self):
        """Start the trading system."""
        self._running = True
        logger.info(
            f"Trading Orchestrator started "
            f"(paper_mode={self.config.paper_mode}, "
            f"bankroll=${self.config.risk_config.initial_bankroll:.2f})"
        )

        # Start the periodic signal generation loop
        asyncio.create_task(self._signal_loop())

    async def stop(self):
        """Stop the trading system gracefully."""
        self._running = False
        logger.info(
            f"Trading Orchestrator stopped. "
            f"Total trades: {self._total_trades}, "
            f"Total PnL: ${self._total_pnl:.2f}, "
            f"Win rate: {self._win_rate():.1%}"
        )

    # --- Data input interface (called by collector) ---

    def on_book_update(
        self,
        token_id: str,
        timestamp: float,
        bid_price: float,
        ask_price: float,
        bid_size: float,
        ask_size: float,
        bid_levels: Optional[list] = None,
        ask_levels: Optional[list] = None,
    ):
        """Receive order book update from collector."""
        self._active_markets.add(token_id)
        mid = (bid_price + ask_price) / 2.0
        self._market_prices[token_id] = mid

        proc = self.signals.get_processor(token_id)
        proc.on_book_update(
            timestamp, bid_price, ask_price, bid_size, ask_size,
            bid_levels, ask_levels,
        )

    def on_trade(
        self,
        token_id: str,
        timestamp: float,
        price: float,
        size: float,
        side: str,
    ):
        """Receive trade event from collector."""
        self._active_markets.add(token_id)
        self._market_prices[token_id] = price

        proc = self.signals.get_processor(token_id)
        proc.on_trade(timestamp, price, size, side)

    def on_belief_state_change(self, token_id: str, new_state: str):
        """Receive belief state change from reactor."""
        proc = self.signals.get_processor(token_id)
        proc.on_belief_state_change(new_state)

    def on_market_resolution(self, token_id: str, outcome: int):
        """Handle market resolution."""
        # Settle position
        pnl = self.risk.settle_position(token_id, outcome)
        if pnl is not None:
            self._total_pnl += pnl
            if pnl > 0:
                self._winning_trades += 1

            # Settle in execution client
            if self.config.paper_mode:
                self.execution.paper_settle(
                    token_id, 1.0 if outcome == 1 else 0.0
                )

            # Update Kelly posterior
            self.kelly.update_outcome(token_id, outcome)

            logger.info(
                f"Market resolved: {token_id[:8]}... "
                f"outcome={'YES' if outcome == 1 else 'NO'} "
                f"pnl=${pnl:.2f}"
            )

    # --- Core trading loop ---

    async def _signal_loop(self):
        """Periodic signal generation and trade execution."""
        while self._running:
            try:
                now = time.time()

                # Generate signals
                if now - self._last_signal_time >= self.config.signal_interval_seconds:
                    await self._generate_and_execute()
                    self._last_signal_time = now

                # Provide feedback to ensemble
                if now - self._last_feedback_time >= self.config.feedback_interval_seconds:
                    self._provide_feedback()
                    self._last_feedback_time = now

                await asyncio.sleep(1.0)

            except Exception as e:
                logger.error(f"Error in signal loop: {e}", exc_info=True)
                await asyncio.sleep(5.0)

    async def _generate_and_execute(self):
        """Generate signals for all markets and execute trades."""
        if not self._market_prices:
            return

        all_signals = self.signals.generate_all_signals(self._market_prices)

        for token_id, sig in all_signals.items():
            # Store for feedback
            if token_id not in self._signal_snapshots:
                self._signal_snapshots[token_id] = deque(maxlen=100)
            self._signal_snapshots[token_id].append(sig)

            # Check if signal is strong enough
            if sig.direction_strength < self.config.min_direction_strength:
                continue

            # Update regime in risk manager
            self.risk.update_regime(sig.regime)

            # Skip if VPIN is extreme (flow too toxic)
            if sig.toxicity_level == "EXTREME":
                logger.debug(f"{token_id[:8]}: Skipping due to extreme VPIN")
                continue

            # Size position via Kelly
            market_price = self._market_prices.get(token_id, 0.5)
            sizing = self.kelly.size_position(
                market_id=token_id,
                p_estimate=sig.p_estimate,
                market_price=market_price,
                bankroll=self.risk.bankroll,
            )

            if sizing["side"] is None or sizing["size_usd"] < 1.0:
                continue

            # Risk check
            risk_result = self.risk.evaluate_trade(
                market_id=token_id,
                side=sizing["side"],
                size_usd=sizing["size_usd"],
                entry_price=market_price,
            )

            if not risk_result["approved"]:
                logger.debug(
                    f"{token_id[:8]}: Trade rejected by risk: {risk_result['reason']}"
                )
                continue

            # Execute trade
            adjusted_size = risk_result["adjusted_size"]
            await self._execute_trade(
                token_id=token_id,
                side=sizing["side"],
                price=market_price,
                size_usd=adjusted_size,
                signals=sig,
                risk_check=risk_result,
            )

    async def _execute_trade(
        self,
        token_id: str,
        side: str,
        price: float,
        size_usd: float,
        signals: MarketSignals,
        risk_check: Dict,
    ):
        """Execute a single trade."""
        order_side = OrderSide.BUY  # Always buying the token we want
        order = OrderRequest(
            token_id=token_id,
            side=order_side,
            price=price,
            size=size_usd,
        )

        response = await self.execution.place_order(order)

        if response.status == "MATCHED":
            quantity = size_usd / price if price > 0 else 0

            # Record in risk manager
            self.risk.open_position(
                market_id=token_id,
                side=side,
                entry_price=price,
                size=size_usd,
                quantity=quantity,
            )

            # Record trade
            record = TradeRecord(
                trade_id=response.order_id,
                timestamp=time.time(),
                market_id=token_id,
                side=side,
                price=price,
                size_usd=size_usd,
                quantity=quantity,
                signals={
                    "direction": signals.direction,
                    "p_estimate": signals.p_estimate,
                    "regime": signals.regime,
                    "vpin": signals.vpin,
                    "belief_state": signals.belief_state,
                    "confidence": signals.p_confidence,
                },
                risk_check=risk_check,
                order_id=response.order_id,
            )
            self._trade_history.append(record)
            self._total_trades += 1

            logger.info(
                f"TRADE: {side} {token_id[:8]}... "
                f"${size_usd:.2f} @ {price:.4f} "
                f"(edge={signals.p_estimate - price:+.3f}, "
                f"regime={signals.regime}, "
                f"vpin={signals.vpin:.2f})"
            )
        elif response.error:
            logger.warning(f"Order rejected: {response.error}")

    def _provide_feedback(self):
        """Provide price-move feedback to ensemble for weight learning."""
        for token_id, snapshots in self._signal_snapshots.items():
            if len(snapshots) < 2:
                continue

            # Compare current price to price at signal time
            current_price = self._market_prices.get(token_id)
            if current_price is None:
                continue

            old_sig = snapshots[0]
            if old_sig.timestamp == 0:
                continue

            old_price = self._market_prices.get(token_id, 0.5)
            price_move = current_price - old_price

            proc = self.signals.get_processor(token_id)
            proc.feedback(price_move)

    def _win_rate(self) -> float:
        if self._total_trades == 0:
            return 0.0
        return self._winning_trades / self._total_trades

    # --- Status and reporting ---

    def get_status(self) -> Dict:
        """Get current trading system status."""
        portfolio = self.risk.get_portfolio_summary()
        return {
            "running": self._running,
            "paper_mode": self.config.paper_mode,
            "portfolio": portfolio,
            "active_markets": len(self._active_markets),
            "total_trades": self._total_trades,
            "total_pnl": self._total_pnl,
            "win_rate": self._win_rate(),
            "recent_trades": [
                {
                    "market": t.market_id[:8],
                    "side": t.side,
                    "price": t.price,
                    "size": t.size_usd,
                    "signals": t.signals,
                }
                for t in list(self._trade_history)[-10:]
            ],
        }

    def get_signal_snapshot(self, token_id: str) -> Optional[MarketSignals]:
        """Get latest signals for a market."""
        snapshots = self._signal_snapshots.get(token_id)
        if snapshots:
            return snapshots[-1]
        return None
