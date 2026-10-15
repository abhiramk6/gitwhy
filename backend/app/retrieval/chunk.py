"""Cover a whole text with consecutive spans on natural boundaries (blank lines, then lines).

Nothing is dropped: the spans tile the text, so a long document is embedded in full rather than by its first N
characters. `target` is a size budget for the embedding model, not a relevance rule.
"""
from __future__ import annotations


def chunk_spans(text: str, target: int = 1800) -> list[tuple[int, int]]:
    if not text:
        return [(0, 0)]
    if len(text) <= target:
        return [(0, len(text))]
    # boundaries: end offsets of paragraphs (after blank-line runs), then of lines inside oversized paragraphs
    bounds: list[int] = []
    i, n = 0, len(text)
    while i < n:
        j = text.find("\n\n", i)
        j = n if j == -1 else j + 2
        while j < n and text[j] == "\n":
            j += 1
        if j - i > target:  # oversized paragraph: split on line ends, then hard-split long lines
            k = i
            while k < j:
                nl = text.find("\n", k, j)
                end = j if nl == -1 else nl + 1
                while end - k > target:
                    bounds.append(k + target)
                    k += target
                bounds.append(end)
                k = end
        else:
            bounds.append(j)
        i = j
    spans: list[tuple[int, int]] = []
    start = 0
    for b in bounds:
        if b - start >= target:
            spans.append((start, b))
            start = b
    if start < n:
        if spans and n - start < target // 4:
            spans[-1] = (spans[-1][0], n)  # fold a tiny tail into the previous chunk
        else:
            spans.append((start, n))
    return spans
