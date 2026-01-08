"""
Prometheus-compatible Metrics Module

Provides:
- Counter, Gauge, Histogram metric types
- Thread-safe metric registry
- Prometheus text format export
- FastAPI middleware for request metrics

"Every system needs numbers to tell its story"
"""

import time
import threading
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum


class MetricType(Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class MetricValue:
    """Single metric value with labels"""
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class Counter:
    """
    Monotonically increasing counter.

    Usage:
        counter = Counter("http_requests_total", "Total HTTP requests")
        counter.inc()
        counter.inc(labels={"method": "GET", "status": "200"})
    """

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.type = MetricType.COUNTER
        self._values: Dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """Increment counter by value"""
        label_key = self._labels_to_key(labels)
        with self._lock:
            self._values[label_key] += value

    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current counter value"""
        label_key = self._labels_to_key(labels)
        with self._lock:
            return self._values.get(label_key, 0.0)

    def _labels_to_key(self, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return ""
        return ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))

    def collect(self) -> List[tuple]:
        """Collect all values for export"""
        with self._lock:
            return [(k, v) for k, v in self._values.items()]


class Gauge:
    """
    Value that can go up and down.

    Usage:
        gauge = Gauge("active_connections", "Number of active connections")
        gauge.set(10)
        gauge.inc()
        gauge.dec()
    """

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.type = MetricType.GAUGE
        self._values: Dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()

    def set(self, value: float, labels: Optional[Dict[str, str]] = None):
        """Set gauge to specific value"""
        label_key = self._labels_to_key(labels)
        with self._lock:
            self._values[label_key] = value

    def inc(self, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """Increment gauge"""
        label_key = self._labels_to_key(labels)
        with self._lock:
            self._values[label_key] += value

    def dec(self, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """Decrement gauge"""
        label_key = self._labels_to_key(labels)
        with self._lock:
            self._values[label_key] -= value

    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current gauge value"""
        label_key = self._labels_to_key(labels)
        with self._lock:
            return self._values.get(label_key, 0.0)

    def _labels_to_key(self, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return ""
        return ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))

    def collect(self) -> List[tuple]:
        """Collect all values for export"""
        with self._lock:
            return [(k, v) for k, v in self._values.items()]


class Histogram:
    """
    Histogram for tracking distributions (latencies, sizes).

    Usage:
        histogram = Histogram("request_duration_seconds", buckets=[0.01, 0.05, 0.1, 0.5, 1.0])
        histogram.observe(0.042)
    """

    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0, float('inf'))

    def __init__(self, name: str, description: str = "", buckets: tuple = None):
        self.name = name
        self.description = description
        self.type = MetricType.HISTOGRAM
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._buckets: Dict[str, Dict[float, int]] = {}
        self._sums: Dict[str, float] = defaultdict(float)
        self._counts: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def observe(self, value: float, labels: Optional[Dict[str, str]] = None):
        """Record an observation"""
        label_key = self._labels_to_key(labels)
        with self._lock:
            # Initialize buckets for this label combo if needed
            if label_key not in self._buckets:
                self._buckets[label_key] = {b: 0 for b in self.buckets}

            # Update buckets (cumulative)
            for bucket in self.buckets:
                if value <= bucket:
                    self._buckets[label_key][bucket] += 1

            # Update sum and count
            self._sums[label_key] += value
            self._counts[label_key] += 1

    def _labels_to_key(self, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return ""
        return ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))

    def collect(self) -> Dict[str, dict]:
        """Collect all histogram data"""
        with self._lock:
            result = {}
            for label_key in self._buckets:
                result[label_key] = {
                    'buckets': dict(self._buckets[label_key]),
                    'sum': self._sums[label_key],
                    'count': self._counts[label_key],
                }
            return result


class MetricsRegistry:
    """
    Central registry for all metrics.

    Provides:
    - Metric registration
    - Prometheus format export
    - Thread-safe access
    """

    def __init__(self):
        self._metrics: Dict[str, object] = {}
        self._lock = threading.Lock()
        self._start_time = time.time()

        # Register default process metrics
        self._register_default_metrics()

    def _register_default_metrics(self):
        """Register standard process metrics"""
        self.register(Gauge("process_start_time_seconds", "Start time of the process"))
        self.get_metric("process_start_time_seconds").set(self._start_time)

    def register(self, metric) -> None:
        """Register a metric"""
        with self._lock:
            if metric.name in self._metrics:
                raise ValueError(f"Metric {metric.name} already registered")
            self._metrics[metric.name] = metric

    def get_metric(self, name: str):
        """Get a registered metric by name"""
        with self._lock:
            return self._metrics.get(name)

    def counter(self, name: str, description: str = "") -> Counter:
        """Get or create a counter"""
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = Counter(name, description)
            return self._metrics[name]

    def gauge(self, name: str, description: str = "") -> Gauge:
        """Get or create a gauge"""
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = Gauge(name, description)
            return self._metrics[name]

    def histogram(self, name: str, description: str = "", buckets: tuple = None) -> Histogram:
        """Get or create a histogram"""
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = Histogram(name, description, buckets)
            return self._metrics[name]

    def export_prometheus(self) -> str:
        """Export all metrics in Prometheus text format"""
        lines = []

        with self._lock:
            for name, metric in sorted(self._metrics.items()):
                # Add HELP and TYPE comments
                if metric.description:
                    lines.append(f"# HELP {name} {metric.description}")
                lines.append(f"# TYPE {name} {metric.type.value}")

                if isinstance(metric, Counter) or isinstance(metric, Gauge):
                    for label_key, value in metric.collect():
                        if label_key:
                            lines.append(f"{name}{{{label_key}}} {value}")
                        else:
                            lines.append(f"{name} {value}")

                elif isinstance(metric, Histogram):
                    for label_key, data in metric.collect().items():
                        base_labels = f"{{{label_key}," if label_key else "{"

                        # Bucket values
                        for bucket, count in sorted(data['buckets'].items()):
                            le_value = "+Inf" if bucket == float('inf') else str(bucket)
                            if label_key:
                                lines.append(f'{name}_bucket{{{label_key},le="{le_value}"}} {count}')
                            else:
                                lines.append(f'{name}_bucket{{le="{le_value}"}} {count}')

                        # Sum and count
                        if label_key:
                            lines.append(f"{name}_sum{{{label_key}}} {data['sum']}")
                            lines.append(f"{name}_count{{{label_key}}} {data['count']}")
                        else:
                            lines.append(f"{name}_sum {data['sum']}")
                            lines.append(f"{name}_count {data['count']}")

                lines.append("")  # Empty line between metrics

        return "\n".join(lines)


# Global registry singleton
_registry: Optional[MetricsRegistry] = None


def get_metrics_registry() -> MetricsRegistry:
    """Get the global metrics registry"""
    global _registry
    if _registry is None:
        _registry = MetricsRegistry()
    return _registry


# Pre-defined application metrics
def create_app_metrics(registry: MetricsRegistry):
    """Create standard application metrics"""

    # HTTP metrics
    registry.counter("http_requests_total", "Total HTTP requests received")
    registry.histogram("http_request_duration_seconds", "HTTP request latency",
                      buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float('inf')))
    registry.counter("http_request_errors_total", "Total HTTP request errors")

    # WebSocket metrics
    registry.gauge("websocket_connections_active", "Active WebSocket connections")
    registry.counter("websocket_messages_sent_total", "Total WebSocket messages sent")
    registry.counter("websocket_messages_received_total", "Total WebSocket messages received")

    # Event processing metrics
    registry.counter("events_processed_total", "Total events processed")
    registry.histogram("event_processing_duration_seconds", "Event processing latency")

    # Alert metrics
    registry.counter("alerts_created_total", "Total alerts created")
    registry.counter("alerts_acknowledged_total", "Total alerts acknowledged")
    registry.counter("alerts_resolved_total", "Total alerts resolved")
    registry.gauge("alerts_open_count", "Current open alerts")

    # Data pipeline metrics
    registry.counter("shocks_detected_total", "Total shock events detected")
    registry.counter("reactions_classified_total", "Total reactions classified")
    registry.counter("leading_events_detected_total", "Total leading events detected")
    registry.counter("belief_state_changes_total", "Total belief state changes")

    # Database metrics
    registry.histogram("db_query_duration_seconds", "Database query latency")
    registry.counter("db_query_errors_total", "Database query errors")
    registry.gauge("db_connection_pool_size", "Database connection pool size")

    # Bundle verification metrics
    registry.counter("bundle_verifications_total", "Total bundle verifications")
    registry.counter("bundle_verification_failures_total", "Bundle verification failures")

    # Tile generation metrics
    registry.counter("tiles_generated_total", "Total tiles generated")
    registry.histogram("tile_generation_duration_seconds", "Tile generation latency")


def metrics_middleware(app):
    """
    FastAPI middleware for automatic request metrics.

    Usage:
        from backend.monitoring import metrics_middleware
        metrics_middleware(app)
    """
    from fastapi import Request
    from starlette.middleware.base import BaseHTTPMiddleware
    import asyncio

    registry = get_metrics_registry()
    create_app_metrics(registry)

    class MetricsMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            start_time = time.time()

            # Get labels
            method = request.method
            path = request.url.path

            # Normalize path (remove IDs for grouping)
            import re
            normalized_path = re.sub(r'/[0-9a-f-]{32,}', '/{id}', path)
            normalized_path = re.sub(r'/\d+', '/{id}', normalized_path)

            try:
                response = await call_next(request)
                status = str(response.status_code)
            except Exception as e:
                status = "500"
                registry.counter("http_request_errors_total").inc(
                    labels={"method": method, "path": normalized_path, "error": type(e).__name__}
                )
                raise

            # Record metrics
            duration = time.time() - start_time
            labels = {"method": method, "path": normalized_path, "status": status}

            registry.counter("http_requests_total").inc(labels=labels)
            registry.histogram("http_request_duration_seconds").observe(duration, labels=labels)

            return response

    app.add_middleware(MetricsMiddleware)
    return app
