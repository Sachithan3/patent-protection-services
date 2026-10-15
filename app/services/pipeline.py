"""End-to-end embedding, pgvector retrieval, and RAG analysis pipeline."""

import asyncio
import logging
import re
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
_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{2,}")
_STOP_WORDS = {
    "and", "are", "the", "for", "from", "with", "into", "that", "this", "using",
    "wherein", "comprising", "further", "including", "system", "method", "apparatus",
    "claim", "claims", "based", "over", "under", "more", "than", "have", "has",
}


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
    strongest_evidence = max(
        float(patent.get("claim_overlap_score", 0.0) or 0.0)
        for patent in matching_patents
    )
    claims_available = any(bool(patent.get("claims")) for patent in matching_patents)

    # Without claims, the score is a bounded technical-overlap signal from the
    # indexed title/abstract. It must not be presented as proven claim overlap.
    evidence_cap = 100 if claims_available else 80
    calibrated_score = min(round(strongest_evidence), evidence_cap)
    report["risk_score"] = calibrated_score
    report["risk_score_model"] = "claim_overlap_v2" if claims_available else "technical_overlap_v2"
    report["risk_score_basis"] = (
        "claim-level element evidence"
        if claims_available
        else "title/abstract feature coverage plus semantic signal"
    )
    report["overall_infringement_risk"] = (
        "HIGH" if calibrated_score >= 70 and claims_available
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
            semantic_factor["score"] = round(strongest_similarity * 100)
            semantic_factor["rationale"] = (
                f"Strongest retrieved patent has a {retrieval_score}% semantic signal. "
                + ("Complete claims are available for comparison."
                   if claims_available else
                   "Claims are not indexed, so this reflects technical similarity rather than proven claim overlap.")
            )
        claim_factor = next(
            (factor for factor in factors
             if isinstance(factor, dict) and factor.get("name") == "claim_element_overlap"),
            None,
        )
        if claim_factor is not None:
            claim_factor["score"] = round(strongest_evidence)
            claim_factor["rationale"] = (
                (
                    f"Independent claim comparison estimates {round(strongest_evidence)}% "
                    "supported element coverage for the strongest candidate."
                    if claims_available
                    else
                    f"No claims are indexed; title/abstract feature overlap contributes "
                    f"{round(strongest_evidence)}% as a limited fallback signal."
                )
            )
        feature_factor = next(
            (factor for factor in factors
             if isinstance(factor, dict) and factor.get("name") == "feature_coverage"),
            None,
        )
        if feature_factor is not None:
            feature_factor["score"] = round(
                max(float(patent.get("feature_coverage", 0.0) or 0.0)
                    for patent in matching_patents)
            )
            feature_factor["rationale"] = (
                "Technical terms shared between the draft and the strongest indexed "
                "patent record, weighted below claim evidence."
            )
        completeness_factor = next(
            (factor for factor in factors
             if isinstance(factor, dict) and factor.get("name") == "evidence_completeness"),
            None,
        )
        if completeness_factor is not None:
            completeness_factor["score"] = 100 if claims_available else 25
            completeness_factor["rationale"] = (
                "Patent claims are available for element-by-element comparison."
                if claims_available
                else
                "Only title and abstract are indexed; claim-level legal comparison is unavailable."
            )
    if claims_available:
        report["final_legal_verdict_summary"] = (
            f"Calibrated preliminary risk is {report['overall_infringement_risk']} "
            f"at {calibrated_score}/100 based on claim-level element evidence. "
            "This is a non-binding technical assessment and not a final legal opinion."
        )
    else:
        report["final_legal_verdict_summary"] = (
            f"Insufficient retrieved claim evidence. The calibrated technical-overlap "
            f"score is {calibrated_score}/100 based on title/abstract feature coverage "
            "and semantic retrieval. Because no patent claims were supplied, this "
            "does not establish literal claim overlap or high legal risk."
        )
    return parsed_report


def _terms(text: str) -> set[str]:
    """Extract meaningful technical terms for lightweight lexical evidence."""
    return {
        token for token in _TOKEN_PATTERN.findall(text.lower())
        if token not in _STOP_WORDS
    }


def _lexical_overlap(query_terms: set[str], claim: str) -> float:
    """Return query-term coverage in the claim as a percentage."""
    if not query_terms:
        return 0.0
    return 100.0 * len(query_terms.intersection(_terms(claim))) / len(query_terms)


def _patent_feature_overlap(query_terms: set[str], patent: dict[str, Any]) -> float:
    """Measure draft feature coverage in the indexed title and abstract."""
    indexed_text = " ".join(
        str(patent.get(field, "")) for field in ("title", "abstract")
    )
    return _lexical_overlap(query_terms, indexed_text)


def rerank_claim_candidates(
    patents: list[dict[str, Any]],
    user_draft: str,
    query_vector: list[float] | None,
    embedding_engine: Any | None = None,
) -> list[dict[str, Any]]:
    """Rerank document candidates using claim-level semantic and lexical evidence."""
    query_terms = _terms(user_draft)
    claims_to_embed: list[str] = []
    claim_locations: list[tuple[int, int]] = []
    for patent_index, patent in enumerate(patents):
        for claim_index, claim in enumerate(patent.get("claims") or [], start=1):
            claims_to_embed.append(str(claim))
            claim_locations.append((patent_index, claim_index))

    claim_vectors: list[list[float]] = []
    if query_vector is not None and embedding_engine is not None and claims_to_embed:
        claim_vectors = embedding_engine.embed_batch(claims_to_embed)

    evidence_by_patent: dict[int, list[dict[str, Any]]] = {index: [] for index in range(len(patents))}
    for position, (patent_index, claim_number) in enumerate(claim_locations):
        claim = str(patents[patent_index]["claims"][claim_number - 1])
        lexical_score = _lexical_overlap(query_terms, claim)
        semantic_score = (
            max(0.0, min(1.0, sum(a * b for a, b in zip(query_vector or [], claim_vectors[position]))))
            if claim_vectors else 0.0
        )
        evidence_by_patent[patent_index].append({
            "claim_number": claim_number,
            "lexical_score": lexical_score,
            "semantic_score": semantic_score * 100,
            "claim": claim,
        })

    reranked: list[dict[str, Any]] = []
    for patent_index, patent in enumerate(patents):
        evidence = evidence_by_patent[patent_index]
        strongest = sorted(
            evidence,
            key=lambda item: (item["lexical_score"] * 0.55 + item["semantic_score"] * 0.45),
            reverse=True,
        )
        top_claims = strongest[:3]
        claim_coverage = (
            sum(item["lexical_score"] * 0.55 + item["semantic_score"] * 0.45 for item in top_claims)
            / len(top_claims)
            if top_claims else 0.0
        )
        semantic_signal = float(patent.get("cosine_similarity", 0.0)) * 100
        feature_coverage = _patent_feature_overlap(query_terms, patent)
        if evidence:
            evidence_score = min(
                100.0,
                claim_coverage * 0.60
                + semantic_signal * 0.15
                + (min(100.0, len(top_claims) * 25) * 0.15)
                + (10.0 if evidence else 0.0),
            )
            evidence_type = "claim"
        else:
            # Abstract-only imports still need a useful, non-flat ranking. The
            # lexical term coverage prevents generic semantic similarity from
            # turning every related patent into the same risk score.
            evidence_score = min(
                80.0,
                semantic_signal * 0.55
                + feature_coverage * 0.35
                + (10.0 if feature_coverage >= 20 else 0.0),
            )
            evidence_type = "title_abstract"
        patent_copy = dict(patent)
        patent_copy["claim_overlap_score"] = round(evidence_score, 2)
        patent_copy["claim_element_coverage"] = round(claim_coverage, 2)
        patent_copy["feature_coverage"] = round(feature_coverage, 2)
        patent_copy["evidence_type"] = evidence_type
        patent_copy["matched_claims"] = [
            {
                "claim_number": item["claim_number"],
                "score": round(item["lexical_score"] * 0.55 + item["semantic_score"] * 0.45, 2),
                "claim": item["claim"],
            }
            for item in top_claims
            if item["lexical_score"] >= 20 or item["semantic_score"] >= 45
        ]
        reranked.append(patent_copy)

    return sorted(
        reranked,
        key=lambda patent: (
            float(patent.get("claim_overlap_score", 0.0)),
            float(patent.get("cosine_similarity", 0.0)),
        ),
        reverse=True,
    )


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
            candidate_k = min(20, max(top_k * 3, top_k))
            matching_patents = await retrieve_similar_patents(session, query_vector, candidate_k)
        except Exception as embedding_error:
            logger.warning("Embedding retrieval unavailable; using keyword fallback: %s", embedding_error)
            candidate_k = min(20, max(top_k * 3, top_k))
            matching_patents = await retrieve_keyword_patents(session, user_draft, candidate_k)

    if not matching_patents:
        raise LookupError("No indexed patents were found in the database")

    embedding_engine = get_embedding_engine() if query_vector else None
    matching_patents = rerank_claim_candidates(
        matching_patents,
        user_draft,
        query_vector,
        embedding_engine,
    )[:top_k]
    report = await generate_infringement_report(user_draft, matching_patents)
    parsed_report = parse_report_json(report)
    parsed_report = calibrate_report_score(parsed_report, matching_patents)
    return {
        "user_draft": user_draft,
        "embedding_dimension": len(query_vector) if query_vector else None,
        "retrieval_method": "semantic" if query_vector else "keyword_fallback",
        "top_k": top_k,
        "risk_scoring": {
            "model": "claim_overlap_v2" if any(
                bool(patent.get("claims")) for patent in matching_patents
            ) else "technical_overlap_v2",
            "claims_available": any(
                bool(patent.get("claims")) for patent in matching_patents
            ),
        },
        "matching_patents": matching_patents,
        "llm_infringement_report": parsed_report,
    }
