"""Bounded, local lexical similarity. No models or external services."""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz.fuzz import ratio

MAX_SIMILARITY_CHARACTERS = 100_000


def prepare_prompt(text: str) -> tuple[str, bool]:
    sampled = len(text) > MAX_SIMILARITY_CHARACTERS
    if sampled:
        width = MAX_SIMILARITY_CHARACTERS // 3
        middle = len(text) // 2
        text = (
            text[:width]
            + "\n"
            + text[middle - width // 2 : middle + width // 2]
            + "\n"
            + text[-width:]
        )
    return re.sub(
        r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()
    ).strip(), sampled


def text_similarity(
    prepared_source: str, prepared_candidate: str, minimum: float
) -> float:
    if not prepared_source or not prepared_candidate:
        return 0.0
    return ratio(prepared_source, prepared_candidate, score_cutoff=minimum * 100) / 100
