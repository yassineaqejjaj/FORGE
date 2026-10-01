"""Text helpers shared by rules, the heuristic judge and prompt rendering (pure, deterministic)."""

from __future__ import annotations

import re
import unicodedata

_WORD = re.compile(r"[\w'’-]+", re.UNICODE)
_SPACES = re.compile(r"\s+")

#: French + English stop words ignored by keyword overlap measures.
_STOP_WORDS_TEXT = """
    a au aux avec ce ces cet cette dans de des du elle en et est etre il ils je la le les leur lui
    mais me meme mes mon ne nos notre nous on ou par pas pour qu que qui sa se ses son sont sur ta te
    tes ton tu un une vos votre vous y d l s c n j m qu été être fait faire plus moins tout tous toute
    toutes afin ainsi alors aussi autre autres avoir bien car cela celui comme dont donc elles encore
    entre ici leurs lors puis sans selon si sous tres très vers via chaque doit doivent peut peuvent
    the of and or to in on for with is are be by as at an this that it from not no
"""
STOP_WORDS: frozenset[str] = frozenset(_STOP_WORDS_TEXT.split())


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(text: str | None) -> str:
    """Lower-case, accent-free, single-spaced text (used for case/accent-insensitive matching)."""
    return _SPACES.sub(" ", strip_accents(str(text or "")).casefold()).strip()


def words(text: str | None) -> list[str]:
    return _WORD.findall(str(text or ""))


def word_count(text: str | None) -> int:
    return len(words(text))


def keywords(text: str | None, *, min_length: int = 4) -> list[str]:
    """Distinct significant words (normalised, no stop words), in order of first appearance."""
    seen: dict[str, None] = {}
    for word in words(normalize(text)):
        token = word.strip("'’-")
        if len(token) < min_length or token in STOP_WORDS:
            continue
        seen.setdefault(token, None)
    return list(seen)


def excerpt(text: str, start: int, end: int, *, context: int = 40, max_length: int = 240) -> str:
    """Snippet of ``text`` around ``[start, end)`` with ellipses (single line)."""
    lo = max(0, start - context)
    hi = min(len(text), end + context)
    snippet = _SPACES.sub(" ", text[lo:hi]).strip()
    if len(snippet) > max_length:
        snippet = snippet[: max_length - 1] + "…"
    return f"{'…' if lo > 0 else ''}{snippet}{'…' if hi < len(text) else ''}"


def truncate(text: str | None, limit: int) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"


def one_line(text: str | None, limit: int = 200) -> str:
    return truncate(_SPACES.sub(" ", str(text or "")).strip(), limit)


def fr_number(value: float, digits: int = 2) -> str:
    """French decimal formatting: ``0.8234`` → ``0,82``."""
    return f"{value:.{digits}f}".replace(".", ",")


def fr_percent(value: float, digits: int = 0) -> str:
    return f"{value * 100:.{digits}f} %".replace(".", ",")


def find_normalized(haystack_norm: str, needle: str) -> int:
    """Index of the normalised ``needle`` in an already normalised haystack (``-1`` if absent)."""
    target = normalize(needle)
    if not target:
        return -1
    return haystack_norm.find(target)
