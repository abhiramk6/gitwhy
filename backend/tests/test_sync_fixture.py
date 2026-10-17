"""build_fixture run for real (git, file copying, record assembly) with only the GitHub network calls stubbed.

The wiring test in test_accounts.py replaces build_fixture wholesale, so a bug inside it (a PR's changed-file list overwriting
the repo list in the manifest) went unnoticed. This test reads the result back the way ingestion does.
"""
import json
import subprocess

from app.ingestion.fixtures import iter_records
from app.sync import github


def _repo(path):
    run = lambda *a: subprocess.run(["git", "-C", str(path), *a], check=True, capture_output=True)  # noqa: E731
    path.mkdir()
    run("init", "-q", "-b", "main")
    (path / "app.py").write_text('"""The app."""\n\n\ndef handler():\n    return 1\n')
    (path / "README.md").write_text("# Demo\n\nA demo.\n")
    run("add", ".")
    run("-c", "user.name=A", "-c", "user.email=a@example.test", "commit", "-q", "-m", "Add app (#7)")


def test_build_fixture_keeps_repo_names_and_ingests(tmp_path, monkeypatch):
    src = tmp_path / "src"
    _repo(src)
    pr = {"number": 7, "title": "Add app", "body": "Fixes #3", "merged_at": "2026-01-02T00:00:00Z", "user": {"login": "a"}, "head": {"ref": "b"}}
    issue = {"number": 3, "title": "Need app", "body": "", "state": "closed", "labels": [], "updated_at": "2026-01-01T00:00:00Z",
             "html_url": "https://github.com/acme/demo/issues/3"}

    def fake_pages(url, token, limit):
        if "/pulls?" in url:
            return iter([pr])
        if "/issues?" in url:
            return iter([issue])
        return iter([])

    monkeypatch.setattr(github, "_get", lambda url, token: {"html_url": "https://github.com/acme/demo", "default_branch": "main"})
    monkeypatch.setattr(github, "_pages", fake_pages)
    monkeypatch.setattr(github, "_clone", lambda full, token, dest, depth: subprocess.run(["git", "clone", "-q", str(src), str(dest)], check=True))
    monkeypatch.setattr(github, "pr_patches", lambda full, n, token: ({"app.py": "@@ -0,0 +1,2 @@\n+def handler():\n+    return 1"}, ["app.py"], 0))

    out = tmp_path / "fx"
    res = github.build_fixture(out, "acme", "Acme", ["acme/demo"], "ghp_x" * 4, {"commits": 10, "prs": 5, "issues": 5, "threads": 5}, [])
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["repos"] == ["demo"], manifest["repos"]
    assert res["counts"]["pull_requests"] == 1 and res["counts"]["issues"] == 1
    kinds = {}
    for rec in iter_records(out):
        kinds[rec.source_type] = kinds.get(rec.source_type, 0) + 1
    assert kinds["github_pr"] == 1 and kinds["github_commit"] == 1 and kinds["file"] == 1
    pr_rec = next(r for r in iter_records(out) if r.source_type == "github_pr")
    assert "app.py" in pr_rec.payload["files"] and "def handler" in pr_rec.payload["patches"]["app.py"]
