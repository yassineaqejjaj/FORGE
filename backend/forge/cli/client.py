"""Minimal HTTP client of the FORGE public API used by the CLI (``FORGE_URL``, ``FORGE_API_KEY``)."""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_URL = "http://localhost:8100"
API_PREFIX = "/api/v1"
DEFAULT_TIMEOUT = 30.0


class CliError(Exception):
    """User-facing error (French message); exit code 2."""


class ForgeClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        url = (base_url or os.environ.get("FORGE_URL") or DEFAULT_URL).rstrip("/")
        key = api_key if api_key is not None else os.environ.get("FORGE_API_KEY", "")
        headers = {"Accept": "application/json", "User-Agent": "forge-cli"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        self.base_url = url
        self._client = httpx.Client(
            base_url=f"{url}{API_PREFIX}", headers=headers, timeout=timeout, transport=transport
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ForgeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise CliError(f"Délai dépassé en contactant FORGE ({self.base_url})") from exc
        except httpx.HTTPError as exc:
            raise CliError(f"FORGE injoignable ({self.base_url}) : {exc}") from exc
        if response.status_code >= 400:
            raise CliError(_error_message(response))
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise CliError(f"Réponse invalide de FORGE (HTTP {response.status_code})") from exc

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None})

    def post(self, path: str, json: Any = None) -> Any:
        return self.request("POST", path, json=json)


def _error_message(response: httpx.Response) -> str:
    detail: str | None = None
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = body.get("detail") if isinstance(body.get("detail"), str) else None
    except ValueError:
        pass
    if response.status_code == 401:
        hint = " — définissez FORGE_API_KEY (clé fgk_…)"
        return f"Authentification refusée : {detail or 'clé absente ou invalide'}{hint}"
    if response.status_code == 403:
        return f"Accès refusé : {detail or 'rôle insuffisant'}"
    return f"Erreur FORGE (HTTP {response.status_code}) : {detail or response.reason_phrase}"
