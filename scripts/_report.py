"""Shared report plumbing for evaluate.py / oss_cases.py / oss_probe.py.

Every report states, before any result: which provider and models produced it, which embedding model each corpus
was indexed with, how many model calls were live vs replayed from the judgment cache, and how many judgments
could not be made. Outcomes are PASS / FAIL / SKIPPED; a skipped case is never counted as a pass and makes the
script exit non-zero.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import Settings  # noqa: E402
from app.intelligence.judge import delta, meter  # noqa: E402


@dataclass
class Tally:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    by_split: dict[str, list[int]] = field(default_factory=dict)  # split -> [pass, fail, skip]

    def add(self, outcome: str, split: str = "all") -> None:
        i = {"PASS": 0, "FAIL": 1, "SKIPPED": 2}[outcome]
        self.passed, self.failed, self.skipped = (self.passed + (i == 0), self.failed + (i == 1),
                                                  self.skipped + (i == 2))
        self.by_split.setdefault(split, [0, 0, 0])[i] += 1

    @property
    def exit_code(self) -> int:
        return 1 if (self.failed or self.skipped) else 0

    def line(self) -> str:
        head = f"**PASS {self.passed} / FAIL {self.failed} / SKIPPED {self.skipped}**"
        if self.exit_code == 0:
            return head + " (all expectations met)"
        why = []
        if self.failed:
            why.append(f"{self.failed} failed")
        if self.skipped:
            why.append(f"{self.skipped} skipped (a skipped check is not a pass; the run exits non-zero)")
        return head + " — " + "; ".join(why)


def corpus_models(conn, org_id: int) -> list[tuple[str, int]]:
    return [(r["model"], r["n"]) for r in conn.execute(
        "SELECT model, count(*) AS n FROM embeddings WHERE organization_id=%s GROUP BY model ORDER BY n DESC",
        (org_id,))]


def header(prov, conn, org_id: int, *, demo_corpus: bool = False) -> list[str]:
    """Provider / models / embedding model per corpus / model-call accounting, as markdown lines."""
    default_embed = Settings.model_fields["embed_model"].default
    lines = [f"- **Provider:** `{prov.name}` · LLM available: **{'yes' if prov.has_llm else 'no'}**"]
    if prov.has_llm:
        chain = " → ".join(getattr(prov, "models", [getattr(prov, "_gen_model", "?")]))
        lines.append(f"- **Generation model chain:** {chain} (answered by: `{getattr(prov, 'last_model', '?')}`)")
    stored = corpus_models(conn, org_id)
    lines.append("- **Embedding model for this corpus:** "
                 + (", ".join(f"`{m}` ({n} vectors)" for m, n in stored) or "none stored")
                 + f" · configured: `{prov.embed_model}`")
    mixed = len({m for m, _ in stored}) > 1
    if mixed:
        lines.append("- ⚠️ **Mixed embedding models in one corpus** — vectors are not comparable across models; "
                     "re-embed with a single model.")
    if prov.semantic_embeddings and not any(m == prov.embed_model for m, _ in stored):
        lines.append(f"- ⚠️ **No stored vectors for `{prov.embed_model}`:** semantic search is inactive for this "
                     "corpus (lexical + model judgments only).")
    if demo_corpus or (stored and stored[0][0] != default_embed):
        lines.append(f"- **Demo-only embedding model.** This corpus uses `{stored[0][0] if stored else '-'}`; the "
                     f"deployment default is `{default_embed}`. Retrieval results on this corpus are **not "
                     f"predictive of `{default_embed}` quality**.")
    u = getattr(prov, "usage", None) or {}
    snap = meter.snapshot()
    rep = ", ".join(f"{m}×{n}" for m, n in snap["replay_models"].items()) or "none"
    lines.append(f"- **Model calls this run:** live **{snap['live']}** · replayed from judgment cache "
                 f"**{snap['replayed']}** (originally produced by: {rep}) · judgments unavailable "
                 f"**{snap['unavailable']}**")
    if u:
        lines.append(f"- **Provider accounting:** {u.get('calls', 0)} successful calls, {u.get('fallbacks', 0)} "
                     f"answered by a fallback model, {u.get('retries', 0)} retries, "
                     f"{u.get('prompt_tokens', 0)} prompt / {u.get('output_tokens', 0)} output tokens")
    return lines


class CaseMeter:
    """Context manager: model-call accounting for one case."""
    def __enter__(self):
        self._b = meter.snapshot()
        self.d = {"live": 0, "replayed": 0, "unavailable": 0}
        return self

    def __exit__(self, *exc):
        self.d = delta(self._b, meter.snapshot())

    def text(self) -> str:
        return f"live {self.d['live']} · replayed {self.d['replayed']}" + (
            f" · unavailable {self.d['unavailable']}" if self.d["unavailable"] else "")
