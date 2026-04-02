"""
Market Screening Script

Finds markets currently eligible for belief state data collection.

Criteria (optimized for maximizing CRACKING event sample rate):
1. Volume > $10K/day (enough activity to trigger shocks)
2. Liquidity > $5K (enough depth for meaningful reaction analysis)
3. Price between 0.10 and 0.90 (avoid resolved/dead markets)
4. Resolution > 1 week (enough time to collect data)
5. NOT crypto 15-min markets (different dynamics)

Strategy: monitor 30-50 markets in parallel. If each produces
0-2 CRACKING events per day, 30 markets × 1/day × 7 days = 210 samples.
That's enough for DeltaCalibrator (needs ~50+ per state).

Usage:
    # Screen and output token IDs for collector
    python -m backend.backtest.screen_markets

    # Filter by category
    python -m backend.backtest.screen_markets --category politics

    # Output as JSON config for collector
    python -m backend.backtest.screen_markets --format json --output collector_config.json
"""

import sys
import os
import json
import time
import argparse
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests

logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

REQUEST_DELAY = 0.3


def _get(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.warning(f"Failed: {url} — {e}")
    return None


def screen_markets(
    category: Optional[str] = None,
    min_volume: float = 10000,
    min_liquidity: float = 5000,
    min_price: float = 0.10,
    max_price: float = 0.90,
    min_days_to_resolution: float = 7,
    max_markets: int = 50,
    exclude_crypto_short: bool = True,
) -> List[Dict]:
    """
    Screen Polymarket for markets suitable for belief state collection.

    Returns ranked list of markets with book depth info.
    """
    # Step 1: Discover markets from Gamma API
    candidates = []
    offset = 0
    page_size = 100

    print(f"Screening markets (category={category or 'all'}, min_vol=${min_volume:.0f})")

    while True:
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
                    market = _parse_market(m, event)
                    if market:
                        candidates.append(market)
                except Exception:
                    continue

        if len(data) < page_size:
            break
        offset += page_size

    print(f"Found {len(candidates)} raw candidates")

    # Step 2: Filter
    now = datetime.now(timezone.utc)
    filtered = []
    reject_reasons = {}

    for m in candidates:
        # Volume
        if m['volume_24h'] < min_volume:
            reject_reasons['low_volume'] = reject_reasons.get('low_volume', 0) + 1
            continue

        # Liquidity
        if m['liquidity'] < min_liquidity:
            reject_reasons['low_liquidity'] = reject_reasons.get('low_liquidity', 0) + 1
            continue

        # Price bounds
        if m['price'] < min_price or m['price'] > max_price:
            reject_reasons['extreme_price'] = reject_reasons.get('extreme_price', 0) + 1
            continue

        # Resolution time
        if m['end_date']:
            try:
                end = datetime.fromisoformat(m['end_date'].replace('Z', '+00:00'))
                days_left = (end - now).total_seconds() / 86400
                if days_left < min_days_to_resolution:
                    reject_reasons['near_resolution'] = reject_reasons.get('near_resolution', 0) + 1
                    continue
                m['days_to_resolution'] = days_left
            except Exception:
                m['days_to_resolution'] = None

        # Skip crypto short-term markets
        if exclude_crypto_short:
            q = m['question'].lower()
            if any(term in q for term in ['btc above', 'eth above', 'bitcoin above',
                                           'ethereum above', '15 min', '1 hour',
                                           'hourly', 'daily close']):
                reject_reasons['crypto_short'] = reject_reasons.get('crypto_short', 0) + 1
                continue

        filtered.append(m)

    print(f"\nFilter results:")
    print(f"  Passed: {len(filtered)}")
    for reason, count in sorted(reject_reasons.items(), key=lambda x: -x[1]):
        print(f"  Rejected ({reason}): {count}")

    # Step 3: Enrich with book data for top candidates
    # Sort by volume first, then enrich top N
    filtered.sort(key=lambda x: x['volume_24h'], reverse=True)
    top = filtered[:max_markets * 2]  # Over-fetch for book filtering

    print(f"\nFetching order book data for top {len(top)} markets...")
    enriched = []
    for i, m in enumerate(top):
        if len(enriched) >= max_markets:
            break

        book = _get(f"{CLOB_API}/book", {'token_id': m['yes_token_id']})
        if not book:
            continue

        bids = book.get('bids', [])
        asks = book.get('asks', [])

        bid_depth = sum(float(b.get('size', 0)) * float(b.get('price', 0)) for b in bids)
        ask_depth = sum(float(a.get('size', 0)) * float(a.get('price', 0)) for a in asks)
        total_depth = bid_depth + ask_depth

        if total_depth < min_liquidity:
            continue

        spread = 0.0
        if bids and asks:
            spread = float(asks[0]['price']) - float(bids[0]['price'])

        m['bid_depth_usd'] = bid_depth
        m['ask_depth_usd'] = ask_depth
        m['total_depth_usd'] = total_depth
        m['spread'] = spread
        m['n_bid_levels'] = len(bids)
        m['n_ask_levels'] = len(asks)

        # Quality score: prefer high volume, deep books, tight spread
        m['quality_score'] = (
            min(m['volume_24h'] / 100000, 1.0) * 0.3 +
            min(total_depth / 50000, 1.0) * 0.3 +
            max(0, 1.0 - spread / 0.04) * 0.2 +
            (0.2 if 0.3 < m['price'] < 0.7 else 0.1)  # Prefer mid-range prices
        )

        enriched.append(m)

        if (i + 1) % 10 == 0:
            print(f"  Processed {i+1}/{len(top)}...")

    # Sort by quality
    enriched.sort(key=lambda x: x['quality_score'], reverse=True)

    return enriched


def _parse_market(m: dict, event: dict) -> Optional[Dict]:
    """Parse a market from Gamma API response."""
    cid = m.get('conditionId', '')
    if not cid:
        return None

    clob_ids = m.get('clobTokenIds', '[]')
    if isinstance(clob_ids, str):
        clob_ids = json.loads(clob_ids)
    if not clob_ids:
        return None

    try:
        prices = m.get('outcomePrices', '[0.5, 0.5]')
        if isinstance(prices, str):
            prices = json.loads(prices)
        price = float(prices[0])
    except Exception:
        price = 0.5

    return {
        'condition_id': cid,
        'question': m.get('question', ''),
        'yes_token_id': clob_ids[0],
        'no_token_id': clob_ids[1] if len(clob_ids) > 1 else '',
        'volume_24h': float(m.get('volume24hr', 0) or 0),
        'liquidity': float(m.get('liquidityNum', 0) or 0),
        'price': price,
        'end_date': m.get('endDateIso'),
        'event_title': event.get('title', ''),
        'category': event.get('slug', ''),
    }


def print_report(markets: List[Dict]):
    """Print screening results."""
    print(f"\n{'='*80}")
    print(f"SCREENED MARKETS FOR BELIEF STATE COLLECTION ({len(markets)} markets)")
    print(f"{'='*80}")
    print(f"{'#':>3} {'Score':>5} {'Vol24h':>8} {'Depth':>8} {'Spread':>7} {'Price':>6} {'Question'}")
    print(f"{'-'*3} {'-'*5} {'-'*8} {'-'*8} {'-'*7} {'-'*6} {'-'*40}")

    for i, m in enumerate(markets):
        print(f"{i+1:3d} {m['quality_score']:.2f}  "
              f"${m['volume_24h']:>7.0f} ${m['total_depth_usd']:>7.0f} "
              f"{m['spread']:>6.3f}  {m['price']:>5.2f}  "
              f"{m['question'][:45]}")

    # Token IDs for collector
    print(f"\n{'='*80}")
    print(f"TOKEN IDS FOR COLLECTOR (copy-paste into config):")
    print(f"{'='*80}")
    token_ids = [m['yes_token_id'] for m in markets]
    print(json.dumps(token_ids, indent=2))

    # Estimated sample rate
    n = len(markets)
    print(f"\n{'='*80}")
    print(f"ESTIMATED COLLECTION TIMELINE")
    print(f"{'='*80}")
    print(f"  Markets monitored:        {n}")
    print(f"  Est. shocks/market/day:   3-10")
    print(f"  Est. CRACKING events/day: {n * 0.5:.0f}-{n * 2:.0f}")
    print(f"  Days to 100 samples:      {max(1, 100 // (n * 1))}-{max(1, 100 // max(1, n // 2))}")
    print(f"  Days to 200 samples:      {max(1, 200 // (n * 1))}-{max(1, 200 // max(1, n // 2))}")
    print(f"\n  Recommendation: collect for 5-7 days, then run:")
    print(f"    python -m backend.backtest.calibrate --days 7")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Screen Polymarket markets for collection")
    parser.add_argument("--category", type=str, help="Category filter (politics, sports, etc)")
    parser.add_argument("--markets", type=int, default=30, help="Max markets to select")
    parser.add_argument("--min-volume", type=float, default=10000, help="Min 24h volume")
    parser.add_argument("--min-liquidity", type=float, default=5000, help="Min liquidity")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    parser.add_argument("--output", type=str, help="Output file path")
    args = parser.parse_args()

    markets = screen_markets(
        category=args.category,
        min_volume=args.min_volume,
        min_liquidity=args.min_liquidity,
        max_markets=args.markets,
    )

    if args.format == "json":
        result = {
            "screened_at": datetime.now(timezone.utc).isoformat(),
            "n_markets": len(markets),
            "token_ids": [m['yes_token_id'] for m in markets],
            "markets": markets,
        }
        output = json.dumps(result, indent=2, default=str)
        if args.output:
            with open(args.output, 'w') as f:
                f.write(output)
            print(f"Saved to {args.output}")
        else:
            print(output)
    else:
        print_report(markets)

        if args.output:
            # Save token IDs to file
            with open(args.output, 'w') as f:
                json.dump([m['yes_token_id'] for m in markets], f, indent=2)
            print(f"\nToken IDs saved to {args.output}")


if __name__ == "__main__":
    main()
