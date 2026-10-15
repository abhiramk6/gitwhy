def require_service_token(headers: dict) -> str:
    token = headers.get("X-Service-Token", "")
    if not token:
        raise PermissionError("missing service token")
    return token
