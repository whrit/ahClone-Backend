"""Redis-based caching service for performance optimization"""

import hashlib
import json
from functools import wraps
from typing import Any, Callable, TypeVar

from redis import ConnectionError, Redis

from app.core.config import settings

T = TypeVar("T")


class CacheService:
    """Redis-based caching service"""

    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._client: Redis | None = None

    @property
    def client(self) -> Redis:
        """Lazy-load Redis client"""
        if self._client is None:
            self._client = Redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    def get(self, key: str) -> Any | None:
        """Get value from cache

        Args:
            key: Cache key to retrieve

        Returns:
            Cached value (deserialized from JSON) or None if not found
        """
        try:
            value = self.client.get(key)
            if value is None:
                return None

            # Deserialize JSON
            return json.loads(value)
        except (ConnectionError, Exception):
            # Fall back to uncached on any error
            return None

    def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Set value in cache with TTL

        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            ttl: Time to live in seconds (default 5 minutes)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Serialize to JSON
            serialized = json.dumps(value)

            # Set with expiration
            result = self.client.setex(key, ttl, serialized)
            return bool(result)
        except (ConnectionError, Exception):
            # Fall back to uncached on any error
            return False

    def delete(self, key: str) -> bool:
        """Delete key from cache

        Args:
            key: Cache key to delete

        Returns:
            True if key was deleted, False if key didn't exist
        """
        try:
            result = self.client.delete(key)
            return result > 0
        except (ConnectionError, Exception):
            return False

    def clear_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern

        Args:
            pattern: Pattern to match (e.g., 'project:*', 'gsc:*:123:*')

        Returns:
            Number of keys deleted
        """
        try:
            # Find all keys matching pattern
            keys = list(self.client.scan_iter(match=pattern))

            if not keys:
                return 0

            # Delete all matching keys
            deleted = self.client.delete(*keys)
            return deleted
        except (ConnectionError, Exception):
            return 0

    def exists(self, key: str) -> bool:
        """Check if key exists in cache

        Args:
            key: Cache key to check

        Returns:
            True if key exists, False otherwise
        """
        try:
            return bool(self.client.exists(key))
        except (ConnectionError, Exception):
            return False


# Global cache instance
cache = CacheService()


def cached(ttl: int = 300, key_prefix: str = "") -> Callable:
    """Decorator to cache function results

    Args:
        ttl: Time to live in seconds (default 5 minutes)
        key_prefix: Optional prefix for cache key

    Usage:
        @cached(ttl=60, key_prefix="user")
        def get_user(user_id: str) -> dict:
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # Generate cache key from function name and arguments
            key = _generate_cache_key(func, args, kwargs, key_prefix)

            # Try to get from cache
            cached_value = cache.get(key)
            if cached_value is not None:
                return cached_value

            # Call function and cache result
            result = func(*args, **kwargs)
            cache.set(key, result, ttl)
            return result

        return wrapper

    return decorator


def _generate_cache_key(
    func: Callable, args: tuple, kwargs: dict, prefix: str
) -> str:
    """Generate cache key from function and arguments

    Args:
        func: Function being cached
        args: Positional arguments
        kwargs: Keyword arguments
        prefix: Optional prefix for the key

    Returns:
        Cache key string
    """
    # Start with function name
    func_name = func.__name__

    # Create a deterministic representation of arguments
    # Sort kwargs by key to ensure consistent ordering
    sorted_kwargs = sorted(kwargs.items())

    # Create a tuple of all arguments for hashing
    args_tuple = (args, tuple(sorted_kwargs))

    # Generate hash of arguments
    args_json = json.dumps(args_tuple, sort_keys=True)
    args_hash = hashlib.md5(args_json.encode()).hexdigest()

    # Build cache key
    if prefix:
        return f"{prefix}:{func_name}:{args_hash}"
    else:
        return f"{func_name}:{args_hash}"


def invalidate_project_cache(project_id: str) -> int:
    """Invalidate all cache entries for a project

    Args:
        project_id: Project ID to invalidate cache for

    Returns:
        Number of cache entries deleted
    """
    return cache.clear_pattern(f"*:{project_id}:*")


def invalidate_gsc_cache(project_id: str) -> int:
    """Invalidate GSC-related cache for a project

    Args:
        project_id: Project ID to invalidate cache for

    Returns:
        Number of cache entries deleted
    """
    deleted = 0
    deleted += cache.clear_pattern(f"gsc:*:{project_id}:*")
    deleted += cache.clear_pattern(f"opportunities:{project_id}:*")
    return deleted


def invalidate_ads_cache(project_id: str) -> int:
    """Invalidate Ads-related cache for a project

    Args:
        project_id: Project ID to invalidate cache for

    Returns:
        Number of cache entries deleted
    """
    return cache.clear_pattern(f"ads:*:{project_id}:*")


def invalidate_audit_cache(project_id: str) -> int:
    """Invalidate audit-related cache for a project

    Args:
        project_id: Project ID to invalidate cache for

    Returns:
        Number of cache entries deleted
    """
    return cache.clear_pattern(f"audit:*:{project_id}:*")
