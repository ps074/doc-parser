#!/usr/bin/env python3
"""Embedding and retrieval: dense (sentence-transformers), BM25, and hybrid."""
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer


class Embedder:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)
        self.model_name = model_name

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(texts, show_progress_bar=False, convert_to_numpy=True)

    def embed_query(self, query: str) -> np.ndarray:
        return self.model.encode(query, convert_to_numpy=True)


def cosine_similarity(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity between query (dim,) and matrix (N, dim). Returns (N,)."""
    q_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
    m_norm = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10)
    return m_norm @ q_norm


class BM25Index:
    """BM25 keyword index over chunk texts."""

    def __init__(self, texts: list[str]):
        # Tokenize by lowercasing and splitting on non-alphanumeric
        self.tokenized = [self._tokenize(t) for t in texts]
        self.index = BM25Okapi(self.tokenized)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return text.lower().split()

    def score(self, query: str) -> np.ndarray:
        """Score all documents against query. Returns (N,) array."""
        tokens = self._tokenize(query)
        return self.index.get_scores(tokens)


def hybrid_scores(
    dense_scores: np.ndarray,
    bm25_scores: np.ndarray,
    dense_weight: float = 0.5,
) -> np.ndarray:
    """Combine dense and BM25 scores using weighted Reciprocal Rank Fusion.

    Both inputs are (N,) score arrays. Returns (N,) fused scores.
    Uses RRF: score = sum(1 / (k + rank)) across both rankings.
    """
    k = 60  # Standard RRF constant

    # Get rankings (0-based, best = 0)
    dense_ranks = np.argsort(np.argsort(-dense_scores))
    bm25_ranks = np.argsort(np.argsort(-bm25_scores))

    # RRF fusion with weighting
    rrf = (
        dense_weight * (1.0 / (k + dense_ranks)) +
        (1.0 - dense_weight) * (1.0 / (k + bm25_ranks))
    )
    return rrf
