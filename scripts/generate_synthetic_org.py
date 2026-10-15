#!/usr/bin/env python3
"""Deterministically generate the synthetic "Northwind Labs" organization.

Output (default: fixtures/northwind/):
  org.json, people.json, teams.json, manifest.json
  repos/<repo>/...            real Python source, READMEs, ADRs, CODEOWNERS
  history/<repo>.commits.json, prs.json, jira.json

Everything is synthetic: *.example addresses only, no real people, no credentials.
No model calls: same seed => byte-identical output (checked in tests).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import date, timedelta
from pathlib import Path

REF_DATE = date(2026, 9, 15)  # the fixture's "today"
WINDOW_START = date(2026, 3, 15)
ORG = {"slug": "northwind", "name": "Northwind Labs", "is_synthetic": True}
DOMAIN = "northwind.example"

PEOPLE = {
    "dana.okafor": ("Dana Okafor", "Payments"),
    "priya.raman": ("Priya Raman", "Payments"),
    "marcus.lee": ("Marcus Lee", "Platform"),
    "ines.kowalski": ("Ines Kowalski", "Platform"),
    "sofia.alvarez": ("Sofia Alvarez", "Experience"),
    "tom.becker": ("Tom Becker", "Experience"),
}
REPO_TEAM_POOL = {
    "ledger-core": ["dana.okafor", "priya.raman"],
    "payments-api": ["priya.raman", "marcus.lee", "ines.kowalski"],
    "notify-svc": ["sofia.alvarez", "tom.becker", "marcus.lee"],
    "customer-portal": ["tom.becker", "sofia.alvarez", "priya.raman"],
    "platform-libs": ["marcus.lee", "ines.kowalski", "priya.raman"],
}
TEAM_FILE_OWNERS = {
    "ledger-core": "dana.okafor", "payments-api": "priya.raman", "notify-svc": "sofia.alvarez",
    "customer-portal": "tom.becker", "platform-libs": "marcus.lee",
}

# ------------------------------------------------------------------ source files
FILES: dict[str, dict[str, str]] = {
    "platform-libs": {
        "README.md": "# platform-libs\n\nShared Northwind libraries: HTTP client, idempotency, auth, error format.\n"
                     "All outbound HTTP MUST use `platform_libs.http_client` (ADR-004).\n",
        "platform_libs/__init__.py": "",
        "platform_libs/http_client.py": '''"""Outbound HTTP with enforced timeouts and bounded retries (ADR-004)."""
import urllib.request

DEFAULT_TIMEOUT_S = 5
MAX_RETRIES = 2


def request(method: str, url: str, body: bytes | None = None, timeout: float = DEFAULT_TIMEOUT_S) -> bytes:
    last_exc: Exception | None = None
    for _ in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, data=body, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except OSError as exc:
            last_exc = exc
    raise RuntimeError(f"request failed: {url}") from last_exc
''',
        "platform_libs/idempotency.py": '''"""Idempotency keys for mutating endpoints. Reuse this; do not re-implement."""


class IdempotencyStore:
    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def claim(self, key: str, fingerprint: str) -> bool:
        """Return True if this key is new; False if it was already claimed."""
        if key in self._seen:
            return False
        self._seen[key] = fingerprint
        return True

    def release(self, key: str) -> None:
        self._seen.pop(key, None)

    def result(self, key: str) -> str | None:
        return self._seen.get(key)
''',
        "platform_libs/errors.py": '''"""RFC 7807 problem+json error bodies (ADR-005)."""


def problem(status: int, title: str, detail: str = "") -> dict:
    return {"type": "about:blank", "title": title, "status": status, "detail": detail}
''',
        "platform_libs/auth.py": '''def require_service_token(headers: dict) -> str:
    token = headers.get("X-Service-Token", "")
    if not token:
        raise PermissionError("missing service token")
    return token
''',
        "tests/test_idempotency.py": '''from platform_libs.idempotency import IdempotencyStore


def test_claim_once():
    s = IdempotencyStore()
    assert s.claim("k", "f") is True
    assert s.claim("k", "f") is False
''',
        "docs/adr/ADR-001-fastapi.md": "# ADR-001: Use FastAPI for HTTP services\n\nStatus: accepted\nDate: 2026-01-12\nScope: org\n\n"
            "All new Northwind HTTP services use FastAPI.\n",
        "docs/adr/ADR-004-outbound-http.md": "# ADR-004: Outbound HTTP goes through platform_libs.http_client\n\nStatus: accepted\n"
            "Date: 2026-02-03\nScope: org\nTopic: outbound-http\n\n"
            "Every outbound HTTP call must use `platform_libs.http_client.request` so timeouts and bounded retries "
            "are enforced. Exceptions require an `Override:` trailer in the PR description naming this ADR and a reason.\n",
        "docs/adr/ADR-005-problem-json.md": "# ADR-005: Errors use RFC 7807 problem+json\n\nStatus: accepted\nDate: 2026-02-10\n"
            "Scope: payments-api, platform-libs\nTopic: error-format\n\n"
            "HTTP errors are returned as `application/problem+json` using `platform_libs.errors.problem`.\n",
        "CODEOWNERS": "* @marcus.lee\n",
    },
    "ledger-core": {
        "README.md": "# ledger-core\n\nSource of truth for money movements. Amounts are integer minor units (ADR-003).\n",
        "ledger/__init__.py": "",
        "ledger/models.py": '''from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    id: str
    payment_id: str
    amount_cents: int  # ADR-003: integer minor units; see LED-88 for widening
    currency: str
    kind: str  # "capture" | "refund" | "adjustment"
''',
        "ledger/entries.py": '''from .models import Entry

_ENTRIES: dict[str, Entry] = {}


def post_entry(entry: Entry) -> Entry:
    if entry.id in _ENTRIES:
        return _ENTRIES[entry.id]
    _ENTRIES[entry.id] = entry
    return entry


def get_entry(entry_id: str) -> Entry | None:
    return _ENTRIES.get(entry_id)
''',
        "ledger/reconcile.py": '''"""Nightly reconciliation of ledger entries against processor settlement files.

Critical path: month-end close depends on this module.
"""
from platform_libs.http_client import request

from .entries import _ENTRIES


def reconcile_batch(settlement_url: str) -> dict:
    raw = request("GET", settlement_url)
    expected = len(raw.splitlines())
    return {"expected": expected, "posted": len(_ENTRIES), "balanced": expected == len(_ENTRIES)}
''',
        "ledger/api.py": '''from fastapi import APIRouter

from .entries import get_entry, post_entry
from .models import Entry

router = APIRouter()


@router.post("/v1/ledger/entries")
def create_entry(body: dict) -> dict:
    e = post_entry(Entry(**body))
    return {"id": e.id}


@router.get("/v1/ledger/entries/{entry_id}")
def read_entry(entry_id: str) -> dict:
    e = get_entry(entry_id)
    return {"found": e is not None}
''',
        "tests/test_entries.py": '''from ledger.entries import post_entry
from ledger.models import Entry


def test_post_is_idempotent():
    e = Entry("e1", "p1", 100, "EUR", "capture")
    assert post_entry(e) is post_entry(e)
''',
        "docs/adr/ADR-002-sync-http.md": "# ADR-002: Ledger and payments communicate via synchronous HTTP\n\nStatus: superseded\n"
            "Superseded-by: ADR-007\nDate: 2026-01-20\nScope: ledger-core, payments-api\nTopic: service-communication\n\n"
            "Payments calls ledger-core synchronously over HTTP when capturing.\n",
        "docs/adr/ADR-003-minor-units.md": "# ADR-003: Money is stored as integer minor units\n\nStatus: accepted\nDate: 2026-01-25\n"
            "Scope: org\nTopic: money-representation\n\nAll amounts are integers in minor currency units (`amount_cents`).\n",
        "docs/adr/ADR-007-outbox.md": "# ADR-007: Ledger writes are published through a transactional outbox\n\nStatus: accepted\n"
            "Supersedes: ADR-002\nDate: 2026-06-02\nScope: ledger-core, payments-api\nTopic: service-communication\n\n"
            "Ledger-affecting events are written to an outbox and delivered asynchronously. Direct synchronous "
            "calls from payments to ledger are deprecated.\n",
        "CODEOWNERS": "* @dana.okafor\n",
    },
    "payments-api": {
        "README.md": "# payments-api\n\nPublic payments API. Depends on ledger-core, notify-svc and platform-libs.\n",
        "payments/__init__.py": "",
        "payments/api.py": '''from fastapi import APIRouter
from platform_libs.errors import problem
from platform_libs.idempotency import IdempotencyStore

from .ledger_client import post_ledger_entry
from .notifier import notify_customer

router = APIRouter()
_store = IdempotencyStore()


@router.post("/v1/payments")
def create_payment(body: dict) -> dict:
    return {"id": body.get("id", "pay_1"), "status": "authorized"}


@router.post("/v1/payments/{payment_id}/capture")
def capture_payment(payment_id: str, body: dict) -> dict:
    key = body.get("idempotency_key", payment_id)
    if not _store.claim(key, payment_id):
        return problem(409, "duplicate capture")
    post_ledger_entry(payment_id, body["amount_cents"], body["currency"], "capture")
    notify_customer(payment_id, "payment_captured")
    return {"id": payment_id, "status": "captured"}
''',
        "payments/ledger_client.py": '''"""Client for ledger-core.

NOTE: synchronous call per ADR-002. (ADR-002 is superseded by ADR-007; migration to the outbox is pending.)
"""
import json

from platform_libs.http_client import request

LEDGER_URL = "http://ledger-core.internal/v1/ledger/entries"


def post_ledger_entry(payment_id: str, amount_cents: int, currency: str, kind: str) -> None:
    payload = {"id": f"{payment_id}:{kind}", "payment_id": payment_id,
               "amount_cents": amount_cents, "currency": currency, "kind": kind}
    request("POST", LEDGER_URL, json.dumps(payload).encode())
''',
        "payments/notifier.py": '''import json

from platform_libs.http_client import request

NOTIFY_URL = "http://notify-svc.internal/v1/notifications"


def notify_customer(payment_id: str, template: str) -> None:
    request("POST", NOTIFY_URL, json.dumps({"payment_id": payment_id, "template": template}).encode())
''',
        "tests/test_api.py": '''from payments.api import create_payment


def test_create_payment():
    assert create_payment({"id": "p1"})["status"] == "authorized"
''',
        "docs/adr/ADR-005-problem-json.md": "# ADR-005 (applied): payments-api returns problem+json\n\nStatus: accepted\nScope: payments-api\n"
            "Topic: error-format\n\nSee platform-libs ADR-005.\n",
        "CODEOWNERS": "* @priya.raman\n",
    },
    "notify-svc": {
        "README.md": "# notify-svc\n\nEmail/SMS notifications. Error envelope is `{code, message}` (ADR-006).\n",
        "notify/__init__.py": "",
        "notify/api.py": '''from fastapi import APIRouter

from .dedupe import DedupeStore
from .sender import send

router = APIRouter()
_dedupe = DedupeStore()


@router.post("/v1/notifications")
def create_notification(body: dict) -> dict:
    key = body.get("dedupe_key", body.get("payment_id", ""))
    if not _dedupe.claim(key, body.get("template", "")):
        return {"code": "duplicate", "message": "already sent"}
    send(body)
    return {"code": "ok", "message": "queued"}
''',
        "notify/dedupe.py": '''"""Notification de-duplication (own implementation, added in PR #48)."""


class DedupeStore:
    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def claim(self, key: str, fingerprint: str) -> bool:
        if key in self._seen:
            return False
        self._seen[key] = fingerprint
        return True

    def release(self, key: str) -> None:
        self._seen.pop(key, None)

    def result(self, key: str) -> str | None:
        return self._seen.get(key)
''',
        "notify/sender.py": '''"""Provider delivery. Uses `requests` directly (override recorded in PR #41)."""
import requests

PROVIDER_URL = "https://mail-provider.example/send"


def send(body: dict) -> None:
    requests.post(PROVIDER_URL, json=body, timeout=30)
''',
        "tests/test_dedupe.py": '''from notify.dedupe import DedupeStore


def test_dedupe():
    s = DedupeStore()
    assert s.claim("a", "x") and not s.claim("a", "x")
''',
        "docs/adr/ADR-006-code-message.md": "# ADR-006: Notification errors use a {code, message} envelope\n\nStatus: accepted\n"
            "Date: 2026-03-04\nScope: notify-svc\nTopic: error-format\n\n"
            "notify-svc responses use `{ \"code\": ..., \"message\": ... }` so downstream templates stay simple.\n",
        "CODEOWNERS": "* @sofia.alvarez\n",
    },
    "customer-portal": {
        "README.md": "# customer-portal\n\nBackend-for-frontend for the customer web app. Calls payments-api.\n",
        "portal/__init__.py": "",
        "portal/bff.py": '''"""BFF endpoints. NOTE: uses `requests` directly (no override recorded; see PR #57)."""
import requests

PAYMENTS_URL = "http://payments-api.internal/v1/payments"


def capture(payment_id: str, amount_cents: int, currency: str) -> dict:
    r = requests.post(f"{PAYMENTS_URL}/{payment_id}/capture",
                      json={"amount_cents": amount_cents, "currency": currency}, timeout=60)
    return r.json()


def list_receipts(customer_id: str) -> list[dict]:
    return []
''',
        "tests/test_bff.py": '''from portal.bff import list_receipts


def test_list_receipts_empty():
    assert list_receipts("c1") == []
''',
        "CODEOWNERS": "* @tom.becker\n",
    },
}

# ------------------------------------------------------------------ helpers
def d(s: date) -> str:
    return s.isoformat()


def sha(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def spread(n: int, start: date, end: date) -> list[date]:
    span = (end - start).days
    return [start + timedelta(days=(i * span) // max(n - 1, 1)) for i in range(n)]


def source_files(repo: str) -> list[str]:
    return [p for p in FILES[repo] if p.endswith(".py") and "/tests/" not in "/" + p and not p.startswith("tests/")]


# ------------------------------------------------------------------ history
def build_commits() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    dana_last = date(2026, 4, 20)  # S2: inactive > 90 days at REF_DATE
    for repo, pool in REPO_TEAM_POOL.items():
        files = source_files(repo) or list(FILES[repo])
        commits: list[dict] = []
        n = 40 if repo == "ledger-core" else 24
        dates = spread(n, WINDOW_START, REF_DATE - timedelta(days=3))
        if repo == "ledger-core":  # S1/S2: Dana owns ledger; her activity stops 2026-04-20
            dana_dates = spread(36, WINDOW_START, dana_last)
            other_dates = [date(2026, 5, 6), date(2026, 6, 12), date(2026, 7, 21), date(2026, 8, 18)]
            plan = [("dana.okafor", x) for x in dana_dates] + [("priya.raman", x) for x in other_dates]
            plan.sort(key=lambda t: t[1])
            for i, (author, when) in enumerate(plan):
                f = "ledger/reconcile.py" if (author == "dana.okafor" and i % 2 == 0) else files[i % len(files)]
                if author != "dana.okafor":
                    f = "ledger/models.py"
                commits.append(_commit(repo, i, author, when, f))
        else:
            for i, when in enumerate(dates):
                author = pool[i % len(pool)]  # round-robin => no dominant owner
                commits.append(_commit(repo, i, author, when, files[i % len(files)]))
        out[repo] = commits
    return out


def _commit(repo: str, i: int, author: str, when: date, path: str) -> dict:
    return {"sha": sha(repo, str(i), author, d(when)), "repo": repo, "author": author,
            "email": f"{author}@{DOMAIN}", "date": d(when), "files": [path],
            "message": f"{'feat' if i % 3 else 'fix'}({path.split('/')[0]}): update {path.split('/')[-1]} (#{i + 1})"}


def build_jira() -> list[dict]:
    t: list[dict] = []

    def add(key, summary, desc, status, assignee, typ="Task", created="2026-05-01", links=None, labels=None):
        t.append({"key": key, "project": key.split("-")[0], "type": typ, "summary": summary,
                  "description": desc, "status": status, "assignee": assignee, "reporter": "ines.kowalski",
                  "created": created, "updated": d(REF_DATE - timedelta(days=2)),
                  "links": links or [], "labels": labels or [], "synthetic": True})

    add("PAY-142", "Support partial refunds",
        "Customers need partial refunds on captured payments. Expose POST /v1/payments/{id}/refund, write refund "
        "entries to the ledger, notify the customer, and surface refunds in the portal.",
        "Backlog", "priya.raman", typ="Story", created="2026-09-01",
        links=[{"type": "blocked-by", "key": "LED-88"}, {"type": "relates-to", "key": "NTF-31"}],
        labels=["feature-request", "refunds"])
    add("LED-88", "Migrate ledger amounts to widened numeric type",
        "amount_cents is int32 in the ledger table. Multi-currency partial refunds need a wider type; requires a "
        "backfill migration with a maintenance window.",
        "In Progress", "dana.okafor", typ="Task", created="2026-03-30",
        links=[{"type": "blocks", "key": "PAY-142"}], labels=["migration", "risk"])
    add("NTF-31", "Refund confirmation email template", "Template + localisation for refund emails.",
        "To Do", "sofia.alvarez", links=[{"type": "relates-to", "key": "PAY-142"}])
    add("NTF-27", "Reduce duplicate notification sends",
        "Implemented own de-dupe in notify-svc (PR #48). Check whether platform-libs idempotency should be reused.",
        "Done", "sofia.alvarez", created="2026-06-10", labels=["duplication"])
    add("PLT-12", "Enforce outbound HTTP via platform_libs.http_client (ADR-004)",
        "Audit repos for raw requests/urllib usage.", "In Progress", "marcus.lee", created="2026-04-02")
    add("LED-71", "Reconcile job fails on settlement files > 50MB",
        "reconcile_batch loads the whole file. Only Dana knows this path.", "To Do", "dana.okafor",
        typ="Bug", created="2026-04-14", labels=["bus-factor"])
    add("PAY-120", "Move ledger posting to outbox (ADR-007)", "Implements ADR-007; replaces sync calls.",
        "To Do", "priya.raman", typ="Story", created="2026-06-03")
    add("POR-33", "Portal receipt list pagination", "Paginate receipts.", "Done", "tom.becker", created="2026-05-20")
    add("NTF-19", "Standardise notification error envelope", "Keep {code, message} (ADR-006).", "Done",
        "sofia.alvarez", created="2026-03-10")
    add("PAY-98", "Adopt problem+json for all payments errors (ADR-005)", "Per ADR-005.", "Done",
        "priya.raman", created="2026-03-02")
    add("PLT-19", "Document override process for ADR-004", "Overrides use an `Override:` trailer.", "Done",
        "ines.kowalski", created="2026-04-20")
    add("POR-41", "Portal: call payments via platform http client", "Follow-up to PLT-12.", "To Do",
        "tom.becker", created="2026-08-05")
    projects = {"PAY": "payments", "LED": "ledger", "NTF": "notifications", "POR": "portal", "PLT": "platform"}
    people = list(PEOPLE)
    n = 0
    for proj, word in projects.items():
        for i in range(1, 7):
            n += 1
            key = f"{proj}-{200 + i}"
            add(key, f"{word.capitalize()} housekeeping task {i}", f"Routine {word} maintenance item {i}.",
                ["Done", "Done", "In Progress", "To Do"][i % 4], people[(n + i) % len(people)],
                created=d(WINDOW_START + timedelta(days=n * 5)))
    return t


def build_prs(jira: list[dict]) -> list[dict]:
    prs: list[dict] = []
    counters: dict[str, int] = {}

    def add(repo, number, title, author, merged, files, body="", tickets=None, reviewers=None, labels=None,
            adds_imports=None):
        prs.append({"repo": repo, "number": number, "title": title, "author": author,
                    "reviewers": reviewers or [p for p in REPO_TEAM_POOL[repo] if p != author][:1],
                    "state": "merged", "created_at": d(merged - timedelta(days=2)), "merged_at": d(merged),
                    "files": files, "body": body, "linked_tickets": tickets or [], "labels": labels or [],
                    "adds_imports": adds_imports or [], "synthetic": True})
        counters[repo] = max(counters.get(repo, 0), number)

    # handcrafted scenario PRs (S4, S6)
    add("notify-svc", 41, "Send via provider SDK with longer timeout", "sofia.alvarez", date(2026, 5, 14),
        ["notify/sender.py"],
        "Provider needs a 30s timeout; http_client caps at 5s.\n\nOverride: ADR-004 reason=provider batch endpoint "
        "needs 30s timeout; temporary until http_client supports per-call timeouts; approved-by=ines.kowalski",
        ["PLT-12"], ["ines.kowalski"], ["override"], adds_imports=["requests"])
    add("customer-portal", 57, "Call payments-api capture from BFF", "tom.becker", date(2026, 7, 8),
        ["portal/bff.py"], "Adds capture endpoint to BFF using requests.", ["POR-41"], ["sofia.alvarez"],
        adds_imports=["requests"])
    add("notify-svc", 48, "Add own de-dupe store for notifications", "sofia.alvarez", date(2026, 6, 10),
        ["notify/dedupe.py", "notify/api.py"], "Avoid duplicate sends.", ["NTF-27"], ["tom.becker"])
    add("platform-libs", 22, "Add IdempotencyStore", "marcus.lee", date(2026, 4, 9),
        ["platform_libs/idempotency.py"], "Shared idempotency primitive for mutating endpoints.", [],
        ["priya.raman"])
    add("ledger-core", 30, "Reconcile: stream settlement file", "dana.okafor", date(2026, 4, 18),
        ["ledger/reconcile.py"], "Partial work; see LED-71.", ["LED-71"], ["priya.raman"])
    # filler PRs round-robin per repo (balanced authorship)
    keys = [t["key"] for t in jira if t["status"] == "Done"]
    seq = 0
    for repo, pool in REPO_TEAM_POOL.items():
        files = source_files(repo)
        n = 10
        for i in range(n):
            seq += 1
            number = counters.get(repo, 0) + 1
            author = pool[i % len(pool)]
            when = WINDOW_START + timedelta(days=12 + i * 14 + len(repo) % 5)
            if repo == "ledger-core":
                author, when = "dana.okafor", WINDOW_START + timedelta(days=5 + i * 3)
                files_i = ["ledger/reconcile.py"] if i % 2 == 0 else [files[i % len(files)]]
            else:
                files_i = [files[i % len(files)]]
            add(repo, number, f"{repo}: improve {files_i[0].split('/')[-1]} ({seq})", author, when, files_i,
                "Routine change.", [keys[seq % len(keys)]])
    return prs


# ------------------------------------------------------------------ manifest + IO
def build_manifest(commits, prs, jira) -> dict:
    return {
        "organization": ORG, "reference_date": d(REF_DATE), "repos": sorted(FILES),
        "counts": {
            "repos": len(FILES), "people": len(PEOPLE), "jira_issues": len(jira), "pull_requests": len(prs),
            "commits": sum(len(v) for v in commits.values()),
            "adrs": sum(1 for r in FILES.values() for p in r if "/adr/" in p),
        },
        "scenarios": {
            "S1_single_owner": {"repo": "ledger-core", "path": "ledger/reconcile.py", "author": "dana.okafor", "min_share": 0.9},
            "S2_inactive_owner": {"person": "dana.okafor", "repo": "ledger-core", "min_inactive_days": 90},
            "S3_conflicting_conventions": {"adrs": ["ADR-005", "ADR-006"], "topic": "error-format"},
            "S4_standard_bypass": {"adr": "ADR-004", "with_override": ["notify-svc#41"], "without_override": ["customer-portal#57"]},
            "S5_multi_service_feature": {"ticket": "PAY-142", "impact": ["customer-portal", "ledger-core", "notify-svc", "payments-api"]},
            "S6_reuse_candidate": {"existing": "platform-libs:platform_libs/idempotency.py", "duplicate": "notify-svc:notify/dedupe.py"},
            "S7_superseded_decision": {"superseded": "ADR-002", "by": "ADR-007", "stale_reference": "payments-api:payments/ledger_client.py"},
            "S8_migration_risk": {"ticket": "LED-88", "blocks": "PAY-142", "field": "ledger/models.py:amount_cents"},
        },
    }


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def generate(out: Path) -> dict:
    if out.exists():
        shutil.rmtree(out)
    for repo, files in FILES.items():
        for rel, content in files.items():
            p = out / "repos" / repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
    commits = build_commits()
    jira = build_jira()
    prs = build_prs(jira)
    for repo, c in commits.items():
        write_json(out / "history" / f"{repo}.commits.json", c)
    write_json(out / "history" / "prs.json", prs)
    write_json(out / "history" / "jira.json", jira)
    write_json(out / "org.json", ORG)
    write_json(out / "people.json", [{"login": k, "name": v[0], "team": v[1], "email": f"{k}@{DOMAIN}", "synthetic": True}
                                    for k, v in PEOPLE.items()])
    write_json(out / "teams.json", {"Payments": ["dana.okafor", "priya.raman"], "Platform": ["marcus.lee", "ines.kowalski"],
                                    "Experience": ["sofia.alvarez", "tom.becker"]})
    manifest = build_manifest(commits, prs, jira)
    write_json(out / "manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "fixtures" / "northwind"))
    args = ap.parse_args()
    m = generate(Path(args.out))
    print(json.dumps(m["counts"], indent=2))
