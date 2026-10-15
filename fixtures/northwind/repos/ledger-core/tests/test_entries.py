from ledger.entries import post_entry
from ledger.models import Entry


def test_post_is_idempotent():
    e = Entry("e1", "p1", 100, "EUR", "capture")
    assert post_entry(e) is post_entry(e)
