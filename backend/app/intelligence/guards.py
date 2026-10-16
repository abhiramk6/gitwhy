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


def highlight(key: str, text: str, max_words: int = 10) -> str:
    """A highlight is always a literal stretch of `text`. If the model's key is one, use it; if it copied the words from a
    source instead, fall back to the longest run of two or more consecutive words the key and the text share."""
    k = exact(key, text, max_words=max_words)
    if k:
        return k
    words = text.split()
    kw = [norm(w) for w in (key or "").split()]
    best = (0, 0)
    for i in range(len(words)):
        for j in range(len(kw)):
            n = 0
            while i + n < len(words) and j + n < len(kw) and norm(words[i + n]).strip(".,;:!?()\"'") == kw[j + n].strip(".,;:!?()\"'") and n < max_words:
                n += 1
            if n > best[1]:
                best = (i, n)
    return " ".join(words[best[0]:best[0] + best[1]]) if best[1] >= 2 else ""
