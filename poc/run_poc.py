#!/usr/bin/env python3
"""
Belief Reaction System - POC Runner
Connects to Polymarket WebSocket and detects belief reactions in real-time.

Usage:
    python -m poc.run_poc [--markets N] [--verbose]

"看存在没意义，看反应才有意义"
"Observing existence is meaningless; observing REACTION is everything."
"""

import sys
import os
import json
import time
import argparse
import threading
from datetime import datetime
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from websocket import WebSocketApp

from poc.reaction_engine import ReactionEngine
from poc.models import ReactionEvent, BeliefStateChange, STATE_INDICATORS


# ANSI color codes for console output
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"


# Reaction type colors
REACTION_COLORS = {
    'HOLD': Colors.GREEN,
    'DELAY': Colors.YELLOW,
    'PULL': Colors.MAGENTA,
    'VACUUM': Colors.RED,
    'CHASE': Colors.CYAN,
    'FAKE': Colors.BLUE,
}

# State colors
STATE_COLORS = {
    'STABLE': Colors.GREEN,
    'FRAGILE': Colors.YELLOW,
    'CRACKING': Colors.MAGENTA,
    'BROKEN': Colors.RED,
}


class ConsolePrinter:
    """Handles console output with colors and formatting."""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.lock = threading.Lock()

    def log(self, message: str, color: str = Colors.WHITE):
        """Print a timestamped log message."""
        with self.lock:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"{Colors.GRAY}[{timestamp}]{Colors.RESET} {color}{message}{Colors.RESET}")

    def header(self, title: str):
        """Print a header."""
        with self.lock:
            print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}")
            print(f"{Colors.BOLD}{Colors.CYAN}  {title}{Colors.RESET}")
            print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.RESET}\n")

    def alert(self, alert: dict):
        """Print an alert based on type."""
        alert_type = alert.get('type', '')

        if alert_type == 'SHOCK':
            self._print_shock_alert(alert)
        elif alert_type == 'REACTION':
            self._print_reaction_alert(alert)
        elif alert_type == 'STATE_CHANGE':
            self._print_state_change_alert(alert)

    def _print_shock_alert(self, alert: dict):
        """Print shock detection alert."""
        if not self.verbose:
            return

        self.log(
            f"SHOCK @ {alert['price']} ({alert['side']}) "
            f"- {alert['trigger']} trigger "
            f"- vol: {alert['volume']:.1f} / liq: {alert['liquidity_before']:.1f}",
            Colors.YELLOW
        )

    def _print_reaction_alert(self, alert: dict):
        """Print reaction classification alert."""
        reaction_type = alert.get('reaction_type', 'DELAY')
        color = REACTION_COLORS.get(reaction_type, Colors.WHITE)

        self.log(
            f"{Colors.BOLD}{reaction_type}{Colors.RESET}{color} "
            f"@ {alert['price']} "
            f"(refill: {alert['refill_ratio']})",
            color
        )

    def _print_state_change_alert(self, alert: dict):
        """Print state change alert - the most important alert."""
        old_state = alert.get('old_state', 'STABLE')
        new_state = alert.get('new_state', 'STABLE')
        old_color = STATE_COLORS.get(old_state, Colors.WHITE)
        new_color = STATE_COLORS.get(new_state, Colors.WHITE)

        with self.lock:
            print()
            print(f"{Colors.BOLD}{'*'*60}{Colors.RESET}")
            print(f"{Colors.BOLD}  STATE CHANGE: {old_color}{old_state}{Colors.RESET} → {new_color}{Colors.BOLD}{new_state}{Colors.RESET}")
            print(f"  Token: {alert.get('token_id', '')[:20]}...")

            for evidence in alert.get('evidence', []):
                print(f"  • {evidence}")

            print(f"{Colors.BOLD}{'*'*60}{Colors.RESET}")
            print()

    def stats(self, engine: ReactionEngine):
        """Print engine statistics."""
        stats = engine.get_stats()

        with self.lock:
            print(f"\n{Colors.CYAN}--- Statistics ---{Colors.RESET}")
            print(f"  Trades: {stats['trades_processed']}")
            print(f"  Price Changes: {stats['price_changes_processed']}")
            print(f"  Books: {stats['books_processed']}")
            print(f"  Shocks: {stats['shocks_detected']}")
            print(f"  Reactions: {stats['reactions_classified']}")
            print(f"  State Changes: {stats['state_changes']}")

            classifier_stats = stats.get('classifier', {})
            by_type = classifier_stats.get('by_type', {})
            if by_type:
                print(f"\n  Reactions by type:")
                for rtype, count in by_type.items():
                    color = REACTION_COLORS.get(rtype, Colors.WHITE)
                    print(f"    {color}{rtype}: {count}{Colors.RESET}")

            belief_stats = stats.get('belief_engine', {})
            dist = belief_stats.get('state_distribution', {})
            if dist:
                print(f"\n  Markets by state:")
                for state, count in dist.items():
                    color = STATE_COLORS.get(state, Colors.WHITE)
                    print(f"    {color}{state}: {count}{Colors.RESET}")

            print()


def get_active_markets(limit: int = 10) -> List[str]:
    """
    Get active market token IDs from the database.
    Falls back to some known active markets if database is unavailable.
    """
    try:
        from utils.db import engine as db_engine
        from sqlalchemy import text

        with db_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT token_id
                FROM markets
                WHERE active = TRUE AND closed = FALSE
                ORDER BY volume_24h DESC NULLS LAST
                LIMIT :limit
            """), {"limit": limit})
            tokens = [row[0] for row in result.fetchall()]

            if tokens:
                return tokens

    except Exception as e:
        print(f"Could not fetch markets from database: {e}")

    # Fallback: Return some known active Polymarket tokens
    # These are example token IDs - you may need to update them
    print("Using fallback market tokens...")
    return [
        # Add some known active token IDs here if needed
    ]


def run_poc(
    token_ids: List[str],
    verbose: bool = True,
    duration_minutes: int = 0
):
    """
    Run the POC with specified token IDs.

    Args:
        token_ids: List of token IDs to monitor
        verbose: Print verbose output
        duration_minutes: Run for N minutes (0 = indefinitely)
    """
    if not token_ids:
        print("No token IDs provided. Please specify markets to monitor.")
        return

    printer = ConsolePrinter(verbose=verbose)

    printer.header("Belief Reaction System - POC")
    print(f"  Monitoring {len(token_ids)} markets")
    print(f"  Verbose: {verbose}")
    if duration_minutes > 0:
        print(f"  Duration: {duration_minutes} minutes")
    print()
    print(f'  "看存在没意义，看反应才有意义"')
    print(f'  "Observing existence is meaningless; observing REACTION is everything."')
    print()

    # Create reaction engine
    engine = ReactionEngine(
        on_reaction=lambda r: printer.log(
            f"Reaction: {r.reaction_type.value} @ {r.price}",
            REACTION_COLORS.get(r.reaction_type.value, Colors.WHITE)
        ) if verbose else None,
        on_state_change=lambda c: None,  # Handled by alert
        on_alert=printer.alert
    )

    # Start the engine
    engine.start()

    # WebSocket handlers
    def on_open(ws):
        printer.log("Connected to Polymarket WebSocket", Colors.GREEN)
        printer.log(f"Subscribing to {len(token_ids)} assets...", Colors.CYAN)

        subscribe_msg = {
            "assets_ids": token_ids,
            "type": "market"
        }
        ws.send(json.dumps(subscribe_msg))

    def on_message(ws, message: str):
        try:
            if message == "PONG":
                return

            data = json.loads(message)
            event_type = data.get("event_type", "")

            if event_type == "last_trade_price":
                engine.on_trade(data)
            elif event_type == "book":
                engine.on_book(data)
            elif event_type == "price_change":
                engine.on_price_change(data)

        except json.JSONDecodeError:
            printer.log(f"Invalid JSON: {message[:100]}", Colors.RED)
        except Exception as e:
            printer.log(f"Error: {e}", Colors.RED)

    def on_error(ws, error):
        printer.log(f"WebSocket error: {error}", Colors.RED)

    def on_close(ws, close_status_code, close_msg):
        printer.log(f"WebSocket closed: {close_status_code} - {close_msg}", Colors.YELLOW)

    # Ping loop
    def ping_loop(ws, stop_event):
        while not stop_event.is_set():
            try:
                ws.send("PING")
            except:
                break
            stop_event.wait(10)

    # Stats loop
    def stats_loop(stop_event):
        while not stop_event.is_set():
            stop_event.wait(60)  # Print stats every minute
            if not stop_event.is_set():
                printer.stats(engine)

    # Create WebSocket
    ws = WebSocketApp(
        "wss://ws-subscriptions-clob.polymarket.com/ws/market",
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    # Start threads
    stop_event = threading.Event()
    ping_thread = threading.Thread(target=ping_loop, args=(ws, stop_event), daemon=True)
    stats_thread = threading.Thread(target=stats_loop, args=(stop_event,), daemon=True)

    # Run WebSocket
    def run_ws():
        ws.run_forever()

    ws_thread = threading.Thread(target=run_ws, daemon=True)
    ws_thread.start()

    # Wait a moment for connection
    time.sleep(2)

    # Start ping and stats
    ping_thread.start()
    stats_thread.start()

    # Run loop
    try:
        start_time = time.time()
        while True:
            time.sleep(1)

            if duration_minutes > 0:
                elapsed = (time.time() - start_time) / 60
                if elapsed >= duration_minutes:
                    printer.log(f"Duration reached ({duration_minutes} minutes)", Colors.CYAN)
                    break

    except KeyboardInterrupt:
        printer.log("\nShutting down...", Colors.YELLOW)

    # Cleanup
    stop_event.set()
    engine.stop()
    ws.close()

    # Final stats
    printer.header("Final Statistics")
    printer.stats(engine)


def main():
    parser = argparse.ArgumentParser(
        description='Belief Reaction System POC - Real-time belief change detection'
    )
    parser.add_argument(
        '--markets', type=int, default=10,
        help='Number of markets to monitor (default: 10)'
    )
    parser.add_argument(
        '--tokens', type=str, nargs='+',
        help='Specific token IDs to monitor (overrides --markets)'
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Verbose output (show all shocks and reactions)'
    )
    parser.add_argument(
        '--duration', type=int, default=0,
        help='Run for N minutes (0 = indefinitely)'
    )
    parser.add_argument(
        '--quiet', '-q', action='store_true',
        help='Quiet mode (only show state changes)'
    )

    args = parser.parse_args()

    # Determine token IDs
    if args.tokens:
        token_ids = args.tokens
    else:
        token_ids = get_active_markets(limit=args.markets)

    if not token_ids:
        print("No markets found. Please specify token IDs with --tokens or ensure database has active markets.")
        print("\nExample usage:")
        print("  python -m poc.run_poc --tokens TOKEN_ID_1 TOKEN_ID_2")
        return

    # Run POC
    run_poc(
        token_ids=token_ids,
        verbose=not args.quiet and args.verbose,
        duration_minutes=args.duration
    )


if __name__ == "__main__":
    main()
