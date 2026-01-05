#!/usr/bin/env python3
"""
Belief Reaction System - Automated Bundle Verification Job
Periodic job to verify evidence bundle integrity.

Usage:
    python -m backend.jobs.verify_bundles --interval 3600  # Every hour
    python -m backend.jobs.verify_bundles --once  # Run once and exit

This job:
1. Fetches recent evidence bundles from database
2. Verifies hash integrity for each
3. Reports mismatches via alert router (Slack, WebSocket, etc.)
4. Maintains audit trail

"线上防腐层 - 自动化持续验证"
"""

import argparse
import asyncio
import time
import json
import random
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from backend.replay.verifier import BundleVerifier, VerificationStatus, VerificationResult
from backend.alerting import (
    AlertRouter, AlertPayload, AlertPriority, AlertCategory,
    WebSocketBroadcastDestination, LogDestination, SlackDestination,
    create_router_from_config, get_default_router
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('bundle_verifier')


class BundleVerificationJob:
    """
    Automated bundle verification job.

    Runs periodically to verify evidence bundle integrity,
    detecting any hash mismatches that could indicate
    data corruption or tampering.
    """

    def __init__(
        self,
        db_config: Optional[Dict] = None,
        sample_rate: float = 0.1,  # Verify 10% of bundles by default
        max_age_hours: int = 24,   # Only verify bundles from last 24h
        alert_on_mismatch: bool = True,
        alert_router: Optional[AlertRouter] = None,
    ):
        self.db_config = db_config or {
            'host': '127.0.0.1',
            'port': 5433,
            'database': 'belief_reaction',
            'user': 'postgres',
            'password': 'postgres'
        }
        self.sample_rate = sample_rate
        self.max_age_hours = max_age_hours
        self.alert_on_mismatch = alert_on_mismatch
        self.alert_router = alert_router or get_default_router()

        self.verifier = BundleVerifier()

        # Stats
        self.stats = {
            "runs": 0,
            "bundles_checked": 0,
            "bundles_passed": 0,
            "bundles_failed": 0,
            "errors": 0,
            "last_run": None,
            "last_mismatch": None,
        }

    def run_once(self) -> Dict[str, Any]:
        """Run verification once (sync wrapper)"""
        return asyncio.get_event_loop().run_until_complete(self._run_once_async())

    async def _run_once_async(self) -> Dict[str, Any]:
        """Run verification once (async)"""
        run_start = datetime.now()
        logger.info(f"Starting bundle verification run at {run_start.isoformat()}")

        results = []

        try:
            # Fetch bundles to verify
            bundles = self._fetch_bundles()
            logger.info(f"Fetched {len(bundles)} bundles to verify")

            # Verify each bundle
            for bundle_data in bundles:
                result = self._verify_bundle(bundle_data)
                results.append(result)

                if result.overall_status == VerificationStatus.PASS:
                    self.stats["bundles_passed"] += 1
                else:
                    self.stats["bundles_failed"] += 1
                    self.stats["last_mismatch"] = datetime.now().isoformat()

                    if self.alert_on_mismatch:
                        await self._alert_mismatch(result)

                self.stats["bundles_checked"] += 1

        except Exception as e:
            logger.error(f"Verification run error: {e}")
            self.stats["errors"] += 1

            # Alert on system error
            await self._alert_system_error(str(e))

        self.stats["runs"] += 1
        self.stats["last_run"] = datetime.now().isoformat()

        run_duration = (datetime.now() - run_start).total_seconds()
        logger.info(f"Verification run completed in {run_duration:.2f}s")
        logger.info(f"Results: {self.stats['bundles_passed']} passed, {self.stats['bundles_failed']} failed")

        return {
            "run_at": run_start.isoformat(),
            "duration_seconds": run_duration,
            "bundles_checked": len(results),
            "passed": sum(1 for r in results if r.overall_status == VerificationStatus.PASS),
            "failed": sum(1 for r in results if r.overall_status != VerificationStatus.PASS),
            "results": [r.to_dict() for r in results],
        }

    def _fetch_bundles(self) -> List[Dict]:
        """Fetch bundles from database for verification"""
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor

            conn = psycopg2.connect(**self.db_config, cursor_factory=RealDictCursor)
            cutoff = datetime.now() - timedelta(hours=self.max_age_hours)

            with conn.cursor() as cur:
                # Check if evidence_bundles table exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'evidence_bundles'
                    )
                """)
                table_exists = cur.fetchone()['exists']

                if not table_exists:
                    logger.warning("evidence_bundles table does not exist yet")
                    conn.close()
                    return []

                # Calculate sample limit
                cur.execute("SELECT COUNT(*) FROM evidence_bundles WHERE created_at > %s", (cutoff,))
                total_count = cur.fetchone()['count']
                sample_limit = max(1, int(total_count * self.sample_rate))

                logger.info(f"Total bundles in range: {total_count}, sampling {sample_limit}")

                # Fetch random sample of bundles
                cur.execute("""
                    SELECT
                        bundle_id,
                        token_id,
                        t0,
                        bundle_json,
                        bundle_hash,
                        created_at
                    FROM evidence_bundles
                    WHERE created_at > %s
                    ORDER BY RANDOM()
                    LIMIT %s
                """, (cutoff, sample_limit))

                rows = cur.fetchall()

            conn.close()

            # Convert to list of dicts
            bundles = []
            for row in rows:
                bundle_json = row['bundle_json']
                if isinstance(bundle_json, str):
                    bundle_json = json.loads(bundle_json)

                bundles.append({
                    'bundle_id': row['bundle_id'],
                    'token_id': row['token_id'],
                    't0': row['t0'],
                    'bundle_json': bundle_json,
                    'bundle_hash': row['bundle_hash'],
                    'created_at': row['created_at'],
                })

            return bundles

        except ImportError:
            logger.warning("psycopg2 not available - returning empty bundle list")
            return []
        except Exception as e:
            logger.error(f"Error fetching bundles: {e}")
            return []

    def _verify_bundle(self, bundle_data: Dict) -> VerificationResult:
        """Verify a single bundle"""
        bundle = bundle_data.get('bundle_json', {})
        if isinstance(bundle, str):
            bundle = json.loads(bundle)

        expected_hash = bundle_data.get('bundle_hash', '')

        result = self.verifier.verify(bundle, expected_hash)

        if result.overall_status != VerificationStatus.PASS:
            logger.warning(
                f"Verification failed for bundle {result.bundle_id}: "
                f"{result.overall_status.value}"
            )
            for check in result.checks:
                if check.status != VerificationStatus.PASS:
                    logger.warning(f"  - {check.check_name}: {check.message}")

        return result

    async def _alert_mismatch(self, result: VerificationResult):
        """Send alert for hash mismatch via router"""
        # Determine priority based on failure type
        priority = AlertPriority.HIGH
        if result.overall_status == VerificationStatus.CRITICAL_FAIL:
            priority = AlertPriority.CRITICAL

        # Build failure details
        failed_checks = [
            f"- {c.check_name}: {c.message}"
            for c in result.checks
            if c.status != VerificationStatus.PASS
        ]
        failure_details = "\n".join(failed_checks) if failed_checks else "Unknown failure"

        alert = AlertPayload(
            alert_id=f"hash_mismatch_{result.bundle_id}_{int(time.time())}",
            category=AlertCategory.HASH_MISMATCH,
            priority=priority,
            title=f"Bundle Hash Mismatch: {result.bundle_id[:16]}...",
            message=(
                f"Evidence bundle verification failed!\n\n"
                f"**Token:** `{result.token_id}`\n"
                f"**T0:** {result.t0}\n"
                f"**Expected:** `{result.expected_hash[:16]}...`\n"
                f"**Computed:** `{result.computed_hash[:16]}...`\n\n"
                f"**Failed Checks:**\n{failure_details}"
            ),
            token_id=result.token_id,
            data={
                "bundle_id": result.bundle_id,
                "expected_hash": result.expected_hash,
                "computed_hash": result.computed_hash,
                "checks": [c.to_dict() for c in result.checks],
            },
            evidence_ref={
                "token_id": result.token_id,
                "t0": result.t0,
            }
        )

        # Route to all configured destinations
        routing_results = await self.alert_router.route(alert)
        logger.info(f"Alert routed: {routing_results}")

    async def _alert_system_error(self, error_msg: str):
        """Send alert for system error"""
        alert = AlertPayload(
            alert_id=f"verify_error_{int(time.time())}",
            category=AlertCategory.SYSTEM,
            priority=AlertPriority.HIGH,
            title="Bundle Verification Job Error",
            message=f"The bundle verification job encountered an error:\n\n```\n{error_msg}\n```",
            data={"error": error_msg},
        )

        await self.alert_router.route(alert)

    def run_continuous(self, interval_seconds: int = 3600):
        """Run verification continuously at given interval"""
        logger.info(f"Starting continuous verification (interval: {interval_seconds}s)")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        while True:
            try:
                loop.run_until_complete(self._run_once_async())
            except Exception as e:
                logger.error(f"Error in verification run: {e}")

            logger.info(f"Sleeping for {interval_seconds}s until next run...")
            time.sleep(interval_seconds)

    def get_stats(self) -> Dict:
        """Get verification statistics"""
        return self.stats.copy()


def main():
    parser = argparse.ArgumentParser(
        description="Automated Evidence Bundle Verification"
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=3600,
        help='Verification interval in seconds (default: 3600 = 1 hour)'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Run once and exit'
    )
    parser.add_argument(
        '--sample-rate',
        type=float,
        default=0.1,
        help='Fraction of bundles to verify (default: 0.1 = 10%%)'
    )
    parser.add_argument(
        '--max-age',
        type=int,
        default=24,
        help='Max age of bundles to verify in hours (default: 24)'
    )
    parser.add_argument(
        '--no-alert',
        action='store_true',
        help='Disable alerts on mismatch'
    )
    parser.add_argument(
        '--slack-webhook',
        type=str,
        help='Slack webhook URL for alerts'
    )
    parser.add_argument(
        '--config',
        type=str,
        help='Path to JSON config file for alert routing'
    )

    args = parser.parse_args()

    # Build alert router
    if args.config:
        with open(args.config) as f:
            config = json.load(f)
        router = create_router_from_config(config)
    elif args.slack_webhook:
        router = AlertRouter()
        router.add_destination(SlackDestination(
            webhook_url=args.slack_webhook,
            min_priority=AlertPriority.HIGH
        ))
        router.add_destination(WebSocketBroadcastDestination())
        router.add_destination(LogDestination())
    else:
        router = get_default_router()

    job = BundleVerificationJob(
        sample_rate=args.sample_rate,
        max_age_hours=args.max_age,
        alert_on_mismatch=not args.no_alert,
        alert_router=router,
    )

    if args.once:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(job._run_once_async())
        print(json.dumps(result, indent=2, default=str))
    else:
        job.run_continuous(interval_seconds=args.interval)


if __name__ == '__main__':
    main()
