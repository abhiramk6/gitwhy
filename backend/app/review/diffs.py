"""Unified-diff parsing for PR review. Rule-based on purpose: it only parses and locates text, it never judges.

A review comment may name a line only when the model supplied a literal added line (`diff_quote`) and that text really
occurs on a `+` line of the PR's stored patch. The line number is then computed from the hunk headers, not by the model.
"""
from __future__ import annotations

import re

from ..intelligence.guards import norm

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def added_lines(patch: str) -> list[tuple[int, str]]:
    """(line number in the new file, text) for every added line of one file's patch."""
    out, n = [], 0
    for raw in (patch or "").split("\n"):
        m = _HUNK.match(raw)
        if m:
            n = int(m.group(1))
            continue
        if not n:
            continue
        if raw.startswith("+"):
            out.append((n, raw[1:]))
            n += 1
        elif raw.startswith("-") or raw.startswith("\\"):
            continue
        else:
            n += 1
    return out


def locate(patches: dict[str, str], quote: str, file: str = "") -> tuple[str, int, str] | None:
    """Where `quote` sits among the added lines: (file, line, the full line) or None. The quote must be a literal stretch of
    one added line (whitespace/case-insensitive); a stretch that spans lines does not count."""
    q = norm(quote)
    if len(q) < 4:
        return None
    for name in ([file] if file in patches else list(patches)):
        for line, text in added_lines(patches[name]):
            if q in norm(text):
                return name, line, text.strip()
    return None


def digest(patches: dict[str, str], budget: int = 12_000) -> list[dict]:
    """The packet's view of the diff: per file, added and removed lines with their new-file line numbers. Cut at `budget`."""
    out, used = [], 0
    for name, patch in patches.items():
        lines, n = [], 0
        for raw in patch.split("\n"):
            m = _HUNK.match(raw)
            if m:
                n = int(m.group(1))
                continue
            if raw.startswith("+"):
                lines.append(f"{n}+ {raw[1:]}")
                n += 1
            elif raw.startswith("-"):
                lines.append(f"- {raw[1:]}")
            elif n:
                n += 1
        text = "\n".join(lines)
        if used + len(text) > budget:
            text = text[: max(0, budget - used)]
        if text:
            out.append({"file": name, "changes": text})
            used += len(text)
        if used >= budget:
            break
    return out


_LINE_CLAIM = re.compile(r"\b(?:lines?|l)\s*#?\d+\b|\bon line\b|\bat line\b", re.I)


def claims_a_line(text: str) -> bool:
    """True when prose names a specific line ("line 42"); such a claim needs a verified diff quote."""
    return bool(_LINE_CLAIM.search(text or ""))
