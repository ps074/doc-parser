#!/usr/bin/env python3
"""
TurboPuffer vector store for chunking experiments.

Stores chunks with OpenAI text-embedding-3-small embeddings.
Supports vector search, BM25 full-text search, and hybrid retrieval.
"""
import hashlib
import os

from openai import OpenAI
from turbopuffer import Turbopuffer

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536

# Namespace prefix to isolate experiment data
NS_PREFIX = "chunking_exp"


def _get_tpuf_client() -> Turbopuffer:
    return Turbopuffer(region="gcp-us-central1")


def _get_openai_client() -> OpenAI:
    return OpenAI()


def _truncate_for_embedding(text: str, max_tokens: int = 8000) -> str:
    """Truncate text to fit within embedding model token limit."""
    import tiktoken
    enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
    tokens = enc.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return enc.decode(tokens[:max_tokens])


def embed_texts(texts: list[str], client: OpenAI | None = None) -> list[list[float]]:
    """Embed texts using OpenAI text-embedding-3-small."""
    if client is None:
        client = _get_openai_client()

    # Truncate texts that exceed token limit
    texts = [_truncate_for_embedding(t) for t in texts]

    # OpenAI embeds up to 2048 texts per call
    all_embeddings = []
    for i in range(0, len(texts), 2048):
        batch = texts[i:i + 2048]
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        all_embeddings.extend([d.embedding for d in response.data])
    return all_embeddings


def embed_query(query: str, client: OpenAI | None = None) -> list[float]:
    """Embed a single query."""
    if client is None:
        client = _get_openai_client()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=query)
    return response.data[0].embedding


def namespace_id(parser: str, chunker_name: str, doc_name: str) -> str:
    """Generate a unique namespace ID for a parser/chunker/doc combo."""
    return f"{NS_PREFIX}__{parser}__{chunker_name}__{doc_name}"


def upsert_chunks(
    parser: str,
    chunker_name: str,
    doc_name: str,
    chunks: list[dict],
    tpuf: Turbopuffer | None = None,
    oai: OpenAI | None = None,
) -> str:
    """Store chunks in TurboPuffer with embeddings and BM25-enabled text.

    Args:
        chunks: List of dicts with keys: text, page_num, chunk_type, strategy
    Returns:
        namespace ID
    """
    if tpuf is None:
        tpuf = _get_tpuf_client()
    if oai is None:
        oai = _get_openai_client()

    ns_id = namespace_id(parser, chunker_name, doc_name)
    ns = tpuf.namespace(ns_id)

    # Generate embeddings
    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(texts, oai)

    # Build rows
    rows = []
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        rows.append({
            "id": str(i),
            "vector": emb,
            "text": chunk["text"],
            "page_num": chunk.get("page_num", 0),
            "chunk_type": chunk.get("chunk_type", "mixed"),
            "strategy": chunk.get("strategy", chunker_name),
        })

    # Upsert with BM25 schema on text field
    ns.write(
        upsert_rows=rows,
        distance_metric="cosine_distance",
        schema={
            "text": {"type": "string", "full_text_search": True},
            "page_num": {"type": "uint"},
            "chunk_type": {"type": "string"},
            "strategy": {"type": "string"},
        },
    )

    return ns_id


def query_vector(
    ns_id: str,
    query: str,
    top_k: int = 10,
    tpuf: Turbopuffer | None = None,
    oai: OpenAI | None = None,
) -> list[dict]:
    """Vector-only search (ANN)."""
    if tpuf is None:
        tpuf = _get_tpuf_client()
    if oai is None:
        oai = _get_openai_client()

    q_emb = embed_query(query, oai)
    ns = tpuf.namespace(ns_id)

    result = ns.query(
        rank_by=("vector", "ANN", q_emb),
        top_k=top_k,
        include_attributes=["text", "page_num", "chunk_type"],
    )
    return [
        {
            "id": row.id,
            "text": getattr(row, "text", ""),
            "page_num": getattr(row, "page_num", 0),
            "chunk_type": getattr(row, "chunk_type", ""),
            "score": getattr(row, "$dist", 0),
        }
        for row in result.rows
    ]


def query_bm25(
    ns_id: str,
    query: str,
    top_k: int = 10,
    tpuf: Turbopuffer | None = None,
) -> list[dict]:
    """BM25 full-text search."""
    if tpuf is None:
        tpuf = _get_tpuf_client()

    ns = tpuf.namespace(ns_id)

    result = ns.query(
        rank_by=("text", "BM25", query),
        top_k=top_k,
        include_attributes=["text", "page_num", "chunk_type"],
    )
    return [
        {
            "id": row.id,
            "text": getattr(row, "text", ""),
            "page_num": getattr(row, "page_num", 0),
            "chunk_type": getattr(row, "chunk_type", ""),
            "score": getattr(row, "$dist", 0),
        }
        for row in result.rows
    ]


def query_hybrid(
    ns_id: str,
    query: str,
    top_k: int = 10,
    tpuf: Turbopuffer | None = None,
    oai: OpenAI | None = None,
) -> list[dict]:
    """Hybrid search: vector + BM25 with RRF fusion client-side."""
    vector_results = query_vector(ns_id, query, top_k=top_k * 2, tpuf=tpuf, oai=oai)
    bm25_results = query_bm25(ns_id, query, top_k=top_k * 2, tpuf=tpuf)

    # RRF fusion
    k = 60
    scores = {}
    text_map = {}

    for rank, r in enumerate(vector_results):
        rid = r["id"]
        scores[rid] = scores.get(rid, 0) + 0.5 / (k + rank)
        text_map[rid] = r

    for rank, r in enumerate(bm25_results):
        rid = r["id"]
        scores[rid] = scores.get(rid, 0) + 0.5 / (k + rank)
        if rid not in text_map:
            text_map[rid] = r

    # Sort by fused score descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

    return [
        {**text_map[rid], "score": score}
        for rid, score in ranked
    ]


def delete_namespace(
    parser: str,
    chunker_name: str,
    doc_name: str,
    tpuf: Turbopuffer | None = None,
):
    """Delete a namespace (cleanup)."""
    if tpuf is None:
        tpuf = _get_tpuf_client()
    ns_id = namespace_id(parser, chunker_name, doc_name)
    ns = tpuf.namespace(ns_id)
    ns.delete_all()
