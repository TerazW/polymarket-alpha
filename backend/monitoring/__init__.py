"""
Belief Reaction System - Monitoring Module

Production-grade observability:
- Prometheus metrics
- Deep health checks
- System metrics collection
- Automatic health remediation (v5.16)
- Success metrics and CI gates (v5.17)

"可观测性是生产系统的生命线"
"""

from .metrics import (
    MetricsRegistry,
    get_metrics_registry,
    Counter,
    Gauge,
    Histogram,
    metrics_middleware,
)
from .health import (
    HealthChecker,
    HealthStatus,
    CheckResult,
    HealthReport,
    deep_health_check,
)
from .remediation import (
    HealthRemediator,
    RemediationType,
    RemediationAction,
    RemediationResult,
    DegradationLevel,
    DegradationState,
    REMEDIATION_ACTIONS,
    CHECK_TO_REMEDIATION,
    get_remediator,
    process_health_and_remediate,
)
from .success_metrics import (
    SuccessMetricsTracker,
    SuccessReport,
    MetricResult,
    MetricTarget,
    MetricStatus,
    METRIC_TARGETS,
    calculate_percentile,
    ci_gate_check,
    run_ci_gate,
    get_success_tracker,
)
from .cost_alerts import (
    CostMonitor,
    CostMonitorConfig,
    CostMetricsCollector,
    CostThreshold,
    CostCategory,
    CostAlertSeverity,
    CostMetric,
    CostAlert,
    DEFAULT_THRESHOLDS,
    get_cost_monitor,
    get_cost_collector,
    track_api_request,
    track_tile_request,
    track_reactor_event,
    track_upstream_request,
    set_ws_connections,
    set_tracked_markets,
)

__all__ = [
    # Metrics
    'MetricsRegistry',
    'get_metrics_registry',
    'Counter',
    'Gauge',
    'Histogram',
    'metrics_middleware',
    # Health checks
    'HealthChecker',
    'HealthStatus',
    'CheckResult',
    'HealthReport',
    'deep_health_check',
    # Remediation (v5.16)
    'HealthRemediator',
    'RemediationType',
    'RemediationAction',
    'RemediationResult',
    'DegradationLevel',
    'DegradationState',
    'REMEDIATION_ACTIONS',
    'CHECK_TO_REMEDIATION',
    'get_remediator',
    'process_health_and_remediate',
    # Success Metrics (v5.17)
    'SuccessMetricsTracker',
    'SuccessReport',
    'MetricResult',
    'MetricTarget',
    'MetricStatus',
    'METRIC_TARGETS',
    'calculate_percentile',
    'ci_gate_check',
    'run_ci_gate',
    'get_success_tracker',
    # Cost Alerts (v5.36)
    'CostMonitor',
    'CostMonitorConfig',
    'CostMetricsCollector',
    'CostThreshold',
    'CostCategory',
    'CostAlertSeverity',
    'CostMetric',
    'CostAlert',
    'DEFAULT_THRESHOLDS',
    'get_cost_monitor',
    'get_cost_collector',
    'track_api_request',
    'track_tile_request',
    'track_reactor_event',
    'track_upstream_request',
    'set_ws_connections',
    'set_tracked_markets',
]
