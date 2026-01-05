"""
Tests for Cost Throttling Module (v5.22)

Validates:
1. TokenBucket rate limiting
2. SlidingWindowLimiter
3. ConcurrencyLimiter
4. AdaptiveDownsampler
5. BackpressureQueue
6. PerKeyRateLimiter
7. ThrottleRegistry

"控成本，稳质量"
"""

import pytest
import time
import asyncio
from unittest.mock import AsyncMock

from backend.common.throttle import (
    ThrottleResult,
    ThrottleStats,
    TokenBucket,
    AsyncTokenBucket,
    SlidingWindowLimiter,
    ConcurrencyLimiter,
    AdaptiveDownsampler,
    DownsampleConfig,
    BackpressureQueue,
    PerKeyRateLimiter,
    EndpointThrottleConfig,
    ThrottleRegistry,
    get_throttle_registry,
    DEFAULT_ENDPOINT_CONFIGS,
)


class TestThrottleStats:
    """Test ThrottleStats dataclass"""

    def test_default_values(self):
        """Should have sensible defaults"""
        stats = ThrottleStats()

        assert stats.total_requests == 0
        assert stats.allowed_requests == 0
        assert stats.rate_limited == 0
        assert stats.queue_drops == 0

    def test_to_dict(self):
        """Should serialize to dict"""
        stats = ThrottleStats(
            total_requests=100,
            allowed_requests=90,
            rate_limited=10,
            avg_wait_ms=5.5555,
        )

        d = stats.to_dict()

        assert d["total_requests"] == 100
        assert d["allowed_requests"] == 90
        assert d["rate_limited"] == 10
        assert d["avg_wait_ms"] == 5.56  # Rounded


class TestTokenBucket:
    """Test TokenBucket rate limiter"""

    def test_bucket_creation(self):
        """Should create bucket with correct params"""
        bucket = TokenBucket(rate=10, capacity=20)

        assert bucket.rate == 10
        assert bucket.capacity == 20
        assert bucket.tokens == 20  # Starts full

    def test_bucket_with_initial(self):
        """Should respect initial token count"""
        bucket = TokenBucket(rate=10, capacity=20, initial=5)

        assert bucket.tokens == 5

    def test_acquire_success(self):
        """Should allow request when tokens available"""
        bucket = TokenBucket(rate=10, capacity=20)

        result = bucket.acquire()

        assert result is True
        assert bucket.tokens == 19

    def test_acquire_multiple(self):
        """Should allow multiple tokens"""
        bucket = TokenBucket(rate=10, capacity=20)

        result = bucket.acquire(tokens=5)

        assert result is True
        assert bucket.tokens == 15

    def test_acquire_depletes_bucket(self):
        """Should deplete bucket over time"""
        bucket = TokenBucket(rate=10, capacity=5, initial=5)

        for i in range(5):
            assert bucket.acquire() is True

        # Bucket should be empty
        assert bucket.acquire() is False

    def test_refill_over_time(self):
        """Should refill tokens over time"""
        bucket = TokenBucket(rate=100, capacity=10, initial=0)

        # Wait for refill
        time.sleep(0.05)  # 50ms = 5 tokens at 100/s

        # Should have some tokens now
        assert bucket.acquire(tokens=3) is True

    def test_acquire_blocking(self):
        """Should block and wait for tokens"""
        bucket = TokenBucket(rate=100, capacity=1, initial=0)

        start = time.monotonic()
        result = bucket.acquire(tokens=1, blocking=True, timeout=0.1)
        elapsed = time.monotonic() - start

        assert result is True
        assert elapsed < 0.05  # Should complete within 50ms

    def test_acquire_blocking_timeout(self):
        """Should timeout if tokens don't become available"""
        bucket = TokenBucket(rate=0.1, capacity=1, initial=0)  # Very slow refill

        start = time.monotonic()
        result = bucket.acquire(tokens=1, blocking=True, timeout=0.05)
        elapsed = time.monotonic() - start

        assert result is False
        assert 0.04 < elapsed < 0.1  # Should timeout around 50ms

    def test_get_stats(self):
        """Should track statistics"""
        bucket = TokenBucket(rate=10, capacity=5, initial=5)

        bucket.acquire()
        bucket.acquire()
        bucket.acquire()
        bucket.acquire()
        bucket.acquire()
        bucket.acquire()  # This should fail

        stats = bucket.get_stats()

        assert stats.total_requests == 6
        assert stats.allowed_requests == 5
        assert stats.rate_limited == 1


class TestAsyncTokenBucket:
    """Test async token bucket"""

    @pytest.mark.asyncio
    async def test_async_acquire(self):
        """Should work with async/await"""
        bucket = AsyncTokenBucket(rate=10, capacity=5)

        result = await bucket.acquire()

        assert result is True

    @pytest.mark.asyncio
    async def test_async_blocking(self):
        """Should block asynchronously"""
        bucket = AsyncTokenBucket(rate=100, capacity=1, initial=0)

        start = time.monotonic()
        result = await bucket.acquire(tokens=1, blocking=True, timeout=0.1)
        elapsed = time.monotonic() - start

        assert result is True
        assert elapsed < 0.05


class TestSlidingWindowLimiter:
    """Test SlidingWindowLimiter"""

    def test_limiter_creation(self):
        """Should create limiter"""
        limiter = SlidingWindowLimiter(max_requests=10, window_seconds=1.0)

        assert limiter.max_requests == 10
        assert limiter.window_seconds == 1.0

    def test_allows_within_limit(self):
        """Should allow requests within limit"""
        limiter = SlidingWindowLimiter(max_requests=5, window_seconds=1.0)

        for i in range(5):
            assert limiter.acquire() is True

    def test_blocks_over_limit(self):
        """Should block requests over limit"""
        limiter = SlidingWindowLimiter(max_requests=3, window_seconds=1.0)

        assert limiter.acquire() is True
        assert limiter.acquire() is True
        assert limiter.acquire() is True
        assert limiter.acquire() is False

    def test_window_expires(self):
        """Should allow requests after window expires"""
        limiter = SlidingWindowLimiter(max_requests=2, window_seconds=0.05)

        assert limiter.acquire() is True
        assert limiter.acquire() is True
        assert limiter.acquire() is False

        time.sleep(0.06)  # Window expires

        assert limiter.acquire() is True

    def test_get_current_count(self):
        """Should return current request count"""
        limiter = SlidingWindowLimiter(max_requests=10, window_seconds=1.0)

        limiter.acquire()
        limiter.acquire()
        limiter.acquire()

        assert limiter.get_current_count() == 3


class TestConcurrencyLimiter:
    """Test ConcurrencyLimiter"""

    @pytest.mark.asyncio
    async def test_limiter_creation(self):
        """Should create limiter"""
        limiter = ConcurrencyLimiter(max_concurrent=3)

        assert limiter.max_concurrent == 3

    @pytest.mark.asyncio
    async def test_acquire_release(self):
        """Should acquire and release slots"""
        limiter = ConcurrencyLimiter(max_concurrent=2)

        assert await limiter.acquire() is True
        assert await limiter.acquire() is True

        limiter.release()
        limiter.release()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Should work as context manager"""
        limiter = ConcurrencyLimiter(max_concurrent=2)

        async with limiter:
            # Slot acquired
            pass
        # Slot released

    @pytest.mark.asyncio
    async def test_blocks_at_limit(self):
        """Should block when at limit"""
        limiter = ConcurrencyLimiter(max_concurrent=1, timeout=0.05)

        assert await limiter.acquire() is True

        # Second acquire should timeout
        result = await limiter.acquire(timeout=0.02)
        assert result is False

        limiter.release()

    @pytest.mark.asyncio
    async def test_queue_drop(self):
        """Should drop when queue is full"""
        limiter = ConcurrencyLimiter(max_concurrent=1, queue_size=1, timeout=0.1)

        assert await limiter.acquire() is True  # Takes the slot
        # Now 0 waiting, 1 in queue allowed

        # This should be queued
        task1 = asyncio.create_task(limiter.acquire())
        await asyncio.sleep(0.01)  # Let task1 start waiting

        # This should be dropped (queue full)
        result = await limiter.acquire()
        assert result is False

        limiter.release()
        await task1


class TestAdaptiveDownsampler:
    """Test AdaptiveDownsampler"""

    def test_sampler_creation(self):
        """Should create sampler with default config"""
        sampler = AdaptiveDownsampler()

        assert sampler.config.base_interval_ms == 250

    def test_should_sample_first(self):
        """Should sample first event for each key"""
        sampler = AdaptiveDownsampler()

        assert sampler.should_sample("token-1", 1000) is True
        assert sampler.should_sample("token-2", 1000) is True

    def test_respects_interval(self):
        """Should respect sampling interval"""
        config = DownsampleConfig(base_interval_ms=100)
        sampler = AdaptiveDownsampler(config)

        assert sampler.should_sample("token-1", 1000) is True
        assert sampler.should_sample("token-1", 1050) is False  # Too soon
        assert sampler.should_sample("token-1", 1100) is True   # OK

    def test_update_load_min(self):
        """Low load should use min interval"""
        config = DownsampleConfig(
            base_interval_ms=250,
            min_interval_ms=100,
            max_interval_ms=1000,
            load_threshold_low=0.3,
            load_threshold_high=0.8,
        )
        sampler = AdaptiveDownsampler(config)

        sampler.update_load(0.1)  # Low load

        assert sampler.get_current_interval() == 100

    def test_update_load_max(self):
        """High load should use max interval"""
        config = DownsampleConfig(
            base_interval_ms=250,
            min_interval_ms=100,
            max_interval_ms=1000,
            load_threshold_low=0.3,
            load_threshold_high=0.8,
        )
        sampler = AdaptiveDownsampler(config)

        sampler.update_load(0.9)  # High load

        assert sampler.get_current_interval() == 1000

    def test_get_stats(self):
        """Should track statistics"""
        sampler = AdaptiveDownsampler()

        sampler.should_sample("token-1", 1000)
        sampler.should_sample("token-1", 1050)  # Dropped
        sampler.should_sample("token-1", 1300)  # Sampled

        stats = sampler.get_stats()

        assert stats["total_events"] == 3
        assert stats["sampled_events"] == 2
        assert stats["dropped_events"] == 1


class TestBackpressureQueue:
    """Test BackpressureQueue"""

    @pytest.mark.asyncio
    async def test_queue_creation(self):
        """Should create queue"""
        queue = BackpressureQueue(maxsize=100)

        assert queue.maxsize == 100

    @pytest.mark.asyncio
    async def test_put_get(self):
        """Should put and get items"""
        queue = BackpressureQueue(maxsize=10)

        await queue.put("item1")
        await queue.put("item2")

        assert await queue.get() == "item1"
        assert await queue.get() == "item2"

    @pytest.mark.asyncio
    async def test_qsize(self):
        """Should report queue size"""
        queue = BackpressureQueue(maxsize=10)

        await queue.put("item1")
        await queue.put("item2")

        assert queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_backpressure_callback(self):
        """Should call backpressure callback"""
        queue = BackpressureQueue(maxsize=10, high_water=0.5, low_water=0.2)

        callback_values = []

        async def callback(backpressure: bool):
            callback_values.append(backpressure)

        queue.set_backpressure_callback(callback)

        # Fill to high water mark
        for i in range(6):  # >50%
            await queue.put(f"item{i}")

        assert True in callback_values  # Backpressure triggered

    @pytest.mark.asyncio
    async def test_drop_oldest_strategy(self):
        """Should drop oldest on overflow"""
        queue = BackpressureQueue(maxsize=3, overflow_strategy="drop_oldest")

        await queue.put("item1")
        await queue.put("item2")
        await queue.put("item3")
        await queue.put("item4")  # Should drop item1

        assert queue.qsize() == 3
        assert await queue.get() == "item2"  # item1 was dropped

    @pytest.mark.asyncio
    async def test_drop_newest_strategy(self):
        """Should drop newest on overflow"""
        queue = BackpressureQueue(maxsize=3, overflow_strategy="drop_newest")

        await queue.put("item1")
        await queue.put("item2")
        await queue.put("item3")
        result = await queue.put("item4")  # Should be dropped

        assert result is False
        assert queue.qsize() == 3


class TestPerKeyRateLimiter:
    """Test PerKeyRateLimiter"""

    def test_limiter_creation(self):
        """Should create limiter"""
        limiter = PerKeyRateLimiter(rate=10, capacity=20)

        assert limiter.rate == 10
        assert limiter.capacity == 20

    def test_separate_buckets(self):
        """Should have separate buckets per key"""
        limiter = PerKeyRateLimiter(rate=10, capacity=2)

        # Both keys should work
        assert limiter.acquire("key1") is True
        assert limiter.acquire("key1") is True
        assert limiter.acquire("key1") is False  # key1 exhausted

        assert limiter.acquire("key2") is True  # key2 still has tokens

    def test_cleanup(self):
        """Should cleanup stale buckets"""
        limiter = PerKeyRateLimiter(
            rate=10,
            capacity=5,
            cleanup_interval=0.01,
            max_age=0.02,
        )

        limiter.acquire("old_key")
        time.sleep(0.03)  # Let it go stale
        limiter.acquire("new_key")  # Triggers cleanup

        stats = limiter.get_stats()
        # old_key should have been cleaned up, only new_key remains
        assert stats["active_keys"] == 1


class TestEndpointThrottleConfig:
    """Test EndpointThrottleConfig"""

    def test_default_config(self):
        """Should have sensible defaults"""
        config = EndpointThrottleConfig()

        assert config.rate == 10.0
        assert config.burst == 20.0
        assert config.per_key is False

    def test_custom_config(self):
        """Should accept custom values"""
        config = EndpointThrottleConfig(
            rate=5.0,
            burst=10.0,
            per_key=True,
            key_extractor="ip",
        )

        assert config.rate == 5.0
        assert config.per_key is True
        assert config.key_extractor == "ip"


class TestThrottleRegistry:
    """Test ThrottleRegistry singleton"""

    def test_singleton(self):
        """Should be a singleton"""
        registry1 = get_throttle_registry()
        registry2 = get_throttle_registry()

        assert registry1 is registry2

    def test_register_and_get(self):
        """Should register and retrieve throttlers"""
        registry = get_throttle_registry()
        bucket = TokenBucket(rate=10, capacity=20)

        registry.register("test_bucket", bucket)
        retrieved = registry.get_throttler("test_bucket")

        assert retrieved is bucket

    def test_get_or_create_bucket(self):
        """Should create bucket if not exists"""
        registry = get_throttle_registry()

        bucket1 = registry.get_or_create_bucket("auto_bucket", rate=5, capacity=10)
        bucket2 = registry.get_or_create_bucket("auto_bucket", rate=100, capacity=200)

        assert bucket1 is bucket2
        assert bucket1.rate == 5  # Original rate preserved

    def test_get_config_direct(self):
        """Should get config for known endpoint"""
        registry = get_throttle_registry()

        config = registry.get_config("/v1/radar")

        assert config.rate == 2.0

    def test_get_config_wildcard(self):
        """Should match wildcard patterns"""
        registry = get_throttle_registry()

        config = registry.get_config("/v1/alerts/123/ack")

        assert config.rate == 10.0  # From /v1/alerts/*/ack pattern

    def test_get_config_default(self):
        """Should return default config for unknown endpoints"""
        registry = get_throttle_registry()

        config = registry.get_config("/unknown/endpoint")

        assert config.rate == 10.0  # Default


class TestDefaultEndpointConfigs:
    """Test DEFAULT_ENDPOINT_CONFIGS"""

    def test_radar_config(self):
        """Radar should have low rate limit"""
        config = DEFAULT_ENDPOINT_CONFIGS["/v1/radar"]

        assert config.rate == 2.0
        assert config.burst == 5.0

    def test_evidence_config(self):
        """Evidence should be per-key limited"""
        config = DEFAULT_ENDPOINT_CONFIGS["/v1/evidence"]

        assert config.per_key is True
        assert config.key_extractor == "token_id"

    def test_heatmap_config(self):
        """Heatmap should have concurrency limit"""
        config = DEFAULT_ENDPOINT_CONFIGS["/v1/heatmap/tiles"]

        assert config.concurrency_limit == 3

    def test_health_config(self):
        """Health should have high rate limit"""
        config = DEFAULT_ENDPOINT_CONFIGS["/v1/health"]

        assert config.rate == 100.0
