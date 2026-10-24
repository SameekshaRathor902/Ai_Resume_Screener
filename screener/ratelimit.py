"""Rate limiting with two backends.

* MemoryBackend  - the default. Counts live in this process only.
* RedisBackend   - used when REDIS_URL is set. Every worker and server shares the
                   same counters, so the limit is real even with several processes.

If Redis stops responding the limiter lets requests through (and logs a warning)
instead of taking the whole site down.
"""
import logging
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import current_app, jsonify, request

log = logging.getLogger(__name__)


class MemoryBackend:
    """Sliding window kept in memory."""

    def __init__(self):
        self._hits: dict = defaultdict(deque)
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()

    def hit(self, key: str, limit: int, window: int):
        """Record a request. Returns None if allowed, or seconds to wait if blocked."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, int(window - (now - hits[0])))
            hits.append(now)
        return None


class RedisBackend:
    """Fixed window counters stored in Redis (INCR + EXPIRE)."""

    def __init__(self, client, prefix: str = "screener:rl:"):
        self.client = client
        self.prefix = prefix

    def hit(self, key: str, limit: int, window: int):
        now = time.time()
        bucket = int(now // window)
        redis_key = f"{self.prefix}{key}:{bucket}"
        try:
            pipe = self.client.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, window + 1)
            count = pipe.execute()[0]
        except Exception as exc:  # noqa: BLE001 - any Redis failure should fail open
            log.warning("Rate limiter could not reach Redis (%s); allowing request.", type(exc).__name__)
            return None
        if count > limit:
            return max(1, int(window - (now % window)))
        return None


MEMORY = MemoryBackend()


def reset() -> None:
    """Clear the in-memory counters (used by tests)."""
    MEMORY.clear()


def init_app(app) -> None:
    """Pick Redis if REDIS_URL is configured and reachable, otherwise memory."""
    url = app.config.get("REDIS_URL")
    if not url:
        return
    try:
        import redis

        client = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)
        client.ping()
    except Exception as exc:  # noqa: BLE001
        app.logger.warning("REDIS_URL is set but Redis is unavailable (%s). Using memory limits.", type(exc).__name__)
        return
    app.extensions["ratelimit_backend"] = RedisBackend(client)
    app.logger.info("Rate limiting is using Redis.")


def rate_limit(config_key: str = "RATELIMIT_DEFAULT"):
    """Limit a route using a (max_requests, window_seconds) tuple from app config."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_app.config.get("RATELIMIT_ENABLED", True):
                return view(*args, **kwargs)

            limit, window = current_app.config[config_key]
            backend = current_app.extensions.get("ratelimit_backend", MEMORY)
            retry_after = backend.hit(f"{request.remote_addr or 'unknown'}:{config_key}", limit, window)
            if retry_after is not None:
                response = jsonify({"error": f"Too many requests. Try again in {retry_after} seconds."})
                response.status_code = 429
                response.headers["Retry-After"] = str(retry_after)
                return response

            return view(*args, **kwargs)

        return wrapper

    return decorator
