#!/usr/bin/env python3
"""
Evaluate chunking strategies for PDF RAG retrieval.

Supports retrieval modes:
  - dense: sentence-transformer cosine similarity (default)
  - bm25: BM25 keyword matching
  - hybrid: RRF fusion of dense + BM25
  - turbopuffer: TurboPuffer vector store (OpenAI embeddings + BM25)
  - turbopuffer_bm25: TurboPuffer BM25 only
  - turbopuffer_hybrid: TurboPuffer vector + BM25 with RRF

Usage:
    python experiments/chunking/eval_chunking.py --parser pymupdf_fast
    python experiments/chunking/eval_chunking.py --parser pipeline --retrieval hybrid
    python experiments/chunking/eval_chunking.py --parser pymupdf_fast --retrieval turbopuffer_hybrid
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

# Add project root to path so we can import parsers
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "parsers"))

from experiments.chunking.chunkers import Chunk, get_all_chunkers, count_tokens
from experiments.chunking.embedder import (
    Embedder, cosine_similarity, BM25Index, hybrid_scores,
)


def load_markdown(doc_name: str, parser: str, pdf_path: Path) -> str:
    """Load or generate parsed markdown."""
    if parser == "pipeline":
        md_path = PROJECT_ROOT / "output" / "pipeline" / doc_name / f"{doc_name}.md"
        if md_path.exists():
            print(f"  Loading pre-parsed pipeline output: {md_path}")
            return md_path.read_text()
        raise FileNotFoundError(
            f"No pipeline output found at {md_path}. "
            f"Run: python parsers/pipeline.py {pdf_path}"
        )
    elif parser == "pymupdf_fast":
        from pymupdf_fast import parse_document
        print(f"  Parsing with pymupdf_fast: {pdf_path}")
        return parse_document(pdf_path)
    else:
        raise ValueError(f"Unknown parser: {parser}")


def load_qa_pairs(qa_path: Path) -> dict:
    with open(qa_path) as f:
        return json.load(f)["documents"]


def check_recall(chunks: list[Chunk], retrieved_indices: list[int],
                 expected_keywords: list[str]) -> bool:
    """Check if ANY expected keyword appears in ANY of the retrieved chunks."""
    retrieved_text = " ".join(chunks[i].text for i in retrieved_indices)
    retrieved_lower = retrieved_text.lower()
    return any(kw.lower() in retrieved_lower for kw in expected_keywords)


def rank_chunks(
    chunks: list[Chunk],
    query: str,
    embedder: Embedder,
    chunk_embeddings: np.ndarray,
    bm25_index: BM25Index | None,
    retrieval_mode: str,
) -> np.ndarray:
    """Rank chunks by relevance to query. Returns indices sorted best-first."""
    if retrieval_mode == "dense":
        q_embedding = embedder.embed_query(query)
        scores = cosine_similarity(q_embedding, chunk_embeddings)
    elif retrieval_mode == "bm25":
        scores = bm25_index.score(query)
    elif retrieval_mode == "hybrid":
        q_embedding = embedder.embed_query(query)
        dense = cosine_similarity(q_embedding, chunk_embeddings)
        bm25 = bm25_index.score(query)
        scores = hybrid_scores(dense, bm25, dense_weight=0.5)
    else:
        raise ValueError(f"Unknown retrieval mode: {retrieval_mode}")

    return np.argsort(scores)[::-1]


def evaluate_chunker(
    chunker,
    markdown: str,
    questions: list[dict],
    embedder: Embedder,
    retrieval_mode: str = "dense",
    k_values: list[int] = None,
    parser_name: str = "",
    doc_name: str = "",
) -> dict:
    """Run evaluation for one chunker on one document."""
    if k_values is None:
        k_values = [1, 3, 5, 10]

    chunks = chunker.chunk(markdown)
    if not chunks:
        return {
            "chunker": chunker.name, "num_chunks": 0,
            **{f"recall@{k}": 0.0 for k in k_values},
        }

    chunk_texts = [c.text for c in chunks]
    token_counts = [count_tokens(t) for t in chunk_texts]
    avg_tokens = sum(token_counts) / len(token_counts)

    is_tpuf = retrieval_mode.startswith("turbopuffer")

    if is_tpuf:
        from experiments.chunking.store import (
            upsert_chunks, query_vector, query_bm25, query_hybrid,
        )
        # Upsert to TurboPuffer
        chunk_dicts = [
            {
                "text": c.text,
                "page_num": c.metadata.get("page_num", 0),
                "chunk_type": str(c.metadata.get("chunk_type", "mixed")),
                "strategy": chunker.name,
            }
            for c in chunks
        ]
        ns_id = upsert_chunks(parser_name, chunker.name, doc_name, chunk_dicts)

        # Pick the right query function
        if retrieval_mode == "turbopuffer":
            query_fn = lambda q, k: query_vector(ns_id, q, top_k=k)
        elif retrieval_mode == "turbopuffer_bm25":
            query_fn = lambda q, k: query_bm25(ns_id, q, top_k=k)
        elif retrieval_mode == "turbopuffer_hybrid":
            query_fn = lambda q, k: query_hybrid(ns_id, q, top_k=k)
        else:
            raise ValueError(f"Unknown turbopuffer mode: {retrieval_mode}")

        # Evaluate
        recalls = {k: [] for k in k_values}
        per_question = []
        max_k = max(k_values)

        for q in questions:
            results = query_fn(q["question"], max_k)
            retrieved_texts = [r["text"] for r in results]

            q_result = {"id": q["id"]}
            for k in k_values:
                top_texts = " ".join(retrieved_texts[:k])
                hit = any(
                    kw.lower() in top_texts.lower()
                    for kw in q["expected_keywords"]
                )
                recalls[k].append(hit)
                q_result[f"recall@{k}"] = hit
            per_question.append(q_result)
    else:
        # Local retrieval (dense/bm25/hybrid)
        chunk_embeddings = embedder.embed_texts(chunk_texts)
        bm25_index = BM25Index(chunk_texts) if retrieval_mode in ("bm25", "hybrid") else None

        recalls = {k: [] for k in k_values}
        per_question = []

        for q in questions:
            top_indices = rank_chunks(
                chunks, q["question"], embedder, chunk_embeddings,
                bm25_index, retrieval_mode,
            )

            q_result = {"id": q["id"]}
            for k in k_values:
                actual_k = min(k, len(chunks))
                hit = check_recall(chunks, top_indices[:actual_k].tolist(),
                                   q["expected_keywords"])
                recalls[k].append(hit)
                q_result[f"recall@{k}"] = hit
            per_question.append(q_result)

    return {
        "chunker": chunker.name,
        "num_chunks": len(chunks),
        "avg_chunk_tokens": round(avg_tokens, 1),
        "min_chunk_tokens": min(token_counts),
        "max_chunk_tokens": max(token_counts),
        **{f"recall@{k}": round(sum(v) / len(v), 3) for k, v in recalls.items()},
        "per_question": per_question,
    }


def run_evaluation(
    parser: str,
    pdf_paths: list[Path],
    qa_path: Path,
    retrieval_mode: str = "dense",
    embedding_model: str = "all-MiniLM-L6-v2",
    include_contextual: bool = False,
) -> list[dict]:
    """Run all chunkers across all documents."""
    qa_data = load_qa_pairs(qa_path)
    embedder = Embedder(embedding_model)
    chunkers = get_all_chunkers(include_contextual=include_contextual)

    all_results = {c.name: [] for c in chunkers}

    for pdf_path in pdf_paths:
        doc_name = pdf_path.stem
        if doc_name not in qa_data:
            print(f"  Skipping {doc_name} (no QA pairs)")
            continue

        print(f"\n{'=' * 60}")
        print(f"Document: {doc_name} ({parser}, {retrieval_mode})")
        print(f"{'=' * 60}")

        try:
            markdown = load_markdown(doc_name, parser, pdf_path)
        except FileNotFoundError as e:
            print(f"  ERROR: {e}")
            continue

        questions = qa_data[doc_name]["questions"]
        print(f"  {len(questions)} questions, markdown length: {len(markdown)} chars")

        for chunker in chunkers:
            t0 = time.time()
            result = evaluate_chunker(
                chunker, markdown, questions, embedder,
                retrieval_mode=retrieval_mode,
                parser_name=parser, doc_name=doc_name,
            )
            result["document"] = doc_name
            result["parser"] = parser
            result["retrieval"] = retrieval_mode
            result["chunk_time"] = round(time.time() - t0, 3)
            all_results[chunker.name].append(result)

            print(f"  {chunker.name:<30} "
                  f"chunks={result['num_chunks']:<4} "
                  f"avg_tok={result['avg_chunk_tokens']:<7} "
                  f"R@1={result['recall@1']:.3f} "
                  f"R@3={result['recall@3']:.3f} "
                  f"R@5={result['recall@5']:.3f} "
                  f"R@10={result['recall@10']:.3f}")

    # Aggregate across documents
    aggregated = []
    for chunker_name, doc_results in all_results.items():
        if not doc_results:
            continue
        agg = {
            "chunker": chunker_name,
            "parser": parser,
            "retrieval": retrieval_mode,
            "num_docs": len(doc_results),
            "avg_num_chunks": round(np.mean([r["num_chunks"] for r in doc_results]), 1),
            "avg_chunk_tokens": round(np.mean([r["avg_chunk_tokens"] for r in doc_results]), 1),
        }
        for k in [1, 3, 5, 10]:
            key = f"recall@{k}"
            agg[key] = round(np.mean([r[key] for r in doc_results]), 3)
        agg["per_document"] = doc_results
        aggregated.append(agg)

    return aggregated


def print_comparison_table(results: list[dict]):
    retrieval = results[0]["retrieval"] if results else "dense"
    print(f"\n{'=' * 100}")
    print(f"{'CHUNKING STRATEGY COMPARISON (' + retrieval + ')':^100}")
    print(f"{'=' * 100}")
    print(f"{'Strategy':<30} {'Parser':<15} {'Chunks':>7} {'Avg Tok':>8} "
          f"{'R@1':>6} {'R@3':>6} {'R@5':>6} {'R@10':>6}")
    print("-" * 100)

    for r in sorted(results, key=lambda x: x["recall@5"], reverse=True):
        print(f"{r['chunker']:<30} {r['parser']:<15} "
              f"{r['avg_num_chunks']:>7.0f} {r['avg_chunk_tokens']:>8.1f} "
              f"{r['recall@1']:>6.3f} {r['recall@3']:>6.3f} "
              f"{r['recall@5']:>6.3f} {r['recall@10']:>6.3f}")


def print_per_document_table(results: list[dict]):
    print(f"\n{'=' * 100}")
    print(f"{'PER-DOCUMENT BREAKDOWN':^100}")
    print(f"{'=' * 100}")

    for r in sorted(results, key=lambda x: x["recall@5"], reverse=True):
        print(f"\n  {r['chunker']} ({r['parser']}, {r['retrieval']}):")
        for doc_r in r.get("per_document", []):
            print(f"    {doc_r['document']:<25} "
                  f"chunks={doc_r['num_chunks']:<4} "
                  f"R@1={doc_r['recall@1']:.3f} "
                  f"R@3={doc_r['recall@3']:.3f} "
                  f"R@5={doc_r['recall@5']:.3f} "
                  f"R@10={doc_r['recall@10']:.3f}")


def save_results(results: list[dict], output_dir: Path, parser: str, retrieval: str):
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"{parser}_{retrieval}"

    json_path = output_dir / f"results_{suffix}.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    csv_path = output_dir / f"summary_{suffix}.csv"
    with open(csv_path, "w") as f:
        headers = ["strategy", "parser", "retrieval", "num_chunks", "avg_tokens",
                    "recall@1", "recall@3", "recall@5", "recall@10"]
        f.write(",".join(headers) + "\n")
        for r in sorted(results, key=lambda x: x["recall@5"], reverse=True):
            row = [
                r["chunker"], r["parser"], r["retrieval"],
                str(r["avg_num_chunks"]), str(r["avg_chunk_tokens"]),
                str(r["recall@1"]), str(r["recall@3"]),
                str(r["recall@5"]), str(r["recall@10"]),
            ]
            f.write(",".join(row) + "\n")

    print(f"\nResults saved to {json_path} and {csv_path}")


def append_to_comparison_md(results: list[dict], parser: str, retrieval: str):
    """Append a timestamped run to CHUNKING_COMPARISON.md."""
    from datetime import datetime

    md_path = PROJECT_ROOT / "CHUNKING_COMPARISON.md"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    docs = set()
    total_questions = 0
    for r in results:
        for d in r.get("per_document", []):
            docs.add(d["document"])
            total_questions = max(total_questions,
                                  sum(len(d.get("per_question", [])) for d in r.get("per_document", [])))

    lines = [
        f"\n---\n",
        f"## Run: {timestamp} | {parser} + {retrieval}\n",
        f"**Documents**: {', '.join(sorted(docs))}\n",
        f"",
        f"| Strategy | Chunks | Avg Tok | R@1 | R@3 | R@5 | R@10 |",
        f"|----------|:------:|:-------:|:---:|:---:|:---:|:----:|",
    ]

    for r in sorted(results, key=lambda x: (x["recall@5"], x["recall@1"]), reverse=True):
        lines.append(
            f"| {r['chunker']} | {r['avg_num_chunks']:.0f} | {r['avg_chunk_tokens']:.0f} | "
            f"{r['recall@1']:.3f} | {r['recall@3']:.3f} | {r['recall@5']:.3f} | {r['recall@10']:.3f} |"
        )

    lines.append("")

    with open(md_path, "a") as f:
        f.write("\n".join(lines))

    print(f"Appended to {md_path}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate chunking strategies")
    parser.add_argument("--parser", choices=["pymupdf_fast", "pipeline"],
                        required=True)
    parser.add_argument("--retrieval",
                        choices=["dense", "bm25", "hybrid",
                                 "turbopuffer", "turbopuffer_bm25", "turbopuffer_hybrid"],
                        default="dense",
                        help="Retrieval mode (default: dense)")
    parser.add_argument("--contextual", action="store_true",
                        help="Include contextual retrieval variants (requires OpenAI API)")
    parser.add_argument("--docs", nargs="+", type=Path,
                        default=[
                            Path("docs/VAM-3852AO.pdf"),
                            Path("docs/hubspot-q4.pdf"),
                            Path("docs/hubspot-deck.pdf"),
                            Path("docs/2023_report_40_pages.pdf"),
                        ])
    parser.add_argument("--qa", type=Path,
                        default=Path("experiments/chunking/qa_pairs.json"))
    parser.add_argument("--embedding-model", default="all-MiniLM-L6-v2")
    parser.add_argument("--output-dir", type=Path,
                        default=Path("experiments/chunking/results"))
    parser.add_argument("--per-doc", action="store_true",
                        help="Show per-document breakdown")
    args = parser.parse_args()

    results = run_evaluation(
        parser=args.parser,
        pdf_paths=args.docs,
        qa_path=args.qa,
        retrieval_mode=args.retrieval,
        embedding_model=args.embedding_model,
        include_contextual=args.contextual,
    )

    print_comparison_table(results)
    if args.per_doc:
        print_per_document_table(results)
    save_results(results, args.output_dir, args.parser, args.retrieval)
    append_to_comparison_md(results, args.parser, args.retrieval)


if __name__ == "__main__":
    main()
