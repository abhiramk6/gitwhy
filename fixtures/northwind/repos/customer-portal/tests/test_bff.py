from portal.bff import list_receipts


def test_list_receipts_empty():
    assert list_receipts("c1") == []
