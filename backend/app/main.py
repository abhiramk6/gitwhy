from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api.accounts import router as accounts_router
from .api.health import router as health_router
from .api.routes import router as api_router
from .mcp.server import router as mcp_router
from .product import product

app = FastAPI(title=product()["name"], version="0.1.0")
app.include_router(health_router)
app.include_router(accounts_router)
app.include_router(api_router)
app.include_router(mcp_router)

# Serve the built SPA (frontend/dist) from the same service; API and MCP routes are registered first.
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="ui")
