"""Run accounting: live calls vs cache replays vs unavailable judgments, and the PASS/FAIL/SKIPPED tally."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from _report import Tally  # noqa: E402
from app.intelligence.judge import meter, run_task  # noqa: E402
from app.models.provider import LLMUnavailable, OfflineProvider  # noqa: E402
from app.models.testing import ScriptedProvider  # noqa: E402

SCHEMA = {"type": "object"}


def org_id(conn):
    return conn.execute("INSERT INTO organizations (slug, name, is_synthetic) VALUES ('acct','acct',true) "
                        "RETURNING id").fetchone()["id"]


def test_meter_separates_live_replayed_and_unavailable(conn):
    meter.reset()
    org = org_id(conn)
    prov = ScriptedProvider({"t": lambda p: {"ok": True}})
    run_task(conn, org, prov, "t", "sys", {"x": 1}, SCHEMA)       # live
    run_task(conn, org, prov, "t", "sys", {"x": 1}, SCHEMA)       # replayed from cache
    assert (meter.live, meter.replayed, meter.unavailable) == (1, 1, 0)
    assert len(prov.calls) == 1 and meter.replay_models == {"scripted": 1}
    offline = OfflineProvider()
    run_task(conn, org, offline, "t", "sys", {"x": 1}, SCHEMA)    # offline replay is visible as a replay
    assert meter.replayed == 2
    with pytest.raises(LLMUnavailable):
        run_task(conn, org, offline, "t", "sys", {"x": 2}, SCHEMA)
    assert meter.unavailable == 1 and meter.by_task["t"] == {"live": 1, "replayed": 2, "unavailable": 1}


def test_tally_skipped_is_not_a_pass():
    t = Tally()
    t.add("PASS"); t.add("SKIPPED")
    assert t.exit_code == 1 and "SKIPPED 1" in t.line() and "not a pass" in t.line()
    ok = Tally()
    ok.add("PASS")
    assert ok.exit_code == 0
    bad = Tally()
    bad.add("FAIL")
    assert bad.exit_code == 1
