from fastapi import FastAPI

from .api.health import router as health_router
from .api.routes import router as api_router
from .mcp.server import router as mcp_router

app = FastAPI(title="LORE Intelligence", version="0.1.0")
app.include_router(health_router)
app.include_router(api_router)
app.include_router(mcp_router)
