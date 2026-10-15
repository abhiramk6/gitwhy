#!/usr/bin/env python3
"""Known-answer evaluation of retrieval and planning against the seeded dev database.

Usage: DATABASE_URL=... python scripts/evaluate.py [--out docs/eval-report.md]
Expected answers come from eval/known_answers.json (derived from the synthetic data, not from model output).
Outcomes are PASS / FAIL / SKIPPED. A skipped case is not a pass: the script exits non-zero on any failure, any
skip, and any plan containing an unsupported claim.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from _report import CaseMeter, Tally, header  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import connect  # noqa: E402
from app.models.provider import make_provider  # noqa: E402
from app.planning.planner import create_plan, unsupported_claims  # noqa: E402
from app.retrieval.search import search_with_meta  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "eval-report.md"))
    args = ap.parse_args()
    cases = json.loads((ROOT / "eval" / "known_answers.json").read_text())
    prov = make_provider(get_settings())
    lines, tally = [], Tally()
    with connect() as conn:
        org = conn.execute("SELECT id FROM organizations WHERE slug=%s", (get_settings().org_slug,)).fetchone()["id"]

        lines += ["## Retrieval", "", "| Query | Expectation | Mode | Model calls | Result | Rank |",
                  "|---|---|---|---|---|---|"]
        rr, hits_at_k, pos = [], 0, 0
        for c in cases["retrieval"]:
            print(f"retrieval: {c['q']}", file=sys.stderr, flush=True)
            with CaseMeter() as cm:
                hits, meta = search_with_meta(conn, org, prov, c["q"], k=c.get("k", 5))
            ids = [h.source_id for h in hits]
            if c.get("expect_none"):
                if not prov.has_llm and meta["mode"] == "lexical":
                    # Rejecting an unsupported query is a relevance judgment; lexical search cannot make it.
                    tally.add("SKIPPED")
                    lines.append(f"| {c['q']} | no relevant results | {meta['mode']} | {cm.text()} | SKIPPED: "
                                 "needs an LLM relevance judgment | – |")
                    continue
                ok = len(hits) == 0
                tally.add("PASS" if ok else "FAIL")
                lines.append(f"| {c['q']} | no relevant results | {meta['mode']} | {cm.text()} | "
                             f"{'PASS' if ok else 'FAIL: ' + ', '.join(ids[:3])} | – |")
            else:
                pos += 1
                # identity match: an ADR source id looks like "repo:docs/adr/ADR-004-name.md"
                rank = next((i for i, h in enumerate(ids, 1)
                             if any(re.search(rf"(^|[^A-Za-z0-9]){re.escape(e)}([^0-9]|$)", h) for e in c["expect_any"])), None)
                ok = rank is not None
                hits_at_k += ok
                rr.append(1 / rank if rank else 0.0)
                tally.add("PASS" if ok else "FAIL")
                lines.append(f"| {c['q']} | {' / '.join(c['expect_any'])} in top {c.get('k', 5)} | {meta['mode']} | "
                             f"{cm.text()} | {'PASS' if ok else 'FAIL'} | {rank or '–'} |")
        ranks = [round(1 / x) if x else None for x in rr]
        dist = {"rank 1": sum(r == 1 for r in ranks), "rank 2-3": sum(r in (2, 3) for r in ranks),
                "rank 4+": sum(r is not None and r >= 4 for r in ranks), "not found": sum(r is None for r in ranks)}
        lines += ["", f"- found within k: **{hits_at_k} of {pos}** questions; " +
                  ", ".join(f"{k}: {v}" for k, v in dist.items()), ""]

        lines += ["## Planning", "", "| Case | Check | Result |", "|---|---|---|"]
        total_claims = unsupported = 0
        for c in cases["plans"]:
            print(f"plan: {c['name']}", file=sys.stderr, flush=True)
            with CaseMeter() as cm:
                plan = create_plan(conn, org, prov, c["request"], persist=False)
            if plan.get("status") == "llm_required":
                tally.add("SKIPPED")
                lines.append(f"| {c['name']} | plan | SKIPPED: planning needs an LLM provider "
                             "(PROVIDER=gemini + GEMINI_API_KEY, or vertex) and no cached judgment exists |")
                continue
            checks: list[tuple[str, bool]] = []
            if c.get("expect_insufficient"):
                checks.append(("returns insufficient_evidence instead of inventing a plan",
                               plan.get("status") == "insufficient_evidence"))
            else:
                comps = {x["service"] for x in plan["affected_components"]}
                adrs = {d["adr"] for d in plan["decisions"]}
                text = json.dumps(plan["risks"]) + json.dumps([r["type"] for r in plan["risks"]])
                reuse = json.dumps(plan["reuse_candidates"])
                checks += [(f"component {s}", s in comps) for s in c["components"]]
                checks += [(f"decision {a}", a in adrs) for a in c["decisions"]]
                checks += [(f"excludes {a}", a not in adrs) for a in c.get("not_decisions", [])]
                checks += [(f"risk marker {m}", m in text) for m in c.get("risk_markers", [])]
                checks += [(f"reuse marker {m}", m in reuse) for m in c.get("reuse_markers", [])]
                bad = unsupported_claims(plan)
                n = sum(len(plan.get(sec, [])) for sec in ("affected_components", "decisions", "risks",
                                                             "reuse_candidates", "tasks", "open_questions"))
                total_claims += n
                unsupported += len(bad)
                checks.append(("no unsupported claims", not bad))
            for name, ok in checks:
                tally.add("PASS" if ok else "FAIL")
                lines.append(f"| {c['name']} | {name} | {'PASS' if ok else 'FAIL'} |")
            lines.append(f"| {c['name']} | _model calls: {cm.text()} · search mode: {plan.get('search_mode')} · "
                         f"guard drops: {len(plan.get('dropped_claims', []))}_ | – |")
        lines += ["", f"- claims without valid supporting evidence: **{unsupported} of {total_claims}** claims checked", ""]
        prov_lines = header(prov, conn, org)

    out = ["# Evaluation report", "", f"Organization: synthetic Northwind Labs · Result: {tally.line()}", "",
           "Baselines are measured on the synthetic dataset only; they are not claims about real organizations.", "",
           "## Run provenance", ""] + prov_lines + [""]
    Path(args.out).write_text("\n".join(out + lines) + "\n")
    print("\n".join(out + lines))
    return tally.exit_code


if __name__ == "__main__":
    sys.exit(main())
