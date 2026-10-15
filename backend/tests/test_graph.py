from pathlib import Path

import pytest

from app.graph.impact import impact
from app.ingestion.fixtures import ingest
from app.knowledge.build_graph import build

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"


@pytest.fixture()
def org(conn):
    org_id, _ = ingest(conn, FIX)
    build(conn, org_id)
    return org_id


def _totals(conn):
    return {t: conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in ("entities", "edges", "facts")}


def test_known_three_hop_path_with_evidence(conn, org):
    res = impact(conn, org, ["customer-portal"], depth=3)
    by = {d["service"]: d for d in res["dependencies"]}
    assert by["payments-api"]["depth"] == 1
    assert by["ledger-core"]["path"] == ["customer-portal", "payments-api", "ledger-core"]
    assert "platform-libs" in by
    for hop in by["ledger-core"]["evidence"]:
        assert hop["evidence_type"] == "structural" and hop["source"]


def test_feature_impact_radius(conn, org):
    res = impact(conn, org, ["payments-api"], depth=3)
    assert {d["service"] for d in res["dependents"]} == {"customer-portal"}
    assert {"ledger-core", "notify-svc", "platform-libs"} <= {d["service"] for d in res["dependencies"]}


def test_depth_is_bounded(conn, org):
    res = impact(conn, org, ["customer-portal"], depth=1)
    assert {d["service"] for d in res["dependencies"]} <= {"payments-api", "platform-libs"} | {"notify-svc"}
    assert all(d["depth"] == 1 for d in res["dependencies"])


def test_build_is_idempotent(conn, org):
    before = _totals(conn)
    build(conn, org)
    assert _totals(conn) == before


def _facts(conn, ftype):
    return conn.execute("SELECT * FROM facts WHERE fact_type=%s ORDER BY object_value", (ftype,)).fetchall()


def test_seeded_scenarios_become_facts(conn, org):
    own = {(f["predicate"], f["object_value"]) for f in _facts(conn, "ownership")}
    assert ("single_dominant_contributor", "ledger-core:ledger/reconcile.py") in own
    assert ("dormant_owner", "dana.okafor@ledger-core") in own

    ov = _facts(conn, "override")
    assert [f["object_value"] for f in ov] == ["ADR-004@notify-svc#41"]
    assert ov[0]["status"] == "active" and ov[0]["evidence_type"] == "explicit"

    risks = {f["object_value"]: f for f in _facts(conn, "risk")}
    bypass = risks["ADR-004@customer-portal#57"]
    assert bypass["status"] == "candidate" and bypass["evidence_type"] == "inferred"
    assert "ADR-004@notify-svc#41" not in risks  # overridden => not flagged
    flagged = sorted(k for k in risks if k.startswith("ADR-004@"))
    assert flagged == ["ADR-004@customer-portal#57"]  # PRs that merely touch the file are not flagged
    assert risks["LED-88"]["evidence_type"] == "explicit"

    conflict = _facts(conn, "conflict")[0]
    assert conflict["object_value"] == "ADR-005+ADR-006" and conflict["status"] == "candidate"

    dec = {f["object_value"]: f for f in _facts(conn, "decision")}
    assert dec["ADR-002"]["status"] == "superseded" and dec["ADR-007"]["status"] == "active"
    assert dec["ADR-002"]["superseded_by"] == dec["ADR-007"]["id"]

    reuse = _facts(conn, "reuse")[0]
    assert "notify/dedupe.py" in reuse["object_value"] and reuse["status"] == "candidate"


def test_admission_policy_invariants(conn, org):
    # inferred claims are never presented as active/verified; every fact has a source
    assert conn.execute("SELECT count(*) AS n FROM facts WHERE evidence_type='inferred' AND status='active'"
                        ).fetchone()["n"] == 0
    assert conn.execute("SELECT count(*) AS n FROM facts WHERE source_id='' OR source_type=''").fetchone()["n"] == 0
    assert conn.execute("SELECT count(*) AS n FROM edges WHERE source_ref IS NULL AND source_record_id IS NULL"
                        ).fetchone()["n"] == 0


def test_rebuild_retires_stale_derived_facts_but_keeps_user_facts(conn, org):
    ins = ("INSERT INTO facts (organization_id,fact_type,predicate,object_value,summary,evidence_type,status,"
           "source_type,source_id,author) VALUES (%s,'risk','p',%s,'s','inferred','candidate','github_pr',%s,%s) RETURNING id")
    stale = conn.execute(ins, (org, "gone", "x#1", None)).fetchone()["id"]
    mine = conn.execute(ins, (org, "mine", "x#2", "owner")).fetchone()["id"]
    st = build(conn, org)
    status = {r["id"]: r["status"] for r in conn.execute("SELECT id,status FROM facts WHERE id = ANY(%s)", ([stale, mine],))}
    assert status[stale] == "rejected" and status[mine] == "candidate" and st.retired == 1
    assert build(conn, org).retired == 0  # steady state: nothing more to retire
