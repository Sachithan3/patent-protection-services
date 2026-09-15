"""End-to-end embedding, pgvector retrieval, and RAG analysis pipeline."""

import asyncio
import logging
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.patent import Patent
from app.services.rag_service import generate_infringement_report, parse_report_json

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_embedding_engine() -> Any:
    """Load one process-local embedding model instance."""
    from embeddings import EmbeddingEngine

    return EmbeddingEngine(get_settings().embedding_model)


async def retrieve_similar_patents(
    session: AsyncSession,
    query_vector: list[float],
    top_k: int,
) -> list[dict[str, Any]]:
    """Retrieve patents ordered by PostgreSQL pgvector cosine distance."""
    distance_expression = Patent.embedding.cosine_distance(query_vector).label(
        "cosine_distance"
    )
    statement = (
        select(Patent, distance_expression)
        .order_by(distance_expression)
        .limit(top_k)
    )
    result = await session.execute(statement)
    return [
        patent.to_dict(distance=float(distance))
        for patent, distance in result.all()
    ]


async def analyze_draft_infringement(
    user_draft: str,
    top_k: int = 5,
) -> dict[str, Any]:
    """Run embedding, cosine retrieval, context construction, and LLM analysis."""
    if not isinstance(user_draft, str) or not user_draft.strip():
        raise ValueError("user_draft must be a non-empty string")
    if top_k < 1 or top_k > 20:
        raise ValueError("top_k must be between 1 and 20")

    embedding_engine = await asyncio.to_thread(get_embedding_engine)
    query_vector = await asyncio.to_thread(embedding_engine.embed_text, user_draft)
    if len(query_vector) != get_settings().embedding_vector_dimension:
        raise RuntimeError(
            f"Expected a {get_settings().embedding_vector_dimension}-dimensional vector, "
            f"received {len(query_vector)}"
        )

    async with AsyncSessionLocal() as session:
        matching_patents = await retrieve_similar_patents(session, query_vector, top_k)

    if not matching_patents:
        raise LookupError("No indexed patents were found in the database")

    report = await generate_infringement_report(user_draft, matching_patents)
    parsed_report = parse_report_json(report)
    return {
        "user_draft": user_draft,
        "embedding_dimension": len(query_vector),
        "top_k": top_k,
        "matching_patents": matching_patents,
        "llm_infringement_report": parsed_report,
    }
