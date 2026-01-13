"""
Batch test tool for event-level coverage and data health.

Supports:
- Fetch events by category (DB if available, otherwise Polymarket API)
- Aggregate per-event metrics (eligibility, data health, alerts, replayability)
"""

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Any

import psycopg2
from psycopg2.extras import RealDictCursor

from backend.market.eligibility import MarketEligibilityEvaluator, EligibilityStatus
from backend.alerting.evidence_grade import compute_evidence_grade
from poc.config import TIME_BUCKET_MS
from utils.polymarket_api import PolymarketAPI


DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "belief_reaction"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
}


def get_connection():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


def table_exists(conn, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_name = %s
            """,
            (table_name,),
        )
        return cur.fetchone() is not None


def column_exists(conn, table_name: str, column_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            (table_name, column_name),
        )
        return cur.fetchone() is not None


def fetch_events_from_db(conn, category: str, limit: int) -> List[Dict[str, Any]]:
    if not column_exists(conn, "markets", "category"):
        return []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT condition_id, event_id, COALESCE(event_title, question) AS event_title,
                   yes_token_id, no_token_id, volume_24h
            FROM markets
            WHERE category = %s AND event_id IS NOT NULL
            """,
            (category,),
        )
        rows = cur.fetchall()

    events: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        event_id = r.get("event_id") or "unknown"
        event = events.setdefault(
            event_id,
            {
                "event_id": event_id,
                "event_title": r.get("event_title") or "Unknown Event",
                "markets": [],
                "total_volume_24h": 0.0,
            },
        )
        event["markets"].append(r)
        event["total_volume_24h"] += float(r.get("volume_24h") or 0.0)

    event_list = list(events.values())
    event_list.sort(key=lambda e: e["total_volume_24h"], reverse=True)
    return event_list[:limit]


def fetch_events_from_api(category: str, limit: int, min_volume: float) -> List[Dict[str, Any]]:
    api = PolymarketAPI()
    markets = api._get_markets_by_tag_slug(category, min_volume_24h=min_volume)

    events: Dict[str, Dict[str, Any]] = {}
    for m in markets:
        event_id = m.get("event_id") or "unknown"
        event = events.setdefault(
            event_id,
            {
                "event_id": event_id,
                "event_title": m.get("event_title") or "Unknown Event",
                "markets": [],
                "total_volume_24h": 0.0,
            },
        )
        event["markets"].append(m)
        event["total_volume_24h"] += float(m.get("volume_24h") or 0.0)

    event_list = list(events.values())
    event_list.sort(key=lambda e: e["total_volume_24h"], reverse=True)
    return event_list[:limit]


def fetch_metrics(conn, token_ids: List[str], window_minutes: int) -> Dict[str, Dict[str, Any]]:
    if not token_ids:
        return {}

    metrics: Dict[str, Dict[str, Any]] = {tid: {} for tid in token_ids}

    # Book buckets (missing ratio) and baseline liquidity
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT token_id, COUNT(DISTINCT bucket_ts) AS bucket_count
            FROM book_bins
            WHERE token_id = ANY(%s)
              AND bucket_ts >= NOW() - (%s * INTERVAL '1 minute')
            GROUP BY token_id
            """,
            (token_ids, 10),
        )
        for r in cur.fetchall():
            metrics[r["token_id"]]["bucket_count_10m"] = int(r["bucket_count"] or 0)

        cur.execute(
            """
            WITH buckets AS (
                SELECT token_id, bucket_ts, SUM(size) AS depth_sum
                FROM book_bins
                WHERE token_id = ANY(%s)
                  AND bucket_ts >= NOW() - (%s * INTERVAL '1 minute')
                GROUP BY token_id, bucket_ts
            )
            SELECT token_id, AVG(depth_sum) AS avg_depth
            FROM buckets
            GROUP BY token_id
            """,
            (token_ids, window_minutes),
        )
        for r in cur.fetchall():
            metrics[r["token_id"]]["baseline_liquidity"] = float(r["avg_depth"] or 0.0)

        cur.execute(
            """
            SELECT token_id, MAX(ts) AS last_book_ts
            FROM book_bins
            WHERE token_id = ANY(%s)
            GROUP BY token_id
            """,
            (token_ids,),
        )
        for r in cur.fetchall():
            metrics[r["token_id"]]["last_book_ts"] = r.get("last_book_ts")

    # Trade ticks (optional)
    if table_exists(conn, "trade_ticks"):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT token_id, COUNT(*) AS trade_count, MAX(ts) AS last_trade_ts
                FROM trade_ticks
                WHERE token_id = ANY(%s)
                  AND ts >= NOW() - (%s * INTERVAL '1 minute')
                GROUP BY token_id
                """,
                (token_ids, window_minutes),
            )
            for r in cur.fetchall():
                metrics[r["token_id"]]["trade_count_24h"] = int(r["trade_count"] or 0)
                metrics[r["token_id"]]["last_trade_ts"] = r.get("last_trade_ts")

    # Alerts
    if table_exists(conn, "alerts"):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT token_id, COUNT(*) AS alert_count
                FROM alerts
                WHERE token_id = ANY(%s)
                  AND ts >= NOW() - (%s * INTERVAL '1 minute')
                GROUP BY token_id
                """,
                (token_ids, window_minutes),
            )
            for r in cur.fetchall():
                metrics[r["token_id"]]["alert_count"] = int(r["alert_count"] or 0)

    # Raw events (replayable)
    if table_exists(conn, "raw_events"):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT token_id, COUNT(*) AS raw_count
                FROM raw_events
                WHERE token_id = ANY(%s)
                  AND ts >= NOW() - (%s * INTERVAL '1 minute')
                GROUP BY token_id
                """,
                (token_ids, window_minutes),
            )
            for r in cur.fetchall():
                metrics[r["token_id"]]["raw_count"] = int(r["raw_count"] or 0)

    # Evidence bundles (optional)
    if table_exists(conn, "evidence_bundles"):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT token_id,
                       COUNT(*) AS bundle_count,
                       COUNT(bundle_hash) AS bundle_hash_count
                FROM evidence_bundles
                WHERE token_id = ANY(%s)
                  AND created_at >= NOW() - (%s * INTERVAL '1 minute')
                GROUP BY token_id
                """,
                (token_ids, window_minutes),
            )
            for r in cur.fetchall():
                metrics[r["token_id"]]["bundle_count"] = int(r["bundle_count"] or 0)
                metrics[r["token_id"]]["bundle_hash_count"] = int(r["bundle_hash_count"] or 0)

    return metrics


def compute_event_report(events: List[Dict[str, Any]], metrics: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    evaluator = MarketEligibilityEvaluator()
    results = []

    expected_buckets_10m = int((10 * 60 * 1000) / TIME_BUCKET_MS)

    for event in events:
        tokens = set()
        for market in event["markets"]:
            yes_token = market.get("yes_token_id") or market.get("yes_token")
            no_token = market.get("no_token_id") or market.get("no_token")
            if yes_token:
                tokens.add(yes_token)
            if no_token:
                tokens.add(no_token)

        token_list = sorted(tokens)
        eligibility_counts = defaultdict(int)
        grade_counts = defaultdict(int)
        missing_ratios = []
        alerts_total = 0
        replayable_count = 0
        hash_available = 0

        for token_id in token_list:
            m = metrics.get(token_id, {})

            bucket_count = m.get("bucket_count_10m", 0)
            missing_ratio = 1.0
            if expected_buckets_10m > 0:
                missing_ratio = max(0.0, 1.0 - (bucket_count / expected_buckets_10m))
            missing_ratios.append(missing_ratio)

            last_book = m.get("last_book_ts")
            last_trade = m.get("last_trade_ts")
            last_activity = None
            if last_book and last_trade:
                last_activity = max(last_book, last_trade)
            else:
                last_activity = last_book or last_trade

            baseline_liquidity = float(m.get("baseline_liquidity", 0.0))
            trade_count = int(m.get("trade_count_24h", 0))

            eval_metrics = {
                "baseline_liquidity": baseline_liquidity,
                "trade_count_24h": trade_count,
                "unique_traders_24h": trade_count,
                "top_trader_volume_ratio": 0.0,
                "cancel_place_ratio": 0.0,
                "wash_trade_ratio": 0.0,
                "trade_intervals": [],
                "last_activity_ts": int(last_activity.timestamp() * 1000) if last_activity else 0,
            }

            eligibility = evaluator.evaluate(token_id, eval_metrics)
            eligibility_counts[eligibility.status.value] += 1

            bundle_hash_count = m.get("bundle_hash_count", 0)
            hash_verified = bundle_hash_count > 0
            if hash_verified:
                hash_available += 1

            grade = compute_evidence_grade(
                has_gaps=missing_ratio > 0.1,
                hash_verified=hash_verified if "bundle_hash_count" in m else True,
                tainted_windows=0,
                coverage_ratio=max(0.0, 1.0 - missing_ratio),
            )
            grade_counts[grade.value] += 1

            alerts_total += int(m.get("alert_count", 0))
            if int(m.get("raw_count", 0)) > 0:
                replayable_count += 1

        eligible_n = eligibility_counts.get(EligibilityStatus.ELIGIBLE.value, 0)
        degraded_n = eligibility_counts.get(EligibilityStatus.DEGRADED.value, 0)
        eligible_rate = (eligible_n + degraded_n) / max(1, len(token_list))
        replayable_rate = replayable_count / max(1, len(token_list))
        avg_missing_ratio = sum(missing_ratios) / max(1, len(missing_ratios))

        results.append({
            "event_id": event["event_id"],
            "event_title": event["event_title"],
            "market_count": len(event["markets"]),
            "token_count": len(token_list),
            "eligible_rate": round(eligible_rate, 3),
            "eligibility_counts": dict(eligibility_counts),
            "avg_missing_bucket_ratio_10m": round(avg_missing_ratio, 3),
            "evidence_grade_counts": dict(grade_counts),
            "hash_available_rate": round(hash_available / max(1, len(token_list)), 3),
            "alerts_24h": alerts_total,
            "replayable_rate": round(replayable_rate, 3),
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="Batch event testing tool")
    parser.add_argument("--category", default="politics", help="Category slug (default: politics)")
    parser.add_argument("--target-events", type=int, default=50, help="Number of events to test")
    parser.add_argument("--min-volume", type=float, default=100.0, help="Min 24h volume for API fetch")
    parser.add_argument("--window-hours", type=int, default=24, help="Metrics window in hours")
    parser.add_argument("--source", choices=["auto", "db", "api"], default="auto")
    parser.add_argument("--format", choices=["json", "table"], default="json")
    parser.add_argument("--output", help="Output file (optional)")
    args = parser.parse_args()

    window_minutes = max(1, args.window_hours * 60)

    conn = get_connection()

    events: List[Dict[str, Any]] = []
    if args.source in ("auto", "db"):
        events = fetch_events_from_db(conn, args.category, args.target_events)

    if not events and args.source in ("auto", "api"):
        events = fetch_events_from_api(args.category, args.target_events, args.min_volume)

    if not events:
        print("No events found for category.")
        return

    all_tokens = set()
    for event in events:
        for market in event["markets"]:
            yes_token = market.get("yes_token_id") or market.get("yes_token")
            no_token = market.get("no_token_id") or market.get("no_token")
            if yes_token:
                all_tokens.add(yes_token)
            if no_token:
                all_tokens.add(no_token)

    metrics = fetch_metrics(conn, sorted(all_tokens), window_minutes)
    conn.close()

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "category": args.category,
        "target_events": args.target_events,
        "window_hours": args.window_hours,
        "event_count": len(events),
        "events": compute_event_report(events, metrics),
    }

    if args.format == "json":
        output = json.dumps(report, indent=2)
    else:
        lines = []
        lines.append("event_id\tevent_title\tmarkets\ttokens\teligible_rate\tmissing_ratio_10m\talerts_24h\treplayable_rate")
        for e in report["events"]:
            lines.append(
                f"{e['event_id']}\t{e['event_title'][:40]}\t{e['market_count']}\t{e['token_count']}"
                f"\t{e['eligible_rate']}\t{e['avg_missing_bucket_ratio_10m']}\t{e['alerts_24h']}\t{e['replayable_rate']}"
            )
        output = "\n".join(lines)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Report saved to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
