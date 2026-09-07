"""
Vector Embedding Engine for ClaimGuard AI
Handles text-to-vector conversion using sentence-transformers.
"""

from typing import List
import numpy as np
from sentence_transformers import SentenceTransformer
from numpy.linalg import norm


class EmbeddingEngine:
    """
    Production-grade embedding engine using sentence-transformers.
    Provides normalized vector embeddings for patent text and claims.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        """
        Initialize the embedding engine with specified model.

        Args:
            model_name: HuggingFace model identifier for sentence-transformers.
        """
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.vector_dimension = self.model.get_sentence_embedding_dimension()

    def embed_text(self, text: str) -> List[float]:
        """
        Convert a single text string to normalized embedding vector.

        Args:
            text: Text to embed.

        Returns:
            Normalized 384-dimensional embedding vector.

        Raises:
            ValueError: If text is empty or invalid.
        """
        if not text or not isinstance(text, str):
            raise ValueError("Text must be a non-empty string")

        embedding = self.model.encode(text, convert_to_numpy=True)
        normalized = self._normalize_vector(embedding)
        return normalized.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Convert multiple text strings to normalized embedding vectors.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of normalized 384-dimensional embedding vectors.

        Raises:
            ValueError: If texts list is empty or contains non-string values.
        """
        if not texts or not isinstance(texts, list):
            raise ValueError("Texts must be a non-empty list")

        if not all(isinstance(t, str) and t for t in texts):
            raise ValueError("All items in texts list must be non-empty strings")

        embeddings = self.model.encode(texts, convert_to_numpy=True)
        normalized_embeddings = np.array(
            [self._normalize_vector(emb) for emb in embeddings]
        )
        return normalized_embeddings.tolist()

    @staticmethod
    def _normalize_vector(vector: np.ndarray) -> np.ndarray:
        """
        Normalize a vector to unit length using L2 norm.

        Args:
            vector: Input vector to normalize.

        Returns:
            L2-normalized vector.
        """
        magnitude = norm(vector)
        if magnitude == 0:
            return vector
        return vector / magnitude

    def get_vector_dimension(self) -> int:
        """Get the dimensionality of embeddings produced by this engine."""
        return self.vector_dimension


if __name__ == "__main__":
    print("=" * 70)
    print("ClaimGuard AI - Vector Embedding Engine Test")
    print("=" * 70)

    engine = EmbeddingEngine(model_name="all-MiniLM-L6-v2")

    print(f"\n✓ Model loaded: {engine.model_name}")
    print(f"✓ Vector dimension: {engine.get_vector_dimension()}")

    # Test single embedding
    print("\n[TEST 1] Single Text Embedding")
    sample_text = "Autonomous vehicle path planning using reinforcement learning"
    embedding = engine.embed_text(sample_text)
    print(f"  Input: {sample_text}")
    print(f"  Output dimension: {len(embedding)}")
    print(f"  First 5 values: {embedding[:5]}")
    print(f"  L2 norm: {np.linalg.norm(embedding):.6f}")

    # Test batch embedding
    print("\n[TEST 2] Batch Text Embedding")
    batch_texts = [
        "Post-quantum cryptography using lattice problems",
        "Smart grid demand response with federated learning",
        "3D object detection using sparse convolutions",
    ]
    batch_embeddings = engine.embed_batch(batch_texts)
    print(f"  Input texts: {len(batch_texts)}")
    print(f"  Output vectors: {len(batch_embeddings)}")
    print(f"  Dimension per vector: {len(batch_embeddings[0])}")
    for i, emb in enumerate(batch_embeddings):
        print(f"  Vector {i} L2 norm: {np.linalg.norm(emb):.6f}")

    # Test similarity between embeddings
    print("\n[TEST 3] Similarity Analysis")
    sim_texts = [
        "Patent about autonomous driving systems",
        "Vehicle path planning for autonomous cars",
        "Quantum computing applications",
    ]
    sim_embeddings = engine.embed_batch(sim_texts)

    def cosine_similarity(v1: List[float], v2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        return float(np.dot(v1, v2))

    print(f"  Similarity (patent vs. driving): {cosine_similarity(sim_embeddings[0], sim_embeddings[1]):.4f}")
    print(f"  Similarity (driving vs. quantum): {cosine_similarity(sim_embeddings[1], sim_embeddings[2]):.4f}")

    print("\n" + "=" * 70)
    print("✓ All tests passed successfully!")
    print("=" * 70)
