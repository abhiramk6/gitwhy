from platform_libs.idempotency import IdempotencyStore


def test_claim_once():
    s = IdempotencyStore()
    assert s.claim("k", "f") is True
    assert s.claim("k", "f") is False
