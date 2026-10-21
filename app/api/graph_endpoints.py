"""Graph API endpoints for the Patent Knowledge Graph Explorer.

Endpoints:
    GET  /api/v1/graph            → default overview graph (Mode A)
    POST /api/v1/graph/focused    → analysis-result focused graph (Mode B)
    GET  /api/v1/graph/expand/{patent_id} → neighbourhood expansion

All endpoints return JSON in the shape:
    {
        "nodes": [ { id, type, label, ... } ],
        "edges": [ { id, source, target, type, weight, ... } ],
        "meta":  { patent_count, concept_count, total_edge_count, ... }
    }

Similarity threshold semantics:
    similarity_threshold (float 0.0 – 1.0, default 0.75)
    An edge is drawn between two patents when their cosine similarity
    (= 1 − cosine_distance stored by pgvector) ≥ threshold.

Node and edge caps are enforced server-side; see knowledge_graph.py.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from app.core.database import AsyncSessionLocal
from app.services.knowledge_graph import (
    DEFAULT_SIMILARITY_THRESHOLD,
    MAX_PATENTS,
    build_default_graph,
    build_focused_graph,
    expand_patent_node,
)

logger = logging.getLogger(__name__)

graph_router = APIRouter(prefix="/api/v1/graph", tags=["Knowledge Graph"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class FocusedGraphRequest(BaseModel):
    """Request body for a focused graph centred on analysis result patents."""

    patent_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Publication identifiers of the patents to focus on (from /analyze).",
        examples=[["US-20240123456-A1", "US-20230987654-B2"]],
    )
    similarity_threshold: float = Field(
        default=DEFAULT_SIMILARITY_THRESHOLD,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity (0–1) required to draw a patent-patent edge.",
    )
    query_label: str | None = Field(
        default=None,
        description=(
            "Optional description of the analysis draft (the user's own text, "
            "so it is not length-capped).  If provided a temporary 'query' node "
            "is added to the graph, clearly labelled as unsaved."
        ),
    )
    query_similarities: dict[str, float] | None = Field(
        default=None,
        description=(
            "Optional dict mapping patent_id → cosine_similarity from /analyze.  "
            "Used to weight the query→patent edges.  If absent, edges use a default weight."
        ),
    )
    expand_neighbours: bool = Field(
        default=True,
        description="When True, the graph is expanded with each seed patent's nearest neighbours.",
    )

    @field_validator("patent_ids")
    @classmethod
    def strip_and_deduplicate(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for pid in value:
            if not isinstance(pid, str):
                raise ValueError("patent_ids must contain string identifiers")
            pid = pid.strip()
            if pid and pid not in seen:
                seen.add(pid)
                result.append(pid)
        if not result:
            raise ValueError("patent_ids must contain at least one non-empty identifier")
        return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@graph_router.get("", summary="Default knowledge graph overview (Mode A)")
async def default_graph(
    max_patents: int = Query(
        default=30,
        ge=5,
        le=MAX_PATENTS,
        description="Maximum number of patent nodes in the response.",
    ),
    similarity_threshold: float = Query(
        default=DEFAULT_SIMILARITY_THRESHOLD,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity required for patent-patent edges.",
    ),
) -> dict[str, Any]:
    """Return a representative subgraph of the full patent collection.

    The patent sample is selected with a daily-stable random seed so the
    graph looks the same throughout the day but refreshes the next day.
    Apply concept clustering and patent-similarity edges before returning.
    """
    try:
        async with AsyncSessionLocal() as session:
            graph = await build_default_graph(
                session,
                max_patents=max_patents,
                similarity_threshold=similarity_threshold,
            )
        return graph
    except Exception as exc:
        logger.exception("Failed to build default knowledge graph")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Graph generation failed: {exc}",
        ) from exc


@graph_router.post("/focused", summary="Focused graph from analysis results (Mode B)")
async def focused_graph(request: FocusedGraphRequest) -> dict[str, Any]:
    """Return a graph centred on specific patents returned by /analyze.

    The seed patents are highlighted and the graph is optionally expanded
    with their nearest neighbours.  A temporary 'query' node is added when
    *query_label* is provided; it is clearly marked as unsaved.

    The risk assessment from /analyze is unaffected by this endpoint.
    """
    try:
        async with AsyncSessionLocal() as session:
            graph = await build_focused_graph(
                session,
                patent_ids=request.patent_ids,
                similarity_threshold=request.similarity_threshold,
                expand_neighbours=request.expand_neighbours,
                query_label=request.query_label,
                query_similarities=request.query_similarities,
            )
        if not graph["nodes"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="None of the requested patent IDs were found in the database.",
            )
        return graph
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to build focused knowledge graph")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Graph generation failed: {exc}",
        ) from exc


@graph_router.get(
    "/expand/{patent_id:path}",
    summary="Expand a patent node's neighbourhood",
)
async def expand_node(
    patent_id: str,
    similarity_threshold: float = Query(
        default=DEFAULT_SIMILARITY_THRESHOLD,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity for patent-patent edges.",
    ),
    neighbour_k: int = Query(
        default=8,
        ge=1,
        le=20,
        description="Number of nearest neighbours to include.",
    ),
) -> dict[str, Any]:
    """Return a focused graph for a single patent and its nearest neighbours.

    Used when the user clicks a patent node and wants to see its context.
    """
    patent_id = patent_id.strip()
    if not patent_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="patent_id must not be empty.",
        )
    try:
        async with AsyncSessionLocal() as session:
            graph = await expand_patent_node(
                session,
                patent_id=patent_id,
                similarity_threshold=similarity_threshold,
                neighbour_k=neighbour_k,
            )
        if not graph["nodes"]:
            error_msg = graph.get("meta", {}).get("error")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg or f"Patent {patent_id!r} not found.",
            )
        return graph
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to expand patent node %r", patent_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Node expansion failed: {exc}",
        ) from exc
