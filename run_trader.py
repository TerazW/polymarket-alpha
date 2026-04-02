"""
Market Sensemaking - Trading System Entry Point

Starts the autonomous trading system that:
1. Connects to Polymarket WebSocket for real-time data
2. Runs alpha models (HMM, BOCPD, Hawkes, VPIN, microstructure)
3. Combines signals via adaptive ensemble
4. Sizes positions using Bayesian Kelly criterion
5. Manages risk with drawdown controls and circuit breakers
6. Executes trades (paper mode by default)

Usage:
    # Paper trading (default, safe)
    python run_trader.py

    # Live trading (requires API keys)
    TRADING_PAPER_MODE=false \
    POLY_API_KEY=... \
    POLY_API_SECRET=... \
    POLY_API_PASSPHRASE=... \
    python run_trader.py

Environment variables:
    TRADING_PAPER_MODE=true     Paper trading mode (default: true)
    TRADING_BANKROLL=10000      Initial bankroll in USDC
    KELLY_MULTIPLIER=0.5        Fractional Kelly (0.25-0.5 recommended)
    RISK_MAX_DRAWDOWN=0.15      Max drawdown before halt (15%)
    TRADING_SIGNAL_INTERVAL=10  Signal generation interval (seconds)
"""

import sys
import os
import asyncio
import logging
import signal

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.trading.config import load_trading_config
from backend.trading.collector_bridge import CollectorBridge

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("trader")


async def main():
    """Main entry point for the trading system."""
    config = load_trading_config()

    logger.info("=" * 60)
    logger.info("Market Sensemaking - Trading Engine v6.0")
    logger.info("=" * 60)
    logger.info(f"Mode: {'PAPER' if config.paper_mode else 'LIVE'}")
    logger.info(f"Bankroll: ${config.risk_config.initial_bankroll:.2f}")
    logger.info(f"Kelly multiplier: {config.kelly_config.kelly_multiplier}")
    logger.info(f"Max drawdown: {config.risk_config.max_drawdown:.0%}")
    logger.info(f"Signal interval: {config.signal_interval_seconds}s")
    logger.info("=" * 60)

    if not config.paper_mode:
        logger.warning("LIVE TRADING MODE - Real money at risk!")
        logger.warning("Press Ctrl+C within 5 seconds to abort...")
        await asyncio.sleep(5)

    bridge = CollectorBridge(config=config)
    await bridge.start()

    # Graceful shutdown
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def shutdown(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Import and start collector with bridge
    try:
        from utils.polymarket_ws import PolymarketWebSocket
        from utils.polymarket_api import PolymarketAPI

        # Get top markets
        api = PolymarketAPI()
        markets = await asyncio.to_thread(api.get_top_markets)
        logger.info(f"Monitoring {len(markets)} markets")

        # Connect WebSocket
        token_ids = [m.get("yes_token_id", m.get("token_id", "")) for m in markets if m]
        token_ids = [t for t in token_ids if t]

        ws = PolymarketWebSocket(
            token_ids=token_ids,
            on_trade=lambda msg: _handle_trade(bridge, msg),
            on_book=lambda msg: _handle_book(bridge, msg),
        )

        logger.info("Starting WebSocket connection...")
        ws_task = asyncio.create_task(asyncio.to_thread(ws.connect))

        # Wait for shutdown signal
        await stop_event.wait()

    except ImportError:
        logger.info(
            "Collector not available in this environment. "
            "Running in standalone mode (manual data feed)."
        )
        # In standalone mode, just run the trading loop
        await stop_event.wait()
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        await bridge.stop()
        status = bridge.get_status()
        logger.info("Final status:")
        logger.info(f"  Total trades: {status['total_trades']}")
        logger.info(f"  Total PnL: ${status['total_pnl']:.2f}")
        logger.info(f"  Win rate: {status['win_rate']:.1%}")
        logger.info(f"  Final bankroll: ${status['portfolio']['bankroll']:.2f}")


def _handle_trade(bridge: CollectorBridge, msg: dict):
    """Adapter for collector trade messages."""
    bridge.on_trade(
        token_id=msg.get("asset_id", ""),
        timestamp_ms=int(msg.get("timestamp", 0)),
        price=float(msg.get("price", 0)),
        size=float(msg.get("size", 0)),
        side=msg.get("side", "BUY"),
    )


def _handle_book(bridge: CollectorBridge, msg: dict):
    """Adapter for collector book messages."""
    bids = msg.get("bids", [])
    asks = msg.get("asks", [])
    if bids and asks:
        bridge.on_book_snapshot(
            token_id=msg.get("asset_id", ""),
            timestamp_ms=int(msg.get("timestamp", 0)),
            bids=[(float(b["price"]), float(b["size"])) for b in bids],
            asks=[(float(a["price"]), float(a["size"])) for a in asks],
        )


if __name__ == "__main__":
    asyncio.run(main())
