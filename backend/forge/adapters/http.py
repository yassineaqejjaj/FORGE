"""HTTP plumbing shared by the adapters and the context providers.

* :func:`create_client` builds the ``httpx.AsyncClient`` used for every outgoing call; tests (and
  the embedded demo agents) can route calls through another transport with :func:`use_transport`.
* :func:`raise_for_agent_status` / :func:`transport_error` translate HTTP failures into
  ``AgentExecutionError`` with the protocol semantics: 4xx permanent, 408/425/429/5xx retryable,
  connection errors retryable. Messages are French and never contain secrets.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from typing import Any

import httpx

from forge.domain.enums import BuiltinErrorType
from forge.domain.types import AgentExecutionError

RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
ERROR_EXCERPT_CHARS = 300
USER_AGENT = "forge-runner/1.0"

_transport: httpx.AsyncBaseTransport | None = None


def create_client(*, timeout: float, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
    """Client with a total ``timeout`` (seconds). Redirects are not followed (credentials safety)."""
    return httpx.AsyncClient(
        transport=_transport,
        timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
        headers={"User-Agent": USER_AGENT, **(headers or {})},
        follow_redirects=False,
    )


@contextlib.contextmanager
def use_transport(transport: httpx.AsyncBaseTransport | None) -> Iterator[None]:
    """Route every client created in the block through ``transport`` (tests, embedded demo agents)."""
    global _transport
    previous = _transport
    _transport = transport
    try:
        yield
    finally:
        _transport = previous


def error_excerpt(response: httpx.Response) -> str:
    """Short, single-line description of an error body (provider ``error.message`` when present)."""
    try:
        data = response.json()
    except ValueError:
        text = response.text
    else:
        text = _error_message(data) or json.dumps(data, ensure_ascii=False)[:ERROR_EXCERPT_CHARS]
    flat = " ".join(str(text).split())
    return flat[:ERROR_EXCERPT_CHARS]


def _error_message(data: Any) -> str | None:
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("type") or "") or None
        if isinstance(error, str):
            return error
        for key in ("detail", "message"):
            if isinstance(data.get(key), str):
                return str(data[key])
    return None


def raise_for_agent_status(response: httpx.Response, *, target: str) -> None:
    """Raise ``AgentExecutionError`` for non-2xx responses (``target`` = « L'agent », « OpenAI »…)."""
    if response.is_success:
        return
    status = response.status_code
    excerpt = error_excerpt(response)
    suffix = f" : {excerpt}" if excerpt else ""
    if status in (401, 403):
        message = f"{target} a refusé l'authentification (HTTP {status}) — vérifiez l'identifiant{suffix}"
    elif status == 404:
        message = f"{target} est introuvable à cette adresse (HTTP 404){suffix}"
    elif status == 429:
        message = f"{target} limite le débit (HTTP 429){suffix}"
    else:
        message = f"{target} a répondu HTTP {status}{suffix}"
    raise AgentExecutionError(
        message, error_type=BuiltinErrorType.EXECUTION_ERROR, retryable=status in RETRYABLE_STATUSES
    )


def transport_error(exc: httpx.HTTPError, *, target: str) -> AgentExecutionError:
    """Connection / protocol errors → retryable ``AgentExecutionError`` (timeouts → ``TIMEOUT``)."""
    if isinstance(exc, httpx.TimeoutException):
        return AgentExecutionError(
            f"{target} n'a pas répondu dans le délai imparti", error_type=BuiltinErrorType.TIMEOUT
        )
    if isinstance(exc, httpx.ConnectError | httpx.RemoteProtocolError | httpx.ReadError | httpx.WriteError):
        return AgentExecutionError(
            f"{target} est injoignable ({type(exc).__name__})",
            error_type=BuiltinErrorType.EXECUTION_ERROR,
            retryable=True,
        )
    return AgentExecutionError(
        f"Erreur réseau lors de l'appel à {target.lower()} ({type(exc).__name__})",
        error_type=BuiltinErrorType.EXECUTION_ERROR,
        retryable=True,
    )


def json_body(response: httpx.Response, *, target: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise AgentExecutionError(
            f"{target} a renvoyé une réponse qui n'est pas du JSON valide",
            error_type=BuiltinErrorType.EXECUTION_ERROR,
        ) from exc


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    target: str,
    json_payload: Any = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[Any, httpx.Response]:
    """Send a request and return ``(decoded JSON, response)`` or raise ``AgentExecutionError``."""
    try:
        response = await client.request(method, url, json=json_payload, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise transport_error(exc, target=target) from exc
    raise_for_agent_status(response, target=target)
    return json_body(response, target=target), response
