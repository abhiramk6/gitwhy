"""Jira connector: ADF flattening, link direction, idempotent sync (HTTP stubbed; no network)."""
from app.ingestion.jira import Jira, adf_text, map_links, sync, to_rec

ADF = {"type": "doc", "version": 1, "content": [
    {"type": "paragraph", "content": [{"type": "text", "text": "Expose POST /v1/refund"}]},
    {"type": "bulletList", "content": [{"type": "listItem", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "write ledger entry"}]}]}]},
    {"type": "paragraph", "content": [{"type": "text", "text": "see "}, {"type": "mention", "attrs": {"text": "@ines"}}]}]}


def issue(key="KAN-1", summary="Refunds", updated="2026-10-15T17:50:00.000+0000", links=None, desc=ADF):
    return {"key": key, "fields": {
        "summary": summary, "description": desc, "status": {"name": "To Do"}, "issuetype": {"name": "Story"},
        "labels": ["x"], "assignee": None, "reporter": {"displayName": "Rishi"}, "issuelinks": links or [],
        "created": "2026-10-15T17:40:00.000+0000", "updated": updated, "project": {"key": "KAN"},
        "comment": {"comments": [{"author": {"displayName": "Ines"}, "body": ADF}]}}}


def test_adf_flattens_structure_and_mentions():
    text = adf_text(ADF)
    assert "Expose POST /v1/refund" in text and "write ledger entry" in text and "@ines" in text
    assert adf_text(None) == ""


def test_link_direction_is_from_this_issues_point_of_view():
    out = map_links([{"type": {"name": "Blocks", "outward": "blocks", "inward": "is blocked by"},
                      "outwardIssue": {"key": "KAN-2"}},
                     {"type": {"name": "Blocks", "outward": "blocks", "inward": "is blocked by"},
                      "inwardIssue": {"key": "KAN-9"}}])
    assert out == [{"key": "KAN-2", "type": "blocks"}, {"key": "KAN-9", "type": "is-blocked-by"}]


def test_to_rec_includes_comments_and_browse_url():
    rec = to_rec("https://x.atlassian.net", issue())
    assert rec.source_id == "KAN-1" and rec.url == "https://x.atlassian.net/browse/KAN-1"
    assert "Comments:" in rec.body and "Ines:" in rec.body and rec.payload["updated"] == "2026-10-15"


class Stub(Jira):
    def __init__(self, pages):
        self.site, self.pages, self.jqls = "https://x.atlassian.net", pages, []

    def issues(self, jql):
        self.jqls.append(jql)
        yield from self.pages.pop(0)


def test_sync_is_idempotent_and_incremental(conn):
    j = Stub([[issue("KAN-1"), issue("KAN-2", updated="2026-10-15T18:00:00.000+0000")],
              [issue("KAN-2", updated="2026-10-15T18:00:00.000+0000")],
              [issue("KAN-2", summary="Changed", updated="2026-10-15T19:00:00.000+0000")]])
    org, st = sync(conn, j, "KAN", "jira-test", "Jira test")
    assert (st.new, st.changed, st.unchanged) == (2, 0, 0)
    assert "updated >=" not in j.jqls[0]
    _, st = sync(conn, j, "KAN", "jira-test", "Jira test")
    assert (st.new, st.unchanged) == (0, 1) and 'updated >= "2026-10-15 18:00"' in j.jqls[1]
    _, st = sync(conn, j, "KAN", "jira-test", "Jira test")
    assert st.changed == 1
    assert conn.execute("SELECT count(*) AS n FROM source_records WHERE organization_id=%s", (org,)).fetchone()["n"] == 2
