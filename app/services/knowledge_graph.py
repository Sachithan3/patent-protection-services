"""Patent Knowledge Graph service — patent-only edition.

Builds force-directed graph data (nodes + edges) from the indexed patent
collection.  Concepts and concept-extraction have been removed; the graph
shows only patent nodes connected by real embedding-based similarity edges.

Similarity threshold:
    DEFAULT_SIMILARITY_THRESHOLD = 0.45
    This value is calibrated to the actual cosine similarity distribution of
    the patent corpus.  At 0.75 the corpus produces almost no edges; 0.45
    consistently produces a well-connected graph while excluding unrelated
    pairs (similarity < 0.3).  The threshold is fully configurable via the
    API query parameters.

Edge weight = cosine_similarity ∈ [0, 1].  It is mapped to edge thickness
and opacity on the frontend.

Node and edge limits:
    MAX_PATENTS = 50
    MAX_EDGES   = 300  (patent-patent only)

Node IDs:
    patent nodes → "p:<patent_id>"
    query node   → "q:draft"
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patent import Patent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuneable constants
# ---------------------------------------------------------------------------
MAX_PATENTS: int = 50
MAX_EDGES: int = 300

# Calibrated to this corpus: most patent pairs sit between 0.1–0.65.
# 0.45 keeps a well-connected graph without flooding weak relationships.
DEFAULT_SIMILARITY_THRESHOLD: float = 0.45


# ---------------------------------------------------------------------------
# Node builders
# ---------------------------------------------------------------------------

def _node_id_patent(patent_id: str) -> str:
    return f"p:{patent_id}"


def _build_patent_node(
    patent: Patent,
    highlighted: bool = False,
    cosine_similarity: float | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": _node_id_patent(patent.patent_id),
        "type": "patent",
        "label": patent.patent_id,
        "patent_id": patent.patent_id,
        "title": patent.title,
        "abstract": patent.abstract,
        "category": patent.category,
        "claims": patent.claims if isinstance(patent.claims, list) else [],
        "highlighted": highlighted,
    }
    if cosine_similarity is not None:
        node["cosine_similarity"] = round(cosine_similarity, 4)
    return node


# ---------------------------------------------------------------------------
# Similarity edge computation
# ---------------------------------------------------------------------------

async def get_similarity_edges(
    session: AsyncSession,
    patents: list[Patent],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_edges: int = MAX_EDGES,
) -> list[dict[str, Any]]:
    """Return patent-to-patent similarity edges grounded in pgvector distances.

    For each patent we issue one pgvector KNN query against the set of
    selected patent IDs so we stay O(n * k) rather than O(n²).  Edges are
    symmetrically deduplicated.

    Args:
        session:   Active async database session.
        patents:   List of Patent ORM objects already loaded in memory.
        threshold: Minimum cosine similarity (0–1) required to create an edge.
        max_edges: Hard upper limit on total edges returned.

    Returns:
        List of edge dicts.
    """
    if len(patents) < 2:
        return []

    ids_in_set = [p.patent_id for p in patents if p.embedding is not None]
    if len(ids_in_set) < 2:
        return []

    # Build embedding map from already-loaded ORM objects (no extra DB round-trip)
    emb_map: dict[str, list[float]] = {
        p.patent_id: list(p.embedding)
        for p in patents
        if p.embedding is not None
    }

    distance_cutoff = 1.0 - threshold
    seen: set[tuple[str, str]] = set()
    edges: list[dict[str, Any]] = []

    for pid, emb in emb_map.items():
        if len(edges) >= max_edges:
            break
        neighbour_k = min(len(ids_in_set) - 1, 15)
        stmt = (
            select(
                Patent.patent_id,
                Patent.embedding.cosine_distance(emb).label("dist"),
            )
            .where(Patent.patent_id.in_(ids_in_set))
            .where(Patent.patent_id != pid)
            .order_by("dist")
            .limit(neighbour_k)
        )
        rows = (await session.execute(stmt)).all()
        for row in rows:
            dist = float(row.dist)
            if dist > distance_cutoff:
                continue
            neighbour_id: str = row.patent_id
            similarity = round(1.0 - dist, 4)
            key = tuple(sorted([pid, neighbour_id]))
            if key in seen:
                continue
            seen.add(key)
            if len(edges) >= max_edges:
                break
            # weight is the raw similarity; used for edge thickness on frontend
            edges.append({
                "id": f"e:sim:{key[0]}:{key[1]}",
                "source": _node_id_patent(key[0]),
                "target": _node_id_patent(key[1]),
                "type": "PATENT_SIMILAR",
                "weight": similarity,
                "similarity": similarity,
                "label": f"{round(similarity * 100)}% similar",
            })

    # Sort strongest edges first so the edge cap keeps the best connections
    edges.sort(key=lambda e: e["similarity"], reverse=True)
    return edges[:max_edges]


# ---------------------------------------------------------------------------
# Core graph assembly
# ---------------------------------------------------------------------------

async def _assemble_graph(
    session: AsyncSession,
    patents: list[Patent],
    similarity_threshold: float,
    highlighted_patent_ids: set[str] | None = None,
    query_node: dict[str, Any] | None = None,
    # per-patent similarity to the query (for query→patent edge weights)
    query_similarities: dict[str, float] | None = None,
) -> dict[str, Any]:
    highlighted_patent_ids = highlighted_patent_ids or set()
    query_similarities = query_similarities or {}

    patent_nodes = [
        _build_patent_node(
            p,
            highlighted=p.patent_id in highlighted_patent_ids,
            cosine_similarity=query_similarities.get(p.patent_id),
        )
        for p in patents
    ]

    sim_edges = await get_similarity_edges(
        session, patents, threshold=similarity_threshold, max_edges=MAX_EDGES
    )

    # Query → matched-patent edges (Mode B only)
    query_nodes: list[dict[str, Any]] = []
    query_edges: list[dict[str, Any]] = []
    if query_node is not None:
        query_nodes.append(query_node)
        qid = query_node["id"]
        for patent in patents:
            if patent.patent_id not in highlighted_patent_ids:
                continue
            sim = query_similarities.get(patent.patent_id, 0.5)
            query_edges.append({
                "id": f"e:qp:{patent.patent_id}",
                "source": qid,
                "target": _node_id_patent(patent.patent_id),
                "type": "QUERY_MATCH",
                "weight": round(sim, 4),
                "similarity": round(sim, 4),
                "label": f"{round(sim * 100)}% match",
            })

    all_nodes = patent_nodes + query_nodes
    all_edges = sim_edges + query_edges

    return {
        "nodes": all_nodes,
        "edges": all_edges,
        "meta": {
            "patent_count": len(patent_nodes),
            "concept_count": 0,
            "similarity_edge_count": len(sim_edges),
            "query_edge_count": len(query_edges),
            "total_edge_count": len(all_edges),
            "similarity_threshold": similarity_threshold,
            "highlighted_count": len(highlighted_patent_ids),
        },
    }


# ---------------------------------------------------------------------------
# Public graph builders
# ---------------------------------------------------------------------------

async def build_default_graph(
    session: AsyncSession,
    max_patents: int = 30,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> dict[str, Any]:
    """Build a representative overview graph from a random-seeded patent sample.

    Uses a daily-stable seed so the overview is stable within a day.
    """
    max_patents = min(max_patents, MAX_PATENTS)
    from datetime import date as _date
    day_seed = int(_date.today().strftime("%Y%m%d")) % (2**31 - 1)
    await session.execute(text(f"SELECT setseed({day_seed / 2**31})"))
    stmt = select(Patent).order_by(text("random()")).limit(max_patents)
    patents = list((await session.scalars(stmt)).all())

    if not patents:
        return {
            "nodes": [], "edges": [],
            "meta": {"patent_count": 0, "concept_count": 0, "total_edge_count": 0},
        }

    return await _assemble_graph(session, patents, similarity_threshold)


async def build_focused_graph(
    session: AsyncSession,
    patent_ids: list[str],
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    expand_neighbours: bool = True,
    query_label: str | None = None,
    query_similarities: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build a graph centred on specific patents (Mode B – analysis result).

    Args:
        session:               DB session.
        patent_ids:            Seed patent IDs (from /analyze result).
        similarity_threshold:  Edge threshold.
        expand_neighbours:     Whether to add nearest neighbours of each seed.
        query_label:           Short text for the "Your Invention" node.
        query_similarities:    patent_id → cosine_similarity from /analyze,
                               used as edge weights for query→patent edges.
    """
    if not patent_ids:
        return {
            "nodes": [], "edges": [],
            "meta": {"patent_count": 0, "concept_count": 0, "total_edge_count": 0},
        }

    seed_stmt = select(Patent).where(Patent.patent_id.in_(patent_ids))
    seeds = list((await session.scalars(seed_stmt)).all())
    found_ids = {p.patent_id for p in seeds}

    extra_patents: list[Patent] = []
    if expand_neighbours and seeds:
        neighbour_ids: set[str] = set()
        for seed in seeds[:6]:
            if seed.embedding is None:
                continue
            emb = list(seed.embedding)
            nb_stmt = (
                select(Patent)
                .where(Patent.patent_id.notin_(list(found_ids | neighbour_ids)))
                .order_by(Patent.embedding.cosine_distance(emb))
                .limit(2)
            )
            for nb in (await session.scalars(nb_stmt)).all():
                if nb.patent_id not in found_ids:
                    neighbour_ids.add(nb.patent_id)

        if neighbour_ids:
            extra = list(
                (await session.scalars(
                    select(Patent).where(Patent.patent_id.in_(list(neighbour_ids)))
                )).all()
            )
            extra_patents = extra

    all_patents = (seeds + extra_patents)[:MAX_PATENTS]

    query_node: dict[str, Any] | None = None
    if query_label:
        query_node = {
            "id": "q:draft",
            "type": "query",
            "label": "Your Invention",
            "title": query_label,
            "note": "Temporary — not stored in the database.",
            "highlighted": True,
        }

    return await _assemble_graph(
        session,
        all_patents,
        similarity_threshold,
        highlighted_patent_ids=found_ids,
        query_node=query_node,
        query_similarities=query_similarities or {},
    )


async def expand_patent_node(
    session: AsyncSession,
    patent_id: str,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    neighbour_k: int = 10,
) -> dict[str, Any]:
    """Return a small graph centred on one patent and its nearest neighbours."""
    focal = await session.scalar(
        select(Patent).where(Patent.patent_id == patent_id)
    )
    if focal is None:
        return {
            "nodes": [], "edges": [],
            "meta": {
                "patent_count": 0, "concept_count": 0, "total_edge_count": 0,
                "error": f"Patent {patent_id!r} not found",
            },
        }

    patents: list[Patent] = [focal]
    if focal.embedding is not None:
        nb_stmt = (
            select(Patent)
            .where(Patent.patent_id != patent_id)
            .order_by(Patent.embedding.cosine_distance(list(focal.embedding)))
            .limit(neighbour_k)
        )
        patents.extend((await session.scalars(nb_stmt)).all())

    return await _assemble_graph(
        session, patents, similarity_threshold,
        highlighted_patent_ids={patent_id},
    )
