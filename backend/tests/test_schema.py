import psycopg
import pytest

from app import db


def test_migrations_idempotent(test_url):
    first = db.migrate(test_url)
    assert "001_init.sql" in first
    assert db.migrate(test_url) == []  # re-run applies nothing


def test_pgvector_available(conn):
    row = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
    assert row is not None


def test_source_record_unique_per_source(conn):
    org = conn.execute("INSERT INTO organizations (slug,name) VALUES ('t','T') RETURNING id").fetchone()["id"]
    q = ("INSERT INTO source_records (organization_id,source_type,source_id,content_hash) "
         "VALUES (%s,'jira_issue','PAY-1','h')")
    conn.execute(q, (org,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(q, (org,))


def test_fact_and_edge_constraints(conn):
    org = conn.execute("INSERT INTO organizations (slug,name) VALUES ('t2','T2') RETURNING id").fetchone()["id"]
    a = conn.execute("INSERT INTO entities (organization_id,entity_type,canonical_name) "
                     "VALUES (%s,'service','a') RETURNING id", (org,)).fetchone()["id"]
    with pytest.raises(psycopg.errors.CheckViolation):  # self-edge rejected
        conn.execute("INSERT INTO edges (organization_id,src_id,dst_id,rel_type,evidence_type) "
                     "VALUES (%s,%s,%s,'imports','structural')", (org, a, a))
    conn.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):  # LLM claims must use a known evidence_type
        conn.execute("INSERT INTO facts (organization_id,fact_type,predicate,object_value,summary,"
                     "evidence_type,source_type,source_id) VALUES (%s,'decision','p','o','s','guess','adr','1')",
                     (org,))
