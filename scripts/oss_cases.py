#!/usr/bin/env python3
"""Run the retrieval + planning cases in eval/oss_cases.json against the ingested open-source org.

Usage: ORG_SLUG=oss-pallets DATABASE_URL=... python scripts/oss_cases.py [--out docs/oss-demo-report.md]
Expected answers are derived from real upstream structure (imports, config keys) plus the overlay ADRs.
Exits non-zero on any failed expectation or any unsupported claim.
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
from app.models.provider import make_provider  # noqa: E402
from app.planning.planner import create_plan, unsupported_claims  # noqa: E402
from app.retrieval.search import search  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "oss-demo-report.md"))
    a = ap.parse_args()
    cases = json.loads((ROOT / "eval" / "oss_cases.json").read_text())
    s = get_settings()
    prov = make_provider(s)
    out = [f"# Open-source demo report ({cases['org_slug']})", "",
           f"Provider: `{prov.name}`. Real public GitHub history for 8 repositories plus a synthetic team-knowledge "
           "overlay (ADR-101..108, runbooks).", "", "## Retrieval", "",
           "| Query | Expected (any of) | Rank | Top results | Result |", "|---|---|---|---|---|"]
    fails = 0
    with connect() as conn:
        org = conn.execute("SELECT id FROM organizations WHERE slug=%s", (cases["org_slug"],)).fetchone()["id"]
        for c in cases["retrieval"]:
            hits = search(conn, org, prov, c["q"], k=c.get("k", 5))
            ids = [h.source_id for h in hits]
            rank = next((i for i, h in enumerate(ids, 1) if any(
                re.search(rf"(^|[^A-Za-z0-9]){re.escape(e)}([^0-9]|$)", h) for e in c["expect_any"])), None)
            fails += rank is None
            top = "<br>".join(f"{h.source_id} ({'+'.join(h.signals)})" for h in hits[:3])
            out.append(f"| {c['q']} | {', '.join(c['expect_any'][:2])} | {rank or '-'} | {top} | "
                       f"{'PASS' if rank else 'FAIL'} |")
        out += ["", "## Feature plans", ""]
        for c in cases["plans"]:
            plan = create_plan(conn, org, prov, c["request"], persist=False)
            if plan.get("status") == "llm_required":
                out += [f"### SKIPPED — {c['request']}", "", "Planning needs an LLM provider; none configured.", ""]
                continue
            problems = []
            if "expect_status" in c:
                if plan.get("status") != c["expect_status"]:
                    problems.append(f"status {plan.get('status')} != {c['expect_status']}")
            else:
                comps = {x["service"]: x for x in plan.get("affected_components", [])}
                problems += [f"missing component {x}" for x in c["expect_components"] if x not in comps]
                if comps.get(c["expect_primary"], {}).get("role") != "primary":
                    problems.append(f"{c['expect_primary']} is not primary")
                adrs = {d["adr"] for d in plan.get("decisions", [])}
                problems += [f"missing {x}" for x in c.get("expect_decisions", []) if x not in adrs]
                problems += [f"should not include {x}" for x in c.get("exclude_decisions", []) if x in adrs]
                problems += unsupported_claims(plan)
            fails += bool(problems)
            out += [f"### {'PASS' if not problems else 'FAIL'} — {c['request']}", "", f"_Why this case:_ {c['why']}", ""]
            if problems:
                out += [f"**Problems:** {'; '.join(problems)}", ""]
            if plan.get("status") == "insufficient_evidence":
                out += [f"Planner response: `insufficient_evidence` — {plan['open_questions'][0]}", ""]
                continue
            out += ["| Component | Role | Label | Reason |", "|---|---|---|---|"]
            out += [f"| {x['service']} | {x['role']} | {x['label']} | {x['reason']} |" for x in plan["affected_components"]]
            out += ["", "Governing decisions: " + (", ".join(f"{d['adr']} ({d['label']})" for d in plan["decisions"]) or "none"), ""]
            for r in plan["risks"][:5]:
                out.append(f"- risk [{r['label']}] {r['summary']}")
            for t in plan["tasks"][:6]:
                out.append(f"- task [{t.get('label', 'proposed')}] {t['id']} {t['title']}")
            out.append("")
    out += ["---", f"**Failed expectations: {fails}**"]
    Path(a.out).write_text("\n".join(out) + "\n")
    print("\n".join(out[-3:]), f"\nwrote {a.out}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
