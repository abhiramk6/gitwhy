"""Results dashboard numbers: measured vs rated vs estimate, and no comparison before there are enough timed pairs."""
from pathlib import Path

import pytest

from app.ingestion.fixtures import ingest
from app.metrics import metrics

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"


@pytest.fixture()
def org(conn):
    return ingest(conn, FIX)[0]


def ask(conn, org, status="answered", ms=4000, statements=2, dropped=1):
    return metrics.record(conn, org, None, "ask", ms, {"status": status, "statements": statements, "dropped": dropped, "citations": 2})


def test_counts_and_median_use_answered_questions_only(conn, org):
    ask(conn, org, ms=2000), ask(conn, org, ms=6000), ask(conn, org, status="insufficient", ms=90000)
    m = metrics.summary(conn, org)["measured"]
    assert m["questions_asked"] == 3 and m["questions_answered"] == 2 and m["median_seconds_to_sourced_answer"] == 4.0
    assert m["citations"]["statements_shown"] == 6 and m["citations"]["statements_removed_by_guard"] == 3


def test_repeated_issues_are_counted_once_per_pr_and_source(conn, org):
    rep = {"repo": "payments-api", "pr": 11, "type": "past_guidance", "source": "fact:582"}
    for _ in range(2):
        metrics.record(conn, org, None, "review", 100, {"repeats": [rep]})
    metrics.record(conn, org, None, "review", 100, {"repeats": [{**rep, "pr": 12}]})
    assert metrics.summary(conn, org)["measured"]["repeated_issues_detected"] == 2


def test_feedback_is_per_answer_and_replaced_not_duplicated(conn, org):
    e = ask(conn, org)
    assert metrics.feedback(conn, org, None, e, True, "yes", True) and metrics.feedback(conn, org, None, e, True, "no", True)
    r = metrics.summary(conn, org)["rated_by_people"]
    assert r["ratings"] == 1 and r["answers_incorrect"] == 1 and r["correct_share"] == 0.0 and r["onboarding_questions_resolved"] == 1
    assert not metrics.feedback(conn, org, None, 999999, True, "yes", False)      # unknown answer
    other = conn.execute("INSERT INTO organizations (slug, name) VALUES ('other','Other') RETURNING id").fetchone()["id"]
    assert not metrics.feedback(conn, other, None, e, True, "yes", False)          # another org's answer


def test_no_comparison_before_five_paired_tasks_then_a_measured_one(conn, org):
    for i in range(4):
        metrics.record_timed(conn, org, None, f"task {i}", "manual", 600, True)
        metrics.record_timed(conn, org, None, f"task {i}", "gitwhy", 30, True)
    t = metrics.timed_comparison(conn, org)
    assert t["comparison"] is None and t["paired_tasks"] == 4 and t["needed_pairs"] == 5
    metrics.record_timed(conn, org, None, "task 4", "manual", 300, True)
    metrics.record_timed(conn, org, None, "task 4", "gitwhy", 40, True)
    metrics.record_timed(conn, org, None, "task 5", "manual", 900, False)          # not found: never counted as a time
    c = metrics.timed_comparison(conn, org)
    assert c["comparison"]["paired_tasks"] == 5 and c["comparison"]["faster_in"] == 5 and c["not_found"] == 1


def test_estimate_only_when_an_assumption_is_given_and_is_labelled(conn, org):
    ask(conn, org), ask(conn, org)
    assert metrics.summary(conn, org)["estimate"] is None
    e = metrics.summary(conn, org, 15)["estimate"]
    assert e["hours"] == 0.5 and "not a measurement" in e["label"]
