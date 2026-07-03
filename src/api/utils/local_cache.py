"""Two-tier cache: in-memory LRU + diskcache on disk.

Replaces the Fernet-encrypted SecureCache with a simpler, faster approach.
Matches the tag-manager CLI's caching pattern.
"""

import json
import os
import time
from functools import wraps
from typing import Any, Callable, Dict, Optional

from utils.logger_config import log


# ---------------------------------------------------------------------------
# TTL Constants
# ---------------------------------------------------------------------------

TTL_RESOURCES = 300          # 5 minutes — collected resource data
TTL_RECOMMENDATIONS = 300    # 5 minutes — recommendation results
TTL_CFN_OUTPUTS = 3600       # 1 hour — CloudFormation stack outputs
TTL_AUTH = 3600              # 1 hour — API key / auth status
TTL_ASSUMED_ROLE = 3500      # ~58 min — STS assumed role (expires at 1hr)
TTL_VERSION = 86400          # 24 hours — version check
TTL_LOG_SAMPLES = 3600       # 1 hour — raw CloudWatch log samples (re-fetchable)


# ---------------------------------------------------------------------------
# Cache directory
# ---------------------------------------------------------------------------

DEFAULT_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".bluearch", "cache")
DEFAULT_SIZE_LIMIT = 500 * 1024 * 1024  # 500 MB


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------

def generate_key(*parts, **kwargs) -> str:
    """Generate a deterministic cache key from parts and kwargs.

    Args:
        *parts: Key segments (e.g. service name, method name)
        **kwargs: Additional parameters sorted and JSON-encoded

    Returns:
        Stable string key like 'aws:ec2:describe_instances:{"region":"us-east-1"}'
    """
    key = ":".join(str(p) for p in parts)
    if kwargs:
        sorted_params = json.dumps(kwargs, sort_keys=True, default=str)
        key = f"{key}:{sorted_params}"
    return key


# ---------------------------------------------------------------------------
# LocalCacheManager
# ---------------------------------------------------------------------------

class LocalCacheManager:
    """Two-tier cache with in-memory dict + diskcache on disk.

    Memory tier: Python dict with TTL tracking. Items with disk TTL <= 5 min
    are also cached in memory for fast access.

    Disk tier: diskcache.Cache with LRU eviction and configurable size limit.
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, cache_dir=None, size_limit=None):
        if self._initialized:
            return
        self._cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self._size_limit = size_limit or DEFAULT_SIZE_LIMIT
        self._disk_cache = None
        self._memory_cache: Dict[str, tuple] = {}  # key -> (value, expires_at)
        self._memory_ttl_threshold = 300  # Only cache in memory if disk TTL <= 5 min
        self._initialized = True

    @property
    def _disk(self):
        """Lazy-initialize diskcache on first access."""
        if self._disk_cache is None:
            import diskcache
            os.makedirs(self._cache_dir, exist_ok=True)
            self._disk_cache = diskcache.Cache(
                self._cache_dir,
                size_limit=self._size_limit,
                eviction_policy="least-recently-used",
            )
            log.debug(f"Disk cache initialized at {self._cache_dir}")
        return self._disk_cache

    def get(self, key: str) -> Optional[Any]:
        """Get a value from cache (memory first, then disk)."""
        # Check memory
        if key in self._memory_cache:
            value, expires_at = self._memory_cache[key]
            if time.time() < expires_at:
                return value
            else:
                del self._memory_cache[key]

        # Check disk
        value = self._disk.get(key)
        if value is not None:
            # Promote to memory if it's a short-TTL item
            self._memory_cache[key] = (value, time.time() + 60)
        return value

    def set(self, key: str, value: Any, ttl: int = TTL_RESOURCES):
        """Store a value in cache with a TTL (seconds)."""
        # Write to disk
        self._disk.set(key, value, expire=ttl)

        # Also cache in memory for short-TTL items
        if ttl <= self._memory_ttl_threshold:
            self._memory_cache[key] = (value, time.time() + min(ttl, 60))

    def delete(self, key: str):
        """Remove a key from both tiers."""
        self._memory_cache.pop(key, None)
        self._disk.delete(key)

    def clear(self):
        """Clear all cached data."""
        self._memory_cache.clear()
        self._disk.clear()

    def close(self):
        """Close the disk cache."""
        if self._disk_cache is not None:
            self._disk_cache.close()
            self._disk_cache = None

    # ------------------------------------------------------------------
    # Decorator
    # ------------------------------------------------------------------

    def cached(self, ttl: int = TTL_RESOURCES, key_prefix: str = ""):
        """Decorator that caches function return values.

        Args:
            ttl: Cache duration in seconds
            key_prefix: Optional prefix for the cache key

        Usage:
            @cache_manager.cached(ttl=300, key_prefix="ec2")
            def describe_instances(region):
                ...
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                parts = [key_prefix] if key_prefix else [func.__module__, func.__name__]
                cache_key = generate_key(*parts, args=str(args), **kwargs)

                result = self.get(cache_key)
                if result is not None:
                    return result

                result = func(*args, **kwargs)
                if result is not None:
                    self.set(cache_key, result, ttl=ttl)
                return result
            return wrapper
        return decorator


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

cache_manager = LocalCacheManager()
