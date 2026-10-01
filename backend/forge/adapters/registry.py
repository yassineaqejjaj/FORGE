"""Adapter registry: one :class:`~forge.domain.ports.AgentAdapter` per :class:`AdapterKind` (docs §5.2).

Adding a provider = implementing ``AgentAdapter`` and calling :func:`register_adapter` (or adding it
to :data:`_FACTORIES`). Adapters are stateless: a single instance per kind is shared.
"""

from __future__ import annotations

from collections.abc import Callable

from forge.adapters.anthropic import AnthropicAdapter
from forge.adapters.custom_api import CustomApiAdapter
from forge.adapters.mock import MockAdapter
from forge.adapters.nova import NovaAdapter
from forge.adapters.openai import OpenAIAdapter
from forge.domain.enums import AdapterKind
from forge.domain.ports import AgentAdapter

_FACTORIES: dict[AdapterKind, Callable[[], AgentAdapter]] = {
    AdapterKind.openai: OpenAIAdapter,
    AdapterKind.anthropic: AnthropicAdapter,
    AdapterKind.custom_api: CustomApiAdapter,
    AdapterKind.nova: NovaAdapter,
    AdapterKind.mock: MockAdapter,
}
_instances: dict[AdapterKind, AgentAdapter] = {}


class UnknownAdapterError(LookupError):
    """No adapter registered for the requested kind (message is user-facing)."""


def get_adapter(kind: AdapterKind | str) -> AgentAdapter:
    try:
        adapter_kind = AdapterKind(kind)
    except ValueError as exc:
        raise UnknownAdapterError(f"Type d'adapter inconnu : « {kind} »") from exc
    if adapter_kind not in _instances:
        factory = _FACTORIES.get(adapter_kind)
        if factory is None:
            raise UnknownAdapterError(f"Aucun adapter enregistré pour « {adapter_kind.value} »")
        _instances[adapter_kind] = factory()
    return _instances[adapter_kind]


def register_adapter(adapter: AgentAdapter) -> None:
    """Register (or replace) the adapter of ``adapter.kind`` — extensions and tests."""
    _instances[AdapterKind(adapter.kind)] = adapter


def reset_adapters() -> None:
    _instances.clear()
