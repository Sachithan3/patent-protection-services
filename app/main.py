"""ClaimGuard AI FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.api.endpoints import router
from app.core.config import get_settings
from app.core.database import close_database, init_database

settings = get_settings()
logging.basicConfig(level=settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize database structures before serving requests."""
    await init_database()
    yield
    await close_database()


app = FastAPI(
    title="ClaimGuard AI",
    description=(
        "Autonomous IP discovery and preliminary patent infringement analysis "
        "using pgvector retrieval and grounded LLM generation."
    ),
    version="2.0.0",
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """Provide a discoverable root response."""
    return {"service": "ClaimGuard AI", "docs": "/docs", "health": "/api/v1/health"}
