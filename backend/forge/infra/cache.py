"""Valkey (Redis protocol) helpers: distributed concurrency limits and sliding-window rate limits.

FORGE keeps working when Valkey is down: limits degrade to per-process limits (logged once).

* :func:`concurrency_slot` — at most ``limit`` concurrent holders of ``key`` across all workers
  (sorted-set semaphore with expiry, so a crashed worker never leaks a slot for long);
* :func:`throttle` — sliding window of ``limit`` acquisitions per ``window`` seconds;
* :func:`hit` — counter for abuse protection (login attempts).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator

import redis.asyncio as redis
from redis.exceptions import RedisError

from forge.config import settings

logger = logging.getLogger("forge.cache")

_client: redis.Redis | None = None
_degraded_logged = False
_local_semaphores: dict[tuple[str, int], asyncio.Semaphore] = {}
_local_windows: dict[str, deque[float]] = defaultdict(deque)
_local_counters: dict[str, tuple[int, float]] = {}

KEY_PREFIX = "forge:"


class RateLimitExceeded(Exception):
    """Raised when a slot could not be obtained within ``max_wait`` seconds."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def get_valkey() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.valkey_url, decode_responses=True, socket_timeout=3)
    return _client


async def close_valkey() -> None:
    global _client
    if _client is not None:
        with contextlib.suppress(Exception):
            await _client.aclose()
    _client = None


def _degraded(exc: Exception) -> None:
    global _degraded_logged
    if not _degraded_logged:
        logger.warning("Valkey unavailable (%s): limits degrade to per-process limits", exc)
        _degraded_logged = True


@contextlib.asynccontextmanager
async def concurrency_slot(
    key: str, limit: int, *, ttl_seconds: float = 900.0, max_wait: float = 600.0
) -> AsyncIterator[None]:
    """Hold one of ``limit`` distributed slots for ``key`` while the block runs."""
    if limit <= 0:
        yield
        return
    zkey = f"{KEY_PREFIX}sem:{key}"
    token = uuid.uuid4().hex
    deadline = time.monotonic() + max_wait
    client = get_valkey()
    acquired_remote = False
    try:
        while True:
            now = time.time()
            async with client.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(zkey, "-inf", now - ttl_seconds)
                pipe.zadd(zkey, {token: now})
                pipe.zrank(zkey, token)
                pipe.expire(zkey, int(ttl_seconds) + 60)
                _, _, rank, _ = await pipe.execute()
            if rank is not None and rank < limit:
                acquired_remote = True
                break
            await client.zrem(zkey, token)
            if time.monotonic() > deadline:
                raise RateLimitExceeded(f"Concurrence maximale atteinte pour {key}", retry_after=5.0)
            await asyncio.sleep(0.25 + 0.25 * (hash(token) % 4) / 4)
    except RedisError as exc:
        _degraded(exc)
        semaphore = _local_semaphores.setdefault((key, limit), asyncio.Semaphore(limit))
        async with semaphore:
            yield
        return
    try:
        yield
    finally:
        if acquired_remote:
            with contextlib.suppress(RedisError):
                await client.zrem(zkey, token)


async def throttle(key: str, limit: int, *, window_seconds: float = 60.0, max_wait: float = 120.0) -> None:
    """Wait until an acquisition of ``key`` fits in the sliding window (``limit`` per window)."""
    if limit <= 0:
        return
    deadline = time.monotonic() + max_wait
    zkey = f"{KEY_PREFIX}rl:{key}"
    while True:
        try:
            wait = await _throttle_remote(zkey, limit, window_seconds)
        except RedisError as exc:
            _degraded(exc)
            wait = _throttle_local(key, limit, window_seconds)
        if wait <= 0:
            return
        if time.monotonic() + wait > deadline:
            raise RateLimitExceeded(f"Limite de débit atteinte pour {key}", retry_after=wait)
        await asyncio.sleep(min(wait, 5.0))


async def _throttle_remote(zkey: str, limit: int, window: float) -> float:
    client = get_valkey()
    now = time.time()
    token = f"{now:.6f}:{uuid.uuid4().hex[:6]}"
    async with client.pipeline(transaction=True) as pipe:
        pipe.zremrangebyscore(zkey, "-inf", now - window)
        pipe.zcard(zkey)
        _, count = await pipe.execute()
    if count < limit:
        await client.zadd(zkey, {token: now})
        await client.expire(zkey, int(window) + 5)
        return 0.0
    oldest = await client.zrange(zkey, 0, 0, withscores=True)
    if not oldest:
        return 0.1
    return max(0.05, float(oldest[0][1]) + window - now)


def _throttle_local(key: str, limit: int, window: float) -> float:
    now = time.monotonic()
    q = _local_windows[key]
    while q and q[0] <= now - window:
        q.popleft()
    if len(q) < limit:
        q.append(now)
        return 0.0
    return max(0.05, q[0] + window - now)


async def hit(key: str, limit: int, *, window_seconds: int = 60) -> bool:
    """Count one hit on ``key``; ``False`` when the limit is exceeded within the window."""
    rkey = f"{KEY_PREFIX}hit:{key}"
    try:
        client = get_valkey()
        async with client.pipeline(transaction=True) as pipe:
            pipe.incr(rkey)
            pipe.expire(rkey, window_seconds, nx=True)
            count, _ = await pipe.execute()
        return int(count) <= limit
    except RedisError as exc:
        _degraded(exc)
        now = time.monotonic()
        count, started = _local_counters.get(key, (0, now))
        if now - started > window_seconds:
            count, started = 0, now
        count += 1
        _local_counters[key] = (count, started)
        return count <= limit


async def ping() -> None:
    await get_valkey().ping()
