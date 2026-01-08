"""
Cost Throttling Module (v5.22)

Full-pipeline throttling and downsampling for cost control.

Components:
1. TokenBucket - Classic rate limiting
2. SlidingWindowLimiter - Sliding window rate limiting
3. ConcurrencyLimiter - Limit concurrent operations
4. AdaptiveDownsampler - Dynamic downsampling based on load
5. BackpressureQueue - Queue with backpressure signaling
6. ThrottleMiddleware - FastAPI middleware for API throttling

"控成本，稳质量"
"""

import asyncio
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Awaitable, Tuple
from enum import Enum
from collections import deque
import hashlib


class ThrottleResult(str, Enum):
    """Result of a throttle check"""
    ALLOWED = "ALLOWED"
    RATE_LIMITED = "RATE_LIMITED"
    QUEUE_FULL = "QUEUE_FULL"
    TIMEOUT = "TIMEOUT"


@dataclass
class ThrottleStats:
    """Statistics for throttle monitoring"""
    total_requests: int = 0
    allowed_requests: int = 0
    rate_limited: int = 0
    queue_drops: int = 0
    avg_wait_ms: float = 0.0
    current_rate: float = 0.0
    bucket_level: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_requests": self.total_requests,
            "allowed_requests": self.allowed_requests,
            "rate_limited": self.rate_limited,
            "queue_drops": self.queue_drops,
            "avg_wait_ms": round(self.avg_wait_ms, 2),
            "current_rate": round(self.current_rate, 2),
            "bucket_level": round(self.bucket_level, 2),
        }


# =============================================================================
# Token Bucket Rate Limiter
# =============================================================================

class TokenBucket:
    """
    Classic token bucket rate limiter.

    Args:
        rate: Tokens per second refill rate
        capacity: Maximum bucket capacity
        initial: Initial token count (defaults to capacity)

    Usage:
        bucket = TokenBucket(rate=10, capacity=20)  # 10 req/s, burst of 20

        if bucket.acquire():
            # Process request
        else:
            # Rate limited
    """

    def __init__(
        self,
        rate: float,
        capacity: float,
        initial: Optional[float] = None,
    ):
        self.rate = rate
        self.capacity = capacity
        self.tokens = initial if initial is not None else capacity
        self.last_update = time.monotonic()
        self._lock = threading.Lock()

        # Stats
        self._total_requests = 0
        self._allowed_requests = 0
        self._rate_limited = 0

    def _refill(self) -> None:
        """Refill tokens based on elapsed time"""
        now = time.monotonic()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now

    def acquire(self, tokens: float = 1.0, blocking: bool = False, timeout: float = 0.0) -> bool:
        """
        Attempt to acquire tokens from the bucket.

        Args:
            tokens: Number of tokens to acquire
            blocking: If True, wait for tokens to become available
            timeout: Max wait time in seconds (0 = unlimited if blocking)

        Returns:
            True if tokens acquired, False if rate limited
        """
        start_time = time.monotonic()

        with self._lock:
            self._total_requests += 1

            while True:
                self._refill()

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    self._allowed_requests += 1
                    return True

                if not blocking:
                    self._rate_limited += 1
                    return False

                # Calculate wait time
                wait_time = (tokens - self.tokens) / self.rate

                if timeout > 0:
                    elapsed = time.monotonic() - start_time
                    remaining = timeout - elapsed
                    if remaining <= 0:
                        self._rate_limited += 1
                        return False
                    wait_time = min(wait_time, remaining)

                # Release lock while waiting
                self._lock.release()
                time.sleep(wait_time)
                self._lock.acquire()

    def get_stats(self) -> ThrottleStats:
        """Get current statistics"""
        with self._lock:
            self._refill()
            return ThrottleStats(
                total_requests=self._total_requests,
                allowed_requests=self._allowed_requests,
                rate_limited=self._rate_limited,
                bucket_level=self.tokens,
                current_rate=self.rate,
            )


# =============================================================================
# Async Token Bucket
# =============================================================================

class AsyncTokenBucket:
    """Async version of token bucket for use with asyncio"""

    def __init__(
        self,
        rate: float,
        capacity: float,
        initial: Optional[float] = None,
    ):
        self.rate = rate
        self.capacity = capacity
        self.tokens = initial if initial is not None else capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

        # Stats
        self._total_requests = 0
        self._allowed_requests = 0
        self._rate_limited = 0

    def _refill(self) -> None:
        """Refill tokens based on elapsed time"""
        now = time.monotonic()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now

    async def acquire(
        self,
        tokens: float = 1.0,
        blocking: bool = False,
        timeout: float = 0.0,
    ) -> bool:
        """Async token acquisition"""
        start_time = time.monotonic()

        async with self._lock:
            self._total_requests += 1

            while True:
                self._refill()

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    self._allowed_requests += 1
                    return True

                if not blocking:
                    self._rate_limited += 1
                    return False

                # Calculate wait time
                wait_time = (tokens - self.tokens) / self.rate

                if timeout > 0:
                    elapsed = time.monotonic() - start_time
                    remaining = timeout - elapsed
                    if remaining <= 0:
                        self._rate_limited += 1
                        return False
                    wait_time = min(wait_time, remaining)

                # Release lock while waiting
                self._lock.release()
                await asyncio.sleep(wait_time)
                await self._lock.acquire()

    def get_stats(self) -> ThrottleStats:
        """Get current statistics"""
        return ThrottleStats(
            total_requests=self._total_requests,
            allowed_requests=self._allowed_requests,
            rate_limited=self._rate_limited,
            bucket_level=self.tokens,
            current_rate=self.rate,
        )


# =============================================================================
# Sliding Window Rate Limiter
# =============================================================================

class SlidingWindowLimiter:
    """
    Sliding window rate limiter with sub-second precision.

    More accurate than token bucket for bursty traffic.

    Args:
        max_requests: Maximum requests allowed in window
        window_seconds: Time window in seconds
    """

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: deque = deque()
        self._lock = threading.Lock()
        self._total_requests = 0
        self._rate_limited = 0

    def _cleanup(self, now: float) -> None:
        """Remove expired requests from window"""
        cutoff = now - self.window_seconds
        while self.requests and self.requests[0] < cutoff:
            self.requests.popleft()

    def acquire(self) -> bool:
        """Check if request is allowed"""
        now = time.monotonic()

        with self._lock:
            self._total_requests += 1
            self._cleanup(now)

            if len(self.requests) < self.max_requests:
                self.requests.append(now)
                return True

            self._rate_limited += 1
            return False

    def get_current_count(self) -> int:
        """Get current request count in window"""
        now = time.monotonic()
        with self._lock:
            self._cleanup(now)
            return len(self.requests)

    def get_stats(self) -> ThrottleStats:
        """Get statistics"""
        return ThrottleStats(
            total_requests=self._total_requests,
            allowed_requests=self._total_requests - self._rate_limited,
            rate_limited=self._rate_limited,
            current_rate=self.get_current_count() / self.window_seconds,
        )


# =============================================================================
# Concurrency Limiter (Semaphore-based)
# =============================================================================

class ConcurrencyLimiter:
    """
    Limit concurrent operations (e.g., tile generation, DB queries).

    Args:
        max_concurrent: Maximum concurrent operations
        queue_size: Maximum queue size (0 = unlimited)
        timeout: Default timeout for acquiring slot
    """

    def __init__(
        self,
        max_concurrent: int,
        queue_size: int = 0,
        timeout: float = 30.0,
    ):
        self.max_concurrent = max_concurrent
        self.queue_size = queue_size
        self.timeout = timeout
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._waiting = 0
        self._lock = asyncio.Lock()

        # Stats
        self._total_requests = 0
        self._completed = 0
        self._timeouts = 0
        self._queue_drops = 0

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.release()

    async def acquire(self, timeout: Optional[float] = None) -> bool:
        """Acquire a concurrency slot"""
        timeout = timeout if timeout is not None else self.timeout

        async with self._lock:
            self._total_requests += 1

            # Check queue limit
            if self.queue_size > 0 and self._waiting >= self.queue_size:
                self._queue_drops += 1
                return False

            self._waiting += 1

        try:
            acquired = await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=timeout,
            )
            async with self._lock:
                self._waiting -= 1
            return acquired
        except asyncio.TimeoutError:
            async with self._lock:
                self._waiting -= 1
                self._timeouts += 1
            return False

    def release(self) -> None:
        """Release a concurrency slot"""
        self._semaphore.release()
        self._completed += 1

    def get_stats(self) -> ThrottleStats:
        """Get statistics"""
        return ThrottleStats(
            total_requests=self._total_requests,
            allowed_requests=self._completed,
            rate_limited=self._timeouts,
            queue_drops=self._queue_drops,
        )


# =============================================================================
# Adaptive Downsampler
# =============================================================================

@dataclass
class DownsampleConfig:
    """Configuration for adaptive downsampling"""
    base_interval_ms: int = 250         # Base sampling interval
    min_interval_ms: int = 100          # Minimum interval (high priority)
    max_interval_ms: int = 5000         # Maximum interval (under load)
    load_threshold_low: float = 0.5     # Below this, use min interval
    load_threshold_high: float = 0.8    # Above this, use max interval


class AdaptiveDownsampler:
    """
    Dynamic downsampling based on system load.

    Adjusts sampling rate based on:
    - Queue depth
    - Processing latency
    - Error rate

    Usage:
        sampler = AdaptiveDownsampler()

        for event in events:
            if sampler.should_sample(event['token_id'], event['ts']):
                process(event)
    """

    def __init__(self, config: Optional[DownsampleConfig] = None):
        self.config = config or DownsampleConfig()
        self._last_sample: Dict[str, int] = {}  # token_id -> last_ts
        self._current_interval = self.config.base_interval_ms
        self._load_factor = 0.0
        self._lock = threading.Lock()

        # Stats
        self._total_events = 0
        self._sampled_events = 0
        self._dropped_events = 0

    def should_sample(self, key: str, timestamp_ms: int) -> bool:
        """
        Check if this event should be sampled.

        Args:
            key: Grouping key (e.g., token_id)
            timestamp_ms: Event timestamp in milliseconds

        Returns:
            True if event should be processed
        """
        with self._lock:
            self._total_events += 1

            last_ts = self._last_sample.get(key, 0)
            interval = timestamp_ms - last_ts

            if interval >= self._current_interval:
                self._last_sample[key] = timestamp_ms
                self._sampled_events += 1
                return True

            self._dropped_events += 1
            return False

    def update_load(self, load_factor: float) -> None:
        """
        Update load factor and adjust sampling interval.

        Args:
            load_factor: 0.0 (idle) to 1.0+ (overloaded)
        """
        with self._lock:
            self._load_factor = max(0.0, min(1.5, load_factor))

            if self._load_factor <= self.config.load_threshold_low:
                self._current_interval = self.config.min_interval_ms
            elif self._load_factor >= self.config.load_threshold_high:
                self._current_interval = self.config.max_interval_ms
            else:
                # Linear interpolation
                ratio = (self._load_factor - self.config.load_threshold_low) / \
                        (self.config.load_threshold_high - self.config.load_threshold_low)
                self._current_interval = int(
                    self.config.base_interval_ms +
                    ratio * (self.config.max_interval_ms - self.config.base_interval_ms)
                )

    def get_current_interval(self) -> int:
        """Get current sampling interval in ms"""
        with self._lock:
            return self._current_interval

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics"""
        with self._lock:
            return {
                "total_events": self._total_events,
                "sampled_events": self._sampled_events,
                "dropped_events": self._dropped_events,
                "sample_rate": self._sampled_events / max(1, self._total_events),
                "current_interval_ms": self._current_interval,
                "load_factor": self._load_factor,
                "active_keys": len(self._last_sample),
            }


# =============================================================================
# Backpressure Queue
# =============================================================================

class BackpressureQueue:
    """
    Async queue with backpressure signaling and overflow handling.

    Features:
    - Configurable high/low water marks
    - Backpressure callback when high water mark reached
    - Overflow strategies: drop_oldest, drop_newest, block

    Args:
        maxsize: Maximum queue size
        high_water: Trigger backpressure at this level (default: 80%)
        low_water: Release backpressure at this level (default: 50%)
        overflow_strategy: What to do when full
    """

    def __init__(
        self,
        maxsize: int = 1000,
        high_water: float = 0.8,
        low_water: float = 0.5,
        overflow_strategy: str = "drop_oldest",
    ):
        self.maxsize = maxsize
        self.high_water_mark = int(maxsize * high_water)
        self.low_water_mark = int(maxsize * low_water)
        self.overflow_strategy = overflow_strategy

        self._queue: deque = deque(maxlen=maxsize if overflow_strategy == "drop_oldest" else None)
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Condition()
        self._backpressure = False
        self._backpressure_callback: Optional[Callable[[bool], Awaitable[None]]] = None

        # Stats
        self._enqueued = 0
        self._dequeued = 0
        self._dropped = 0

    def set_backpressure_callback(self, callback: Callable[[bool], Awaitable[None]]) -> None:
        """Set callback for backpressure state changes"""
        self._backpressure_callback = callback

    async def put(self, item: Any, timeout: Optional[float] = None) -> bool:
        """
        Add item to queue.

        Returns:
            True if added, False if dropped
        """
        async with self._lock:
            self._enqueued += 1

            if len(self._queue) >= self.maxsize:
                if self.overflow_strategy == "drop_oldest":
                    # deque with maxlen handles this automatically
                    pass
                elif self.overflow_strategy == "drop_newest":
                    self._dropped += 1
                    return False
                elif self.overflow_strategy == "block":
                    # TODO: implement blocking with timeout
                    self._dropped += 1
                    return False

            self._queue.append(item)

            # Check high water mark
            if not self._backpressure and len(self._queue) >= self.high_water_mark:
                self._backpressure = True
                if self._backpressure_callback:
                    await self._backpressure_callback(True)

            async with self._not_empty:
                self._not_empty.notify()

            return True

    async def get(self, timeout: Optional[float] = None) -> Optional[Any]:
        """Get item from queue"""
        async with self._not_empty:
            while not self._queue:
                try:
                    await asyncio.wait_for(
                        self._not_empty.wait(),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError:
                    return None

        async with self._lock:
            if not self._queue:
                return None

            item = self._queue.popleft()
            self._dequeued += 1

            # Check low water mark
            if self._backpressure and len(self._queue) <= self.low_water_mark:
                self._backpressure = False
                if self._backpressure_callback:
                    await self._backpressure_callback(False)

            return item

    def qsize(self) -> int:
        """Get current queue size"""
        return len(self._queue)

    def is_backpressure(self) -> bool:
        """Check if backpressure is active"""
        return self._backpressure

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics"""
        return {
            "current_size": len(self._queue),
            "maxsize": self.maxsize,
            "enqueued": self._enqueued,
            "dequeued": self._dequeued,
            "dropped": self._dropped,
            "backpressure": self._backpressure,
            "fill_ratio": len(self._queue) / self.maxsize,
        }


# =============================================================================
# Per-Key Rate Limiter (for per-token, per-client limiting)
# =============================================================================

class PerKeyRateLimiter:
    """
    Rate limiter with separate buckets per key (e.g., per client IP, per token_id).

    Automatically cleans up stale buckets.

    Args:
        rate: Tokens per second per key
        capacity: Bucket capacity per key
        cleanup_interval: Seconds between cleanup runs
        max_age: Maximum age of unused bucket before cleanup
    """

    def __init__(
        self,
        rate: float,
        capacity: float,
        cleanup_interval: float = 60.0,
        max_age: float = 300.0,
    ):
        self.rate = rate
        self.capacity = capacity
        self.cleanup_interval = cleanup_interval
        self.max_age = max_age

        self._buckets: Dict[str, Tuple[TokenBucket, float]] = {}  # key -> (bucket, last_access)
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    def acquire(self, key: str, tokens: float = 1.0) -> bool:
        """Acquire tokens for a specific key"""
        now = time.monotonic()

        with self._lock:
            # Periodic cleanup
            if now - self._last_cleanup > self.cleanup_interval:
                self._cleanup(now)

            # Get or create bucket
            if key not in self._buckets:
                self._buckets[key] = (TokenBucket(self.rate, self.capacity), now)

            bucket, _ = self._buckets[key]
            self._buckets[key] = (bucket, now)  # Update last access

            return bucket.acquire(tokens)

    def _cleanup(self, now: float) -> None:
        """Remove stale buckets"""
        cutoff = now - self.max_age
        stale_keys = [
            key for key, (_, last_access) in self._buckets.items()
            if last_access < cutoff
        ]
        for key in stale_keys:
            del self._buckets[key]
        self._last_cleanup = now

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics"""
        with self._lock:
            return {
                "active_keys": len(self._buckets),
                "rate_per_key": self.rate,
                "capacity_per_key": self.capacity,
            }


# =============================================================================
# Throttle Configuration
# =============================================================================

@dataclass
class EndpointThrottleConfig:
    """Configuration for a single endpoint's throttling"""
    rate: float = 10.0                  # Requests per second
    burst: float = 20.0                 # Burst capacity
    per_key: bool = False               # Whether to throttle per key
    key_extractor: Optional[str] = None # How to extract key ("ip", "token_id", "api_key")
    concurrency_limit: int = 0          # Max concurrent (0 = unlimited)


# Default throttle configs for endpoints
DEFAULT_ENDPOINT_CONFIGS: Dict[str, EndpointThrottleConfig] = {
    # High cost endpoints
    "/v1/radar": EndpointThrottleConfig(rate=2.0, burst=5.0),
    "/v1/evidence": EndpointThrottleConfig(rate=1.0, burst=3.0, per_key=True, key_extractor="token_id"),
    "/v1/heatmap/tiles": EndpointThrottleConfig(rate=5.0, burst=10.0, concurrency_limit=3),

    # Medium cost endpoints
    "/v1/alerts": EndpointThrottleConfig(rate=5.0, burst=10.0),
    "/v1/replay/catalog": EndpointThrottleConfig(rate=3.0, burst=6.0),

    # Low cost endpoints
    "/v1/health": EndpointThrottleConfig(rate=100.0, burst=200.0),

    # Write endpoints (per-key)
    "/v1/alerts/*/ack": EndpointThrottleConfig(rate=10.0, burst=20.0, per_key=True, key_extractor="ip"),
    "/v1/alerts/*/resolve": EndpointThrottleConfig(rate=10.0, burst=20.0, per_key=True, key_extractor="ip"),
}


# =============================================================================
# Global Throttle Registry
# =============================================================================

class ThrottleRegistry:
    """
    Central registry for all throttlers.

    Provides:
    - Named throttler lookup
    - Global stats collection
    - Configuration management
    """

    _instance: Optional["ThrottleRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._throttlers: Dict[str, Any] = {}
                cls._instance._configs: Dict[str, EndpointThrottleConfig] = DEFAULT_ENDPOINT_CONFIGS.copy()
        return cls._instance

    def get_throttler(self, name: str) -> Optional[Any]:
        """Get a named throttler"""
        return self._throttlers.get(name)

    def register(self, name: str, throttler: Any) -> None:
        """Register a throttler"""
        self._throttlers[name] = throttler

    def get_or_create_bucket(self, name: str, rate: float, capacity: float) -> TokenBucket:
        """Get or create a token bucket throttler"""
        if name not in self._throttlers:
            self._throttlers[name] = TokenBucket(rate, capacity)
        return self._throttlers[name]

    def get_config(self, endpoint: str) -> EndpointThrottleConfig:
        """Get config for an endpoint (with wildcard matching)"""
        # Direct match
        if endpoint in self._configs:
            return self._configs[endpoint]

        # Wildcard match
        for pattern, config in self._configs.items():
            if "*" in pattern:
                regex_pattern = pattern.replace("*", "[^/]+")
                import re
                if re.match(f"^{regex_pattern}$", endpoint):
                    return config

        # Default config
        return EndpointThrottleConfig()

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get stats from all throttlers"""
        stats = {}
        for name, throttler in self._throttlers.items():
            if hasattr(throttler, "get_stats"):
                stats[name] = throttler.get_stats()
        return stats


def get_throttle_registry() -> ThrottleRegistry:
    """Get the global throttle registry singleton"""
    return ThrottleRegistry()
