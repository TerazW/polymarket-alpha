"""
Cost Alerting Module (v5.36)

Monitors cost-related metrics and triggers alerts when thresholds are exceeded.
This is distinct from performance alerting (latency, error rates).

"控成本，不是控延迟"

Cost dimensions monitored:
1. Bandwidth - Heatmap tile egress, API response sizes
2. Storage - Database growth, tile cache size
3. Compute - API calls, tile generation jobs
4. External - WebSocket connections, upstream API calls

Usage:
    monitor = CostMonitor(config)
    monitor.start()

    # Check current costs
    report = monitor.get_cost_report()

    # Manual threshold check
    alerts = monitor.check_thresholds()
"""

import time
import threading
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class CostCategory(str, Enum):
    """Cost alert categories"""
    BANDWIDTH = "BANDWIDTH"       # Data transfer
    STORAGE = "STORAGE"           # Disk/DB storage
    COMPUTE = "COMPUTE"           # CPU/processing
    EXTERNAL = "EXTERNAL"         # Third-party costs


class CostAlertSeverity(str, Enum):
    """Cost alert severity levels"""
    INFO = "INFO"           # 50% of threshold
    WARNING = "WARNING"     # 80% of threshold
    CRITICAL = "CRITICAL"   # 100%+ of threshold


@dataclass
class CostThreshold:
    """Threshold configuration for a cost metric"""
    name: str
    category: CostCategory
    unit: str                    # "GB", "requests", "connections", etc.
    period: str                  # "hourly", "daily", "monthly"

    # Threshold values
    warning_threshold: float     # 80% - send warning
    critical_threshold: float    # 100% - send critical alert

    # Optional soft limit (for degraded mode)
    soft_limit: Optional[float] = None

    # Description for alerts
    description: str = ""


@dataclass
class CostMetric:
    """Current value of a cost metric"""
    name: str
    category: CostCategory
    current_value: float
    unit: str
    period: str
    period_start: int            # Unix timestamp
    period_end: int
    samples: int = 0             # Number of samples in period


@dataclass
class CostAlert:
    """Generated cost alert"""
    alert_id: str
    timestamp: int
    category: CostCategory
    severity: CostAlertSeverity
    metric_name: str
    current_value: float
    threshold_value: float
    unit: str
    period: str
    message: str
    recommendation: str


# =============================================================================
# Default Cost Thresholds
# =============================================================================

DEFAULT_THRESHOLDS: Dict[str, CostThreshold] = {
    # Bandwidth thresholds
    "tile_egress_daily": CostThreshold(
        name="tile_egress_daily",
        category=CostCategory.BANDWIDTH,
        unit="GB",
        period="daily",
        warning_threshold=50.0,      # 50 GB/day warning
        critical_threshold=100.0,    # 100 GB/day critical
        soft_limit=150.0,            # Start degrading at 150 GB
        description="Daily heatmap tile data transfer",
    ),
    "tile_egress_monthly": CostThreshold(
        name="tile_egress_monthly",
        category=CostCategory.BANDWIDTH,
        unit="TB",
        period="monthly",
        warning_threshold=3.0,       # 3 TB/month warning
        critical_threshold=5.0,      # 5 TB/month critical (ChatGPT red line)
        soft_limit=8.0,
        description="Monthly heatmap tile data transfer",
    ),
    "api_egress_daily": CostThreshold(
        name="api_egress_daily",
        category=CostCategory.BANDWIDTH,
        unit="GB",
        period="daily",
        warning_threshold=10.0,
        critical_threshold=20.0,
        description="Daily API response data transfer",
    ),

    # Storage thresholds
    "db_size_total": CostThreshold(
        name="db_size_total",
        category=CostCategory.STORAGE,
        unit="GB",
        period="current",
        warning_threshold=50.0,      # 50 GB warning
        critical_threshold=100.0,    # 100 GB critical
        description="Total database size",
    ),
    "db_growth_daily": CostThreshold(
        name="db_growth_daily",
        category=CostCategory.STORAGE,
        unit="GB",
        period="daily",
        warning_threshold=2.0,       # 2 GB/day growth warning
        critical_threshold=5.0,      # 5 GB/day critical
        description="Daily database growth rate",
    ),
    "tile_cache_size": CostThreshold(
        name="tile_cache_size",
        category=CostCategory.STORAGE,
        unit="GB",
        period="current",
        warning_threshold=20.0,
        critical_threshold=50.0,
        description="Heatmap tile cache size",
    ),

    # Compute thresholds
    "api_requests_daily": CostThreshold(
        name="api_requests_daily",
        category=CostCategory.COMPUTE,
        unit="requests",
        period="daily",
        warning_threshold=100000,    # 100K/day
        critical_threshold=500000,   # 500K/day
        description="Daily API request count",
    ),
    "tile_generations_daily": CostThreshold(
        name="tile_generations_daily",
        category=CostCategory.COMPUTE,
        unit="tiles",
        period="daily",
        warning_threshold=50000,
        critical_threshold=100000,
        description="Daily tile generation jobs",
    ),
    "reactor_events_daily": CostThreshold(
        name="reactor_events_daily",
        category=CostCategory.COMPUTE,
        unit="events",
        period="daily",
        warning_threshold=1000000,   # 1M events/day
        critical_threshold=5000000,  # 5M events/day
        description="Daily reactor event processing",
    ),

    # External thresholds
    "ws_connections_concurrent": CostThreshold(
        name="ws_connections_concurrent",
        category=CostCategory.EXTERNAL,
        unit="connections",
        period="current",
        warning_threshold=500,
        critical_threshold=1000,     # ChatGPT red line
        description="Concurrent WebSocket connections",
    ),
    "upstream_requests_daily": CostThreshold(
        name="upstream_requests_daily",
        category=CostCategory.EXTERNAL,
        unit="requests",
        period="daily",
        warning_threshold=50000,
        critical_threshold=100000,
        description="Daily upstream API calls (Polymarket)",
    ),
    "tracked_markets": CostThreshold(
        name="tracked_markets",
        category=CostCategory.EXTERNAL,
        unit="markets",
        period="current",
        warning_threshold=200,       # ChatGPT stage 1 trigger
        critical_threshold=500,
        description="Number of actively tracked markets",
    ),
}


# =============================================================================
# Cost Metrics Collector
# =============================================================================

class CostMetricsCollector:
    """
    Collects cost-related metrics from various sources.

    Sources:
    - Database queries (storage, growth)
    - Internal counters (requests, events)
    - External APIs (if needed)
    """

    def __init__(self, db_conn=None):
        self._db_conn = db_conn
        self._counters: Dict[str, float] = {}
        self._period_starts: Dict[str, int] = {}
        self._lock = threading.Lock()

    def increment(self, metric: str, value: float = 1.0) -> None:
        """Increment a counter metric"""
        with self._lock:
            self._counters[metric] = self._counters.get(metric, 0) + value

    def set_gauge(self, metric: str, value: float) -> None:
        """Set a gauge metric (current value)"""
        with self._lock:
            self._counters[metric] = value

    def get_counter(self, metric: str) -> float:
        """Get current counter value"""
        with self._lock:
            return self._counters.get(metric, 0)

    def reset_counter(self, metric: str) -> float:
        """Reset counter and return previous value"""
        with self._lock:
            value = self._counters.get(metric, 0)
            self._counters[metric] = 0
            return value

    def collect_db_metrics(self) -> Dict[str, float]:
        """Collect database-related metrics"""
        if not self._db_conn:
            return {}

        metrics = {}

        try:
            with self._db_conn.cursor() as cur:
                # Total database size
                cur.execute("""
                    SELECT pg_database_size(current_database()) / (1024*1024*1024.0) as size_gb
                """)
                row = cur.fetchone()
                if row:
                    metrics["db_size_total"] = float(row[0] if isinstance(row, tuple) else row["size_gb"])

                # Table sizes
                cur.execute("""
                    SELECT
                        relname as table_name,
                        pg_total_relation_size(relid) / (1024*1024*1024.0) as size_gb
                    FROM pg_catalog.pg_statio_user_tables
                    ORDER BY pg_total_relation_size(relid) DESC
                    LIMIT 10
                """)
                for row in cur.fetchall():
                    table_name = row[0] if isinstance(row, tuple) else row["table_name"]
                    size = row[1] if isinstance(row, tuple) else row["size_gb"]
                    metrics[f"table_size_{table_name}"] = float(size)

                # Tile cache size (if heatmap_tiles table exists)
                cur.execute("""
                    SELECT pg_total_relation_size('heatmap_tiles') / (1024*1024*1024.0) as size_gb
                """)
                row = cur.fetchone()
                if row:
                    metrics["tile_cache_size"] = float(row[0] if isinstance(row, tuple) else row["size_gb"])

        except Exception as e:
            logger.warning(f"Failed to collect DB metrics: {e}")

        return metrics

    def collect_all(self, thresholds: Optional[Dict[str, "CostThreshold"]] = None) -> Dict[str, CostMetric]:
        """
        Collect all metrics.

        Args:
            thresholds: Optional custom thresholds dict to include additional metrics
        """
        now_ms = int(time.time() * 1000)
        today_start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        month_start = int(datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)

        # Merge default thresholds with custom ones
        all_thresholds = {**DEFAULT_THRESHOLDS}
        if thresholds:
            all_thresholds.update(thresholds)

        metrics = {}

        # Counter metrics (daily)
        daily_counters = [
            "api_requests_daily",
            "tile_generations_daily",
            "reactor_events_daily",
            "upstream_requests_daily",
            "tile_egress_daily",
            "api_egress_daily",
        ]

        for name in daily_counters:
            metrics[name] = CostMetric(
                name=name,
                category=all_thresholds.get(name, CostThreshold(
                    name=name, category=CostCategory.COMPUTE, unit="count", period="daily",
                    warning_threshold=0, critical_threshold=0
                )).category,
                current_value=self.get_counter(name),
                unit=all_thresholds.get(name).unit if name in all_thresholds else "count",
                period="daily",
                period_start=today_start,
                period_end=now_ms,
            )

        # Gauge metrics (current)
        gauge_names = [
            "ws_connections_concurrent",
            "tracked_markets",
        ]

        for name in gauge_names:
            metrics[name] = CostMetric(
                name=name,
                category=all_thresholds.get(name, CostThreshold(
                    name=name, category=CostCategory.EXTERNAL, unit="count", period="current",
                    warning_threshold=0, critical_threshold=0
                )).category,
                current_value=self.get_counter(name),
                unit=all_thresholds.get(name).unit if name in all_thresholds else "count",
                period="current",
                period_start=now_ms,
                period_end=now_ms,
            )

        # DB metrics
        db_metrics = self.collect_db_metrics()
        for name, value in db_metrics.items():
            if name in all_thresholds:
                threshold = all_thresholds[name]
                metrics[name] = CostMetric(
                    name=name,
                    category=threshold.category,
                    current_value=value,
                    unit=threshold.unit,
                    period=threshold.period,
                    period_start=now_ms,
                    period_end=now_ms,
                )

        # Custom metrics from thresholds (for testing and custom configs)
        for name, threshold in all_thresholds.items():
            if name not in metrics:
                value = self.get_counter(name)
                if value > 0 or name in (thresholds or {}):
                    metrics[name] = CostMetric(
                        name=name,
                        category=threshold.category,
                        current_value=value,
                        unit=threshold.unit,
                        period=threshold.period,
                        period_start=today_start if threshold.period == "daily" else now_ms,
                        period_end=now_ms,
                    )

        return metrics


# =============================================================================
# Cost Monitor
# =============================================================================

@dataclass
class CostMonitorConfig:
    """Configuration for cost monitoring"""
    check_interval_seconds: int = 300      # Check every 5 minutes
    alert_cooldown_seconds: int = 3600     # Don't repeat same alert within 1 hour
    enable_auto_degradation: bool = True   # Auto-enable degraded mode on soft limit
    thresholds: Dict[str, CostThreshold] = field(default_factory=lambda: DEFAULT_THRESHOLDS.copy())


class CostMonitor:
    """
    Main cost monitoring service.

    Periodically checks cost metrics against thresholds and generates alerts.
    """

    def __init__(
        self,
        config: Optional[CostMonitorConfig] = None,
        collector: Optional[CostMetricsCollector] = None,
        alert_callback: Optional[Callable[[CostAlert], None]] = None,
    ):
        self.config = config or CostMonitorConfig()
        self.collector = collector or CostMetricsCollector()
        self.alert_callback = alert_callback

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_alerts: Dict[str, int] = {}  # metric_name -> last alert timestamp
        self._alerts_generated: List[CostAlert] = []

        # Degradation state
        self._degraded_metrics: set = set()

    def start(self) -> None:
        """Start the cost monitor"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("[CostMonitor] Started")

    def stop(self) -> None:
        """Stop the cost monitor"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("[CostMonitor] Stopped")

    def _run_loop(self) -> None:
        """Main monitoring loop"""
        while self._running:
            try:
                self.check_thresholds()
            except Exception as e:
                logger.error(f"[CostMonitor] Error in check loop: {e}")

            time.sleep(self.config.check_interval_seconds)

    def check_thresholds(self) -> List[CostAlert]:
        """Check all metrics against thresholds"""
        now_ms = int(time.time() * 1000)
        metrics = self.collector.collect_all(thresholds=self.config.thresholds)
        alerts = []

        for metric_name, threshold in self.config.thresholds.items():
            metric = metrics.get(metric_name)
            if not metric:
                continue

            # Check if in cooldown
            last_alert = self._last_alerts.get(metric_name, 0)
            if now_ms - last_alert < self.config.alert_cooldown_seconds * 1000:
                continue

            # Determine severity
            severity = None
            threshold_value = 0

            if metric.current_value >= threshold.critical_threshold:
                severity = CostAlertSeverity.CRITICAL
                threshold_value = threshold.critical_threshold
            elif metric.current_value >= threshold.warning_threshold:
                severity = CostAlertSeverity.WARNING
                threshold_value = threshold.warning_threshold
            elif metric.current_value >= threshold.warning_threshold * 0.5:
                # Info at 50% of warning threshold
                severity = CostAlertSeverity.INFO
                threshold_value = threshold.warning_threshold * 0.5

            if severity:
                alert = self._create_alert(
                    metric=metric,
                    threshold=threshold,
                    severity=severity,
                    threshold_value=threshold_value,
                )
                alerts.append(alert)
                self._alerts_generated.append(alert)
                self._last_alerts[metric_name] = now_ms

                # Send to callback
                if self.alert_callback:
                    try:
                        self.alert_callback(alert)
                    except Exception as e:
                        logger.error(f"[CostMonitor] Alert callback error: {e}")

                # Check for auto-degradation
                if (self.config.enable_auto_degradation and
                    threshold.soft_limit and
                    metric.current_value >= threshold.soft_limit):
                    self._degraded_metrics.add(metric_name)
                    logger.warning(f"[CostMonitor] Degraded mode enabled for {metric_name}")

        return alerts

    def _create_alert(
        self,
        metric: CostMetric,
        threshold: CostThreshold,
        severity: CostAlertSeverity,
        threshold_value: float,
    ) -> CostAlert:
        """Create a cost alert"""
        # Generate recommendation based on metric
        recommendation = self._get_recommendation(metric, threshold, severity)

        # Format message
        pct = (metric.current_value / threshold_value) * 100 if threshold_value > 0 else 0
        message = (
            f"{threshold.description}: {metric.current_value:.2f} {metric.unit} "
            f"({pct:.0f}% of {severity.value.lower()} threshold)"
        )

        return CostAlert(
            alert_id=f"cost_{metric.name}_{int(time.time())}",
            timestamp=int(time.time() * 1000),
            category=metric.category,
            severity=severity,
            metric_name=metric.name,
            current_value=metric.current_value,
            threshold_value=threshold_value,
            unit=metric.unit,
            period=metric.period,
            message=message,
            recommendation=recommendation,
        )

    def _get_recommendation(
        self,
        metric: CostMetric,
        threshold: CostThreshold,
        severity: CostAlertSeverity,
    ) -> str:
        """Generate recommendation based on metric type"""
        recommendations = {
            "tile_egress_daily": "Consider enabling CDN, reducing LOD, or limiting tile requests per client",
            "tile_egress_monthly": "Evaluate CDN migration, implement aggressive caching, review tile retention policy",
            "db_size_total": "Review retention policies, archive old data, consider table partitioning",
            "db_growth_daily": "Check for runaway data, review raw_events retention, optimize storage",
            "api_requests_daily": "Review rate limits, check for abuse, consider request batching",
            "ws_connections_concurrent": "Implement connection pooling, review client reconnection logic",
            "tracked_markets": "Review market eligibility criteria, prioritize high-value markets",
            "tile_cache_size": "Run tile cleanup job, reduce historical tile retention",
        }

        base_rec = recommendations.get(metric.name, "Review usage patterns and consider optimization")

        if severity == CostAlertSeverity.CRITICAL:
            return f"URGENT: {base_rec}. Consider immediate throttling."
        elif severity == CostAlertSeverity.WARNING:
            return f"{base_rec}. Plan optimization within 24-48 hours."
        else:
            return f"Monitor: {base_rec}"

    def get_cost_report(self) -> Dict[str, Any]:
        """Generate a cost report"""
        metrics = self.collector.collect_all()

        report = {
            "generated_at": int(time.time() * 1000),
            "categories": {},
            "alerts": [],
            "degraded_metrics": list(self._degraded_metrics),
        }

        # Group by category
        for category in CostCategory:
            cat_metrics = {
                name: {
                    "current": m.current_value,
                    "unit": m.unit,
                    "warning_threshold": self.config.thresholds.get(name, CostThreshold(
                        name=name, category=category, unit="", period="",
                        warning_threshold=0, critical_threshold=0
                    )).warning_threshold,
                    "critical_threshold": self.config.thresholds.get(name, CostThreshold(
                        name=name, category=category, unit="", period="",
                        warning_threshold=0, critical_threshold=0
                    )).critical_threshold,
                    "pct_of_warning": (m.current_value / self.config.thresholds[name].warning_threshold * 100)
                        if name in self.config.thresholds and self.config.thresholds[name].warning_threshold > 0
                        else 0,
                }
                for name, m in metrics.items()
                if m.category == category
            }
            if cat_metrics:
                report["categories"][category.value] = cat_metrics

        # Recent alerts
        report["alerts"] = [
            {
                "alert_id": a.alert_id,
                "timestamp": a.timestamp,
                "severity": a.severity.value,
                "metric": a.metric_name,
                "value": a.current_value,
                "threshold": a.threshold_value,
                "message": a.message,
            }
            for a in self._alerts_generated[-20:]  # Last 20 alerts
        ]

        return report

    def is_degraded(self, metric_name: str) -> bool:
        """Check if a metric is in degraded mode"""
        return metric_name in self._degraded_metrics

    def clear_degraded(self, metric_name: str) -> None:
        """Clear degraded mode for a metric"""
        self._degraded_metrics.discard(metric_name)


# =============================================================================
# Singleton Instance
# =============================================================================

_cost_monitor: Optional[CostMonitor] = None
_cost_collector: Optional[CostMetricsCollector] = None


def get_cost_collector() -> CostMetricsCollector:
    """Get the global cost metrics collector"""
    global _cost_collector
    if _cost_collector is None:
        _cost_collector = CostMetricsCollector()
    return _cost_collector


def get_cost_monitor() -> CostMonitor:
    """Get the global cost monitor"""
    global _cost_monitor
    if _cost_monitor is None:
        _cost_monitor = CostMonitor(collector=get_cost_collector())
    return _cost_monitor


# =============================================================================
# Convenience Functions
# =============================================================================

def track_api_request(bytes_out: int = 0) -> None:
    """Track an API request (call from middleware)"""
    collector = get_cost_collector()
    collector.increment("api_requests_daily")
    if bytes_out > 0:
        collector.increment("api_egress_daily", bytes_out / (1024 * 1024 * 1024))  # Convert to GB


def track_tile_request(bytes_out: int) -> None:
    """Track a tile request"""
    collector = get_cost_collector()
    collector.increment("tile_generations_daily")
    collector.increment("tile_egress_daily", bytes_out / (1024 * 1024 * 1024))


def track_reactor_event() -> None:
    """Track a reactor event processed"""
    get_cost_collector().increment("reactor_events_daily")


def track_upstream_request() -> None:
    """Track an upstream API call"""
    get_cost_collector().increment("upstream_requests_daily")


def set_ws_connections(count: int) -> None:
    """Set current WebSocket connection count"""
    get_cost_collector().set_gauge("ws_connections_concurrent", count)


def set_tracked_markets(count: int) -> None:
    """Set current tracked market count"""
    get_cost_collector().set_gauge("tracked_markets", count)
