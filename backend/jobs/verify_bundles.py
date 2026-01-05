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
3. Reports mismatches via alert/log
4. Maintains audit trail

"线上防腐层 - 自动化持续验证"
"""

import argparse
import time
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from backend.replay.verifier import BundleVerifier, VerificationStatus, VerificationResult

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
        """Run verification once"""
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
                        self._alert_mismatch(result)

                self.stats["bundles_checked"] += 1

        except Exception as e:
            logger.error(f"Verification run error: {e}")
            self.stats["errors"] += 1

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
        # TODO: Implement actual database fetch
        # For now, return empty list as placeholder

        # In production, this would:
        # 1. Connect to database
        # 2. Query evidence_bundles table for recent entries
        # 3. Apply sampling if sample_rate < 1.0
        # 4. Return list of (bundle_data, expected_hash) tuples

        logger.warning("Database fetch not implemented - returning empty list")
        return []

        # Example implementation:
        # import psycopg2
        # from psycopg2.extras import RealDictCursor
        #
        # conn = psycopg2.connect(**self.db_config, cursor_factory=RealDictCursor)
        # cutoff = datetime.now() - timedelta(hours=self.max_age_hours)
        #
        # with conn.cursor() as cur:
        #     cur.execute("""
        #         SELECT token_id, t0, bundle_json, bundle_hash
        #         FROM evidence_bundles
        #         WHERE created_at > %s
        #         ORDER BY RANDOM()
        #         LIMIT %s
        #     """, (cutoff, int(1000 * self.sample_rate)))
        #
        #     rows = cur.fetchall()
        #
        # conn.close()
        # return rows

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

    def _alert_mismatch(self, result: VerificationResult):
        """Send alert for hash mismatch"""
        logger.critical(
            f"ALERT: Hash mismatch detected!\n"
            f"Bundle: {result.bundle_id}\n"
            f"Token: {result.token_id}\n"
            f"T0: {result.t0}\n"
            f"Expected: {result.expected_hash}\n"
            f"Computed: {result.computed_hash}"
        )

        # TODO: Send to alert system, Slack, PagerDuty, etc.

    def run_continuous(self, interval_seconds: int = 3600):
        """Run verification continuously at given interval"""
        logger.info(f"Starting continuous verification (interval: {interval_seconds}s)")

        while True:
            try:
                self.run_once()
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

    args = parser.parse_args()

    job = BundleVerificationJob(
        sample_rate=args.sample_rate,
        max_age_hours=args.max_age,
        alert_on_mismatch=not args.no_alert,
    )

    if args.once:
        result = job.run_once()
        print(json.dumps(result, indent=2))
    else:
        job.run_continuous(interval_seconds=args.interval)


if __name__ == '__main__':
    main()
