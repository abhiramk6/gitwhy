"""Shared guards for model output that quotes or highlights text."""
from __future__ import annotations

import re

_CURLY = str.maketrans("‘’“”", "''\"\"")


def norm(s: str) -> str:
    """Whitespace, case, markdown ticks/emphasis and curly quotes are not content; the words themselves must match."""
    return re.sub(r"\s+", " ", (s or "").replace("`", "").replace("*", "").translate(_CURLY)).strip().lower()


def occurs(fragment: str, text: str) -> bool:
    return bool(norm(fragment)) and norm(fragment) in norm(text)


def exact(fragment: str, *texts: str, max_words: int = 0) -> str:
    """The fragment if it literally occurs in one of the texts (and is not absurdly long), else an empty string.
    Used for highlights and proof quotes: a highlight that is not in the text is dropped, never shown."""
    f = (fragment or "").strip()
    if not f or (max_words and len(f.split()) > max_words):
        return ""
    return f if any(occurs(f, t) for t in texts if t) else ""
