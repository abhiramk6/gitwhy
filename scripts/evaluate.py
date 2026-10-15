#!/usr/bin/env python3
"""Known-answer evaluation of retrieval and planning against the seeded dev database.

Usage: DATABASE_URL=... python scripts/evaluate.py [--out docs/eval-report.md]
Expected answers come from eval/known_answers.json (derived from the synthetic data, not from model output).
Exits non-zero if any retrieval or plan case fails or any plan contains an unsupported claim.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import connect  # noqa: E402
from app.models.provider import OfflineProvider, VertexProvider  # noqa: E402
from app.planning.planner import create_plan, unsupported_claims  # noqa: E402
from app.retrieval.search import search  # noqa: E402


def provider():
    s = get_settings()
    if s.provider == "vertex":
        return VertexProvider(s.gcp_project, s.gcp_location, s.gen_model, s.embed_model)
    return OfflineProvider()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "eval-report.md"))
    args = ap.parse_args()
    cases = json.loads((ROOT / "eval" / "known_answers.json").read_text())
    prov = provider()
    lines, failures = [], 0
    with connect() as conn:
        org = conn.execute("SELECT id FROM organizations WHERE slug=%s", (get_settings().org_slug,)).fetchone()["id"]

        lines += ["## Retrieval", "", "| Query | Expectation | Result | Rank |", "|---|---|---|---|"]
        rr, hits_at_k, pos = [], 0, 0
        for c in cases["retrieval"]:
            hits = search(conn, org, prov, c["q"], k=c.get("k", 5))
            ids = [h.source_id for h in hits]
            if c.get("expect_none") and c.get("needs_semantic_provider") and prov.name.startswith("offline"):
                lines.append(f"| {c['q']} | no relevant results | SKIPPED: offline hashing embeddings cannot "
                             "reject unsupported queries; verify with the Vertex provider | – |")
                continue
            if c.get("expect_none"):
                ok = len(hits) == 0
                lines.append(f"| {c['q']} | no relevant results | {'PASS' if ok else 'FAIL: ' + ', '.join(ids[:3])} | – |")
            else:
                pos += 1
                # identity match: an ADR source id looks like "repo:docs/adr/ADR-004-name.md"
                rank = next((i for i, h in enumerate(ids, 1)
                             if any(re.search(rf"(^|[^A-Za-z0-9]){re.escape(e)}([^0-9]|$)", h) for e in c["expect_any"])), None)
                ok = rank is not None
                hits_at_k += ok
                rr.append(1 / rank if rank else 0.0)
                lines.append(f"| {c['q']} | {' / '.join(c['expect_any'])} in top {c.get('k', 5)} | "
                             f"{'PASS' if ok else 'FAIL'} | {rank or '–'} |")
            failures += 0 if ok else 1
        lines += ["", f"- hit rate@k: **{hits_at_k}/{pos}**; MRR: **{sum(rr) / max(len(rr), 1):.2f}**", ""]

        lines += ["## Planning", "", "| Case | Check | Result |", "|---|---|---|"]
        total_claims = unsupported = 0
        for c in cases["plans"]:
            plan = create_plan(conn, org, prov, c["request"], persist=False)
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
                failures += 0 if ok else 1
                lines.append(f"| {c['name']} | {name} | {'PASS' if ok else 'FAIL'} |")
        rate = unsupported / total_claims if total_claims else 0.0
        lines += ["", f"- unsupported-claim rate: **{rate:.1%}** ({unsupported}/{total_claims} claims)", ""]

    header = ["# Evaluation report", "",
              f"Provider: `{prov.name}` · Organization: synthetic Northwind Labs · Result: "
              f"**{'ALL PASS' if failures == 0 else str(failures) + ' FAILURE(S)'}**", "",
              "Baselines are measured on the synthetic dataset only; they are not claims about real organizations.", ""]
    Path(args.out).write_text("\n".join(header + lines) + "\n")
    print("\n".join(header + lines))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
