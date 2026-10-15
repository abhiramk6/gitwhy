from notify.dedupe import DedupeStore


def test_dedupe():
    s = DedupeStore()
    assert s.claim("a", "x") and not s.claim("a", "x")
