"""Regression tests for claim-level evidence scoring."""

from app.services.pipeline import calibrate_report_score, rerank_claim_candidates


class FakeEmbeddingEngine:
    """Small deterministic embedding stub for scoring tests."""

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def _patent() -> dict:
    return {
        "patent_id": "P-1",
        "title": "Sensor navigation",
        "abstract": "Navigation using LiDAR.",
        "claims": [
            "A method comprising receiving LiDAR sensor data and generating an occupancy map.",
            "The method of claim 1 further comprising wireless fleet coordination.",
        ],
        "cosine_similarity": 0.62,
    }


def test_claim_level_evidence_separates_direct_and_unrelated_drafts() -> None:
    direct = rerank_claim_candidates(
        [_patent()],
        "A system receives LiDAR sensor data and generates an occupancy map.",
        [1.0, 0.0],
        FakeEmbeddingEngine(),
    )[0]
    unrelated = rerank_claim_candidates(
        [_patent()],
        "A cryptographic signature uses lattice bases and rejection sampling.",
        [0.0, 1.0],
        FakeEmbeddingEngine(),
    )[0]

    assert direct["claim_overlap_score"] > unrelated["claim_overlap_score"]
    assert direct["matched_claims"]
    assert unrelated["matched_claims"] == []


def test_calibration_uses_independent_claim_evidence_not_llm_score() -> None:
    parsed = {
        "structured": True,
        "report": {
            "risk_score": 99,
            "overall_infringement_risk": "HIGH",
            "risk_factors": [
                {"name": "semantic_similarity", "score": 0, "weight": 20},
                {"name": "claim_element_overlap", "score": 0, "weight": 45},
            ],
        },
    }

    calibrated = calibrate_report_score(
        parsed,
        [{"cosine_similarity": 0.62, "claim_overlap_score": 28, "claims": ["claim"]}],
    )

    assert calibrated["report"]["risk_score"] == 28
    assert calibrated["report"]["overall_infringement_risk"] == "LOW"
    assert calibrated["report"]["risk_score_model"] == "claim_overlap_v2"


def test_abstract_only_scoring_varies_with_feature_overlap() -> None:
    direct = rerank_claim_candidates(
        [{
            "title": "Tree data compression method",
            "abstract": "Compressing leaf nodes while leaving root-child node data uncompressed.",
            "claims": [],
            "cosine_similarity": 0.80,
        }],
        "Compress tree data by leaving root-child nodes uncompressed and compressing leaf-child nodes.",
        [1.0, 0.0],
        FakeEmbeddingEngine(),
    )[0]
    generic = rerank_claim_candidates(
        [{
            "title": "Data processing system",
            "abstract": "A system processes and stores information efficiently.",
            "claims": [],
            "cosine_similarity": 0.80,
        }],
        "Compress tree data by leaving root-child nodes uncompressed and compressing leaf-child nodes.",
        [1.0, 0.0],
        FakeEmbeddingEngine(),
    )[0]

    assert direct["evidence_type"] == "title_abstract"
    assert direct["claim_overlap_score"] > generic["claim_overlap_score"]
    assert direct["claim_overlap_score"] <= 80


def test_abstract_only_evidence_cannot_be_labeled_high_legal_risk() -> None:
    parsed = {
        "structured": True,
        "report": {
            "risk_score": 99,
            "overall_infringement_risk": "HIGH",
            "final_legal_verdict_summary": "Contradictory model summary",
            "risk_factors": [],
        },
    }

    calibrated = calibrate_report_score(
        parsed,
        [{
            "cosine_similarity": 0.79,
            "claim_overlap_score": 71,
            "claims": [],
        }],
    )["report"]

    assert calibrated["risk_score"] == 71
    assert calibrated["overall_infringement_risk"] == "MEDIUM"
    assert "does not establish literal claim overlap" in calibrated["final_legal_verdict_summary"]


def test_calibrated_summary_matches_claim_evidence_score() -> None:
    parsed = {
        "structured": True,
        "report": {
            "risk_score": 15,
            "overall_infringement_risk": "LOW",
            "final_legal_verdict_summary": "The model returned a stale score of 15/100.",
            "risk_factors": [],
        },
    }

    calibrated = calibrate_report_score(
        parsed,
        [{"cosine_similarity": 0.67, "claim_overlap_score": 59, "claims": ["claim"]}],
    )["report"]

    assert calibrated["risk_score"] == 59
    assert calibrated["overall_infringement_risk"] == "MEDIUM"
    assert "59/100" in calibrated["final_legal_verdict_summary"]
    assert "MEDIUM" in calibrated["final_legal_verdict_summary"]
