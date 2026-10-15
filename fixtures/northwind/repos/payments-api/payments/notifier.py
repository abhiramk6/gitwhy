import json

from platform_libs.http_client import request

NOTIFY_URL = "http://notify-svc.internal/v1/notifications"


def notify_customer(payment_id: str, template: str) -> None:
    request("POST", NOTIFY_URL, json.dumps({"payment_id": payment_id, "template": template}).encode())
