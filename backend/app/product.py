"""The product's name lives in ONE file, product.json at the repository root (copied into the image). Change it there and the
UI (brand, page title), API title, MCP server name and /api/meta all follow. Docs and ops scripts are static text."""
import json
import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def product() -> dict:
    path = Path(os.environ.get("PRODUCT_FILE") or Path(__file__).resolve().parents[2] / "product.json")
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        d = {}
    return {"name": d.get("name", "Gitwhy"), "slug": d.get("slug", "gitwhy"), "tagline": d.get("tagline", "")}
