"""Restricted expression interpreter for ``custom`` multi-judge aggregation (docs §7.4).

The expression is parsed with :mod:`ast` and **interpreted** node by node — never passed to
``eval``/``exec``/``compile``. Only a whitelist of nodes is accepted:

* numbers, booleans, lists/tuples, variables (``scores``, ``weights``, ``confidences`` and any name
  explicitly provided), subscripts ``scores[0]`` / slices ``scores[1:]``;
* arithmetic ``+ - * / // % **`` (bounded exponent), unary ``- + not``;
* comparisons (``< <= > >= == !=``, chained), ``and`` / ``or``, ``x if cond else y``;
* calls to ``mean``, ``median``, ``min``, ``max``, ``abs``, ``len``, ``sum``, ``round``, ``clamp``
  (positional arguments only).

Attribute access, comprehensions, lambdas, keyword arguments, strings and any other construct are
rejected at compile time with a French message (:class:`ExpressionError`).
"""

from __future__ import annotations

import ast
import math
import operator
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MAX_EXPRESSION_LENGTH = 1000
MAX_DEPTH = 40
MAX_EXPONENT = 16
MAX_SEQUENCE = 10_000

AGGREGATION_VARIABLES = ("scores", "weights", "confidences")


class ExpressionError(ValueError):
    """Invalid or unsafe expression / evaluation failure (French message)."""


def _as_list(value: Any) -> list[float]:
    if isinstance(value, list | tuple):
        return [float(v) for v in value]
    return [float(value)]


def _flatten(args: Sequence[Any]) -> list[float]:
    if len(args) == 1 and isinstance(args[0], list | tuple):
        return _as_list(args[0])
    return [float(a) for a in args]


def _mean(*args: Any) -> float:
    values = _flatten(args)
    if not values:
        raise ExpressionError("mean() d'une liste vide")
    return math.fsum(values) / len(values)


def _median(*args: Any) -> float:
    values = _flatten(args)
    if not values:
        raise ExpressionError("median() d'une liste vide")
    return float(statistics.median(values))


def _min(*args: Any) -> float:
    values = _flatten(args)
    if not values:
        raise ExpressionError("min() d'une liste vide")
    return min(values)


def _max(*args: Any) -> float:
    values = _flatten(args)
    if not values:
        raise ExpressionError("max() d'une liste vide")
    return max(values)


def _sum(*args: Any) -> float:
    return math.fsum(_flatten(args))


def _len(value: Any) -> int:
    if not isinstance(value, list | tuple):
        raise ExpressionError("len() attend une liste")
    return len(value)


def _abs(value: Any) -> float:
    return abs(float(value))


def _round(value: Any, digits: Any = 0) -> float:
    return round(float(value), int(digits))


def _clamp(value: Any, low: Any = 0.0, high: Any = 1.0) -> float:
    return max(float(low), min(float(high), float(value)))


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "mean": _mean,
    "median": _median,
    "min": _min,
    "max": _max,
    "abs": _abs,
    "len": _len,
    "sum": _sum,
    "round": _round,
    "clamp": _clamp,
}


def _safe_pow(base: Any, exponent: Any) -> float:
    if abs(float(exponent)) > MAX_EXPONENT:
        raise ExpressionError(f"exposant trop grand (maximum {MAX_EXPONENT})")
    return float(base) ** float(exponent)


def _safe_div(left: Any, right: Any) -> float:
    if float(right) == 0:
        raise ExpressionError("division par zéro")
    return float(left) / float(right)


def _safe_floordiv(left: Any, right: Any) -> float:
    if float(right) == 0:
        raise ExpressionError("division par zéro")
    return float(left) // float(right)


def _safe_mod(left: Any, right: Any) -> float:
    if float(right) == 0:
        raise ExpressionError("division par zéro")
    return float(left) % float(right)


def _add(left: Any, right: Any) -> Any:
    if isinstance(left, list | tuple) or isinstance(right, list | tuple):
        if not (isinstance(left, list | tuple) and isinstance(right, list | tuple)):
            raise ExpressionError("addition d'une liste et d'un nombre")
        if len(left) + len(right) > MAX_SEQUENCE:
            raise ExpressionError("liste trop longue")
        return [*left, *right]
    return float(left) + float(right)


def _numeric(fn: Callable[[float, float], Any]) -> Callable[[Any, Any], Any]:
    def wrapper(left: Any, right: Any) -> Any:
        if isinstance(left, list | tuple) or isinstance(right, list | tuple):
            raise ExpressionError("opération arithmétique sur une liste (utilisez mean, sum…)")
        return fn(float(left), float(right))

    return wrapper


_BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: _add,
    ast.Sub: _numeric(operator.sub),
    ast.Mult: _numeric(operator.mul),
    ast.Div: _numeric(_safe_div),
    ast.FloorDiv: _numeric(_safe_floordiv),
    ast.Mod: _numeric(_safe_mod),
    ast.Pow: _numeric(_safe_pow),
}
_CMP_OPS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}
_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Subscript,
    ast.Slice,
    ast.And,
    ast.Or,
    ast.Not,
    ast.USub,
    ast.UAdd,
    *_BIN_OPS.keys(),
    *_CMP_OPS.keys(),
)


@dataclass(frozen=True, slots=True)
class CompiledExpression:
    source: str
    tree: ast.Expression
    names: frozenset[str]

    def evaluate(self, variables: Mapping[str, Any]) -> Any:
        missing = [n for n in self.names if n not in variables and n not in FUNCTIONS]
        if missing:
            raise ExpressionError(f"variable(s) inconnue(s) : {', '.join(sorted(missing))}")
        try:
            return _Interpreter(variables).visit(self.tree.body)
        except ExpressionError:
            raise
        except (TypeError, ValueError, IndexError, OverflowError, ZeroDivisionError) as exc:
            raise ExpressionError(f"évaluation impossible ({exc})") from exc


def _depth(node: ast.AST, level: int = 0) -> int:
    children = list(ast.iter_child_nodes(node))
    if not children:
        return level
    return max(_depth(child, level + 1) for child in children)


def compile_expression(
    source: str, *, allowed_names: Sequence[str] = AGGREGATION_VARIABLES
) -> CompiledExpression:
    """Parse and validate ``source``. Raises :class:`ExpressionError` on any forbidden construct."""
    text = (source or "").strip()
    if not text:
        raise ExpressionError("expression vide")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError(f"expression trop longue (maximum {MAX_EXPRESSION_LENGTH} caractères)")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"syntaxe invalide ({exc.msg}, colonne {exc.offset})") from exc
    if _depth(tree) > MAX_DEPTH:
        raise ExpressionError("expression trop imbriquée")
    names: set[str] = set()
    allowed = set(allowed_names)
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(f"construction non autorisée : {type(node).__name__}")
        if isinstance(node, ast.Constant) and (
            isinstance(node.value, str | bytes | complex) or node.value is None or node.value is Ellipsis
        ):
            raise ExpressionError("seuls les nombres et booléens sont autorisés comme constantes")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                raise ExpressionError(f"fonction non autorisée (autorisées : {', '.join(sorted(FUNCTIONS))})")
            if node.keywords:
                raise ExpressionError("arguments nommés non autorisés")
            if any(isinstance(arg, ast.Starred) for arg in node.args):
                raise ExpressionError("arguments étoilés non autorisés")
        if isinstance(node, ast.Name):
            if node.id.startswith("_"):
                raise ExpressionError(f"nom non autorisé : {node.id}")
            is_function_ref = node.id in FUNCTIONS
            if not is_function_ref and node.id not in allowed:
                raise ExpressionError(
                    f"variable inconnue « {node.id} » (disponibles : {', '.join(sorted(allowed))})"
                )
            names.add(node.id)
    return CompiledExpression(text, tree, frozenset(names))


def evaluate_expression(
    source: str | CompiledExpression,
    variables: Mapping[str, Any],
    *,
    allowed_names: Sequence[str] | None = None,
) -> Any:
    compiled = (
        source
        if isinstance(source, CompiledExpression)
        else compile_expression(source, allowed_names=allowed_names or tuple(variables))
    )
    return compiled.evaluate(variables)


class _Interpreter:
    def __init__(self, variables: Mapping[str, Any]) -> None:
        self.variables = variables

    def visit(self, node: ast.AST) -> Any:
        method = getattr(self, f"visit_{type(node).__name__}", None)
        if method is None:  # pragma: no cover - rejected at compile time
            raise ExpressionError(f"construction non autorisée : {type(node).__name__}")
        return method(node)

    def visit_Constant(self, node: ast.Constant) -> Any:
        return node.value

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id in self.variables:
            value = self.variables[node.id]
            if isinstance(value, list | tuple) and len(value) > MAX_SEQUENCE:
                raise ExpressionError("liste trop longue")
            return list(value) if isinstance(value, tuple) else value
        raise ExpressionError(f"« {node.id} » n'est pas une valeur")

    def visit_List(self, node: ast.List) -> list[Any]:
        return [self.visit(e) for e in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> list[Any]:
        return [self.visit(e) for e in node.elts]

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        return _BIN_OPS[type(node.op)](self.visit(node.left), self.visit(node.right))

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        value = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not value
        if isinstance(value, list | tuple):
            raise ExpressionError("opérateur unaire sur une liste")
        return -float(value) if isinstance(node.op, ast.USub) else float(value)

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        if isinstance(node.op, ast.And):
            result: Any = True
            for value in node.values:
                result = self.visit(value)
                if not result:
                    return result
            return result
        result = False
        for value in node.values:
            result = self.visit(value)
            if result:
                return result
        return result

    def visit_Compare(self, node: ast.Compare) -> bool:
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = self.visit(comparator)
            if not _CMP_OPS[type(op)](left, right):
                return False
            left = right
        return True

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        return self.visit(node.body) if self.visit(node.test) else self.visit(node.orelse)

    def visit_Call(self, node: ast.Call) -> Any:
        assert isinstance(node.func, ast.Name)
        return FUNCTIONS[node.func.id](*[self.visit(a) for a in node.args])

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        target = self.visit(node.value)
        if not isinstance(target, list | tuple):
            raise ExpressionError("indexation d'une valeur qui n'est pas une liste")
        if isinstance(node.slice, ast.Slice):
            lower = None if node.slice.lower is None else int(self.visit(node.slice.lower))
            upper = None if node.slice.upper is None else int(self.visit(node.slice.upper))
            if node.slice.step is not None:
                raise ExpressionError("pas de découpage non autorisé")
            return list(target[lower:upper])
        index = self.visit(node.slice)
        if isinstance(index, bool) or not float(index).is_integer():
            raise ExpressionError("index entier attendu")
        try:
            return target[int(index)]
        except IndexError as exc:
            raise ExpressionError(f"index {int(index)} hors limites (taille {len(target)})") from exc
