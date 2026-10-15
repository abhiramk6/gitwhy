#!/usr/bin/env python3
"""Free-form probe of the open-source org: questions written from outside knowledge of the projects.
Unlike oss_cases.py this never fails the build; it records how the system behaves (docs/oss-probe-report.md)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
from _report import CaseMeter, Tally, header  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import connect  # noqa: E402
from app.models.provider import make_provider  # noqa: E402
from app.planning.planner import create_plan  # noqa: E402
from app.retrieval.search import search_with_meta  # noqa: E402


def main() -> int:
    cfg = json.loads((ROOT / "eval" / "oss_probe.json").read_text())
    s = get_settings()
    prov = make_provider(s)
    tally = Tally()
    body = ["## Questions (top 5)", "", "| Question | First correct source (rank) | Mode | Model calls | Top 3 |",
            "|---|---|---|---|---|"]
    with connect() as conn:
        org = conn.execute("SELECT id FROM organizations WHERE slug=%s", (cfg["org_slug"],)).fetchone()["id"]
        for c in cfg["questions"]:
            with CaseMeter() as cm:
                hits, meta = search_with_meta(conn, org, prov, c["q"], k=5)
            ids = [h.source_id for h in hits]
            top = "<br>".join(i[:70] for i in ids[:3])
            if not c["expect"]:
                body.append(f"| {c['q']} | n/a - {c['note']} | {meta['mode']} | {cm.text()} | {top} |")
                continue
            rank = next((n for n, i in enumerate(ids, 1) if any(e.lower() in i.lower() for e in c["expect"])), None)
            tally.add("PASS" if rank else "FAIL")
            body.append(f"| {c['q']} | {'rank ' + str(rank) if rank else 'MISS'} | {meta['mode']} | {cm.text()} | {top} |")
        body += ["", f"**Answered within top 5: {tally.passed}/{tally.passed + tally.failed}**", "",
                 "## Feature requests", ""]
        for r in cfg["plans"]:
            with CaseMeter() as cm:
                p = create_plan(conn, org, prov, r, persist=False)
            body += [f"### {r}", ""]
            if p.get("status") == "llm_required":
                tally.add("SKIPPED")
                body += [f"SKIPPED: planning needs an LLM and no cached judgment exists (model calls: {cm.text()}).", ""]
                continue
            if p.get("status") == "insufficient_evidence":
                body += [f"Not planned: `insufficient_evidence` (model calls: {cm.text()}).", ""]
                continue
            body.append(f"_Model calls: {cm.text()} · search mode: {p.get('search_mode')} · guard drops: "
                        f"{len(p.get('dropped_claims', []))}_")
            body.append("")
            body.append("Components: " + ", ".join(f"{c['service']} ({c['role']}, {c['label']})" for c in p["affected_components"]))
            body.append("")
            body.append("Decisions: " + (", ".join(d["adr"] for d in p["decisions"]) or "none"))
            body.append("")
            body.append(f"Risks: {len(p['risks'])}; tasks: {len(p['tasks'])}; open questions: {len(p['open_questions'])}")
            body.append("")
        prov_lines = header(prov, conn, org, demo_corpus=True)
    out = ["# Open-source probe report", "",
           "Questions were written from general knowledge of Flask/Werkzeug/Jinja/Click/Requests/urllib3, not from "
           f"the indexed text. Result: {tally.line()}", "", "## Run provenance", ""] + prov_lines + [""] + body
    Path(ROOT / "docs" / "oss-probe-report.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return tally.exit_code


if __name__ == "__main__":
    sys.exit(main())
