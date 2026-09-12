"""Lightweight, thread-safe in-memory caching engine with configurable TTL and tag-based invalidation.

Provides deterministic hit-rate tracking, monotonic time expiration, tag/prefix invalidation,
and memory bounds for high-performance dashboard summary and entity queries.
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger(__name__)

# Configurable expiration times loaded from environment with resilient defaults
DEFAULT_CACHE_TTL: float = float(os.getenv("CACHE_TTL_SECONDS", "60.0"))
DASHBOARD_CACHE_TTL: float = float(os.getenv("DASHBOARD_CACHE_TTL_SECONDS", "60.0"))
CACHE_MAX_SIZE: int = int(os.getenv("CACHE_MAX_SIZE", "1000"))


@dataclass
class CacheEntry:
    """Represents a cached item with metadata for expiration and invalidation."""

    value: Any
    expires_at: Optional[float]
    created_at: float = field(default_factory=time.monotonic)
    tags: set[str] = field(default_factory=set)

    def is_expired(self, now: float) -> bool:
        """Check whether the entry has exceeded its time-to-live.

        Args:
            now: Current monotonic timestamp.

        Returns:
            True if expired, False otherwise.
        """
        return self.expires_at is not None and now >= self.expires_at


class InMemoryCache:
    """Thread-safe in-memory cache supporting TTL expiration and tag-based invalidation."""

    def __init__(
        self,
        default_ttl: float = DEFAULT_CACHE_TTL,
        max_size: int = CACHE_MAX_SIZE,
    ) -> None:
        """Initialize the cache with default TTL and maximum capacity.

        Args:
            default_ttl: Default expiration period in seconds.
            max_size: Maximum number of entries stored before eviction.
        """
        self._default_ttl: float = default_ttl
        self._max_size: int = max_size
        self._store: dict[str, CacheEntry] = {}
        self._lock: threading.RLock = threading.RLock()
        self._hits: int = 0
        self._misses: int = 0

    @property
    def default_ttl(self) -> float:
        """Return the default expiration time in seconds."""
        return self._default_ttl

    @default_ttl.setter
    def default_ttl(self, ttl: float) -> None:
        """Update the default expiration time in seconds."""
        self._default_ttl = ttl

    def has(self, key: str) -> bool:
        """Check whether a non-expired entry exists in the cache without updating metrics.

        Args:
            key: Unique cache key.

        Returns:
            True if entry exists and is not expired, False otherwise.
        """
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None or entry.is_expired(now):
                return False
            return True

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value from the cache if present and unexpired.

        Args:
            key: Unique cache key.
            default: Value to return if missing or expired.

        Returns:
            Cached value if valid, or default.
        """
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return default

            if entry.is_expired(now):
                del self._store[key]
                self._misses += 1
                return default

            self._hits += 1
            return entry.value

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
        tags: Optional[Iterable[str]] = None,
    ) -> None:
        """Store a value in the cache with optional TTL and tags.

        Args:
            key: Unique cache key.
            value: Value to cache.
            ttl: Time-to-live in seconds; uses default_ttl if None. Set to <= 0 to bypass.
            tags: Iterable of string tags for grouped invalidation.
        """
        effective_ttl = self._default_ttl if ttl is None else ttl
        if effective_ttl <= 0:
            # TTL of 0 or negative means do not cache
            return

        now = time.monotonic()
        expires_at = now + effective_ttl
        entry_tags = set(tags) if tags is not None else set()

        with self._lock:
            # Enforce max capacity bounds with purge if necessary
            if len(self._store) >= self._max_size and key not in self._store:
                self._evict_stale(now)
                if len(self._store) >= self._max_size:
                    # Evict the oldest entry
                    oldest_key = min(self._store.keys(), key=lambda k: self._store[k].created_at)
                    del self._store[oldest_key]

            self._store[key] = CacheEntry(
                value=value,
                expires_at=expires_at,
                created_at=now,
                tags=entry_tags,
            )

    def delete(self, key: str) -> bool:
        """Delete a single key from the cache.

        Args:
            key: Cache key to remove.

        Returns:
            True if key was removed, False if not present.
        """
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def invalidate_by_tag(self, tag: str) -> int:
        """Invalidate all cached items associated with the specified tag.

        Args:
            tag: Tag identifier to match.

        Returns:
            Count of evicted entries.
        """
        with self._lock:
            keys_to_remove = [k for k, entry in self._store.items() if tag in entry.tags]
            for k in keys_to_remove:
                del self._store[k]
            return len(keys_to_remove)

    def invalidate_by_prefix(self, prefix: str) -> int:
        """Invalidate all cached items whose key starts with the specified prefix.

        Args:
            prefix: Key prefix string.

        Returns:
            Count of evicted entries.
        """
        with self._lock:
            keys_to_remove = [k for k in self._store.keys() if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._store[k]
            return len(keys_to_remove)

    def clear(self) -> None:
        """Remove all entries from the cache."""
        with self._lock:
            self._store.clear()

    def get_stats(self) -> dict[str, Any]:
        """Return operational cache metrics and hit-rate statistics.

        Returns:
            Dictionary containing hits, misses, total_requests, hit_rate, and size.
        """
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total) if total > 0 else 0.0
            return {
                "hits": self._hits,
                "misses": self._misses,
                "total_requests": total,
                "hit_rate": round(hit_rate, 4),
                "size": len(self._store),
            }

    def reset_stats(self) -> None:
        """Reset hit and miss counters to zero."""
        with self._lock:
            self._hits = 0
            self._misses = 0

    def _evict_stale(self, now: float) -> None:
        """Evict all expired entries from storage.

        Args:
            now: Current monotonic timestamp.
        """
        expired_keys = [k for k, entry in self._store.items() if entry.is_expired(now)]
        for k in expired_keys:
            del self._store[k]

    def memoize(
        self,
        ttl: Optional[float] = None,
        prefix: str = "",
        tags: Optional[Iterable[str]] = None,
    ) -> Callable[..., Any]:
        """Decorator to cache return values of synchronous or asynchronous functions.

        Args:
            ttl: Optional TTL override in seconds.
            prefix: Optional key prefix.
            tags: Optional tags for grouped invalidation.

        Returns:
            Wrapped callable with caching logic.
        """
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            func_prefix = prefix or f"{func.__module__}.{func.__qualname__}"

            if inspect.iscoroutinefunction(func):
                @functools.wraps(func)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                    key = f"{func_prefix}:{args}:{sorted(kwargs.items())}"
                    cached_val = self.get(key)
                    if cached_val is not None:
                        return cached_val
                    result = await func(*args, **kwargs)
                    self.set(key, result, ttl=ttl, tags=tags)
                    return result

                return async_wrapper
            else:
                @functools.wraps(func)
                def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                    key = f"{func_prefix}:{args}:{sorted(kwargs.items())}"
                    cached_val = self.get(key)
                    if cached_val is not None:
                        return cached_val
                    result = func(*args, **kwargs)
                    self.set(key, result, ttl=ttl, tags=tags)
                    return result

                return sync_wrapper

        return decorator


# Global shared cache instance
cache = InMemoryCache(default_ttl=DEFAULT_CACHE_TTL)
