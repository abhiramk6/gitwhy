"""CLI entrypoint (also the Cloud Run Job command): python -m app.ingestion.run [--mode backfill|incremental]"""
import argparse
import json
from pathlib import Path

from ..db import connect, migrate
from .fixtures import ingest

DEFAULT = Path(__file__).resolve().parents[3] / "fixtures" / "northwind"

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=str(DEFAULT))
    ap.add_argument("--mode", default="backfill", choices=["backfill", "incremental"])
    a = ap.parse_args()
    migrate()
    with connect() as conn:
        org_id, st = ingest(conn, Path(a.path), a.mode)
    print(json.dumps({"organization_id": org_id, **st.__dict__}, indent=2))
