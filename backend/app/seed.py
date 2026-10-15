"""One-shot demo bootstrap (also the Cloud Run Job command): migrate -> ingest -> build graph -> embed.

Idempotent: re-running changes nothing. Usage: python -m app.seed [--path FIXTURES]
"""
import argparse
import json
from pathlib import Path

from .config import get_settings
from .db import connect, migrate
from .ingestion.fixtures import ingest
from .knowledge.build_graph import build
from .models.provider import make_provider
from .retrieval.embed import embed_org

DEFAULT = Path(__file__).resolve().parents[2] / "fixtures" / "northwind"


def run(path: Path = DEFAULT) -> dict:
    s = get_settings()
    provider = make_provider(s)
    applied = migrate()
    with connect() as conn:
        org, st = ingest(conn, path, "backfill")
        g = build(conn, org, provider)
        e = embed_org(conn, org, provider)
    return {"migrations_applied": applied, "ingest": st.__dict__, "graph": g.__dict__, "embeddings": e,
            "provider": provider.name}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=str(DEFAULT))
    print(json.dumps(run(Path(ap.parse_args().path)), indent=2, default=str))
