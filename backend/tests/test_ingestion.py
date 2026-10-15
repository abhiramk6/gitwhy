from pathlib import Path

from app.ingestion.fixtures import ingest

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"


def _counts(conn):
    return {
        t: conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
        for t in ("organizations", "repositories", "source_records")
    }


def test_rerun_creates_no_duplicates(conn):
    org_id, first = ingest(conn, FIX)
    after_first = _counts(conn)
    assert first.new == first.seen > 0 and first.changed == 0
    assert after_first["repositories"] == 5
    _, second = ingest(conn, FIX)
    assert second.new == 0 and second.changed == 0 and second.unchanged == second.seen == first.seen
    assert _counts(conn) == after_first


def test_provenance_and_run_records(conn):
    ingest(conn, FIX)
    missing = conn.execute("SELECT count(*) AS n FROM source_records WHERE source_url IS NULL OR content_hash=''"
                           ).fetchone()["n"]
    assert missing == 0
    runs = conn.execute("SELECT status, records_seen FROM ingestion_runs ORDER BY id").fetchall()
    assert runs and all(r["status"] == "succeeded" for r in runs)


def test_changed_content_updates_in_place(conn):
    org_id, _ = ingest(conn, FIX)
    conn.execute("UPDATE source_records SET content_hash='stale' WHERE source_id='PAY-142'")
    before = _counts(conn)
    _, st = ingest(conn, FIX)
    assert st.changed == 1 and st.new == 0 and _counts(conn) == before


def test_incremental_skips_already_ingested(conn):
    ingest(conn, FIX, "backfill")
    _, st = ingest(conn, FIX, "incremental")
    # only undated records (files/ADRs/docs) are re-evaluated; none are new
    assert st.new == 0 and st.changed == 0
    assert st.by_type.get("github_pr", 0) == 0 and st.by_type.get("jira_issue", 0) == 0
