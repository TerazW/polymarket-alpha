"""
Deep Health Check Module

Provides comprehensive health checks for:
- Database connectivity and performance
- WebSocket stream manager
- Data pipeline freshness
- External dependencies

"A healthy system knows its own status"
"""

import time
import asyncio
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta


class HealthStatus(Enum):
    """Health check status"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class CheckResult:
    """Result of a single health check"""
    name: str
    status: HealthStatus
    message: str = ""
    latency_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "latency_ms": round(self.latency_ms, 2),
            "details": self.details,
            "checked_at": self.checked_at.isoformat() + "Z",
        }


@dataclass
class HealthReport:
    """Complete health report"""
    status: HealthStatus
    checks: List[CheckResult]
    version: str
    uptime_seconds: float
    checked_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "version": self.version,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "checked_at": self.checked_at.isoformat() + "Z",
            "checks": [c.to_dict() for c in self.checks],
            "summary": {
                "total": len(self.checks),
                "healthy": sum(1 for c in self.checks if c.status == HealthStatus.HEALTHY),
                "degraded": sum(1 for c in self.checks if c.status == HealthStatus.DEGRADED),
                "unhealthy": sum(1 for c in self.checks if c.status == HealthStatus.UNHEALTHY),
            }
        }


class HealthChecker:
    """
    Comprehensive health checker for production monitoring.

    Features:
    - Multiple check types (database, websocket, pipeline, etc.)
    - Configurable timeouts
    - Aggregate health status
    - Detailed diagnostics

    Usage:
        checker = HealthChecker(db_config=DB_CONFIG, version="1.0.0")
        report = await checker.run_all_checks()
    """

    def __init__(
        self,
        db_config: Dict[str, Any] = None,
        version: str = "1.0.0",
        start_time: float = None,
    ):
        self.db_config = db_config or {}
        self.version = version
        self.start_time = start_time or time.time()
        self._checks: List[Callable] = []

        # Register default checks
        self._register_default_checks()

    def _register_default_checks(self):
        """Register all default health checks"""
        self._checks.append(self._check_database)
        self._checks.append(self._check_database_performance)
        self._checks.append(self._check_websocket_manager)
        self._checks.append(self._check_data_freshness)
        self._checks.append(self._check_alert_queue)
        self._checks.append(self._check_tile_generation)

    async def run_all_checks(self, timeout: float = 10.0) -> HealthReport:
        """Run all registered health checks"""
        checks = []
        overall_status = HealthStatus.HEALTHY

        for check_fn in self._checks:
            try:
                result = await asyncio.wait_for(
                    check_fn(),
                    timeout=timeout
                )
                checks.append(result)

                # Update overall status
                if result.status == HealthStatus.UNHEALTHY:
                    overall_status = HealthStatus.UNHEALTHY
                elif result.status == HealthStatus.DEGRADED and overall_status != HealthStatus.UNHEALTHY:
                    overall_status = HealthStatus.DEGRADED

            except asyncio.TimeoutError:
                checks.append(CheckResult(
                    name=check_fn.__name__.replace('_check_', ''),
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check timed out after {timeout}s",
                ))
                overall_status = HealthStatus.UNHEALTHY
            except Exception as e:
                checks.append(CheckResult(
                    name=check_fn.__name__.replace('_check_', ''),
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check failed: {str(e)}",
                ))
                overall_status = HealthStatus.UNHEALTHY

        uptime = time.time() - self.start_time

        return HealthReport(
            status=overall_status,
            checks=checks,
            version=self.version,
            uptime_seconds=uptime,
        )

    async def _check_database(self) -> CheckResult:
        """Check database connectivity"""
        start = time.time()
        try:
            import psycopg2

            conn = psycopg2.connect(**self.db_config)
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            conn.close()

            latency = (time.time() - start) * 1000

            return CheckResult(
                name="database",
                status=HealthStatus.HEALTHY,
                message="Database connection successful",
                latency_ms=latency,
                details={"host": self.db_config.get('host'), "database": self.db_config.get('database')},
            )

        except Exception as e:
            return CheckResult(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message=f"Database connection failed: {str(e)}",
                latency_ms=(time.time() - start) * 1000,
            )

    async def _check_database_performance(self) -> CheckResult:
        """Check database query performance"""
        start = time.time()
        try:
            import psycopg2

            conn = psycopg2.connect(**self.db_config)

            # Run a representative query
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FROM trade_ticks
                    WHERE ts > NOW() - INTERVAL '1 hour'
                """)
                recent_trades = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(*) FROM shock_events
                    WHERE ts > NOW() - INTERVAL '1 hour'
                """)
                recent_shocks = cur.fetchone()[0]

            conn.close()
            latency = (time.time() - start) * 1000

            # Check if latency is acceptable
            status = HealthStatus.HEALTHY
            message = "Database performance normal"

            if latency > 1000:
                status = HealthStatus.DEGRADED
                message = "Database queries slower than expected"
            elif latency > 5000:
                status = HealthStatus.UNHEALTHY
                message = "Database queries critically slow"

            return CheckResult(
                name="database_performance",
                status=status,
                message=message,
                latency_ms=latency,
                details={
                    "recent_trades_1h": recent_trades,
                    "recent_shocks_1h": recent_shocks,
                },
            )

        except Exception as e:
            return CheckResult(
                name="database_performance",
                status=HealthStatus.UNHEALTHY,
                message=f"Performance check failed: {str(e)}",
                latency_ms=(time.time() - start) * 1000,
            )

    async def _check_websocket_manager(self) -> CheckResult:
        """Check WebSocket stream manager status"""
        start = time.time()
        try:
            from backend.api.stream import stream_manager

            connection_count = stream_manager.connection_count
            is_running = stream_manager._running

            latency = (time.time() - start) * 1000

            if not is_running:
                return CheckResult(
                    name="websocket_manager",
                    status=HealthStatus.UNHEALTHY,
                    message="WebSocket manager not running",
                    latency_ms=latency,
                )

            return CheckResult(
                name="websocket_manager",
                status=HealthStatus.HEALTHY,
                message=f"WebSocket manager running with {connection_count} connections",
                latency_ms=latency,
                details={
                    "active_connections": connection_count,
                    "is_running": is_running,
                },
            )

        except ImportError:
            return CheckResult(
                name="websocket_manager",
                status=HealthStatus.UNKNOWN,
                message="WebSocket manager not available",
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="websocket_manager",
                status=HealthStatus.DEGRADED,
                message=f"Could not check WebSocket manager: {str(e)}",
                latency_ms=(time.time() - start) * 1000,
            )

    async def _check_data_freshness(self) -> CheckResult:
        """Check if data pipeline is producing fresh data"""
        start = time.time()
        try:
            import psycopg2

            conn = psycopg2.connect(**self.db_config)

            with conn.cursor() as cur:
                # Check latest trade timestamp
                cur.execute("SELECT MAX(ts) FROM trade_ticks")
                latest_trade = cur.fetchone()[0]

                # Check latest book snapshot
                cur.execute("SELECT MAX(ts) FROM book_bins")
                latest_book = cur.fetchone()[0]

            conn.close()
            latency = (time.time() - start) * 1000

            now = datetime.utcnow()
            details = {}

            # Determine freshness status
            status = HealthStatus.HEALTHY
            message = "Data pipeline is fresh"

            if latest_trade:
                trade_age = (now - latest_trade).total_seconds()
                details["latest_trade_age_seconds"] = round(trade_age, 1)

                if trade_age > 300:  # 5 minutes
                    status = HealthStatus.DEGRADED
                    message = "Trade data is stale"
                if trade_age > 600:  # 10 minutes
                    status = HealthStatus.UNHEALTHY
                    message = "Trade data is critically stale"
            else:
                status = HealthStatus.DEGRADED
                message = "No trade data found"

            if latest_book:
                book_age = (now - latest_book).total_seconds()
                details["latest_book_age_seconds"] = round(book_age, 1)

            return CheckResult(
                name="data_freshness",
                status=status,
                message=message,
                latency_ms=latency,
                details=details,
            )

        except Exception as e:
            return CheckResult(
                name="data_freshness",
                status=HealthStatus.UNHEALTHY,
                message=f"Data freshness check failed: {str(e)}",
                latency_ms=(time.time() - start) * 1000,
            )

    async def _check_alert_queue(self) -> CheckResult:
        """Check alert processing status"""
        start = time.time()
        try:
            import psycopg2

            conn = psycopg2.connect(**self.db_config)

            with conn.cursor() as cur:
                # Count open alerts
                cur.execute("SELECT COUNT(*) FROM alerts WHERE status = 'OPEN'")
                open_alerts = cur.fetchone()[0]

                # Count alerts in last hour
                cur.execute("""
                    SELECT COUNT(*) FROM alerts
                    WHERE ts > NOW() - INTERVAL '1 hour'
                """)
                recent_alerts = cur.fetchone()[0]

            conn.close()
            latency = (time.time() - start) * 1000

            status = HealthStatus.HEALTHY
            message = f"{open_alerts} open alerts"

            # Too many open alerts might indicate a problem
            if open_alerts > 100:
                status = HealthStatus.DEGRADED
                message = f"High number of open alerts: {open_alerts}"
            if open_alerts > 500:
                status = HealthStatus.UNHEALTHY
                message = f"Critical: {open_alerts} unacknowledged alerts"

            return CheckResult(
                name="alert_queue",
                status=status,
                message=message,
                latency_ms=latency,
                details={
                    "open_alerts": open_alerts,
                    "alerts_last_hour": recent_alerts,
                },
            )

        except Exception as e:
            return CheckResult(
                name="alert_queue",
                status=HealthStatus.DEGRADED,
                message=f"Alert queue check failed: {str(e)}",
                latency_ms=(time.time() - start) * 1000,
            )

    async def _check_tile_generation(self) -> CheckResult:
        """Check heatmap tile generation status"""
        start = time.time()
        try:
            import psycopg2

            conn = psycopg2.connect(**self.db_config)

            with conn.cursor() as cur:
                # Check latest tile
                cur.execute("SELECT MAX(t_end), COUNT(*) FROM heatmap_tiles")
                row = cur.fetchone()
                latest_tile_end = row[0]
                tile_count = row[1]

            conn.close()
            latency = (time.time() - start) * 1000

            status = HealthStatus.HEALTHY
            message = f"{tile_count} tiles in cache"
            details = {"total_tiles": tile_count}

            if latest_tile_end:
                now_ms = int(time.time() * 1000)
                tile_age_ms = now_ms - latest_tile_end
                details["latest_tile_age_seconds"] = round(tile_age_ms / 1000, 1)

                if tile_age_ms > 60000:  # 1 minute
                    status = HealthStatus.DEGRADED
                    message = "Tile generation may be delayed"

            return CheckResult(
                name="tile_generation",
                status=status,
                message=message,
                latency_ms=latency,
                details=details,
            )

        except Exception as e:
            return CheckResult(
                name="tile_generation",
                status=HealthStatus.DEGRADED,
                message=f"Tile check failed: {str(e)}",
                latency_ms=(time.time() - start) * 1000,
            )


# Factory function for deep health check
async def deep_health_check(db_config: Dict[str, Any], version: str = "1.0.0") -> HealthReport:
    """
    Run comprehensive health checks.

    Usage:
        report = await deep_health_check(DB_CONFIG)
        print(report.to_dict())
    """
    checker = HealthChecker(db_config=db_config, version=version)
    return await checker.run_all_checks()
