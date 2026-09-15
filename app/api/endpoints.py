"""FastAPI presentation endpoints for ClaimGuard analysis."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.services.pipeline import analyze_draft_infringement, get_embedding_engine
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["ClaimGuard Analysis"])


class AnalyzeRequest(BaseModel):
    """Request body for patent infringement analysis."""

    user_draft: str = Field(
        ...,
        min_length=20,
        description="Technical product or implementation draft to analyze.",
        examples=[
            "An autonomous indoor drone uses LiDAR and event cameras to build a sparse "
            "3D occupancy map, then applies reinforcement learning for collision-free "
            "path planning on an edge FPGA."
        ],
    )


@router.post("/analyze", summary="Analyze a technical draft for patent overlap")
async def analyze(
    request: AnalyzeRequest,
    top_k: int = Query(default=5, ge=1, le=20, description="Number of patents to retrieve"),
) -> dict[str, Any]:
    """Return cosine matches and a grounded LLM infringement report."""
    try:
        return await analyze_draft_infringement(request.user_draft, top_k=top_k)
    except (ValueError, LookupError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except RuntimeError as error:
        logger.exception("RAG analysis failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error


@router.get("/health", summary="Check database and embedding model health")
async def health() -> dict[str, Any]:
    """Check core dependencies needed for live analysis."""
    database_healthy = False
    database_error: str | None = None
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        database_healthy = True
    except Exception as error:
        database_error = str(error)

    embedding_healthy = False
    embedding_error: str | None = None
    try:
        embedding_engine = await asyncio.to_thread(get_embedding_engine)
        embedding_healthy = (
            embedding_engine.get_vector_dimension()
            == get_settings().embedding_vector_dimension
        )
    except Exception as error:
        embedding_error = str(error)

    overall_status = "healthy" if database_healthy and embedding_healthy else "degraded"
    return {
        "status": overall_status,
        "database": {"healthy": database_healthy, "error": database_error},
        "embedding_model": {
            "healthy": embedding_healthy,
            "model": get_settings().embedding_model,
            "dimension": get_settings().embedding_vector_dimension,
            "error": embedding_error,
        },
    }
