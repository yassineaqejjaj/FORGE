"""HTTP plumbing shared by the LLM clients: errors, retries with exponential backoff.

Retried: HTTP 408/409/425/429, 5xx (incl. Anthropic 529 « overloaded »), timeouts and transport
errors, up to ``max_retries`` extra attempts (``FORGE_JUDGE_MAX_RETRIES``), honouring
``Retry-After`` (capped). Secrets (API keys, headers) are never logged nor put in error messages.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("forge.llm")

RETRY_STATUSES = frozenset({408, 409, 425, 429})
MAX_RETRY_AFTER_SECONDS = 30.0
MAX_ERROR_DETAIL = 500

#: Patched in tests to avoid real waits.
sleep = asyncio.sleep


class LLMError(Exception):
    """Failure of an LLM call (message safe to show: no secret)."""

    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class LLMHTTPError(LLMError):
    def __init__(self, message: str, *, status_code: int, body: Any = None, retryable: bool = False) -> None:
        super().__init__(message, status_code=status_code, retryable=retryable)
        self.body = body


class LLMTimeoutError(LLMError):
    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class LLMRefusalError(LLMError):
    """The model declined to answer (safety refusal): retrying the same request is pointless."""


class LLMResponseError(LLMError):
    """Unexpected response shape."""


def host_of(url: str) -> str:
    return urlsplit(url).netloc or url


def error_detail(body: Any) -> str:
    """Provider error message (``{"error": {"message": …}}``) truncated."""
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("type") or ""
            return str(message)[:MAX_ERROR_DETAIL]
        if isinstance(error, str):
            return error[:MAX_ERROR_DETAIL]
        if body.get("message"):
            return str(body["message"])[:MAX_ERROR_DETAIL]
    if isinstance(body, str):
        return body[:MAX_ERROR_DETAIL]
    return ""


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, min(MAX_RETRY_AFTER_SECONDS, float(value)))
    except ValueError:
        return None


def backoff(attempt: int, base_delay: float) -> float:
    if base_delay <= 0:
        return 0.0
    return min(MAX_RETRY_AFTER_SECONDS, base_delay * (2**attempt)) * random.uniform(0.8, 1.2)


def _parse_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


async def post_json(
    url: str,
    *,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float,
    max_retries: int,
    base_delay: float = 1.0,
    provider: str = "llm",
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[dict[str, Any], float]:
    """POST ``payload`` and return ``(json body, latency ms of the successful attempt)``.

    Raises :class:`LLMHTTPError` (non-retryable status or retries exhausted) or
    :class:`LLMTimeoutError`.
    """
    attempt = 0
    host = host_of(url)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds), transport=transport) as client:
        while True:
            started = time.perf_counter()
            try:
                response = await client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                if attempt >= max_retries:
                    raise LLMTimeoutError(
                        f"{provider} : délai dépassé après {attempt + 1} tentative(s) ({host})"
                    ) from exc
                delay = backoff(attempt, base_delay)
                logger.warning(
                    "%s call to %s timed out (attempt %d), retrying in %.1fs",
                    provider,
                    host,
                    attempt + 1,
                    delay,
                )
            except httpx.TransportError as exc:
                if attempt >= max_retries:
                    raise LLMError(
                        f"{provider} : connexion impossible à {host} ({type(exc).__name__})", retryable=True
                    ) from exc
                delay = backoff(attempt, base_delay)
                logger.warning(
                    "%s transport error to %s (%s), retrying in %.1fs",
                    provider,
                    host,
                    type(exc).__name__,
                    delay,
                )
            else:
                latency_ms = (time.perf_counter() - started) * 1000
                status = response.status_code
                if 200 <= status < 300:
                    body = _parse_body(response)
                    if not isinstance(body, dict):
                        raise LLMResponseError(f"{provider} : réponse non JSON ({host})")
                    return body, latency_ms
                body = _parse_body(response)
                retryable = status in RETRY_STATUSES or status >= 500
                detail = error_detail(body)
                if not retryable or attempt >= max_retries:
                    suffix = f" après {attempt + 1} tentative(s)" if retryable else ""
                    raise LLMHTTPError(
                        f"{provider} : erreur HTTP {status}{suffix}{' — ' + detail if detail else ''}",
                        status_code=status,
                        body=body,
                        retryable=retryable,
                    )
                retry_after = _retry_after(response)
                delay = retry_after if retry_after is not None else backoff(attempt, base_delay)
                logger.warning(
                    "%s HTTP %d from %s (attempt %d), retrying in %.1fs",
                    provider,
                    status,
                    host,
                    attempt + 1,
                    delay,
                )
            attempt += 1
            await sleep(delay)
