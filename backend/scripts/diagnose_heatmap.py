#!/usr/bin/env python3
"""
Heatmap Data Diagnostic Script

Diagnoses why heatmap tiles might be empty by checking:
1. Token IDs in book_bins vs markets table
2. Time ranges of available data
3. Recent data availability
"""

import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta

# Database configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "belief_reaction"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
}


def get_connection():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)


def diagnose():
    conn = get_connection()
    cur = conn.cursor()

    print("=" * 80)
    print("HEATMAP DATA DIAGNOSTIC REPORT")
    print("=" * 80)
    print(f"Generated at: {datetime.now()}")
    print()

    # 1. Check total records in book_bins
    print("1. BOOK_BINS TABLE OVERVIEW")
    print("-" * 40)
    cur.execute("SELECT COUNT(*) as total FROM book_bins")
    total = cur.fetchone()['total']
    print(f"Total records: {total:,}")

    cur.execute("SELECT MIN(bucket_ts) as min_ts, MAX(bucket_ts) as max_ts FROM book_bins")
    time_range = cur.fetchone()
    print(f"Time range: {time_range['min_ts']} to {time_range['max_ts']}")
    print()

    # 2. List all unique token_ids in book_bins
    print("2. TOKEN_IDs IN BOOK_BINS")
    print("-" * 40)
    cur.execute("""
        SELECT
            token_id,
            COUNT(*) as record_count,
            MIN(bucket_ts) as first_record,
            MAX(bucket_ts) as last_record
        FROM book_bins
        GROUP BY token_id
        ORDER BY last_record DESC
    """)
    book_tokens = cur.fetchall()

    print(f"Found {len(book_tokens)} unique token_ids:")
    for row in book_tokens:
        age = datetime.now() - row['last_record'].replace(tzinfo=None) if row['last_record'] else None
        age_str = f"({age.days}d {age.seconds//3600}h ago)" if age else "(unknown)"
        print(f"  {row['token_id'][:20]}... : {row['record_count']:>8,} records, last: {row['last_record']} {age_str}")
    print()

    # 3. Check markets table
    print("3. MARKETS TABLE TOKEN_IDs")
    print("-" * 40)
    cur.execute("""
        SELECT
            condition_id,
            question,
            yes_token_id,
            no_token_id
        FROM markets
        ORDER BY condition_id
    """)
    markets = cur.fetchall()

    print(f"Found {len(markets)} markets:")
    for m in markets:
        print(f"  Condition: {m['condition_id'][:20]}...")
        print(f"    Question: {m['question'][:50]}...")
        print(f"    YES token: {m['yes_token_id'][:20] if m['yes_token_id'] else 'NULL'}...")
        print(f"    NO token:  {m['no_token_id'][:20] if m['no_token_id'] else 'NULL'}...")
        print()

    # 4. Check for token_id mismatches
    print("4. TOKEN_ID MATCHING ANALYSIS")
    print("-" * 40)

    book_token_set = set(row['token_id'] for row in book_tokens)
    market_yes_tokens = set(m['yes_token_id'] for m in markets if m['yes_token_id'])
    market_no_tokens = set(m['no_token_id'] for m in markets if m['no_token_id'])
    all_market_tokens = market_yes_tokens | market_no_tokens

    matched = book_token_set & all_market_tokens
    in_books_only = book_token_set - all_market_tokens
    in_markets_only = all_market_tokens - book_token_set

    print(f"Tokens in both book_bins and markets: {len(matched)}")
    print(f"Tokens in book_bins ONLY (not in markets): {len(in_books_only)}")
    print(f"Tokens in markets ONLY (not in book_bins): {len(in_markets_only)}")

    if in_books_only:
        print("\n  Tokens with data but NO market entry:")
        for t in in_books_only:
            print(f"    - {t}")

    if in_markets_only:
        print("\n  Markets WITHOUT book_bins data:")
        for t in in_markets_only:
            print(f"    - {t}")
    print()

    # 5. Check recent data (last 2 hours)
    print("5. RECENT DATA CHECK (last 2 hours)")
    print("-" * 40)
    cur.execute("""
        SELECT
            token_id,
            COUNT(*) as recent_count
        FROM book_bins
        WHERE bucket_ts > NOW() - INTERVAL '2 hours'
        GROUP BY token_id
    """)
    recent = cur.fetchall()

    if recent:
        print(f"Tokens with recent data: {len(recent)}")
        for row in recent:
            print(f"  {row['token_id'][:20]}... : {row['recent_count']:,} records")
    else:
        print("NO RECENT DATA in book_bins!")
        print("This is the likely cause of empty heatmap tiles.")

        # Check when was the last data
        cur.execute("SELECT MAX(bucket_ts) as last FROM book_bins")
        last = cur.fetchone()['last']
        if last:
            age = datetime.now() - last.replace(tzinfo=None)
            print(f"\nLast data was {age.days} days and {age.seconds//3600} hours ago at: {last}")
    print()

    # 6. Check collector activity
    print("6. RAW_EVENTS TABLE CHECK")
    print("-" * 40)
    cur.execute("""
        SELECT
            event_type,
            COUNT(*) as count,
            MAX(ts) as last_ts
        FROM raw_events
        WHERE ts > NOW() - INTERVAL '2 hours'
        GROUP BY event_type
    """)
    events = cur.fetchall()

    if events:
        print("Recent raw events:")
        for e in events:
            print(f"  {e['event_type']}: {e['count']:,} events, last: {e['last_ts']}")
    else:
        print("NO RECENT RAW EVENTS - Collector may not be running!")
    print()

    # 7. Check database timezone
    print("7. DATABASE TIMEZONE")
    print("-" * 40)
    cur.execute("SHOW timezone")
    tz = cur.fetchone()
    print(f"Database timezone: {tz['TimeZone']}")
    cur.execute("SELECT NOW() as db_time")
    db_time = cur.fetchone()['db_time']
    print(f"Database time: {db_time}")
    print(f"Local time: {datetime.now()}")
    print()

    conn.close()
    print("=" * 80)
    print("DIAGNOSIS COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    diagnose()
