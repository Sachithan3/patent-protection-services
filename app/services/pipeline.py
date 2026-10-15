"""End-to-end embedding, pgvector retrieval, and RAG analysis pipeline."""

import asyncio
import logging
import threading
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.patent import Patent
from app.services.rag_service import generate_infringement_report, parse_report_json

logger = logging.getLogger(__name__)
_embedding_engine: Any | None = None
_embedding_engine_lock = threading.Lock()


def calibrate_report_score(
    parsed_report: dict[str, Any],
    matching_patents: list[dict[str, Any]],
) -> dict[str, Any]:
    """Keep the LLM report consistent with retrieval evidence without overstating legal risk."""
    if not parsed_report.get("structured"):
        return parsed_report

    report = parsed_report.get("report")
    if not isinstance(report, dict) or not matching_patents:
        return parsed_report

    strongest_similarity = max(
        float(patent.get("cosine_similarity", 0.0)) for patent in matching_patents
    )
    retrieval_score = round(max(0.0, min(100.0, strongest_similarity * 100)))
    claims_available = any(bool(patent.get("claims")) for patent in matching_patents)

    # Missing claims prevent a legal-overlap conclusion, but should not erase a strong
    # semantic match. Cap this as preliminary similarity risk until claims are indexed.
    evidence_cap = 85 if claims_available else 65
    calibrated_score = max(
        int(report.get("risk_score", 0) or 0),
        min(retrieval_score, evidence_cap),
    )
    report["risk_score"] = calibrated_score
    report["overall_infringement_risk"] = (
        "HIGH" if calibrated_score >= 70
        else "MEDIUM" if calibrated_score >= 40
        else "LOW"
    )

    factors = report.get("risk_factors")
    if isinstance(factors, list):
        semantic_factor = next(
            (factor for factor in factors
             if isinstance(factor, dict) and factor.get("name") == "semantic_similarity"),
            None,
        )
        if semantic_factor is not None:
            semantic_factor["score"] = max(
                int(semantic_factor.get("score", 0) or 0),
                retrieval_score,
            )
            semantic_factor["rationale"] = (
                f"Strongest retrieved patent has a {retrieval_score}% semantic signal. "
                + ("Complete claims are available for comparison."
                   if claims_available else
                   "Claims are not indexed, so this reflects technical similarity rather than proven claim overlap.")
            )
    return parsed_report


def get_embedding_engine() -> Any:
    """Load one process-local embedding model instance."""
    global _embedding_engine
    from embeddings import EmbeddingEngine

    if _embedding_engine is None:
        with _embedding_engine_lock:
            if _embedding_engine is None:
                _embedding_engine = EmbeddingEngine(get_settings().embedding_model)
    return _embedding_engine


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


async def retrieve_keyword_patents(
    session: AsyncSession,
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """Retrieve records by PostgreSQL full-text relevance when embeddings are unavailable."""
    query_vector = func.plainto_tsquery("english", query)
    rank = func.ts_rank_cd(
        func.to_tsvector("english", Patent.searchable_text),
        query_vector,
    ).label("rank")
    statement = (
        select(Patent, rank)
        .order_by(desc(rank), Patent.id.desc())
        .limit(top_k)
    )
    result = await session.execute(statement)
    return [
        patent.to_dict(distance=float(max(0.0, 1.0 - rank_value)))
        for patent, rank_value in result.all()
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

    async with AsyncSessionLocal() as session:
        query_vector: list[float] | None = None
        try:
            embedding_engine = await asyncio.to_thread(get_embedding_engine)
            query_vector = await asyncio.to_thread(embedding_engine.embed_text, user_draft)
            if len(query_vector) != get_settings().embedding_vector_dimension:
                raise RuntimeError(
                    f"Expected a {get_settings().embedding_vector_dimension}-dimensional vector, "
                    f"received {len(query_vector)}"
                )
            matching_patents = await retrieve_similar_patents(session, query_vector, top_k)
        except Exception as embedding_error:
            logger.warning("Embedding retrieval unavailable; using keyword fallback: %s", embedding_error)
            matching_patents = await retrieve_keyword_patents(session, user_draft, top_k)

    if not matching_patents:
        raise LookupError("No indexed patents were found in the database")

    report = await generate_infringement_report(user_draft, matching_patents)
    parsed_report = parse_report_json(report)
    parsed_report = calibrate_report_score(parsed_report, matching_patents)
    return {
        "user_draft": user_draft,
        "embedding_dimension": len(query_vector) if query_vector else None,
        "retrieval_method": "semantic" if query_vector else "keyword_fallback",
        "top_k": top_k,
        "matching_patents": matching_patents,
        "llm_infringement_report": parsed_report,
    }
