"""Typed (de)serialisation of domain dataclasses (manifests, JSONB columns).

``from_dict(ScenarioSpec, data)`` rebuilds nested dataclasses, enums, lists and dicts from JSON using
the type hints. Unknown keys are ignored (forward compatibility of stored manifests); missing keys
take the dataclass defaults.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from datetime import datetime
from enum import Enum
from functools import cache
from typing import Any, TypeVar, get_args, get_origin

from forge.domain import types as domain_types

T = TypeVar("T")


@cache
def _hints(cls: type) -> dict[str, Any]:
    return typing.get_type_hints(cls, vars(domain_types))


def _convert(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in get_args(tp) if a is not type(None)]
        for arg in args:
            try:
                return _convert(arg, value)
            except (TypeError, ValueError, KeyError):
                continue
        return value
    if origin in (list, typing.List, tuple, set, frozenset):  # noqa: UP006
        (item_tp, *_) = get_args(tp) or (Any,)
        return [_convert(item_tp, v) for v in value]
    if origin in (dict, typing.Dict):  # noqa: UP006
        key_tp, val_tp = get_args(tp) or (Any, Any)
        return {_convert(key_tp, k): _convert(val_tp, v) for k, v in dict(value).items()}
    if tp is Any or tp is typing.Any:
        return value
    if isinstance(tp, type):
        if dataclasses.is_dataclass(tp):
            if isinstance(value, tp):
                return value
            if not isinstance(value, dict):
                raise TypeError(f"{tp.__name__} attendu")
            return from_dict(tp, value)
        if issubclass(tp, Enum):
            return tp(value)
        if tp is datetime and isinstance(value, str):
            return datetime.fromisoformat(value)
        if tp is float and isinstance(value, int | float):
            return float(value)
        if tp is int and isinstance(value, int | float) and not isinstance(value, bool):
            return int(value)
        if tp is str and not isinstance(value, str):
            return str(value)
    return value


def from_dict[T](cls: type[T], data: dict[str, Any] | None) -> T:
    """Build dataclass ``cls`` from a JSON-like dict."""
    if data is None:
        data = {}
    hints = _hints(cls)  # type: ignore[arg-type]
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):  # type: ignore[arg-type]
        if f.name not in data or not f.init:
            continue
        kwargs[f.name] = _convert(hints.get(f.name, Any), data[f.name])
    return cls(**kwargs)


def list_from_dicts[T](cls: type[T], items: list[dict[str, Any]] | None) -> list[T]:
    return [from_dict(cls, item) for item in (items or [])]
