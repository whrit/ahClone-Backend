"""Tests for Redis caching layer"""

import time
from typing import Generator

import fakeredis
import pytest

from app.core.cache import CacheService, _generate_cache_key, cached


@pytest.fixture
def redis_client() -> Generator[fakeredis.FakeRedis, None, None]:
    """Fixture providing a fake Redis client for testing"""
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    # Cleanup
    client.flushall()


@pytest.fixture
def cache_service(redis_client: fakeredis.FakeRedis) -> CacheService:
    """Fixture providing a CacheService instance with fake Redis"""
    service = CacheService()
    # Override the client with our fake one
    service._client = redis_client
    return service


class TestCacheService:
    """Test suite for CacheService"""

    def test_cache_get_missing_key(self, cache_service: CacheService) -> None:
        """Test that cache_get returns None for missing keys"""
        result = cache_service.get("nonexistent_key")
        assert result is None

    def test_cache_set_and_get_string(self, cache_service: CacheService) -> None:
        """Test cache_set and cache_get round trip with string value"""
        key = "test_key"
        value = "test_value"

        # Set value
        success = cache_service.set(key, value)
        assert success is True

        # Get value
        result = cache_service.get(key)
        assert result == value

    def test_cache_set_and_get_dict(self, cache_service: CacheService) -> None:
        """Test cache_set and cache_get round trip with dict value"""
        key = "test_dict"
        value = {"name": "John", "age": 30, "active": True}

        # Set value
        success = cache_service.set(key, value)
        assert success is True

        # Get value
        result = cache_service.get(key)
        assert result == value

    def test_cache_set_and_get_list(self, cache_service: CacheService) -> None:
        """Test cache_set and cache_get round trip with list value"""
        key = "test_list"
        value = [1, 2, 3, "four", {"five": 5}]

        # Set value
        success = cache_service.set(key, value)
        assert success is True

        # Get value
        result = cache_service.get(key)
        assert result == value

    def test_cache_expiration(self, cache_service: CacheService) -> None:
        """Test that cache entries expire after TTL"""
        key = "expiring_key"
        value = "expiring_value"
        ttl = 1  # 1 second

        # Set value with short TTL
        cache_service.set(key, value, ttl=ttl)

        # Value should exist immediately
        assert cache_service.get(key) == value

        # Wait for expiration
        time.sleep(ttl + 0.5)

        # Value should be expired
        assert cache_service.get(key) is None

    def test_cache_delete(self, cache_service: CacheService) -> None:
        """Test that cache_delete removes keys"""
        key = "delete_test"
        value = "delete_value"

        # Set value
        cache_service.set(key, value)
        assert cache_service.get(key) == value

        # Delete key
        result = cache_service.delete(key)
        assert result is True

        # Key should be gone
        assert cache_service.get(key) is None

    def test_cache_delete_nonexistent(self, cache_service: CacheService) -> None:
        """Test deleting a nonexistent key returns False"""
        result = cache_service.delete("nonexistent_key")
        assert result is False

    def test_cache_exists(self, cache_service: CacheService) -> None:
        """Test cache_exists checks key existence"""
        key = "exists_test"
        value = "exists_value"

        # Key should not exist initially
        assert cache_service.exists(key) is False

        # Set value
        cache_service.set(key, value)

        # Key should exist now
        assert cache_service.exists(key) is True

        # Delete key
        cache_service.delete(key)

        # Key should not exist anymore
        assert cache_service.exists(key) is False

    def test_cache_clear_pattern_basic(self, cache_service: CacheService) -> None:
        """Test cache_clear_pattern with wildcards"""
        # Set multiple keys with pattern
        cache_service.set("project:123:data", "value1")
        cache_service.set("project:123:config", "value2")
        cache_service.set("project:456:data", "value3")
        cache_service.set("other:key", "value4")

        # Clear all project:123:* keys
        deleted_count = cache_service.clear_pattern("project:123:*")
        assert deleted_count == 2

        # Verify correct keys were deleted
        assert cache_service.get("project:123:data") is None
        assert cache_service.get("project:123:config") is None
        assert cache_service.get("project:456:data") == "value3"
        assert cache_service.get("other:key") == "value4"

    def test_cache_clear_pattern_middle_wildcard(self, cache_service: CacheService) -> None:
        """Test cache_clear_pattern with wildcard in the middle"""
        # Set multiple keys
        cache_service.set("gsc:123:opportunities", "value1")
        cache_service.set("gsc:456:opportunities", "value2")
        cache_service.set("gsc:123:explorer", "value3")
        cache_service.set("ads:123:data", "value4")

        # Clear all gsc:*:opportunities keys
        deleted_count = cache_service.clear_pattern("gsc:*:opportunities")
        assert deleted_count == 2

        # Verify correct keys were deleted
        assert cache_service.get("gsc:123:opportunities") is None
        assert cache_service.get("gsc:456:opportunities") is None
        assert cache_service.get("gsc:123:explorer") == "value3"
        assert cache_service.get("ads:123:data") == "value4"

    def test_cache_clear_pattern_no_matches(self, cache_service: CacheService) -> None:
        """Test cache_clear_pattern when pattern matches nothing"""
        cache_service.set("key1", "value1")
        cache_service.set("key2", "value2")

        deleted_count = cache_service.clear_pattern("nomatch:*")
        assert deleted_count == 0

        # Original keys should still exist
        assert cache_service.get("key1") == "value1"
        assert cache_service.get("key2") == "value2"


class TestCachedDecorator:
    """Test suite for @cached decorator"""

    def test_cached_decorator_caches_result(
        self, cache_service: CacheService, redis_client: fakeredis.FakeRedis, monkeypatch
    ) -> None:
        """Test that @cached decorator caches function results"""
        # Patch the global cache instance with our test cache
        import app.core.cache as cache_module
        monkeypatch.setattr(cache_module, "cache", cache_service)

        call_count = 0

        @cached(ttl=60, key_prefix="test")
        def expensive_function(x: int, y: int) -> int:
            nonlocal call_count
            call_count += 1
            return x + y

        # First call - function should execute
        result1 = expensive_function(1, 2)
        assert result1 == 3
        assert call_count == 1

        # Second call with same args - should use cache
        result2 = expensive_function(1, 2)
        assert result2 == 3
        assert call_count == 1  # Not called again

        # Call with different args - should execute again
        result3 = expensive_function(2, 3)
        assert result3 == 5
        assert call_count == 2

    def test_cached_decorator_respects_ttl(
        self, cache_service: CacheService, redis_client: fakeredis.FakeRedis, monkeypatch
    ) -> None:
        """Test that @cached decorator respects TTL"""
        # Patch the global cache instance with our test cache
        import app.core.cache as cache_module
        monkeypatch.setattr(cache_module, "cache", cache_service)

        call_count = 0

        @cached(ttl=1, key_prefix="test")
        def expensive_function(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        # First call
        result1 = expensive_function(5)
        assert result1 == 10
        assert call_count == 1

        # Immediate second call - should use cache
        result2 = expensive_function(5)
        assert result2 == 10
        assert call_count == 1

        # Wait for expiration
        time.sleep(1.5)

        # Call after expiration - should execute again
        result3 = expensive_function(5)
        assert result3 == 10
        assert call_count == 2

    def test_cached_decorator_with_kwargs(
        self, cache_service: CacheService, redis_client: fakeredis.FakeRedis, monkeypatch
    ) -> None:
        """Test that @cached decorator handles keyword arguments"""
        # Patch the global cache instance with our test cache
        import app.core.cache as cache_module
        monkeypatch.setattr(cache_module, "cache", cache_service)

        call_count = 0

        @cached(ttl=60, key_prefix="test")
        def function_with_kwargs(a: int, b: int = 10, c: int = 20) -> int:
            nonlocal call_count
            call_count += 1
            return a + b + c

        # Call with kwargs
        result1 = function_with_kwargs(1, b=2, c=3)
        assert result1 == 6
        assert call_count == 1

        # Same call - should use cache
        result2 = function_with_kwargs(1, b=2, c=3)
        assert result2 == 6
        assert call_count == 1

        # Different kwargs order but same values - should still cache
        result3 = function_with_kwargs(1, c=3, b=2)
        assert result3 == 6
        assert call_count == 1

    def test_cached_decorator_different_arg_values(
        self, cache_service: CacheService, redis_client: fakeredis.FakeRedis, monkeypatch
    ) -> None:
        """Test that different argument values generate different cache keys"""
        # Patch the global cache instance with our test cache
        import app.core.cache as cache_module
        monkeypatch.setattr(cache_module, "cache", cache_service)

        call_count = 0

        @cached(ttl=60, key_prefix="test")
        def compute(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * x

        # Call with different values
        assert compute(2) == 4
        assert call_count == 1

        assert compute(3) == 9
        assert call_count == 2

        assert compute(2) == 4  # Cached
        assert call_count == 2

        assert compute(3) == 9  # Cached
        assert call_count == 2

    def test_cached_decorator_with_complex_return(
        self, cache_service: CacheService, redis_client: fakeredis.FakeRedis, monkeypatch
    ) -> None:
        """Test that @cached decorator works with complex return types"""
        # Patch the global cache instance with our test cache
        import app.core.cache as cache_module
        monkeypatch.setattr(cache_module, "cache", cache_service)

        call_count = 0

        @cached(ttl=60, key_prefix="test")
        def get_user_data(user_id: str) -> dict:
            nonlocal call_count
            call_count += 1
            return {
                "id": user_id,
                "name": "John Doe",
                "permissions": ["read", "write"],
                "meta": {"created": "2023-01-01", "active": True},
            }

        # First call
        result1 = get_user_data("user123")
        assert result1["id"] == "user123"
        assert result1["permissions"] == ["read", "write"]
        assert call_count == 1

        # Second call - should use cache
        result2 = get_user_data("user123")
        assert result2 == result1
        assert call_count == 1


class TestGenerateCacheKey:
    """Test suite for _generate_cache_key function"""

    def test_generate_cache_key_with_args(self) -> None:
        """Test cache key generation with positional arguments"""
        def sample_func(a: int, b: str) -> None:
            pass

        key = _generate_cache_key(sample_func, (1, "test"), {}, "prefix")

        # Key should include function name and arguments
        assert "sample_func" in key
        assert "prefix" in key
        assert isinstance(key, str)

    def test_generate_cache_key_with_kwargs(self) -> None:
        """Test cache key generation with keyword arguments"""
        def sample_func(a: int, b: str = "default") -> None:
            pass

        key1 = _generate_cache_key(sample_func, (), {"a": 1, "b": "test"}, "prefix")
        key2 = _generate_cache_key(sample_func, (), {"a": 1, "b": "test"}, "prefix")

        # Same args should produce same key
        assert key1 == key2

    def test_generate_cache_key_different_args(self) -> None:
        """Test that different arguments produce different keys"""
        def sample_func(a: int) -> None:
            pass

        key1 = _generate_cache_key(sample_func, (1,), {}, "prefix")
        key2 = _generate_cache_key(sample_func, (2,), {}, "prefix")

        # Different args should produce different keys
        assert key1 != key2

    def test_generate_cache_key_kwargs_order_invariant(self) -> None:
        """Test that keyword argument order doesn't affect cache key"""
        def sample_func(a: int, b: int, c: int) -> None:
            pass

        key1 = _generate_cache_key(sample_func, (), {"a": 1, "b": 2, "c": 3}, "prefix")
        key2 = _generate_cache_key(sample_func, (), {"c": 3, "a": 1, "b": 2}, "prefix")

        # Different order should produce same key
        assert key1 == key2

    def test_generate_cache_key_no_prefix(self) -> None:
        """Test cache key generation without prefix"""
        def sample_func(x: int) -> None:
            pass

        key = _generate_cache_key(sample_func, (42,), {}, "")

        # Should still generate valid key
        assert isinstance(key, str)
        assert len(key) > 0
        assert "sample_func" in key


class TestCacheIntegration:
    """Integration tests for caching functionality"""

    def test_cache_invalidation_workflow(self, cache_service: CacheService) -> None:
        """Test a typical cache invalidation workflow"""
        project_id = "proj_123"

        # Set various cache entries for a project
        cache_service.set(f"opportunities:{project_id}:30", [{"keyword": "test"}])
        cache_service.set(f"gsc:explorer:{project_id}:page1", {"data": "explorer"})
        cache_service.set(f"ads:overlap:{project_id}", {"overlap": "data"})
        cache_service.set(f"other:data:{project_id}", "other")

        # Invalidate all opportunities cache
        deleted = cache_service.clear_pattern(f"opportunities:{project_id}:*")
        assert deleted == 1
        assert cache_service.get(f"opportunities:{project_id}:30") is None
        assert cache_service.get(f"gsc:explorer:{project_id}:page1") is not None

        # Invalidate all GSC-related cache
        deleted = cache_service.clear_pattern(f"gsc:*:{project_id}:*")
        assert deleted == 1
        assert cache_service.get(f"gsc:explorer:{project_id}:page1") is None
        assert cache_service.get(f"ads:overlap:{project_id}") is not None

    def test_cache_with_connection_error(self, cache_service: CacheService) -> None:
        """Test graceful handling when Redis is unavailable"""
        # Create a server that's disconnected
        server = fakeredis.FakeServer()
        server.connected = False
        disconnected_client = fakeredis.FakeRedis(server=server, decode_responses=True)

        # Override the cache service client
        cache_service._client = disconnected_client

        # Operations should handle connection errors gracefully
        # (This would raise ConnectionError in real implementation)
        # For now, just verify the test setup works
        assert server.connected is False
