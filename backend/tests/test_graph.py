from pathlib import Path

import pytest

from app.graph.impact import impact
from app.ingestion.fixtures import ingest
from app.knowledge.build_graph import build
from tests.fake_model import ideal_provider

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"


@pytest.fixture()
def org(conn):
    org_id, _ = ingest(conn, FIX)
    build(conn, org_id, ideal_provider())
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
    build(conn, org, ideal_provider())
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
    assert risks["LED-88"]["evidence_type"] == "explicit" and risks["LED-88"]["predicate"] == "open_blocker"

    conflict = _facts(conn, "conflict")[0]
    assert conflict["object_value"] == "ADR-005+ADR-006" and conflict["status"] == "candidate"
    assert conflict["evidence_type"] == "inferred"

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
    st = build(conn, org, ideal_provider())
    status = {r["id"]: r["status"] for r in conn.execute("SELECT id,status FROM facts WHERE id = ANY(%s)", ([stale, mine],))}
    assert status[stale] == "rejected" and status[mine] == "candidate" and st.retired == 1
    assert build(conn, org, ideal_provider()).retired == 0  # steady state: nothing more to retire


def test_without_an_llm_no_judgment_facts_are_invented(conn):
    org_id, _ = ingest(conn, FIX)
    st = build(conn, org_id)  # no provider: conflicts, compliance and reuse are not guessed from rules
    kinds = {r["fact_type"] for r in conn.execute("SELECT DISTINCT fact_type FROM facts")}
    assert not ({"conflict", "override", "reuse"} & kinds)
    assert not any(f["predicate"] == "unrecorded_standard_bypass" for f in _facts(conn, "risk"))
    assert {"decision", "ownership"} <= kinds and st.judgments == {}


def test_model_quotes_must_exist_in_the_source(conn):
    def bad_pairs(p):
        return {"pairs": [{"a": x["a"], "b": x["b"], "relation": "conflict", "reason": "r",
                           "quote_a": "this sentence is not in the ADR", "quote_b": "neither is this"}
                          for x in p["pairs"]]}

    def bad_pr(p):
        return {"findings": [{"pr": pr["id"], "adr": "ADR-004", "verdict": "violates", "override_recorded": True,
                              "override_quote": "Override: invented words", "reason": "r"} for pr in p["pull_requests"]]}

    org_id, _ = ingest(conn, FIX)
    build(conn, org_id, ideal_provider(decision_pairs=bad_pairs, pr_compliance=bad_pr))
    assert _facts(conn, "conflict") == []  # fabricated quotes -> finding discarded
    assert _facts(conn, "override") == []  # an override is only recorded when its quote is in the PR text
    assert all(f["evidence_type"] == "inferred" for f in _facts(conn, "risk") if "@" in f["object_value"])


def test_reuse_pairs_must_span_repositories_and_exist(conn):
    org_id, _ = ingest(conn, FIX)
    build(conn, org_id, ideal_provider(reuse_pairs=lambda p: {"pairs": [
        {"existing": "x:a.py::A", "duplicate": "x:b.py::B", "reason": "unknown ids"}]}))
    assert _facts(conn, "reuse") == []


def test_unknown_real_world_jira_link_types_do_not_break_the_build(conn):
    import json
    from pathlib import Path
    from app.ingestion.fixtures import ingest
    from app.knowledge.build_graph import build
    from tests.fake_model import ideal_provider
    org, _ = ingest(conn, Path(__file__).resolve().parents[2] / "fixtures" / "northwind")
    rows = conn.execute("SELECT id, payload FROM source_records WHERE organization_id=%s AND source_type='jira_issue' ORDER BY id LIMIT 2", (org,)).fetchall()
    a, b = rows[0], rows[1]
    p = a["payload"]; p["links"] = [{"key": b["payload"]["key"], "type": "is-blocked-by"}, {"key": b["payload"]["key"], "type": "duplicates"}]
    conn.execute("UPDATE source_records SET payload=%s::jsonb WHERE id=%s", (json.dumps(p), a["id"]))
    build(conn, org, ideal_provider(choose=lambda x: []))
    rels = {r["rel_type"] for r in conn.execute("SELECT rel_type FROM edges WHERE organization_id=%s", (org,))}
    assert {"blocked_by", "relates_to"} <= rels
