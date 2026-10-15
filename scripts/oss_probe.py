#!/usr/bin/env python3
"""Free-form probe of the open-source org: questions written from outside knowledge of the projects.
Unlike oss_cases.py this never fails the build; it records how the system behaves (docs/oss-probe-report.md)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import get_settings  # noqa: E402
from app.db import connect  # noqa: E402
from app.models.provider import OfflineProvider, VertexProvider  # noqa: E402
from app.planning.planner import create_plan  # noqa: E402
from app.retrieval.search import search  # noqa: E402


def main() -> int:
    cfg = json.loads((ROOT / "eval" / "oss_probe.json").read_text())
    s = get_settings()
    prov = VertexProvider(s.gcp_project, s.gcp_location, s.gen_model, s.embed_model) if s.provider == "vertex" \
        else OfflineProvider()
    out = [f"# Open-source probe report", "", f"Provider: `{prov.name}`. Questions were written from general knowledge "
           "of Flask/Werkzeug/Jinja/Click/Requests/urllib3, not from the indexed text.", "",
           "## Questions (top 5)", "", "| Question | First correct source (rank) | Top 3 |", "|---|---|---|"]
    found = scored = 0
    with connect() as conn:
        org = conn.execute("SELECT id FROM organizations WHERE slug=%s", (cfg["org_slug"],)).fetchone()["id"]
        for c in cfg["questions"]:
            hits = search(conn, org, prov, c["q"], k=5)
            ids = [h.source_id for h in hits]
            top = "<br>".join(i[:70] for i in ids[:3])
            if not c["expect"]:
                out.append(f"| {c['q']} | n/a - {c['note']} | {top} |")
                continue
            scored += 1
            rank = next((n for n, i in enumerate(ids, 1) if any(e.lower() in i.lower() for e in c["expect"])), None)
            found += rank is not None
            out.append(f"| {c['q']} | {'rank ' + str(rank) if rank else 'MISS'} | {top} |")
        out += ["", f"**Answered within top 5: {found}/{scored}**", "", "## Feature requests", ""]
        for r in cfg["plans"]:
            p = create_plan(conn, org, prov, r, persist=False)
            out += [f"### {r}", ""]
            if p.get("status") == "insufficient_evidence":
                out += ["Refused: `insufficient_evidence`.", ""]
                continue
            out.append("Components: " + ", ".join(f"{c['service']} ({c['role']}, {c['label']})" for c in p["affected_components"]))
            out.append("")
            out.append("Decisions: " + (", ".join(d["adr"] for d in p["decisions"]) or "none"))
            out.append("")
            out.append(f"Risks: {len(p['risks'])}; tasks: {len(p['tasks'])}; open questions: {len(p['open_questions'])}")
            out.append("")
    Path(ROOT / "docs" / "oss-probe-report.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
