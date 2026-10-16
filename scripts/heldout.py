#!/usr/bin/env python3
"""Held-out protocol tooling: freeze prompts, count runs per case, refuse reruns.

    scripts/heldout.py status     # frozen hash match? runs per case
    scripts/heldout.py freeze     # record the prompt/code hash (do this once, before the held-out run)

Scoring is deliberately not implemented here until the owner confirms the allowlists.
"""
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTO = ROOT / "eval" / "heldout_protocol.json"
COVERED = ["backend/app/intelligence/tasks.py", "backend/app/planning/planner.py", "backend/app/retrieval/search.py",
           "backend/app/knowledge/build_graph.py", "backend/app/knowledge/judgments.py", "backend/app/retrieval/embed.py",
           "backend/app/models/voyage.py"]


def prompt_hash() -> str:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import get_settings
    h = hashlib.sha256()
    for rel in COVERED:
        h.update(rel.encode() + b"\0" + (ROOT / rel).read_bytes() + b"\0")
    cfg = get_settings()   # effective configuration (env included): a run with a different model/provider is a different run
    h.update(json.dumps([getattr(cfg, k) for k in ("gen_model", "gen_fallback_models", "embed_provider", "embed_model",
                                                    "voyage_model", "voyage_dim")]).encode())
    return h.hexdigest()


def runs() -> dict[str, int]:
    log = ROOT / json.loads(PROTO.read_text())["run_log"]
    out: dict[str, int] = {}
    if log.exists():
        for line in log.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["case"]] = out.get(r["case"], 0) + 1
    return out


def assert_runnable(case_id: str) -> None:
    """Called before a held-out case is executed: file unchanged, prompts frozen and unchanged, run budget left."""
    p = json.loads(PROTO.read_text())
    got = hashlib.sha256((ROOT / p["frozen_file"]).read_bytes()).hexdigest()
    if got != p["frozen_sha256"]:
        raise SystemExit(f"held-out file changed (sha256 {got[:12]} != frozen {p['frozen_sha256'][:12]}): not a held-out run")
    fh = p["prompt_freeze"]["frozen_hash"]
    if not fh:
        raise SystemExit("prompts are not frozen: run `heldout.py freeze` first")
    if prompt_hash() != fh:
        raise SystemExit("prompts/code changed since freeze: held-out run refused")
    if runs().get(case_id, 0) >= p["runs_allowed_per_case"]:
        raise SystemExit(f"{case_id} has already been run {runs()[case_id]} time(s); budget is {p['runs_allowed_per_case']}")


def log_run(case_id: str, provider: str, model: str, outcome: str) -> None:
    p = json.loads(PROTO.read_text())
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "case": case_id, "provider": provider,
             "model": model, "prompt_hash": prompt_hash(), "outcome": outcome}
    with (ROOT / p["run_log"]).open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    p = json.loads(PROTO.read_text())
    if cmd == "freeze":
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", *COVERED],
                               capture_output=True, text=True).stdout.strip()
        if dirty:
            print("refusing to freeze: uncommitted changes in covered files:\n" + dirty)
            return 1
        p["prompt_freeze"].update(frozen_hash=prompt_hash(), frozen_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        p["status"] = "prompts frozen; held-out not yet run"
        PROTO.write_text(json.dumps(p, indent=2) + "\n")
        print("frozen:", p["prompt_freeze"]["frozen_hash"])
        return 0
    cases = [c["id"] for c in json.loads((ROOT / p["frozen_file"]).read_text())["cases"]]
    got = hashlib.sha256((ROOT / p["frozen_file"]).read_bytes()).hexdigest()
    r = runs()
    print(f"held-out file unchanged: {got == p['frozen_sha256']}")
    fh = p["prompt_freeze"]["frozen_hash"]
    print(f"prompts frozen: {bool(fh)}" + (f"; unchanged since freeze: {prompt_hash() == fh}" if fh else ""))
    print("runs per case (budget %d): " % p["runs_allowed_per_case"] + ", ".join(f"{c}={r.get(c, 0)}" for c in cases))
    return 0


if __name__ == "__main__":
    sys.exit(main())
