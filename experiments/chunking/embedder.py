#!/usr/bin/env python3
"""Embedding and retrieval: OpenAI dense embeddings, BM25, and hybrid."""
import time
import tiktoken
import numpy as np
from openai import OpenAI
from rank_bm25 import BM25Okapi

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536

_enc = tiktoken.encoding_for_model("gpt-3.5-turbo")


def _truncate(text: str, max_tokens: int = 8000) -> str:
    tokens = _enc.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return _enc.decode(tokens[:max_tokens])


class Embedder:
    def __init__(self, model_name: str = EMBEDDING_MODEL):
        self.model_name = model_name
        self._client = OpenAI()

    def _call_with_retry(self, fn, retries=2, backoff=5):
        for attempt in range(retries + 1):
            try:
                return fn()
            except Exception as e:
                if attempt < retries:
                    wait = backoff * (attempt + 1)
                    print(f"  Embedding API error: {e}. Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        texts = [_truncate(t) for t in texts]
        all_embeddings = []
        for i in range(0, len(texts), 2048):
            batch = texts[i:i + 2048]
            response = self._call_with_retry(
                lambda b=batch: self._client.embeddings.create(model=self.model_name, input=b)
            )
            all_embeddings.extend([d.embedding for d in response.data])
        return np.array(all_embeddings, dtype=np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        response = self._call_with_retry(
            lambda: self._client.embeddings.create(model=self.model_name, input=query)
        )
        return np.array(response.data[0].embedding, dtype=np.float32)


def cosine_similarity(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity between query (dim,) and matrix (N, dim). Returns (N,)."""
    q_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
    m_norm = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10)
    return m_norm @ q_norm


class BM25Index:
    """BM25 keyword index over chunk texts."""

    def __init__(self, texts: list[str]):
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
    """Combine dense and BM25 scores using weighted Reciprocal Rank Fusion."""
    k = 60
    dense_ranks = np.argsort(np.argsort(-dense_scores))
    bm25_ranks = np.argsort(np.argsort(-bm25_scores))
    rrf = (
        dense_weight * (1.0 / (k + dense_ranks)) +
        (1.0 - dense_weight) * (1.0 / (k + bm25_ranks))
    )
    return rrf
