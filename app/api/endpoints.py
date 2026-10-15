"""FastAPI presentation endpoints for ClaimGuard analysis."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.patent import Patent
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


@router.get("/patents", summary="Browse indexed patents")
async def list_patents(
    limit: int = Query(default=12, ge=1, le=100),
    category: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return a lightweight catalogue for the web application."""
    async with AsyncSessionLocal() as session:
        statement = select(Patent).order_by(Patent.id.desc()).limit(limit)
        if category:
            statement = statement.where(Patent.category == category)
        patents = (await session.scalars(statement)).all()
        categories = (
            await session.scalars(select(Patent.category).distinct().order_by(Patent.category))
        ).all()
    return {
        "patents": [patent.to_dict() for patent in patents],
        "categories": categories,
    }


@router.get("/stats", summary="Summarize the indexed patent collection")
async def stats() -> dict[str, Any]:
    """Return collection counts used by the dashboard."""
    async with AsyncSessionLocal() as session:
        total = await session.scalar(select(func.count(Patent.id)))
        categories = await session.scalar(select(func.count(func.distinct(Patent.category))))
    return {"patent_count": total or 0, "category_count": categories or 0}


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
