"""
Historical Data Backfill from Polymarket Public APIs

Pulls historical TRADE and PRICE data from Polymarket public APIs.
Useful for price-move analysis and cost model calibration.

IMPORTANT LIMITATION:
  Polymarket has NO public API for historical order book snapshots.
  The Belief State system (STABLE→CRACKING) requires tick-by-tick
  order book dynamics (did the market maker refill? how fast?).
  This data only exists in the real-time WebSocket stream.

  Therefore: this script can backfill trades and price history,
  but CANNOT replay the full Reactor pipeline. For belief state
  calibration, you must collect data live using the collector.

  See screen_markets.py for finding markets to monitor.

Data sources (all public, no auth required):
1. Gamma API — market discovery
2. CLOB API — historical trades, current book snapshot, price candles
3. Data API — alternative trades endpoint

Usage:
    # Pull trade/price data for analysis
    python -m backend.backtest.backfill --markets 20 --days 7

    # Pull specific category
    python -m backend.backtest.backfill --category politics --markets 10
"""

import os
import sys
import json
import time
import sqlite3
import argparse
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests

logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

# Rate limiting
REQUEST_DELAY = 0.3  # seconds between requests


def _get(url, params=None, retries=3) -> Optional[dict]:
    """GET request with retry and rate limiting."""
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request failed (attempt {attempt+1}): {url} — {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


# =============================================================================
# Step 1: Market Discovery
# =============================================================================

def discover_markets(
    category: Optional[str] = None,
    min_volume: float = 5000,
    max_markets: int = 20,
) -> List[Dict]:
    """
    Discover active markets from Gamma API.

    Returns list of market dicts with:
        condition_id, question, token_ids, volume_24h, liquidity, end_date
    """
    markets = []
    offset = 0
    page_size = 100

    logger.info(f"Discovering markets (category={category}, min_vol=${min_volume})")

    while len(markets) < max_markets * 3:  # Over-fetch to allow filtering
        params = {
            'limit': page_size,
            'offset': offset,
            'closed': 'false',
        }
        if category:
            params['tag_slug'] = category

        data = _get(f"{GAMMA_API}/events", params)
        if not data:
            break

        for event in data:
            for m in event.get('markets', []):
                try:
                    vol = float(m.get('volume24hr', 0))
                    if vol < min_volume:
                        continue

                    clob_ids = m.get('clobTokenIds', '[]')
                    if isinstance(clob_ids, str):
                        clob_ids = json.loads(clob_ids)
                    if not clob_ids or len(clob_ids) < 1:
                        continue

                    liq = float(m.get('liquidityNum', 0) or 0)

                    markets.append({
                        'condition_id': m['conditionId'],
                        'question': m.get('question', ''),
                        'yes_token_id': clob_ids[0],
                        'no_token_id': clob_ids[1] if len(clob_ids) > 1 else '',
                        'volume_24h': vol,
                        'liquidity': liq,
                        'end_date': m.get('endDateIso'),
                        'price': _parse_price(m),
                        'event_title': event.get('title', ''),
                    })
                except Exception:
                    continue

        if len(data) < page_size:
            break
        offset += page_size

    # Deduplicate and sort by volume
    seen = set()
    unique = []
    for m in markets:
        if m['condition_id'] not in seen:
            seen.add(m['condition_id'])
            unique.append(m)

    unique.sort(key=lambda x: x['volume_24h'], reverse=True)
    result = unique[:max_markets]

    logger.info(f"Found {len(result)} markets")
    for i, m in enumerate(result[:5]):
        logger.info(f"  {i+1}. {m['question'][:60]} (vol=${m['volume_24h']:.0f})")

    return result


def _parse_price(m: dict) -> float:
    """Parse outcome price from market data."""
    try:
        prices = m.get('outcomePrices', '[0.5, 0.5]')
        if isinstance(prices, str):
            prices = json.loads(prices)
        return float(prices[0])
    except Exception:
        return 0.5


# =============================================================================
# Step 2: Trade History
# =============================================================================

def fetch_trades(
    condition_id: str,
    token_id: str,
    days_back: int = 7,
    max_trades: int = 50000,
) -> List[Dict]:
    """
    Fetch historical trades for a market.

    Uses CLOB API GET /trades which returns paginated trade history.
    """
    trades = []
    cursor = None

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    cutoff_ts = int(cutoff.timestamp())

    logger.info(f"Fetching trades for {token_id[:16]}... (last {days_back} days)")

    while len(trades) < max_trades:
        params = {
            'asset_id': token_id,
            'limit': 500,
        }
        if cursor:
            params['cursor'] = cursor

        data = _get(f"{CLOB_API}/trades", params)
        if data is None:
            break

        # Handle both list and dict responses
        if isinstance(data, dict):
            batch = data.get('data', data.get('trades', []))
            cursor = data.get('next_cursor')
        elif isinstance(data, list):
            batch = data
            cursor = None
        else:
            break

        if not batch:
            break

        for t in batch:
            try:
                ts = int(t.get('timestamp', t.get('match_time', 0)))
                # Some APIs return seconds, some milliseconds
                if ts > 1e12:
                    ts_sec = ts / 1000
                else:
                    ts_sec = ts

                if ts_sec < cutoff_ts:
                    # Past our cutoff
                    return trades

                trades.append({
                    'ts': ts,
                    'token_id': token_id,
                    'price': float(t.get('price', 0)),
                    'size': float(t.get('size', t.get('amount', 0))),
                    'side': t.get('side', 'BUY').upper(),
                })
            except (ValueError, TypeError):
                continue

        if not cursor or len(batch) < 500:
            break

    logger.info(f"  Got {len(trades)} trades")
    return trades


# =============================================================================
# Step 3: Order Book Snapshot
# =============================================================================

def fetch_book(token_id: str) -> Optional[Dict]:
    """Fetch current order book for spread/depth estimation."""
    data = _get(f"{CLOB_API}/book", {'token_id': token_id})
    if not data:
        return None

    bids = data.get('bids', [])
    asks = data.get('asks', [])

    bid_depth = sum(float(b.get('size', 0)) * float(b.get('price', 0)) for b in bids)
    ask_depth = sum(float(a.get('size', 0)) * float(a.get('price', 0)) for a in asks)
    spread = 0.0
    if bids and asks:
        best_bid = float(bids[0].get('price', 0))
        best_ask = float(asks[0].get('price', 0))
        spread = best_ask - best_bid

    return {
        'token_id': token_id,
        'n_bid_levels': len(bids),
        'n_ask_levels': len(asks),
        'bid_depth_usd': bid_depth,
        'ask_depth_usd': ask_depth,
        'spread': spread,
        'best_bid': float(bids[0]['price']) if bids else 0,
        'best_ask': float(asks[0]['price']) if asks else 1,
    }


# =============================================================================
# Step 4: Price History (candles)
# =============================================================================

def fetch_price_history(
    token_id: str,
    interval: str = "1h",
    fidelity: int = 60,
) -> List[Dict]:
    """
    Fetch price candle history.

    Args:
        token_id: CLOB token ID
        interval: candle interval (1m, 5m, 1h, 1d)
        fidelity: number of candles
    """
    data = _get(f"{CLOB_API}/prices-history", {
        'market': token_id,
        'interval': interval,
        'fidelity': fidelity,
    })

    if not data:
        return []

    history = data.get('history', [])
    logger.info(f"  Got {len(history)} price candles ({interval})")
    return history


# =============================================================================
# Step 5: SQLite Storage
# =============================================================================

def init_sqlite(db_path: str) -> sqlite3.Connection:
    """Initialize SQLite database for backfill data."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS markets (
            condition_id TEXT PRIMARY KEY,
            question TEXT,
            yes_token_id TEXT,
            no_token_id TEXT,
            volume_24h REAL,
            liquidity REAL,
            end_date TEXT,
            price REAL,
            event_title TEXT,
            fetched_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            ts INTEGER,
            token_id TEXT,
            price REAL,
            size REAL,
            side TEXT,
            PRIMARY KEY (ts, token_id, price)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            token_id TEXT PRIMARY KEY,
            n_bid_levels INTEGER,
            n_ask_levels INTEGER,
            bid_depth_usd REAL,
            ask_depth_usd REAL,
            spread REAL,
            best_bid REAL,
            best_ask REAL,
            fetched_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            token_id TEXT,
            ts INTEGER,
            price REAL,
            PRIMARY KEY (token_id, ts)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_token ON trades(token_id, ts)")
    conn.commit()
    return conn


def save_markets(conn: sqlite3.Connection, markets: List[Dict]):
    """Save markets to SQLite."""
    now = datetime.now(timezone.utc).isoformat()
    for m in markets:
        conn.execute("""
            INSERT OR REPLACE INTO markets
            (condition_id, question, yes_token_id, no_token_id,
             volume_24h, liquidity, end_date, price, event_title, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            m['condition_id'], m['question'], m['yes_token_id'], m['no_token_id'],
            m['volume_24h'], m['liquidity'], m.get('end_date'), m['price'],
            m.get('event_title', ''), now,
        ))
    conn.commit()


def save_trades(conn: sqlite3.Connection, trades: List[Dict]):
    """Save trades to SQLite."""
    for t in trades:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO trades (ts, token_id, price, size, side)
                VALUES (?, ?, ?, ?, ?)
            """, (t['ts'], t['token_id'], t['price'], t['size'], t['side']))
        except sqlite3.IntegrityError:
            pass
    conn.commit()


def save_book(conn: sqlite3.Connection, book: Dict):
    """Save book snapshot."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO books
        (token_id, n_bid_levels, n_ask_levels, bid_depth_usd, ask_depth_usd,
         spread, best_bid, best_ask, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        book['token_id'], book['n_bid_levels'], book['n_ask_levels'],
        book['bid_depth_usd'], book['ask_depth_usd'], book['spread'],
        book['best_bid'], book['best_ask'], now,
    ))
    conn.commit()


# =============================================================================
# Step 6: Offline Belief State Replay
# =============================================================================

def replay_belief_states(
    conn: sqlite3.Connection,
    token_id: str,
) -> List[Dict]:
    """
    DEPRECATED: Cannot produce valid belief states from trade data alone.

    The Belief State system requires order book dynamics (liquidity refill
    timing, depth changes between trades) which are NOT available in
    historical trade data. Reaction classification (VACUUM, PULL, HOLD)
    needs to see what happened to the order book AFTER a shock, not just
    the trades themselves.

    For valid belief state data, use the live collector with WebSocket.
    See: screen_markets.py for finding markets to monitor.

    This function is kept for reference but will produce unreliable results.
    """
    logger.warning(
        "replay_belief_states() cannot produce valid results from trade data alone. "
        "Use the live collector for belief state data collection."
    )
    from poc.shock_detector import ShockDetector
    from poc.reaction_classifier import ReactionClassifier
    from poc.belief_state_machine import BeliefStateMachine
    from poc.models import TradeEvent, PriceLevel, BeliefState
    from decimal import Decimal

    # Load trades
    cursor = conn.execute(
        "SELECT ts, token_id, price, size, side FROM trades WHERE token_id = ? ORDER BY ts",
        (token_id,)
    )
    trades_raw = cursor.fetchall()
    if not trades_raw:
        return []

    logger.info(f"Replaying {len(trades_raw)} trades for {token_id[:16]}...")

    # Initialize components
    shock_detector = ShockDetector()
    reaction_classifier = ReactionClassifier()
    state_machine = BeliefStateMachine()

    # Price level tracker
    price_levels = {}
    transitions = []
    prev_state = "STABLE"

    for ts, tid, price, size, side in trades_raw:
        # Create trade event
        trade = TradeEvent(
            token_id=tid,
            price=Decimal(str(price)),
            size=float(size),
            side=side,
            timestamp=int(ts) if ts > 1e12 else int(ts * 1000),
        )

        # Update price level
        level_key = (tid, str(price), 'bid' if side == 'BUY' else 'ask')
        if level_key not in price_levels:
            price_levels[level_key] = PriceLevel(
                token_id=tid,
                price=Decimal(str(price)),
                side='bid' if side == 'BUY' else 'ask',
            )
        pl = price_levels[level_key]
        pl.update_size(float(size), trade.timestamp)

        # Detect shocks
        shocks = shock_detector.detect(trade, pl)
        if not shocks:
            continue

        for shock in shocks:
            # Classify reactions (simplified — use end_size as approximation)
            reaction = reaction_classifier.classify_immediate(shock, pl)
            if reaction is None:
                continue

            # Update state machine
            new_state = state_machine.update(reaction)
            state_str = new_state.value if hasattr(new_state, 'value') else str(new_state)

            if state_str != prev_state:
                transitions.append({
                    'ts': trade.timestamp,
                    'token_id': tid,
                    'old_state': prev_state,
                    'new_state': state_str,
                    'reaction_type': reaction.reaction_type.value,
                    'reaction_side': shock.side,
                    'price_at_event': float(price),
                })
                prev_state = state_str

    logger.info(f"  Found {len(transitions)} state transitions")
    return transitions


# =============================================================================
# Main
# =============================================================================

def run_backfill(
    category: Optional[str] = None,
    max_markets: int = 20,
    days_back: int = 7,
    db_path: str = "data/backfill.db",
):
    """Run the full backfill pipeline."""
    os.makedirs(os.path.dirname(db_path) or '.', exist_ok=True)
    conn = init_sqlite(db_path)

    # Step 1: Discover markets
    print(f"\n{'='*60}")
    print(f"STEP 1: Discovering markets")
    print(f"{'='*60}")
    markets = discover_markets(category=category, max_markets=max_markets)
    save_markets(conn, markets)

    # Step 2: Fetch trades for each market
    print(f"\n{'='*60}")
    print(f"STEP 2: Fetching trade history ({days_back} days)")
    print(f"{'='*60}")
    total_trades = 0
    for i, m in enumerate(markets):
        print(f"\n[{i+1}/{len(markets)}] {m['question'][:50]}")
        trades = fetch_trades(m['condition_id'], m['yes_token_id'], days_back=days_back)
        save_trades(conn, trades)
        total_trades += len(trades)

    print(f"\nTotal trades: {total_trades}")

    # Step 3: Fetch book snapshots
    print(f"\n{'='*60}")
    print(f"STEP 3: Fetching order book snapshots")
    print(f"{'='*60}")
    for m in markets:
        book = fetch_book(m['yes_token_id'])
        if book:
            save_book(conn, book)
            print(f"  {m['question'][:40]}: spread={book['spread']:.3f}, "
                  f"depth=${book['bid_depth_usd']:.0f}+${book['ask_depth_usd']:.0f}")

    # Step 4: Fetch price history
    print(f"\n{'='*60}")
    print(f"STEP 4: Fetching price history")
    print(f"{'='*60}")
    for m in markets:
        candles = fetch_price_history(m['yes_token_id'], interval='1h', fidelity=24*days_back)
        for c in candles:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO price_history (token_id, ts, price) VALUES (?, ?, ?)",
                    (m['yes_token_id'], int(c.get('t', 0)), float(c.get('p', 0)))
                )
            except Exception:
                pass
        conn.commit()

    # Summary
    trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    market_count = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
    book_count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]

    print(f"\n{'='*60}")
    print(f"BACKFILL COMPLETE")
    print(f"{'='*60}")
    print(f"  Database: {db_path}")
    print(f"  Markets:  {market_count}")
    print(f"  Trades:   {trade_count}")
    print(f"  Books:    {book_count}")
    print(f"\nNext step:")
    print(f"  python -m backend.backtest.backfill --replay --db {db_path}")
    print(f"  python -m backend.backtest.calibrate --csv data/transitions.csv")

    conn.close()
    return db_path


def run_replay(db_path: str, export_csv: str = "data/transitions.csv"):
    """
    Replay trades through belief state machine and export transitions.

    This creates the calibration data needed by DeltaCalibrator.
    """
    from backend.backtest.data_loader import BeliefTransition

    conn = init_sqlite(db_path)

    # Get all token_ids with trades
    tokens = conn.execute(
        "SELECT DISTINCT token_id FROM trades ORDER BY token_id"
    ).fetchall()

    all_transitions = []
    for (token_id,) in tokens:
        transitions = replay_belief_states(conn, token_id)
        all_transitions.extend(transitions)

    if not all_transitions:
        print("No state transitions found. Markets may be too stable.")
        conn.close()
        return

    # Enrich with price outcomes
    print(f"\nEnriching {len(all_transitions)} transitions with price outcomes...")
    for t in all_transitions:
        event_ts = t['ts']
        token_id = t['token_id']

        for horizon_min, field in [(1, 'price_1m'), (5, 'price_5m'),
                                    (15, 'price_15m'), (30, 'price_30m')]:
            if event_ts > 1e12:
                target_ts = event_ts + horizon_min * 60 * 1000
            else:
                target_ts = event_ts + horizon_min * 60

            # Find closest trade
            row = conn.execute("""
                SELECT price FROM trades
                WHERE token_id = ? AND ts BETWEEN ? - 30000 AND ? + 30000
                ORDER BY ABS(ts - ?)
                LIMIT 1
            """, (token_id, target_ts, target_ts, target_ts)).fetchone()
            if row:
                t[field] = float(row[0])

        # Book context
        book = conn.execute(
            "SELECT spread, bid_depth_usd, ask_depth_usd FROM books WHERE token_id = ?",
            (token_id,)
        ).fetchone()
        if book:
            t['spread'] = book[0]
            t['bid_depth_usd'] = book[1]
            t['ask_depth_usd'] = book[2]

    # Export to CSV
    os.makedirs(os.path.dirname(export_csv) or '.', exist_ok=True)
    import csv
    fields = ['ts', 'token_id', 'old_state', 'new_state', 'reaction_type',
              'reaction_side', 'price_at_event', 'price_1m', 'price_5m',
              'price_15m', 'price_30m', 'spread', 'bid_depth_usd', 'ask_depth_usd']
    with open(export_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for t in all_transitions:
            # Convert timestamp to ISO
            ts = t['ts']
            if ts > 1e12:
                t['ts'] = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
            else:
                t['ts'] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            writer.writerow(t)

    print(f"\nExported {len(all_transitions)} transitions to {export_csv}")
    print(f"\nNow run calibration:")
    print(f"  python -m backend.backtest.calibrate --csv {export_csv}")

    conn.close()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="Backfill historical data from Polymarket")
    parser.add_argument("--markets", type=int, default=20, help="Number of markets to fetch")
    parser.add_argument("--days", type=int, default=7, help="Days of trade history")
    parser.add_argument("--category", type=str, help="Market category filter")
    parser.add_argument("--db", type=str, default="data/backfill.db", help="SQLite database path")
    parser.add_argument("--replay", action="store_true", help="Replay trades through belief state machine")
    parser.add_argument("--export", type=str, default="data/transitions.csv", help="CSV export path")
    args = parser.parse_args()

    if args.replay:
        run_replay(args.db, args.export)
    else:
        run_backfill(
            category=args.category,
            max_markets=args.markets,
            days_back=args.days,
            db_path=args.db,
        )


if __name__ == "__main__":
    main()
