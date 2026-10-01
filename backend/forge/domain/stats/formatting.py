"""French presentation of statistics (decimal comma, explicit sign, percentages)."""

from __future__ import annotations

import math


def fr_number(value: float | None, digits: int = 1, *, signed: bool = False) -> str:
    """``1234.5`` → ``"1 234,5"``; ``signed=True`` → ``"+1,2"`` / ``"−1,2"``; ``None`` → ``"—"``."""
    if value is None or not math.isfinite(value):
        return "—"
    rounded = round(float(value), digits)
    if rounded == 0:
        rounded = 0.0  # avoid "-0,0"
    text = f"{abs(rounded):,.{digits}f}".replace(",", " ").replace(".", ",")
    if rounded < 0:
        return f"−{text}"
    return f"+{text}" if signed and rounded > 0 else text


def fr_percent(ratio: float | None, digits: int = 0, *, signed: bool = False) -> str:
    """Ratio (0.123) → ``"12 %"``."""
    if ratio is None or not math.isfinite(ratio):
        return "—"
    return f"{fr_number(ratio * 100, digits, signed=signed)} %"


def fr_p_value(p: float | None) -> str:
    if p is None or not math.isfinite(p):
        return "p non calculable"
    if p < 0.001:
        return "p < 0,001"
    return f"p = {fr_number(p, 3)}"


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    word = singular if abs(count) <= 1 else (plural_form or f"{singular}s")
    return f"{count} {word}"
