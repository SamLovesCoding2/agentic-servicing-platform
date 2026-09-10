"""
Deterministic output filter.

Rewrites customer-facing text in code, not via prompts.
- Word-boundary-aware (doesn't rewrite inside other words)
- Case-preserving (Loan → Contract, LOAN → CONTRACT, loan → contract)
- Streaming-safe (works on partial text chunks)
- Configurable replacement map
"""

from __future__ import annotations

import re
from typing import Callable


def _preserve_case(original: str, replacement: str) -> str:
    """Preserve the case pattern of the original word in the replacement."""
    if original.isupper():
        return replacement.upper()
    elif original[0].isupper() and original[1:].islower():
        return replacement[0].upper() + replacement[1:].lower()
    elif original.islower():
        return replacement.lower()
    else:
        # Mixed case — just use replacement as-is
        return replacement


def make_filter(replacements: dict[str, str]) -> Callable:
    """
    Create a streaming-safe output filter with the given replacements.

    Args:
        replacements: {original_word: replacement_word}

    Returns:
        A function(text: str) -> str that applies the replacements.
    """
    # Build a regex pattern that matches any replacement word at word boundaries
    # Sort by length descending so longer matches take priority
    sorted_words = sorted(replacements.keys(), key=len, reverse=True)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(w) for w in sorted_words) + r")\b",
        re.IGNORECASE if not any(w.isupper() for w in sorted_words) else 0,
    )

    def _replace(match: re.Match) -> str:
        original = match.group(0)
        # Find the replacement key (case-insensitive lookup)
        for key, val in replacements.items():
            if key.lower() == original.lower():
                return _preserve_case(original, val)
        return original

    def filter_fn(text: str) -> str:
        if not text:
            return text
        return pattern.sub(_replace, text)

    return filter_fn


# ── Default filter ───────────────────────────────────────────────────────────

DEFAULT_REPLACEMENTS: dict[str, str] = {
    "loan": "contract",
    "loans": "contracts",
    "lender": "creditor",
    "borrower": "customer",
}

# Singleton filter instance with default replacements
default_filter = make_filter(DEFAULT_REPLACEMENTS)


def filter_output(text: str, replacements: dict[str, str] | None = None) -> str:
    """
    Apply the output filter to customer-facing text.

    Args:
        text: The text to filter
        replacements: Optional custom replacement map. Uses DEFAULT_REPLACEMENTS if None.

    Returns:
        Filtered text with word-boundary-aware, case-preserving replacements.
    """
    if replacements is None:
        return default_filter(text)
    return make_filter(replacements)(text)
