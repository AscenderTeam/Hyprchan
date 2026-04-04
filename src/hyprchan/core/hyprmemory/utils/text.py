from __future__ import annotations

import re
from collections import Counter
from typing import Iterable


_TOKEN_RE = re.compile(r"[A-Za-z0-9_']+")


def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def lexical_similarity(a: str, b: str) -> float:
    tokens_a = tokenize(a)
    tokens_b = tokenize(b)
    if not tokens_a or not tokens_b:
        return 0.0
    counter_a = Counter(tokens_a)
    counter_b = Counter(tokens_b)
    intersection = sum((counter_a & counter_b).values())
    union = sum((counter_a | counter_b).values())
    if union == 0:
        return 0.0
    return intersection / union


def join_nonempty(parts: Iterable[str], *, sep: str = " ") -> str:
    return sep.join(part for part in parts if part)
