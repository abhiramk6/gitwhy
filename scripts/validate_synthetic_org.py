#!/usr/bin/env python3
"""Independent validator: re-derives every demo scenario from the generated data (not from the manifest's
own claims) and fails loudly if a scenario is not present. Also checks hygiene (no real-looking data)."""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path


def load(p: Path):
    return json.loads(p.read_text())


def py_imports(path: Path) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(ast.parse(path.read_text())):
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.add(n.module.split(".")[0])
    return out


def methods(path: Path, cls: str) -> set[str]:
    for n in ast.walk(ast.parse(path.read_text())):
        if isinstance(n, ast.ClassDef) and n.name == cls:
            return {m.name for m in n.body if isinstance(m, ast.FunctionDef) and m.name != "__init__"}
    return set()


def adr_meta(text: str) -> dict:
    meta = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z-]+):\s*(.+)$", line)
        if m:
            meta[m.group(1).lower()] = m.group(2).strip()
    return meta


def validate(root: Path) -> list[str]:
    errs: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            errs.append(msg)

    man = load(root / "manifest.json")
    ref = date.fromisoformat(man["reference_date"])
    repos = man["repos"]
    prs = load(root / "history/prs.json")
    jira = load(root / "history/jira.json")
    commits = {r: load(root / f"history/{r}.commits.json") for r in repos}
    people = {p["login"] for p in load(root / "people.json")}

    # --- counts & integrity
    c = man["counts"]
    check(c["repos"] == len(repos) and 5 <= len(repos) <= 10, "repo count")
    check(c["jira_issues"] == len(jira) and len(jira) >= 40, f"jira count {len(jira)} (<40 or mismatch)")
    check(c["pull_requests"] == len(prs) and len(prs) >= 50, f"PR count {len(prs)} (<50 or mismatch)")
    check(c["commits"] == sum(map(len, commits.values())), "commit count")
    check(len({t['key'] for t in jira}) == len(jira), "duplicate jira keys")
    check(len({(p['repo'], p['number']) for p in prs}) == len(prs), "duplicate PR ids")
    keys = {t["key"] for t in jira}
    for t in jira:
        for l in t["links"]:
            check(l["key"] in keys, f"{t['key']} links to missing {l['key']}")
    for p in prs:
        check(p["author"] in people, f"PR author unknown {p['author']}")
        for k in p["linked_tickets"]:
            check(k in keys, f"PR {p['repo']}#{p['number']} links missing ticket {k}")
    for r in repos:
        for py in (root / "repos" / r).rglob("*.py"):
            try:
                ast.parse(py.read_text())
            except SyntaxError as e:
                errs.append(f"syntax error {py}: {e}")

    # --- hygiene: synthetic only
    blob = " ".join(p.read_text() for p in root.rglob("*") if p.is_file() and p.suffix in {".json", ".py", ".md"})
    for email in set(re.findall(r"[\w.+-]+@[\w.-]+\.\w+", blob)):
        check(email.endswith(".example"), f"non-.example email {email}")
    check(not re.search(r"AKIA[0-9A-Z]{16}|BEGIN (RSA|PRIVATE)|ghp_[A-Za-z0-9]{20,}|xox[bp]-", blob), "secret-like string")

    # --- S1 single dominant contributor (and only one such file org-wide)
    dominant = []
    per_file: dict[tuple[str, str], Counter] = {}
    for r, cs in commits.items():
        for cm in cs:
            for f in cm["files"]:
                per_file.setdefault((r, f), Counter())[cm["author"]] += 1
    for (r, f), cnt in per_file.items():
        tot = sum(cnt.values())
        if tot >= 10:
            a, n = cnt.most_common(1)[0]
            if n / tot >= 0.9:
                dominant.append((r, f, a, round(n / tot, 2)))
    s1 = man["scenarios"]["S1_single_owner"]
    check(dominant == [(s1["repo"], s1["path"], s1["author"], dominant[0][3] if dominant else 0)],
          f"S1: expected exactly {s1['repo']}/{s1['path']} dominated by {s1['author']}, got {dominant}")

    # --- S2 owner inactive > 90 days
    s2 = man["scenarios"]["S2_inactive_owner"]
    last = max(date.fromisoformat(cm["date"]) for cm in commits[s2["repo"]] if cm["author"] == s2["person"])
    last_pr = [date.fromisoformat(p["merged_at"]) for p in prs if p["author"] == s2["person"]]
    last = max([last] + last_pr)
    check((ref - last).days > s2["min_inactive_days"], f"S2: {s2['person']} last active {last}, only {(ref - last).days}d")
    co = (root / "repos" / s2["repo"] / "CODEOWNERS").read_text()
    check(f"@{s2['person']}" in co, "S2: inactive person is not CODEOWNER")

    # --- ADRs
    adrs: dict[str, dict] = {}
    for p in (root / "repos").rglob("docs/adr/ADR-*.md"):
        meta = adr_meta(p.read_text())
        adrs.setdefault(p.name.split("-")[0] + "-" + p.name.split("-")[1], []).append((p, meta))
    check(len(adrs) >= 6, f"need >= 6 distinct ADRs, got {len(adrs)}")

    # --- S3 conflicting conventions: two active ADRs, same topic, different scope+format
    s3 = man["scenarios"]["S3_conflicting_conventions"]
    a, b = (adrs[x][0][1] for x in s3["adrs"])
    check(a.get("topic") == b.get("topic") == s3["topic"], "S3: topics differ")
    check(a["status"] == b["status"] == "accepted" and a["scope"] != b["scope"], "S3: not two active, scoped ADRs")
    check("problem+json" in " ".join(p.read_text() for p, _ in adrs[s3["adrs"][0]]) and
          "{ \"code\"" in " ".join(p.read_text() for p, _ in adrs[s3["adrs"][1]]), "S3: formats not in conflict")

    # --- S4 standard bypass: repos whose code imports requests instead of platform_libs.http_client
    s4 = man["scenarios"]["S4_standard_bypass"]
    for ref_id, want_override in [(x, True) for x in s4["with_override"]] + [(x, False) for x in s4["without_override"]]:
        repo, num = ref_id.split("#")
        pr = next((p for p in prs if p["repo"] == repo and p["number"] == int(num)), None)
        check(pr is not None, f"S4: missing PR {ref_id}")
        if not pr:
            continue
        touched = [root / "repos" / repo / f for f in pr["files"]]
        raw = any("requests" in py_imports(f) for f in touched if f.suffix == ".py")
        check(raw, f"S4: {ref_id} does not introduce raw `requests`")
        has = bool(re.search(r"^Override:\s*ADR-004\b.*reason=", pr["body"], re.M))
        check(has == want_override, f"S4: {ref_id} override-present={has}, expected {want_override}")

    # --- S5 impact radius from code, not manifest
    s5 = man["scenarios"]["S5_multi_service_feature"]
    svc_urls = {"ledger-core.internal": "ledger-core", "notify-svc.internal": "notify-svc",
                "payments-api.internal": "payments-api"}
    dep: dict[str, set[str]] = {r: set() for r in repos}
    for r in repos:
        for py in (root / "repos" / r).rglob("*.py"):
            txt = py.read_text()
            for host, target in svc_urls.items():
                if host in txt and target != r:
                    dep[r].add(target)
            if "platform_libs" in py_imports(py) and r != "platform-libs":
                dep[r].add("platform-libs")
    seen, stack = set(), ["customer-portal"]
    while stack:
        n = stack.pop()
        for m in dep.get(n, ()):
            if m not in seen and m != "platform-libs":
                seen.add(m)
                stack.append(m)
    impact = sorted(seen | {"customer-portal"})
    check(impact == s5["impact"], f"S5: derived impact {impact} != {s5['impact']}")
    check(any(t["key"] == s5["ticket"] for t in jira), "S5: ticket missing")

    # --- S6 reuse: duplicate class has near-identical interface to the shared one
    s6 = man["scenarios"]["S6_reuse_candidate"]
    (r1, f1), (r2, f2) = s6["existing"].split(":"), s6["duplicate"].split(":")
    m1 = methods(root / "repos" / r1 / f1, "IdempotencyStore")
    m2 = methods(root / "repos" / r2 / f2, "DedupeStore")
    jac = len(m1 & m2) / max(len(m1 | m2), 1)
    check(jac >= 0.8, f"S6: interface overlap only {jac:.2f}")

    # --- S7 superseded ADR still referenced in code
    s7 = man["scenarios"]["S7_superseded_decision"]
    old, new = adrs[s7["superseded"]][0][1], adrs[s7["by"]][0][1]
    check(old["status"] == "superseded" and old.get("superseded-by") == s7["by"], "S7: ADR-002 not marked superseded")
    check(new["status"] == "accepted" and new.get("supersedes") == s7["superseded"], "S7: ADR-007 does not supersede")
    r, f = s7["stale_reference"].split(":")
    check(s7["superseded"] in (root / "repos" / r / f).read_text(), "S7: no stale reference in code")

    # --- S8 migration risk: blocking ticket + the actual schema field
    s8 = man["scenarios"]["S8_migration_risk"]
    blocker = next((t for t in jira if t["key"] == s8["ticket"]), None)
    check(blocker is not None and blocker["status"] != "Done", "S8: blocker missing or done")
    feat = next(t for t in jira if t["key"] == s8["blocks"])
    check({"type": "blocked-by", "key": s8["ticket"]} in feat["links"], "S8: feature not blocked-by ticket")
    path, field = s8["field"].split(":")
    check(field in (root / "repos" / "ledger-core" / path).read_text(), "S8: field missing from model")
    return errs


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "fixtures" / "northwind")
    problems = validate(root)
    if problems:
        print("INVALID:")
        print("\n".join(f" - {p}" for p in problems))
        sys.exit(1)
    print(f"OK: synthetic org at {root} satisfies all 8 scenarios")
