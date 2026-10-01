"""Restricted expression interpreter (custom aggregation): allowed constructs and refusals."""

from __future__ import annotations

import pytest

from forge.domain.judges.safe_expr import ExpressionError, compile_expression, evaluate_expression

VARS = {"scores": [0.2, 0.6, 1.0], "weights": [1.0, 2.0, 1.0], "confidences": [0.5, 0.9, 0.7]}


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("mean(scores)", 0.6),
        ("median(scores)", 0.6),
        ("min(scores) + max(scores)", 1.2),
        ("sum(scores) / len(scores)", 0.6),
        ("abs(-0.5)", 0.5),
        ("scores[0] * 2", 0.4),
        ("mean(scores[1:])", 0.8),
        ("sum([s * w for s, w in []]) if False else 1", 1),
    ],
)
def test_allowed_expressions(expression: str, expected: float) -> None:
    if "for" in expression:
        with pytest.raises(ExpressionError):
            compile_expression(expression)
        return
    assert evaluate_expression(expression, VARS) == pytest.approx(expected)


def test_conditionals_comparisons_and_bool_ops() -> None:
    assert (
        evaluate_expression("min(scores) if max(scores) - min(scores) > 0.5 else mean(scores)", VARS) == 0.2
    )
    assert evaluate_expression("1 if 0 < scores[1] <= 0.6 and not False else 0", VARS) == 1
    assert evaluate_expression("clamp(1.7)", VARS) == 1.0
    assert evaluate_expression("round(0.456, 2)", VARS) == pytest.approx(0.46)
    assert evaluate_expression("2 ** 3", VARS) == 8


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "scores.__class__",
        "open('/etc/passwd')",
        "eval('1')",
        "(lambda x: x)(1)",
        "[x for x in scores]",
        "mean(scores, key=1)",
        "'texte'",
        "unknown_var + 1",
        "_private",
        "mean(*scores)",
        "2 ** 1000",
        "",
        "x" * 2000,
    ],
)
def test_forbidden_or_invalid(expression: str) -> None:
    with pytest.raises(ExpressionError):
        evaluate_expression(expression, VARS, allowed_names=("scores", "weights", "confidences"))


def test_runtime_errors_are_expression_errors() -> None:
    with pytest.raises(ExpressionError):
        evaluate_expression("1 / 0", VARS)
    with pytest.raises(ExpressionError):
        evaluate_expression("scores[10]", VARS)
    with pytest.raises(ExpressionError):
        evaluate_expression("scores * 2", VARS)
    with pytest.raises(ExpressionError):
        evaluate_expression("mean([])", VARS)


def test_compiled_expression_is_reusable() -> None:
    compiled = compile_expression("mean(scores) * (1 - (max(scores) - min(scores)) / 2)")
    assert compiled.evaluate(VARS) == pytest.approx(0.6 * 0.6)
    assert compiled.evaluate({**VARS, "scores": [1.0, 1.0]}) == 1.0
    assert {"scores"} <= compiled.names
