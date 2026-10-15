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

from _report import CaseMeter, Tally, evidential, header  # noqa: E402
from _score import score_plan  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import connect  # noqa: E402
from app.models.provider import make_provider  # noqa: E402
from app.planning.planner import create_plan, unsupported_claims  # noqa: E402
from app.retrieval.search import search_with_meta  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "oss-demo-report.md"))
    a = ap.parse_args()
    cases = json.loads((ROOT / "eval" / "oss_cases.json").read_text())
    s = get_settings()
    prov = make_provider(s)
    tally = Tally()
    lists = json.loads((ROOT / "eval" / "oss_dev_lists.json").read_text())
    by_request = {c["request"]: c for c in lists["cases"]}
    review_items: list[str] = []
    with connect() as conn:
        org = conn.execute("SELECT id FROM organizations WHERE slug=%s", (cases["org_slug"],)).fetchone()["id"]
        repos = {r["name"] for r in conn.execute("SELECT name FROM repositories WHERE organization_id=%s", (org,))}
        out = [f"# Open-source demo report ({cases['org_slug']})", "",
               "Real public GitHub history for 8 repositories plus a synthetic team-knowledge overlay "
               "(ADR-101..108, runbooks).", ""]
        body = ["## Retrieval", "", "| Query | Expected (any of) | Rank | Mode | Model calls | Top results | Result |",
                "|---|---|---|---|---|---|---|"]
        for c in cases["retrieval"]:
            with CaseMeter() as cm:
                hits, meta = search_with_meta(conn, org, prov, c["q"], k=c.get("k", 5))
            ids = [h.source_id for h in hits]
            rank = next((i for i, h in enumerate(ids, 1) if any(
                re.search(rf"(^|[^A-Za-z0-9]){re.escape(e)}([^0-9]|$)", h) for e in c["expect_any"])), None)
            tally.add("PASS" if rank else "FAIL", c.get("split", "dev"))
            top = "<br>".join(f"{h.source_id} ({'+'.join(h.signals)})" for h in hits[:3])
            body.append(f"| {c['q']} | {', '.join(c['expect_any'][:2])} | {rank or '-'} | {meta['mode']} | "
                        f"{cm.text()} | {top} | {'PASS' if rank else 'FAIL'} |")
        body += ["", "## Feature plans", ""]
        for c in cases["plans"]:
            with CaseMeter() as cm:
                plan = create_plan(conn, org, prov, c["request"], persist=False)
            if plan.get("status") == "llm_required":
                tally.add("SKIPPED", c.get("split", "dev"))
                body += [f"### SKIPPED — {c['request']}", "",
                         f"Planning needs an LLM provider and no cached judgment exists (model calls: {cm.text()}).", ""]
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
            sc = score_plan(plan, by_request[c["request"]], repos) if c["request"] in by_request else None
            if sc:
                problems += [f"required decision missing: {x}" for x in sc["decisions_missing"]]
                problems += [f"excluded decision present: {x}" for x in sc["decisions_excluded_present"]]
                problems += [f"excluded subject in risk: {x['subject']}" for x in sc["risks_excluded"]]
                review_items += [f"[{c['request'][:40]}…] decision {x} (unlisted)" for x in sc["decisions_unlisted"]]
                review_items += [f"[{c['request'][:40]}…] risk (unlisted): {x['summary']}" for x in sc["risks_unlisted"]]
                review_items += [f"[{c['request'][:40]}…] reuse (unlisted): {x['summary']}" for x in sc["reuse_unlisted"]]
            tally.add("FAIL" if problems else "PASS", c.get("split", "dev"))
            body += [f"### {'PASS' if not problems else 'FAIL'} — {c['request']}", "",
                     f"_Why this case:_ {c['why']}", "",
                     f"_Search mode:_ {plan.get('search_mode')} · _model calls:_ {cm.text()} · "
                     f"_guard drops:_ {len(plan.get('dropped_claims', []))}", ""]
            if problems:
                body += [f"**Problems:** {'; '.join(problems)}", ""]
            if plan.get("status") == "insufficient_evidence":
                body += [f"Planner response: `insufficient_evidence` — {plan['open_questions'][0]}", ""]
                continue
            body += ["| Component | Role | Label | Reason |", "|---|---|---|---|"]
            body += [f"| {x['service']} | {x['role']} | {x['label']} | {x['reason']} |" for x in plan["affected_components"]]
            body += ["", "Governing decisions: " + (", ".join(f"{d['adr']} ({d['label']})" for d in plan["decisions"]) or "none"), ""]
            if sc:
                body += [f"_Bucket counts (dev):_ decisions required-missing {len(sc['decisions_missing'])} · excluded-present "
                         f"{len(sc['decisions_excluded_present'])} · unlisted {len(sc['decisions_unlisted'])}; risks ok "
                         f"{sc['risks_ok']} · excluded {len(sc['risks_excluded'])} · unlisted {len(sc['risks_unlisted'])}; "
                         f"reuse ok {sc['reuse_ok']} · unlisted {len(sc['reuse_unlisted'])}", ""]
            for r in plan["risks"][:5]:
                body.append(f"- risk [{r['label']}] {r['summary']}")
            for t in plan["tasks"][:6]:
                body.append(f"- task [{t.get('label', 'proposed')}] {t['id']} {t['title']}")
            body.append("")
        out += ["## Run provenance", ""] + header(prov, conn, org, demo_corpus=True) + [""] + body
        is_evidence, _why = evidential(conn, org, prov)
    fails = tally.failed
    out += ["## Scoring lists", "",
            f"- Lists: `eval/oss_dev_lists.json` — **{lists['_confirmation']}**. {lists['_excluded_provenance']}",
            f"- Unlisted items for review (dev only; not auto-failed): **{len(review_items)}**", ""]
    out += [f"  - {x}" for x in review_items] + [""]
    out += ["---", f"**Result: {tally.line()}**", f"**Failed expectations: {fails}**"]
    target = Path(a.out)
    if not is_evidence and a.out == str(ROOT / "docs" / "oss-demo-report.md"):
        target = ROOT / "docs" / "oss-demo-report.PARTIAL-NON-EVIDENTIAL.md"  # never overwrite the evidential report
    target.write_text("\n".join(out) + "\n")
    print("\n".join(out[-3:]), f"\nwrote {target}")
    return tally.exit_code


if __name__ == "__main__":
    sys.exit(main())
