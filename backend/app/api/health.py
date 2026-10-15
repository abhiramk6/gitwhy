from fastapi import APIRouter, Response

from ..db import connect

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/health/db")
def health_db(response: Response) -> dict:
    try:
        with connect() as conn:
            vec = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
            migrations = conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"]
        return {"status": "ok", "pgvector": vec["extversion"] if vec else None, "migrations": migrations}
    except Exception as exc:  # report, never leak connection strings
        response.status_code = 503
        return {"status": "error", "detail": type(exc).__name__}
