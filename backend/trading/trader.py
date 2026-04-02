"""
Trading Orchestrator (v6.1 — Architectural Fix)

DESIGN CHANGES:

1. Belief State is the PRIMARY directional signal.
   - STABLE: no trade (trust the market)
   - FRAGILE: watch closely, maybe trade small
   - CRACKING/BROKEN: market dislocated, this is where edge lives

2. Microstructure signals are RISK GATES, not direction:
   - VPIN high → don't trade (toxic flow)
   - Hawkes endogeneity high → don't trade (herding cascade)
   - HMM volatile → reduce size

3. Kelly uses p_estimate directly (no posterior self-feeding).

4. Reactions carry SIDE information for directionality.
"""

import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Set
from collections import deque

from backend.strategy.signals import (
    SignalAggregator, MarketSignals, TradeGateVerdict,
)
from backend.strategy.kelly import KellyPositionSizer, KellyConfig
from backend.strategy.risk_manager import RiskManager, RiskConfig, RiskLevel
from backend.strategy.cost_model import TransactionCostModel, CostConfig
from backend.strategy.market_filter import MarketFilter, MarketFilterConfig, MarketSnapshot
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
    signal_interval_seconds: float = 10.0
    feedback_interval_seconds: float = 60.0

    # Trade triggers — based on belief state, not direction strength
    min_belief_severity: float = 0.3   # FRAGILE or worse to consider trading
    min_edge: float = 0.02             # Minimum 2% edge
    min_confidence: float = 0.55

    # Execution
    paper_mode: bool = True
    max_slippage: float = 0.01

    # Kelly
    kelly_config: KellyConfig = field(default_factory=KellyConfig)

    # Risk
    risk_config: RiskConfig = field(default_factory=RiskConfig)

    # Costs
    cost_config: CostConfig = field(default_factory=CostConfig)

    # Market filter
    filter_config: MarketFilterConfig = field(default_factory=MarketFilterConfig)


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

    Decision flow:
      1. Belief State → "Is there a dislocation?" (primary alpha)
      2. Risk Gates → "Is it safe to trade now?" (VPIN, Hawkes, regime)
      3. Kelly → "How much?" (position sizing from edge estimate)
      4. Risk Manager → "Portfolio-level OK?" (drawdown, limits)
      5. Execution → place order
    """

    def __init__(self, config: Optional[TradingConfig] = None):
        self.config = config or TradingConfig()

        # Core components
        self.signals = SignalAggregator()
        self.kelly = KellyPositionSizer(config=self.config.kelly_config)
        self.risk = RiskManager(config=self.config.risk_config)
        self.cost = TransactionCostModel(config=self.config.cost_config)
        self.market_filter = MarketFilter(config=self.config.filter_config)
        self.execution = PolymarketExecutionClient(paper_mode=self.config.paper_mode)

        # Market metadata for filtering
        self._market_metadata: Dict[str, Dict] = {}  # token_id → {volume_24h, depth, ...}

        # State
        self._running = False
        self._market_prices: Dict[str, float] = {}
        self._active_markets: Set[str] = set()
        self._trade_history: deque = deque(maxlen=10000)
        self._last_signal_time: float = 0.0
        self._signal_snapshots: Dict[str, deque] = {}

        # Statistics
        self._total_trades = 0
        self._total_pnl = 0.0
        self._winning_trades = 0

    async def start(self):
        self._running = True
        logger.info(
            f"Trading Orchestrator started "
            f"(paper_mode={self.config.paper_mode}, "
            f"bankroll=${self.config.risk_config.initial_bankroll:.2f})"
        )
        asyncio.create_task(self._signal_loop())

    async def stop(self):
        self._running = False
        logger.info(
            f"Trading Orchestrator stopped. "
            f"Total trades: {self._total_trades}, "
            f"Total PnL: ${self._total_pnl:.2f}, "
            f"Win rate: {self._win_rate():.1%}"
        )

    # --- Data input interface (called by collector bridge) ---

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
        self._active_markets.add(token_id)
        mid = (bid_price + ask_price) / 2.0
        self._market_prices[token_id] = mid
        proc = self.signals.get_processor(token_id)
        proc.on_book_update(
            timestamp, bid_price, ask_price, bid_size, ask_size,
            bid_levels, ask_levels,
        )

    def on_trade(
        self, token_id: str, timestamp: float,
        price: float, size: float, side: str,
    ):
        self._active_markets.add(token_id)
        self._market_prices[token_id] = price
        proc = self.signals.get_processor(token_id)
        proc.on_trade(timestamp, price, size, side)

    def on_belief_state_change(self, token_id: str, new_state: str):
        """PRIMARY alpha signal."""
        proc = self.signals.get_processor(token_id)
        proc.on_belief_state_change(new_state)

    def on_reaction(self, token_id: str, reaction_type: str, side: str):
        """Reaction with side info for directionality."""
        proc = self.signals.get_processor(token_id)
        proc.on_reaction(reaction_type, side)

    def on_market_resolution(self, token_id: str, outcome: int):
        pnl = self.risk.settle_position(token_id, outcome)
        if pnl is not None:
            self._total_pnl += pnl
            if pnl > 0:
                self._winning_trades += 1

            if self.config.paper_mode:
                self.execution.paper_settle(
                    token_id, 1.0 if outcome == 1 else 0.0
                )

            # This is the ONLY valid posterior update
            self.kelly.update_outcome(token_id, outcome)

            logger.info(
                f"Market resolved: {token_id[:8]}... "
                f"outcome={'YES' if outcome == 1 else 'NO'} "
                f"pnl=${pnl:.2f}"
            )

    # --- Core trading loop ---

    async def _signal_loop(self):
        while self._running:
            try:
                now = time.time()
                if now - self._last_signal_time >= self.config.signal_interval_seconds:
                    await self._generate_and_execute()
                    self._last_signal_time = now
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"Error in signal loop: {e}", exc_info=True)
                await asyncio.sleep(5.0)

    async def _generate_and_execute(self):
        if not self._market_prices:
            return

        all_signals = self.signals.generate_all_signals(self._market_prices)

        for token_id, sig in all_signals.items():
            if token_id not in self._signal_snapshots:
                self._signal_snapshots[token_id] = deque(maxlen=100)
            self._signal_snapshots[token_id].append(sig)

            # === STEP 1: Belief state filter (primary alpha) ===
            # Only trade when belief state indicates dislocation
            if sig.belief_state_severity < self.config.min_belief_severity:
                continue  # STABLE market, no edge

            if sig.edge_direction == "NONE":
                continue  # No directional signal

            # === STEP 2: Risk gates ===
            if sig.gate.verdict == TradeGateVerdict.NO_TRADE:
                logger.debug(
                    f"{token_id[:8]}: Risk gate blocked: {sig.gate.reasons}"
                )
                continue

            # Update regime in risk manager
            self.risk.update_regime(sig.hmm_regime)

            # === STEP 3: Cost check — is edge profitable after costs? ===
            market_price = self._market_prices.get(token_id, 0.5)
            meta = self._market_metadata.get(token_id, {})
            cost_check = self.cost.is_trade_profitable(
                edge=sig.edge,
                price=market_price,
                size_usd=self.risk.bankroll * 0.05,
                spread=meta.get("spread"),
                book_depth_usd=meta.get("depth_usd"),
                daily_volume=meta.get("volume_24h"),
            )

            if not cost_check["profitable_hold_to_resolution"]:
                logger.debug(
                    f"{token_id[:8]}: Edge {sig.edge:.3f} insufficient after costs "
                    f"(cost={cost_check['total_cost_one_way']:.3f})"
                )
                continue

            # === STEP 4: Kelly sizing (using NET edge) ===
            sizing = self.kelly.size_position(
                market_id=token_id,
                p_estimate=sig.p_estimate,
                market_price=market_price,
                bankroll=self.risk.bankroll,
                belief_state=sig.belief_state,
            )

            if sizing["side"] is None or sizing["size_usd"] < 1.0:
                continue

            # Apply risk gate size scaling
            adjusted_kelly_size = sizing["size_usd"] * sig.gate.size_scale

            # === STEP 5: Portfolio risk check ===
            risk_result = self.risk.evaluate_trade(
                market_id=token_id,
                side=sizing["side"],
                size_usd=adjusted_kelly_size,
                entry_price=market_price,
            )

            if not risk_result["approved"]:
                logger.debug(
                    f"{token_id[:8]}: Risk rejected: {risk_result['reason']}"
                )
                continue

            # === STEP 6: Execute ===
            await self._execute_trade(
                token_id=token_id,
                side=sizing["side"],
                price=market_price,
                size_usd=risk_result["adjusted_size"],
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
        order = OrderRequest(
            token_id=token_id,
            side=OrderSide.BUY,
            price=price,
            size=size_usd,
        )

        response = await self.execution.place_order(order)

        if response.status == "MATCHED":
            quantity = size_usd / price if price > 0 else 0

            self.risk.open_position(
                market_id=token_id,
                side=side,
                entry_price=price,
                size=size_usd,
                quantity=quantity,
            )

            record = TradeRecord(
                trade_id=response.order_id,
                timestamp=time.time(),
                market_id=token_id,
                side=side,
                price=price,
                size_usd=size_usd,
                quantity=quantity,
                signals={
                    "p_estimate": signals.p_estimate,
                    "edge": signals.edge,
                    "belief_state": signals.belief_state,
                    "belief_severity": signals.belief_state_severity,
                    "belief_direction": signals.belief_state_direction,
                    "vpin": signals.vpin,
                    "hmm_regime": signals.hmm_regime,
                    "gate_verdict": signals.gate.verdict.value,
                    "gate_scale": signals.gate.size_scale,
                    "changepoint_prob": signals.changepoint_prob,
                },
                risk_check=risk_check,
                order_id=response.order_id,
            )
            self._trade_history.append(record)
            self._total_trades += 1

            logger.info(
                f"TRADE: {side} {token_id[:8]}... "
                f"${size_usd:.2f} @ {price:.4f} "
                f"(edge={signals.edge:+.3f}, "
                f"belief={signals.belief_state}, "
                f"gate={signals.gate.verdict.value}, "
                f"vpin={signals.vpin:.2f})"
            )
        elif response.error:
            logger.warning(f"Order rejected: {response.error}")

    def _win_rate(self) -> float:
        if self._total_trades == 0:
            return 0.0
        return self._winning_trades / self._total_trades

    # --- Status ---

    def get_status(self) -> Dict:
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
        snapshots = self._signal_snapshots.get(token_id)
        if snapshots:
            return snapshots[-1]
        return None
