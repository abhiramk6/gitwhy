import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load("generate_synthetic_org")
val = _load("validate_synthetic_org")


def _digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def test_generation_is_deterministic(tmp_path):
    gen.generate(tmp_path / "a")
    gen.generate(tmp_path / "b")
    assert _digest(tmp_path / "a") == _digest(tmp_path / "b")


def test_committed_fixtures_match_generator(tmp_path):
    gen.generate(tmp_path / "fresh")
    assert _digest(tmp_path / "fresh") == _digest(ROOT / "fixtures" / "northwind"), \
        "fixtures/northwind is stale: rerun scripts/generate_synthetic_org.py"


def test_all_scenarios_validate(tmp_path):
    gen.generate(tmp_path / "o")
    assert val.validate(tmp_path / "o") == []


def test_validator_catches_missing_override(tmp_path):
    root = tmp_path / "o"
    gen.generate(root)
    prs = json.loads((root / "history/prs.json").read_text())
    for p in prs:
        if p["repo"] == "notify-svc" and p["number"] == 41:
            p["body"] = "no override here"
    (root / "history/prs.json").write_text(json.dumps(prs))
    errs = val.validate(root)
    assert any("S4" in e and "notify-svc#41" in e for e in errs)


def test_validator_catches_active_owner(tmp_path):
    root = tmp_path / "o"
    gen.generate(root)
    path = root / "history/ledger-core.commits.json"
    cs = json.loads(path.read_text())
    cs[-1]["author"], cs[-1]["date"] = "dana.okafor", "2026-09-10"
    path.write_text(json.dumps(cs))
    assert any(e.startswith("S2") for e in val.validate(root))
