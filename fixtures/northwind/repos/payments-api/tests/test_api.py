from payments.api import create_payment


def test_create_payment():
    assert create_payment({"id": "p1"})["status"] == "authorized"
