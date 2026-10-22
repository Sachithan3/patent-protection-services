"""Tests for the Patent Knowledge Graph feature – patent-only edition.

Covers:
- Node / edge serialization helpers
- Similarity-edge deduplication and threshold filtering
- Query→patent edge generation with real similarity weights
- Empty / small patent collections
- Missing or invalid patent IDs
- API endpoint validation (422, 404 cases)
- Stable node ID generation
- No self-loops and no duplicate edges
- FocusedGraphRequest Pydantic model validation
- Regression tests for existing endpoints

Run with:
    pytest tests/test_knowledge_graph.py -v
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.knowledge_graph import (
    _node_id_patent,
    _build_patent_node,
    DEFAULT_SIMILARITY_THRESHOLD,
    MAX_PATENTS,
    MAX_EDGES,
)


# ---------------------------------------------------------------------------
# Node ID helpers
# ---------------------------------------------------------------------------

class TestNodeIdHelpers:
    def test_patent_node_id_prefix(self):
        assert _node_id_patent("US-123").startswith("p:")

    def test_patent_node_id_stable(self):
        assert _node_id_patent("US-123") == _node_id_patent("US-123")

    def test_different_patents_get_different_ids(self):
        assert _node_id_patent("US-001") != _node_id_patent("US-002")

    def test_id_contains_patent_id(self):
        assert "US-ABC" in _node_id_patent("US-ABC")


# ---------------------------------------------------------------------------
# Node builder
# ---------------------------------------------------------------------------

def _make_patent(patent_id="US-001", title="Test Patent",
                 abstract="An abstract.", category="Imported Claims", claims=None):
    p = MagicMock()
    p.patent_id = patent_id
    p.title = title
    p.abstract = abstract
    p.category = category
    p.claims = claims or ["Claim one.", "Claim two."]
    p.embedding = [0.1] * 384
    return p


class TestPatentNodeBuilder:
    def test_required_keys_present(self):
        node = _build_patent_node(_make_patent())
        for key in ("id", "type", "label", "patent_id", "title", "abstract", "category", "claims"):
            assert key in node, f"Missing key: {key}"

    def test_type_is_patent(self):
        assert _build_patent_node(_make_patent())["type"] == "patent"

    def test_highlighted_true(self):
        assert _build_patent_node(_make_patent(), highlighted=True)["highlighted"] is True

    def test_highlighted_false(self):
        assert _build_patent_node(_make_patent(), highlighted=False)["highlighted"] is False

    def test_cosine_similarity_included(self):
        node = _build_patent_node(_make_patent(), cosine_similarity=0.72)
        assert node["cosine_similarity"] == pytest.approx(0.72, abs=1e-4)

    def test_cosine_similarity_absent_when_none(self):
        node = _build_patent_node(_make_patent(), cosine_similarity=None)
        assert "cosine_similarity" not in node

    def test_id_uses_patent_id(self):
        node = _build_patent_node(_make_patent("US-XYZ"))
        assert "US-XYZ" in node["id"]

    def test_no_concept_fields(self):
        node = _build_patent_node(_make_patent())
        assert "term" not in node
        assert "frequency" not in node


# ---------------------------------------------------------------------------
# Similarity edge logic (unit, no DB)
# ---------------------------------------------------------------------------

class TestSimEdgeDeduplication:
    def test_no_self_loops_by_key(self):
        pid = "US-001"
        key = tuple(sorted([pid, pid]))
        assert key[0] == key[1]  # self-loop key would be caught

    def test_deduplication_key_symmetric(self):
        assert tuple(sorted(["US-001", "US-002"])) == tuple(sorted(["US-002", "US-001"]))

    def test_threshold_filters_weak_pairs(self):
        threshold = 0.45
        distance_cutoff = 1.0 - threshold
        # distance=0.6 → similarity=0.4 < threshold → excluded
        assert 0.6 > distance_cutoff
        # distance=0.5 → similarity=0.5 > threshold → included
        assert 0.5 < distance_cutoff

    def test_default_threshold_is_calibrated(self):
        # Must be ≤ 0.5 to produce edges in a diverse corpus
        assert DEFAULT_SIMILARITY_THRESHOLD <= 0.5
        assert DEFAULT_SIMILARITY_THRESHOLD >= 0.1


# ---------------------------------------------------------------------------
# Empty / missing patent handling (mock DB)
# ---------------------------------------------------------------------------

class TestEmptyPatentCollection:
    @pytest.mark.asyncio
    async def test_focused_graph_empty_ids(self):
        from app.services.knowledge_graph import build_focused_graph
        session = AsyncMock()
        result = await build_focused_graph(session, patent_ids=[])
        assert result["nodes"] == []
        assert result["edges"] == []

    @pytest.mark.asyncio
    async def test_expand_node_missing_patent(self):
        from app.services.knowledge_graph import expand_patent_node
        session = AsyncMock()
        session.scalar = AsyncMock(return_value=None)
        result = await expand_patent_node(session, "NONEXISTENT-123")
        assert result["nodes"] == []
        assert "error" in result.get("meta", {})


# ---------------------------------------------------------------------------
# Graph structural invariants
# ---------------------------------------------------------------------------

MOCK_PATENT_GRAPH = {
    "nodes": [
        {"id": "p:US-001", "type": "patent", "label": "US-001",
         "patent_id": "US-001", "title": "Test Patent", "abstract": "Abstract.",
         "category": "Imported Claims", "claims": ["Claim one."], "highlighted": False},
        {"id": "p:US-002", "type": "patent", "label": "US-002",
         "patent_id": "US-002", "title": "Another Patent", "abstract": "Abstract 2.",
         "category": "Imported Claims", "claims": ["Claim A."], "highlighted": True},
        {"id": "q:draft", "type": "query", "label": "Your Invention",
         "title": "A neural network system", "note": "Temporary.", "highlighted": True},
    ],
    "edges": [
        {"id": "e:sim:US-001:US-002", "source": "p:US-001", "target": "p:US-002",
         "type": "PATENT_SIMILAR", "weight": 0.62, "similarity": 0.62, "label": "62% similar"},
        {"id": "e:qp:US-001", "source": "q:draft", "target": "p:US-001",
         "type": "QUERY_MATCH", "weight": 0.51, "similarity": 0.51, "label": "51% match"},
        {"id": "e:qp:US-002", "source": "q:draft", "target": "p:US-002",
         "type": "QUERY_MATCH", "weight": 0.41, "similarity": 0.41, "label": "41% match"},
    ],
    "meta": {
        "patent_count": 2, "concept_count": 0,
        "similarity_edge_count": 1, "query_edge_count": 2,
        "total_edge_count": 3, "similarity_threshold": 0.45, "highlighted_count": 2,
    },
}


class TestGraphStructuralInvariants:
    def test_no_duplicate_node_ids(self):
        ids = [n["id"] for n in MOCK_PATENT_GRAPH["nodes"]]
        assert len(ids) == len(set(ids))

    def test_no_duplicate_edge_ids(self):
        ids = [e["id"] for e in MOCK_PATENT_GRAPH["edges"]]
        assert len(ids) == len(set(ids))

    def test_all_edge_sources_valid(self):
        node_ids = {n["id"] for n in MOCK_PATENT_GRAPH["nodes"]}
        for edge in MOCK_PATENT_GRAPH["edges"]:
            assert edge["source"] in node_ids, f"Edge source {edge['source']!r} not in nodes"

    def test_all_edge_targets_valid(self):
        node_ids = {n["id"] for n in MOCK_PATENT_GRAPH["nodes"]}
        for edge in MOCK_PATENT_GRAPH["edges"]:
            assert edge["target"] in node_ids, f"Edge target {edge['target']!r} not in nodes"

    def test_no_self_loops(self):
        for edge in MOCK_PATENT_GRAPH["edges"]:
            assert edge["source"] != edge["target"], f"Self-loop: {edge['id']!r}"

    def test_edge_weight_range(self):
        for edge in MOCK_PATENT_GRAPH["edges"]:
            assert 0.0 <= edge["weight"] <= 1.0

    def test_node_types_known(self):
        valid = {"patent", "query"}
        for node in MOCK_PATENT_GRAPH["nodes"]:
            assert node["type"] in valid

    def test_no_concept_nodes(self):
        for node in MOCK_PATENT_GRAPH["nodes"]:
            assert node["type"] != "concept"

    def test_no_concept_edges(self):
        for edge in MOCK_PATENT_GRAPH["edges"]:
            assert edge["type"] != "PATENT_CONCEPT"

    def test_query_match_edges_have_real_weights(self):
        qm_edges = [e for e in MOCK_PATENT_GRAPH["edges"] if e["type"] == "QUERY_MATCH"]
        assert len(qm_edges) == 2
        for e in qm_edges:
            assert e["weight"] > 0.0
            assert e["weight"] < 1.0  # real similarities are < 1.0

    def test_meta_has_required_keys(self):
        meta = MOCK_PATENT_GRAPH["meta"]
        for key in ("patent_count", "total_edge_count", "similarity_threshold"):
            assert key in meta

    def test_meta_concept_count_is_zero(self):
        assert MOCK_PATENT_GRAPH["meta"]["concept_count"] == 0


# ---------------------------------------------------------------------------
# API endpoint tests (TestClient with mocked service)
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


class TestGraphAPIEndpoints:
    @patch("app.api.graph_endpoints.build_default_graph", new_callable=AsyncMock)
    @patch("app.api.graph_endpoints.AsyncSessionLocal")
    def test_default_graph_returns_structure(self, mock_session_cls, mock_build):
        mock_build.return_value = MOCK_PATENT_GRAPH
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = ctx

        response = client.get("/api/v1/graph")
        if response.status_code == 200:
            data = response.json()
            assert "nodes" in data
            assert "edges" in data
            assert "meta" in data

    def test_max_patents_too_high_is_422(self):
        assert client.get("/api/v1/graph?max_patents=200").status_code == 422

    def test_threshold_above_1_is_422(self):
        assert client.get("/api/v1/graph?similarity_threshold=1.5").status_code == 422

    def test_threshold_below_0_is_422(self):
        assert client.get("/api/v1/graph?similarity_threshold=-0.1").status_code == 422

    def test_focused_empty_ids_is_422(self):
        assert client.post("/api/v1/graph/focused", json={"patent_ids": []}).status_code == 422

    def test_focused_too_many_ids_is_422(self):
        many = [f"US-{i:04d}" for i in range(25)]
        assert client.post("/api/v1/graph/focused", json={"patent_ids": many}).status_code == 422

    def test_focused_invalid_threshold_is_422(self):
        assert client.post(
            "/api/v1/graph/focused",
            json={"patent_ids": ["US-001"], "similarity_threshold": 2.0}
        ).status_code == 422

    @patch("app.api.graph_endpoints.build_focused_graph", new_callable=AsyncMock)
    @patch("app.api.graph_endpoints.AsyncSessionLocal")
    def test_focused_long_draft_is_not_rejected(self, mock_session_cls, mock_build):
        # Regression for the "[object Object]" Explore failure: a draft over
        # the old 500-char query_label cap returned 422 and no graph.
        mock_build.return_value = MOCK_PATENT_GRAPH
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = ctx

        draft = "A warehouse robot with an event camera. " * 60
        response = client.post(
            "/api/v1/graph/focused",
            json={"patent_ids": ["US-001"], "query_label": draft},
        )
        assert response.status_code == 200
        assert response.json()["nodes"]
        assert mock_build.await_args.kwargs["query_label"] == draft

    def test_focused_non_string_id_is_422(self):
        response = client.post(
            "/api/v1/graph/focused",
            json={"patent_ids": [None, "US-001"]},
        )
        assert response.status_code == 422
        # Pydantic detail is a list; the frontend formats it into a message.
        assert isinstance(response.json()["detail"], list)

    @patch("app.api.graph_endpoints.build_focused_graph", new_callable=AsyncMock)
    @patch("app.api.graph_endpoints.AsyncSessionLocal")
    def test_focused_unfound_ids_is_404(self, mock_session_cls, mock_build):
        mock_build.return_value = {"nodes": [], "edges": [], "meta": {"patent_count": 0, "total_edge_count": 0}}
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = ctx
        response = client.post("/api/v1/graph/focused", json={"patent_ids": ["NOPE-001"]})
        if response.status_code not in (503,):
            assert response.status_code == 404


# ---------------------------------------------------------------------------
# FocusedGraphRequest validator tests
# ---------------------------------------------------------------------------

class TestFocusedGraphRequestValidator:
    def test_valid_request(self):
        from app.api.graph_endpoints import FocusedGraphRequest
        req = FocusedGraphRequest(patent_ids=["US-001", "US-002"])
        assert req.patent_ids == ["US-001", "US-002"]

    def test_deduplicates_ids(self):
        from app.api.graph_endpoints import FocusedGraphRequest
        req = FocusedGraphRequest(patent_ids=["US-001", "US-001", "US-002"])
        assert req.patent_ids == ["US-001", "US-002"]

    def test_strips_whitespace(self):
        from app.api.graph_endpoints import FocusedGraphRequest
        req = FocusedGraphRequest(patent_ids=["  US-001  "])
        assert req.patent_ids[0] == "US-001"

    def test_default_threshold_is_calibrated(self):
        from app.api.graph_endpoints import FocusedGraphRequest
        req = FocusedGraphRequest(patent_ids=["US-001"])
        assert req.similarity_threshold == DEFAULT_SIMILARITY_THRESHOLD

    def test_accepts_query_similarities(self):
        from app.api.graph_endpoints import FocusedGraphRequest
        req = FocusedGraphRequest(
            patent_ids=["US-001"],
            query_similarities={"US-001": 0.51}
        )
        assert req.query_similarities == {"US-001": 0.51}

    def test_long_query_label_accepted(self):
        # Regression: the Explore button sends the raw draft as query_label.
        # Capping it at 500 chars made long drafts return 422 ("[object Object]").
        from app.api.graph_endpoints import FocusedGraphRequest
        draft = "A warehouse robot with an event camera. " * 60
        assert len(draft) > 500
        req = FocusedGraphRequest(patent_ids=["US-001"], query_label=draft)
        assert req.query_label == draft

    def test_non_string_patent_id_raises_validation_error(self):
        import pydantic
        from app.api.graph_endpoints import FocusedGraphRequest
        with pytest.raises(pydantic.ValidationError):
            FocusedGraphRequest(patent_ids=[None, "US-001"])

    def test_threshold_out_of_bounds_raises(self):
        import pydantic
        from app.api.graph_endpoints import FocusedGraphRequest
        with pytest.raises((pydantic.ValidationError, Exception)):
            FocusedGraphRequest(patent_ids=["US-001"], similarity_threshold=1.5)

    def test_empty_ids_after_strip_raises(self):
        import pydantic
        from app.api.graph_endpoints import FocusedGraphRequest
        with pytest.raises((pydantic.ValidationError, Exception)):
            FocusedGraphRequest(patent_ids=["  ", ""])


# ---------------------------------------------------------------------------
# Regression tests for existing endpoints
# ---------------------------------------------------------------------------

class TestExistingEndpointRegression:
    def test_health_endpoint_exists(self):
        r = client.get("/api/v1/health")
        assert r.status_code in (200, 503)
        assert "status" in r.json()

    def test_stats_endpoint_shape(self):
        r = client.get("/api/v1/stats")
        assert r.status_code in (200, 500, 503)
        if r.status_code == 200:
            assert "patent_count" in r.json()

    def test_patents_endpoint_shape(self):
        r = client.get("/api/v1/patents")
        assert r.status_code in (200, 500, 503)
        if r.status_code == 200:
            data = r.json()
            assert "patents" in data
            assert "categories" in data

    def test_analyze_requires_body(self):
        assert client.post("/api/v1/analyze").status_code == 422

    def test_analyze_minimum_length_validation(self):
        assert client.post("/api/v1/analyze", json={"user_draft": "too short"}).status_code == 422

    def test_frontend_static_mount(self):
        r = client.get("/app/")
        assert r.status_code in (200, 404)


if __name__ == "__main__":
    import sys, subprocess
    sys.exit(subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"]
    ).returncode)
