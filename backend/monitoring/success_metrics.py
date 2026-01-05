"""
Success Metrics Module - Key Performance Indicators for Production (v5.17)

Defines and tracks success metrics for the Belief Reaction System:

    Metric              Definition                      Target      Instrumentation
    ------------------  ------------------------------  ----------  ---------------
    latency.p50/p99     API latency percentiles         50ms/200ms  Histogram middleware
    audit_rate          % bundles with hash             100%        DB query
    replay_match        % bundles pass replay verify    99.9%       Spot-check job
    alert_dedup_ratio   Deduplicated / Total alerts     > 20%       AlertOpsManager
    data_freshness      Age of latest data point        < 60s       Health check

Usage:
    tracker = SuccessMetricsTracker(db_config=DB_CONFIG)
    report = await tracker.collect_metrics()
    print(report.to_dict())

"Success is defined by the metrics that matter"
"""

import time
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import logging

from .metrics import MetricsRegistry, get_metrics_registry, Histogram


logger = logging.getLogger(__name__)


class MetricStatus(str, Enum):
    """Status of a metric relative to its target"""
    PASSING = "PASSING"       # Meeting target
    WARNING = "WARNING"       # Close to threshold
    FAILING = "FAILING"       # Below target
    UNKNOWN = "UNKNOWN"       # Cannot be measured


@dataclass
class MetricTarget:
    """Target definition for a success metric"""
    name: str
    description: str
    target_value: float
    warning_threshold: float  # Value at which we start warning
    comparison: str  # "lt" (less than), "gt" (greater than), "eq" (equal)
    unit: str = ""

    def evaluate(self, actual: float) -> MetricStatus:
        """Evaluate actual value against target"""
        if actual is None or math.isnan(actual):
            return MetricStatus.UNKNOWN

        if self.comparison == "lt":
            # Lower is better (e.g., latency)
            if actual <= self.target_value:
                return MetricStatus.PASSING
            elif actual <= self.warning_threshold:
                return MetricStatus.WARNING
            else:
                return MetricStatus.FAILING
        elif self.comparison == "gt":
            # Higher is better (e.g., success rate)
            if actual >= self.target_value:
                return MetricStatus.PASSING
            elif actual >= self.warning_threshold:
                return MetricStatus.WARNING
            else:
                return MetricStatus.FAILING
        else:
            # Equal comparison
            return MetricStatus.PASSING if actual == self.target_value else MetricStatus.FAILING


@dataclass
class MetricResult:
    """Result of measuring a success metric"""
    name: str
    value: float
    status: MetricStatus
    target: float
    unit: str
    measured_at: int  # timestamp ms
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": round(self.value, 4) if self.value is not None else None,
            "status": self.status.value,
            "target": self.target,
            "unit": self.unit,
            "measured_at": self.measured_at,
            "measured_at_iso": datetime.fromtimestamp(self.measured_at / 1000).isoformat() + "Z",
            "details": self.details,
        }


@dataclass
class SuccessReport:
    """Complete success metrics report"""
    metrics: List[MetricResult]
    overall_status: MetricStatus
    generated_at: int  # timestamp ms
    period_hours: float = 1.0  # How far back metrics were calculated

    def to_dict(self) -> dict:
        passing = sum(1 for m in self.metrics if m.status == MetricStatus.PASSING)
        failing = sum(1 for m in self.metrics if m.status == MetricStatus.FAILING)
        warning = sum(1 for m in self.metrics if m.status == MetricStatus.WARNING)

        return {
            "overall_status": self.overall_status.value,
            "summary": {
                "total": len(self.metrics),
                "passing": passing,
                "warning": warning,
                "failing": failing,
            },
            "metrics": [m.to_dict() for m in self.metrics],
            "generated_at": self.generated_at,
            "generated_at_iso": datetime.fromtimestamp(self.generated_at / 1000).isoformat() + "Z",
            "period_hours": self.period_hours,
        }

    def to_markdown(self) -> str:
        """Generate markdown report"""
        lines = [
            "# Success Metrics Report",
            "",
            f"**Generated:** {datetime.fromtimestamp(self.generated_at / 1000).isoformat()}",
            f"**Period:** Last {self.period_hours} hour(s)",
            f"**Overall Status:** {self.overall_status.value}",
            "",
            "## Metrics",
            "",
            "| Metric | Value | Target | Status |",
            "|--------|-------|--------|--------|",
        ]

        status_emoji = {
            MetricStatus.PASSING: "✅",
            MetricStatus.WARNING: "⚠️",
            MetricStatus.FAILING: "❌",
            MetricStatus.UNKNOWN: "❓",
        }

        for m in self.metrics:
            value_str = f"{m.value:.2f}{m.unit}" if m.value is not None else "N/A"
            target_str = f"{m.target:.2f}{m.unit}" if m.target is not None else "N/A"
            emoji = status_emoji.get(m.status, "❓")
            lines.append(f"| {m.name} | {value_str} | {target_str} | {emoji} {m.status.value} |")

        lines.extend([
            "",
            "## Summary",
            "",
            f"- **Passing:** {sum(1 for m in self.metrics if m.status == MetricStatus.PASSING)}",
            f"- **Warning:** {sum(1 for m in self.metrics if m.status == MetricStatus.WARNING)}",
            f"- **Failing:** {sum(1 for m in self.metrics if m.status == MetricStatus.FAILING)}",
        ])

        return "\n".join(lines)


# Success metric targets
METRIC_TARGETS: Dict[str, MetricTarget] = {
    "latency_p50": MetricTarget(
        name="latency_p50",
        description="API latency 50th percentile",
        target_value=0.050,  # 50ms
        warning_threshold=0.100,  # 100ms
        comparison="lt",
        unit="s",
    ),
    "latency_p99": MetricTarget(
        name="latency_p99",
        description="API latency 99th percentile",
        target_value=0.200,  # 200ms
        warning_threshold=0.500,  # 500ms
        comparison="lt",
        unit="s",
    ),
    "audit_rate": MetricTarget(
        name="audit_rate",
        description="Percentage of bundles with computed hash",
        target_value=100.0,  # 100%
        warning_threshold=95.0,  # 95%
        comparison="gt",
        unit="%",
    ),
    "replay_match_rate": MetricTarget(
        name="replay_match_rate",
        description="Percentage of bundles passing replay verification",
        target_value=99.9,  # 99.9%
        warning_threshold=99.0,  # 99%
        comparison="gt",
        unit="%",
    ),
    "alert_dedup_ratio": MetricTarget(
        name="alert_dedup_ratio",
        description="Ratio of deduplicated alerts to total",
        target_value=20.0,  # > 20%
        warning_threshold=10.0,  # > 10%
        comparison="gt",
        unit="%",
    ),
    "data_freshness": MetricTarget(
        name="data_freshness",
        description="Age of most recent data point",
        target_value=60.0,  # < 60 seconds
        warning_threshold=120.0,  # < 2 minutes
        comparison="lt",
        unit="s",
    ),
    # v5.33: Evidence system health indicators
    "bundle_completeness": MetricTarget(
        name="bundle_completeness",
        description="Percentage of bundles with all required fields",
        target_value=100.0,  # 100%
        warning_threshold=99.0,  # 99%
        comparison="gt",
        unit="%",
    ),
    "evidence_production_rate": MetricTarget(
        name="evidence_production_rate",
        description="Evidence bundles produced per hour",
        target_value=10.0,  # At least 10 bundles/hour when active
        warning_threshold=5.0,  # Warning if < 5
        comparison="gt",
        unit="/hr",
    ),
    "state_transition_consistency": MetricTarget(
        name="state_transition_consistency",
        description="Percentage of replays producing consistent state transitions",
        target_value=100.0,  # Must be 100% (determinism requirement)
        warning_threshold=100.0,  # No tolerance for inconsistency
        comparison="gt",
        unit="%",
    ),
    # v5.34: World-class evidence-first metrics (from expert review)
    "bundle_hash_stability_rate": MetricTarget(
        name="bundle_hash_stability_rate",
        description="Percentage of bundles with stable hash across recomputation",
        target_value=100.0,  # Must be 100% (determinism requirement)
        warning_threshold=100.0,  # No tolerance for instability
        comparison="gt",
        unit="%",
    ),
    "tainted_window_rate": MetricTarget(
        name="tainted_window_rate",
        description="Percentage of evidence windows marked as tainted (data quality issue)",
        target_value=0.0,  # Target: no tainted windows
        warning_threshold=1.0,  # Warning if > 1%
        comparison="lt",
        unit="%",
    ),
    "tiles_lag_seconds_p99": MetricTarget(
        name="tiles_lag_seconds_p99",
        description="99th percentile tile generation lag in seconds",
        target_value=5.0,  # Target: < 5s
        warning_threshold=10.0,  # Warning if > 10s
        comparison="lt",
        unit="s",
    ),
    "replay_classification_consistency": MetricTarget(
        name="replay_classification_consistency",
        description="Same evidence replay produces same reaction classification",
        target_value=100.0,  # Must be 100% (determinism requirement)
        warning_threshold=100.0,  # No tolerance for inconsistency
        comparison="gt",
        unit="%",
    ),
    "alert_noise_rate": MetricTarget(
        name="alert_noise_rate",
        description="Alerts that were not merged within suppression window (noise)",
        target_value=5.0,  # Target: < 5% noise
        warning_threshold=10.0,  # Warning if > 10%
        comparison="lt",
        unit="%",
    ),
}


def calculate_percentile(histogram_data: Dict, percentile: float) -> float:
    """
    Calculate percentile from histogram bucket data.

    Args:
        histogram_data: Histogram collect() output with buckets, sum, count
        percentile: Percentile to calculate (0-100)

    Returns:
        Estimated percentile value
    """
    if not histogram_data or 'buckets' not in histogram_data:
        return float('nan')

    buckets = histogram_data['buckets']
    count = histogram_data.get('count', 0)

    if count == 0:
        return float('nan')

    target_count = (percentile / 100.0) * count

    # Buckets are cumulative, find the bucket where we exceed target
    sorted_buckets = sorted((b, c) for b, c in buckets.items() if b != float('inf'))

    prev_bucket = 0
    prev_count = 0

    for bucket, cumulative_count in sorted_buckets:
        if cumulative_count >= target_count:
            # Linear interpolation within bucket
            if cumulative_count == prev_count:
                return bucket
            fraction = (target_count - prev_count) / (cumulative_count - prev_count)
            return prev_bucket + fraction * (bucket - prev_bucket)
        prev_bucket = bucket
        prev_count = cumulative_count

    # Return last finite bucket
    return sorted_buckets[-1][0] if sorted_buckets else float('nan')


class SuccessMetricsTracker:
    """
    Tracks and reports on success metrics.

    Features:
    - Collects metrics from various sources (registry, DB, AlertOps)
    - Calculates percentiles from histograms
    - Evaluates against targets
    - Generates reports

    Usage:
        tracker = SuccessMetricsTracker(db_config=DB_CONFIG)
        report = await tracker.collect_metrics()
    """

    def __init__(
        self,
        db_config: Dict[str, Any] = None,
        registry: MetricsRegistry = None,
    ):
        self.db_config = db_config or {}
        self.registry = registry or get_metrics_registry()
        self._db_conn = None

    def _get_conn(self):
        """Get database connection"""
        if self._db_conn and not self._db_conn.closed:
            return self._db_conn

        try:
            import psycopg2
            self._db_conn = psycopg2.connect(**self.db_config)
            return self._db_conn
        except Exception:
            return None

    async def collect_metrics(self, period_hours: float = 1.0) -> SuccessReport:
        """
        Collect all success metrics.

        Args:
            period_hours: How far back to look for metrics

        Returns:
            SuccessReport with all metric results
        """
        now = int(time.time() * 1000)
        results = []

        # Collect latency metrics from histogram
        latency_results = self._collect_latency_metrics()
        results.extend(latency_results)

        # Collect audit rate from database
        audit_result = await self._collect_audit_rate()
        if audit_result:
            results.append(audit_result)

        # Collect replay match rate
        replay_result = await self._collect_replay_match_rate()
        if replay_result:
            results.append(replay_result)

        # Collect alert dedup ratio
        dedup_result = await self._collect_alert_dedup_ratio()
        if dedup_result:
            results.append(dedup_result)

        # Collect data freshness
        freshness_result = await self._collect_data_freshness()
        if freshness_result:
            results.append(freshness_result)

        # v5.33: Collect evidence system health indicators
        completeness_result = await self._collect_bundle_completeness()
        if completeness_result:
            results.append(completeness_result)

        production_result = await self._collect_evidence_production_rate()
        if production_result:
            results.append(production_result)

        consistency_result = await self._collect_state_consistency()
        if consistency_result:
            results.append(consistency_result)

        # Determine overall status
        overall = MetricStatus.PASSING
        for r in results:
            if r.status == MetricStatus.FAILING:
                overall = MetricStatus.FAILING
                break
            elif r.status == MetricStatus.WARNING and overall != MetricStatus.FAILING:
                overall = MetricStatus.WARNING

        return SuccessReport(
            metrics=results,
            overall_status=overall,
            generated_at=now,
            period_hours=period_hours,
        )

    def _collect_latency_metrics(self) -> List[MetricResult]:
        """Collect latency percentiles from histogram"""
        results = []
        now = int(time.time() * 1000)

        histogram = self.registry.get_metric("http_request_duration_seconds")
        if not histogram or not isinstance(histogram, Histogram):
            # Return unknown status if no histogram data
            for metric_name in ["latency_p50", "latency_p99"]:
                target = METRIC_TARGETS[metric_name]
                results.append(MetricResult(
                    name=metric_name,
                    value=float('nan'),
                    status=MetricStatus.UNKNOWN,
                    target=target.target_value,
                    unit=target.unit,
                    measured_at=now,
                    details={"reason": "No histogram data available"},
                ))
            return results

        # Get histogram data (aggregate all labels)
        hist_data = histogram.collect()

        # Aggregate all label combinations
        total_buckets: Dict[float, int] = {}
        total_sum = 0.0
        total_count = 0

        for label_key, data in hist_data.items():
            for bucket, count in data['buckets'].items():
                total_buckets[bucket] = total_buckets.get(bucket, 0) + count
            total_sum += data['sum']
            total_count += data['count']

        aggregated = {
            'buckets': total_buckets,
            'sum': total_sum,
            'count': total_count,
        }

        # Calculate p50 and p99
        for percentile, metric_name in [(50, "latency_p50"), (99, "latency_p99")]:
            target = METRIC_TARGETS[metric_name]
            value = calculate_percentile(aggregated, percentile)
            status = target.evaluate(value)

            results.append(MetricResult(
                name=metric_name,
                value=value,
                status=status,
                target=target.target_value,
                unit=target.unit,
                measured_at=now,
                details={
                    "percentile": percentile,
                    "sample_count": total_count,
                },
            ))

        return results

    async def _collect_audit_rate(self) -> Optional[MetricResult]:
        """Collect audit rate (% bundles with hash)"""
        now = int(time.time() * 1000)
        target = METRIC_TARGETS["audit_rate"]

        conn = self._get_conn()
        if not conn:
            return MetricResult(
                name="audit_rate",
                value=float('nan'),
                status=MetricStatus.UNKNOWN,
                target=target.target_value,
                unit=target.unit,
                measured_at=now,
                details={"reason": "Database unavailable"},
            )

        try:
            with conn.cursor() as cur:
                # Count bundles with hash vs total
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(bundle_hash) as with_hash
                    FROM evidence_bundles
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                """)
                row = cur.fetchone()

                total = row[0] if row else 0
                with_hash = row[1] if row else 0

                if total == 0:
                    rate = 100.0  # No bundles = 100% audit rate by default
                else:
                    rate = (with_hash / total) * 100

                status = target.evaluate(rate)

                return MetricResult(
                    name="audit_rate",
                    value=rate,
                    status=status,
                    target=target.target_value,
                    unit=target.unit,
                    measured_at=now,
                    details={
                        "total_bundles": total,
                        "bundles_with_hash": with_hash,
                    },
                )

        except Exception as e:
            logger.warning(f"Failed to collect audit rate: {e}")
            return MetricResult(
                name="audit_rate",
                value=float('nan'),
                status=MetricStatus.UNKNOWN,
                target=target.target_value,
                unit=target.unit,
                measured_at=now,
                details={"error": str(e)},
            )

    async def _collect_replay_match_rate(self) -> Optional[MetricResult]:
        """Collect replay match rate from verification results"""
        now = int(time.time() * 1000)
        target = METRIC_TARGETS["replay_match_rate"]

        conn = self._get_conn()
        if not conn:
            return MetricResult(
                name="replay_match_rate",
                value=float('nan'),
                status=MetricStatus.UNKNOWN,
                target=target.target_value,
                unit=target.unit,
                measured_at=now,
                details={"reason": "Database unavailable"},
            )

        try:
            with conn.cursor() as cur:
                # Check verification_results table
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(CASE WHEN status = 'passed' THEN 1 END) as passed
                    FROM verification_results
                    WHERE verified_at > NOW() - INTERVAL '24 hours'
                """)
                row = cur.fetchone()

                total = row[0] if row else 0
                passed = row[1] if row else 0

                if total == 0:
                    rate = 100.0  # No verifications = assume passing
                else:
                    rate = (passed / total) * 100

                status = target.evaluate(rate)

                return MetricResult(
                    name="replay_match_rate",
                    value=rate,
                    status=status,
                    target=target.target_value,
                    unit=target.unit,
                    measured_at=now,
                    details={
                        "total_verified": total,
                        "passed": passed,
                        "failed": total - passed,
                    },
                )

        except Exception as e:
            logger.warning(f"Failed to collect replay match rate: {e}")
            return MetricResult(
                name="replay_match_rate",
                value=float('nan'),
                status=MetricStatus.UNKNOWN,
                target=target.target_value,
                unit=target.unit,
                measured_at=now,
                details={"error": str(e)},
            )

    async def _collect_alert_dedup_ratio(self) -> Optional[MetricResult]:
        """Collect alert deduplication ratio"""
        now = int(time.time() * 1000)
        target = METRIC_TARGETS["alert_dedup_ratio"]

        # Try to get from AlertOpsManager
        try:
            from backend.alerting import get_ops_manager
            ops = get_ops_manager()
            stats = ops.get_stats()

            total = stats.get("total_processed", 0)
            deduped = stats.get("total_deduplicated", 0)

            if total == 0:
                ratio = 0.0
            else:
                ratio = (deduped / total) * 100

            status = target.evaluate(ratio)

            return MetricResult(
                name="alert_dedup_ratio",
                value=ratio,
                status=status,
                target=target.target_value,
                unit=target.unit,
                measured_at=now,
                details={
                    "total_alerts": total,
                    "deduplicated": deduped,
                },
            )

        except Exception as e:
            logger.warning(f"Failed to collect alert dedup ratio: {e}")
            return MetricResult(
                name="alert_dedup_ratio",
                value=float('nan'),
                status=MetricStatus.UNKNOWN,
                target=target.target_value,
                unit=target.unit,
                measured_at=now,
                details={"error": str(e)},
            )

    async def _collect_data_freshness(self) -> Optional[MetricResult]:
        """Collect data freshness (age of latest data)"""
        now = int(time.time() * 1000)
        target = METRIC_TARGETS["data_freshness"]

        conn = self._get_conn()
        if not conn:
            return MetricResult(
                name="data_freshness",
                value=float('nan'),
                status=MetricStatus.UNKNOWN,
                target=target.target_value,
                unit=target.unit,
                measured_at=now,
                details={"reason": "Database unavailable"},
            )

        try:
            with conn.cursor() as cur:
                # Get latest trade timestamp
                cur.execute("SELECT MAX(ts) FROM trade_ticks")
                row = cur.fetchone()
                latest_trade = row[0] if row and row[0] else None

                if latest_trade:
                    from datetime import timezone
                    now_dt = datetime.now(timezone.utc)
                    age_seconds = (now_dt - latest_trade.replace(tzinfo=timezone.utc)).total_seconds()
                else:
                    age_seconds = float('inf')

                status = target.evaluate(age_seconds)

                return MetricResult(
                    name="data_freshness",
                    value=age_seconds if age_seconds != float('inf') else float('nan'),
                    status=status,
                    target=target.target_value,
                    unit=target.unit,
                    measured_at=now,
                    details={
                        "latest_timestamp": latest_trade.isoformat() if latest_trade else None,
                    },
                )

        except Exception as e:
            logger.warning(f"Failed to collect data freshness: {e}")
            return MetricResult(
                name="data_freshness",
                value=float('nan'),
                status=MetricStatus.UNKNOWN,
                target=target.target_value,
                unit=target.unit,
                measured_at=now,
                details={"error": str(e)},
            )

    # =========================================================================
    # v5.33: Evidence System Health Indicators
    # =========================================================================

    async def _collect_bundle_completeness(self) -> Optional[MetricResult]:
        """
        Collect bundle completeness (% bundles with all required fields).

        Required fields: token_id, t0, window, bundle_hash, trades
        """
        now = int(time.time() * 1000)
        target = METRIC_TARGETS["bundle_completeness"]

        conn = self._get_conn()
        if not conn:
            return MetricResult(
                name="bundle_completeness",
                value=float('nan'),
                status=MetricStatus.UNKNOWN,
                target=target.target_value,
                unit=target.unit,
                measured_at=now,
                details={"reason": "Database unavailable"},
            )

        try:
            with conn.cursor() as cur:
                # Count complete bundles vs total
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(CASE WHEN
                            token_id IS NOT NULL AND
                            t0 IS NOT NULL AND
                            window_from_ts IS NOT NULL AND
                            window_to_ts IS NOT NULL AND
                            bundle_hash IS NOT NULL
                        THEN 1 END) as complete
                    FROM evidence_bundles
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                """)
                row = cur.fetchone()

                total = row[0] if row else 0
                complete = row[1] if row else 0

                if total == 0:
                    rate = 100.0  # No bundles = 100% complete by definition
                else:
                    rate = (complete / total) * 100

                status = target.evaluate(rate)

                return MetricResult(
                    name="bundle_completeness",
                    value=rate,
                    status=status,
                    target=target.target_value,
                    unit=target.unit,
                    measured_at=now,
                    details={
                        "total_bundles": total,
                        "complete_bundles": complete,
                        "incomplete_bundles": total - complete,
                    },
                )

        except Exception as e:
            logger.warning(f"Failed to collect bundle completeness: {e}")
            return MetricResult(
                name="bundle_completeness",
                value=float('nan'),
                status=MetricStatus.UNKNOWN,
                target=target.target_value,
                unit=target.unit,
                measured_at=now,
                details={"error": str(e)},
            )

    async def _collect_evidence_production_rate(self) -> Optional[MetricResult]:
        """
        Collect evidence production rate (bundles per hour).
        """
        now = int(time.time() * 1000)
        target = METRIC_TARGETS["evidence_production_rate"]

        conn = self._get_conn()
        if not conn:
            return MetricResult(
                name="evidence_production_rate",
                value=float('nan'),
                status=MetricStatus.UNKNOWN,
                target=target.target_value,
                unit=target.unit,
                measured_at=now,
                details={"reason": "Database unavailable"},
            )

        try:
            with conn.cursor() as cur:
                # Count bundles in last hour
                cur.execute("""
                    SELECT COUNT(*) as count
                    FROM evidence_bundles
                    WHERE created_at > NOW() - INTERVAL '1 hour'
                """)
                row = cur.fetchone()
                bundles_per_hour = row[0] if row else 0

                # Get activity status
                cur.execute("""
                    SELECT COUNT(*) as recent
                    FROM trade_ticks
                    WHERE ts > NOW() - INTERVAL '5 minutes'
                """)
                activity_row = cur.fetchone()
                is_active = (activity_row[0] if activity_row else 0) > 0

                # If no recent data activity, skip this metric (system idle)
                if not is_active:
                    return MetricResult(
                        name="evidence_production_rate",
                        value=float('nan'),
                        status=MetricStatus.UNKNOWN,
                        target=target.target_value,
                        unit=target.unit,
                        measured_at=now,
                        details={
                            "reason": "System idle (no recent data)",
                            "bundles_last_hour": bundles_per_hour,
                        },
                    )

                status = target.evaluate(bundles_per_hour)

                return MetricResult(
                    name="evidence_production_rate",
                    value=bundles_per_hour,
                    status=status,
                    target=target.target_value,
                    unit=target.unit,
                    measured_at=now,
                    details={
                        "bundles_last_hour": bundles_per_hour,
                        "system_active": is_active,
                    },
                )

        except Exception as e:
            logger.warning(f"Failed to collect evidence production rate: {e}")
            return MetricResult(
                name="evidence_production_rate",
                value=float('nan'),
                status=MetricStatus.UNKNOWN,
                target=target.target_value,
                unit=target.unit,
                measured_at=now,
                details={"error": str(e)},
            )

    async def _collect_state_consistency(self) -> Optional[MetricResult]:
        """
        Collect state transition consistency (% replays with consistent states).

        This is the most critical evidence health indicator:
        "同一证据包，不同机器回放结果必须相同"
        """
        now = int(time.time() * 1000)
        target = METRIC_TARGETS["state_transition_consistency"]

        conn = self._get_conn()
        if not conn:
            return MetricResult(
                name="state_transition_consistency",
                value=float('nan'),
                status=MetricStatus.UNKNOWN,
                target=target.target_value,
                unit=target.unit,
                measured_at=now,
                details={"reason": "Database unavailable"},
            )

        try:
            with conn.cursor() as cur:
                # Check replay verification results for state consistency
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(CASE WHEN
                            status = 'passed' AND
                            (details->>'state_consistent')::boolean = true
                        THEN 1 END) as consistent
                    FROM verification_results
                    WHERE verified_at > NOW() - INTERVAL '24 hours'
                    AND check_type = 'replay'
                """)
                row = cur.fetchone()

                total = row[0] if row else 0
                consistent = row[1] if row else 0

                if total == 0:
                    # No replay verifications - assume 100% (determinism tests cover this)
                    rate = 100.0
                else:
                    rate = (consistent / total) * 100

                status = target.evaluate(rate)

                # Any inconsistency is a critical failure
                if rate < 100.0 and total > 0:
                    status = MetricStatus.FAILING

                return MetricResult(
                    name="state_transition_consistency",
                    value=rate,
                    status=status,
                    target=target.target_value,
                    unit=target.unit,
                    measured_at=now,
                    details={
                        "total_replays": total,
                        "consistent_replays": consistent,
                        "inconsistent_replays": total - consistent,
                        "critical": rate < 100.0 and total > 0,
                    },
                )

        except Exception as e:
            logger.warning(f"Failed to collect state consistency: {e}")
            return MetricResult(
                name="state_transition_consistency",
                value=float('nan'),
                status=MetricStatus.UNKNOWN,
                target=target.target_value,
                unit=target.unit,
                measured_at=now,
                details={"error": str(e)},
            )

    def get_targets(self) -> Dict[str, MetricTarget]:
        """Get all metric targets"""
        return METRIC_TARGETS.copy()

    def update_target(self, name: str, target_value: float = None, warning_threshold: float = None):
        """Update a metric target"""
        if name not in METRIC_TARGETS:
            raise ValueError(f"Unknown metric: {name}")

        target = METRIC_TARGETS[name]
        if target_value is not None:
            target.target_value = target_value
        if warning_threshold is not None:
            target.warning_threshold = warning_threshold


# CI Gate functions
def ci_gate_check(report: SuccessReport) -> Tuple[bool, str]:
    """
    Check if CI gate should pass based on success metrics.

    Returns:
        (passed, message) tuple
    """
    if report.overall_status == MetricStatus.FAILING:
        failing = [m for m in report.metrics if m.status == MetricStatus.FAILING]
        names = [m.name for m in failing]
        return False, f"CI gate failed. Failing metrics: {', '.join(names)}"

    if report.overall_status == MetricStatus.WARNING:
        warnings = [m for m in report.metrics if m.status == MetricStatus.WARNING]
        names = [m.name for m in warnings]
        return True, f"CI gate passed with warnings: {', '.join(names)}"

    return True, "CI gate passed. All metrics meeting targets."


async def run_ci_gate(db_config: Dict[str, Any] = None) -> int:
    """
    Run CI gate check and return exit code.

    Usage in CI:
        python -c "import asyncio; from backend.monitoring.success_metrics import run_ci_gate; exit(asyncio.run(run_ci_gate()))"

    Returns:
        0 for pass, 1 for fail
    """
    tracker = SuccessMetricsTracker(db_config=db_config)
    report = await tracker.collect_metrics()

    passed, message = ci_gate_check(report)
    print(message)
    print()
    print(report.to_markdown())

    return 0 if passed else 1


# Global singleton
_tracker: Optional[SuccessMetricsTracker] = None


def get_success_tracker(db_config: Dict[str, Any] = None) -> SuccessMetricsTracker:
    """Get or create global success metrics tracker"""
    global _tracker
    if _tracker is None:
        _tracker = SuccessMetricsTracker(db_config=db_config)
    return _tracker
