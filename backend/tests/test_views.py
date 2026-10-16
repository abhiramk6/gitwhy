from pathlib import Path

import pytest

from app.api import views
from app.ingestion.fixtures import ingest

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"


@pytest.fixture()
def org(conn):
    return ingest(conn, FIX)[0]


def test_pr_list_has_comment_counts_and_newest_first(conn, org):
    rows = views.pr_list(conn, org, 100)
    assert rows[0]["merged_at"] >= rows[-1]["merged_at"]
    by = {r["id"]: r for r in rows}
    assert by["payments-api#6"]["comments"] == 3 and by["payments-api#11"]["comments"] == 0


def test_provenance_of_a_comment_returns_the_whole_thread_and_its_pr(conn, org):
    rid = conn.execute("SELECT id FROM source_records WHERE organization_id=%s AND source_id='payments-api#6/review_comment-9001'",
                       (org,)).fetchone()["id"]
    v = views.provenance(conn, org, rid)
    assert v["author"] == "priya.raman" and v["date"] == "2026-06-08"
    assert [t["who"] for t in v["thread"]] == ["priya.raman", "ines.kowalski", "priya.raman"]
    assert [t["current"] for t in v["thread"]] == [True, False, False]
    assert v["related"][0]["kind"] == "pull_request" and views.provenance(conn, org, 0) is None


def test_sources_report_counts_and_limits(conn, org):
    s = views.sources(conn, org)
    assert s["by_type"]["github_comment"]["count"] == 13 and s["embeddings"] == {} and s["limits"]


def test_tags_resolve_who_and_when_for_every_id_style(conn, org):
    rid = conn.execute("SELECT id FROM source_records WHERE organization_id=%s AND source_id='payments-api#6/review_comment-9001'",
                       (org,)).fetchone()["id"]
    out = views.tags(conn, org, [f"record:{rid}", f"hit:record:{rid}", "pr:payments-api#11", "ticket:PAY-142", "edge:a->b",
                                 "area:x/y", "record:nope", "record:0", "fact:0"])
    assert out[f"record:{rid}"]["who"] == "priya.raman" and out[f"hit:record:{rid}"]["when"] == "2026-06-08"
    assert out["pr:payments-api#11"]["who"] == "ines.kowalski" and out["ticket:PAY-142"]["type"] == "jira_issue"
    assert out["edge:a->b"]["type"] == "dependency" and "record:nope" not in out and "record:0" not in out and "fact:0" not in out
