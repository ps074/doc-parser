#!/usr/bin/env python3
"""
Evaluate chunking strategies for PDF RAG retrieval.

Supports retrieval modes:
  - dense: OpenAI text-embedding-3-small cosine similarity
  - bm25: BM25 keyword matching
  - hybrid: RRF fusion of dense + BM25 (default)
  - turbopuffer / turbopuffer_bm25 / turbopuffer_hybrid: TurboPuffer vector store
  - pdftriage / pdftriage_pipeline: Structure-aware LLM triage (no chunking)

Usage:
    python experiments/chunking/eval_chunking.py --parser pymupdf_fast
    python experiments/chunking/eval_chunking.py --parser pipeline --retrieval hybrid
    python experiments/chunking/eval_chunking.py --parser pipeline --retrieval pdftriage_pipeline
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


def load_markdown(doc_name: str, parser: str, pdf_path: Path, force_parse: bool = False) -> str:
    """Load or generate parsed markdown."""
    if parser == "pipeline":
        md_path = PROJECT_ROOT / "output" / "pipeline" / doc_name / f"{doc_name}.md"
        if md_path.exists() and not force_parse:
            print(f"  Loading pre-parsed pipeline output: {md_path}")
            return md_path.read_text()
        if force_parse:
            import asyncio
            from pipeline import run_pipeline
            print(f"  Force-parsing with pipeline: {pdf_path}")
            asyncio.run(run_pipeline(pdf_path))
            return md_path.read_text()
        raise FileNotFoundError(
            f"No pipeline output found at {md_path}. "
            f"Run: python parsers/pipeline.py {pdf_path}"
        )
    elif parser == "pymupdf_fast":
        from pymupdf_fast import parse_document
        print(f"  Parsing with pymupdf_fast: {pdf_path}")
        return parse_document(pdf_path)
    elif parser == "pymupdf4llm":
        import pymupdf4llm
        print(f"  Parsing with pymupdf4llm: {pdf_path}")
        pages = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True, show_progress=False)
        parts = []
        for page in pages:
            pn = page["metadata"]["page_number"]
            parts.append(f"<!-- page: {pn} -->\n\n{page['text']}")
        return "\n\n".join(parts)
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


def compute_mrr_rank(chunks: list[Chunk], ranked_indices: list[int],
                     expected_keywords: list[str]) -> int | None:
    """Find the 1-based rank of the first chunk containing any expected keyword.
    Returns None if no chunk matches."""
    for rank_pos, idx in enumerate(ranked_indices):
        text_lower = chunks[idx].text.lower()
        if any(kw.lower() in text_lower for kw in expected_keywords):
            return rank_pos + 1
    return None


def compute_mrr_rank_from_texts(texts: list[str],
                                expected_keywords: list[str]) -> int | None:
    """MRR rank from ordered list of retrieved text strings (TurboPuffer path)."""
    for rank_pos, text in enumerate(texts):
        if any(kw.lower() in text.lower() for kw in expected_keywords):
            return rank_pos + 1
    return None


def llm_eval_answer(question: str, context_chunks: list[str],
                    expected_keywords: list[str]) -> tuple[bool, str]:
    """Send top-k chunks + question to LLM, check if answer contains keywords.
    Returns (hit, answer_text)."""
    from openai import OpenAI
    client = OpenAI()

    context = "\n\n---\n\n".join(context_chunks)
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        temperature=0,
        max_tokens=512,
        messages=[
            {"role": "system", "content": (
                "Answer the question using only the provided context. "
                "Use exact numbers, dollar amounts, and percentages from the context. "
                "Do not round or approximate any values."
            )},
            {"role": "user", "content": (
                f"Context:\n{context}\n\n"
                f"Question: {question}"
            )},
        ],
    )
    answer = response.choices[0].message.content.strip()
    hit = any(kw.lower() in answer.lower() for kw in expected_keywords)
    return hit, answer


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


def _save_eval_chunks(chunks: list[Chunk], chunker_name: str, doc_name: str):
    """Save chunks to the pipeline output dir for inspection."""
    out_dir = PROJECT_ROOT / "output" / "pipeline" / doc_name
    if not out_dir.exists():
        return
    out_path = out_dir / f"{doc_name}_chunks_{chunker_name}.json"
    data = [
        {
            "id": i,
            "text": c.text,
            "chunk_type": str(c.metadata.get("chunk_type", "")),
            "page_num": c.metadata.get("page_num"),
            "tokens": count_tokens(c.text),
        }
        for i, c in enumerate(chunks)
    ]
    out_path.write_text(json.dumps(data, indent=2))


def evaluate_chunker(
    chunker,
    markdown: str,
    questions: list[dict],
    embedder: Embedder,
    retrieval_mode: str = "dense",
    k_values: list[int] = None,
    parser_name: str = "",
    doc_name: str = "",
    llm_eval: bool = False,
) -> dict:
    """Run evaluation for one chunker on one document."""
    if k_values is None:
        k_values = [1, 3, 5, 10]

    chunks = chunker.chunk(markdown)
    # Save chunks to the pipeline output dir for inspection
    if parser_name == "pipeline" and doc_name:
        _save_eval_chunks(chunks, chunker.name, doc_name)

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

            q_result = {
                "id": q["id"],
                "question": q["question"],
                "expected_keywords": q["expected_keywords"],
            }
            for k in k_values:
                top_texts = " ".join(retrieved_texts[:k])
                hit = any(
                    kw.lower() in top_texts.lower()
                    for kw in q["expected_keywords"]
                )
                recalls[k].append(hit)
                q_result[f"recall@{k}"] = hit

            # MRR
            q_result["mrr_rank"] = compute_mrr_rank_from_texts(
                retrieved_texts, q["expected_keywords"]
            )

            # Top-5 retrieved chunks for debugging
            q_result["retrieved_chunks"] = [
                {"rank": i + 1, "text": t[:500],
                 "has_keyword": any(kw.lower() in t.lower() for kw in q["expected_keywords"])}
                for i, t in enumerate(retrieved_texts[:5])
            ]

            # LLM eval
            if llm_eval:
                hit, answer = llm_eval_answer(
                    q["question"], retrieved_texts[:5], q["expected_keywords"]
                )
                q_result["llm_hit"] = hit
                q_result["llm_answer"] = answer

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

            q_result = {
                "id": q["id"],
                "question": q["question"],
                "expected_keywords": q["expected_keywords"],
            }
            for k in k_values:
                actual_k = min(k, len(chunks))
                hit = check_recall(chunks, top_indices[:actual_k].tolist(),
                                   q["expected_keywords"])
                recalls[k].append(hit)
                q_result[f"recall@{k}"] = hit

            # MRR: scan full ranking
            q_result["mrr_rank"] = compute_mrr_rank(
                chunks, top_indices.tolist(), q["expected_keywords"]
            )

            # Top-5 retrieved chunks for debugging
            top5_idx = top_indices[:min(5, len(chunks))].tolist()
            q_result["retrieved_chunks"] = [
                {"rank": i + 1, "chunk_index": idx,
                 "page_num": chunks[idx].metadata.get("page_num"),
                 "chunk_type": str(chunks[idx].metadata.get("chunk_type", "")),
                 "text": chunks[idx].text[:500],
                 "has_keyword": any(kw.lower() in chunks[idx].text.lower()
                                    for kw in q["expected_keywords"])}
                for i, idx in enumerate(top5_idx)
            ]

            # LLM eval on top-5
            if llm_eval:
                top5_texts = [chunks[i].text for i in top5_idx]
                hit, answer = llm_eval_answer(
                    q["question"], top5_texts, q["expected_keywords"]
                )
                q_result["llm_hit"] = hit
                q_result["llm_answer"] = answer

            per_question.append(q_result)

    # Compute MRR
    mrr_ranks = [pq["mrr_rank"] for pq in per_question if pq["mrr_rank"] is not None]
    mrr = round(np.mean([1.0 / r for r in mrr_ranks]), 3) if mrr_ranks else 0.0

    result = {
        "chunker": chunker.name,
        "num_chunks": len(chunks),
        "avg_chunk_tokens": round(avg_tokens, 1),
        "min_chunk_tokens": min(token_counts),
        "max_chunk_tokens": max(token_counts),
        "mrr": mrr,
        **{f"recall@{k}": round(sum(v) / len(v), 3) for k, v in recalls.items()},
        "per_question": per_question,
    }

    if llm_eval:
        llm_hits = [pq["llm_hit"] for pq in per_question]
        result["llm_recall@5"] = round(sum(llm_hits) / len(llm_hits), 3)

    return result


def run_pdftriage_evaluation(
    pdf_paths: list[Path],
    qa_path: Path,
    use_pipeline: bool = False,
) -> list[dict]:
    """Run PDFTriage evaluation (structure-aware, no chunking)."""
    from experiments.chunking.pdftriage import extract_structure, triage_answer

    qa_data = load_qa_pairs(qa_path)
    all_doc_results = []

    for pdf_path in pdf_paths:
        doc_name = pdf_path.stem
        if doc_name not in qa_data:
            print(f"  Skipping {doc_name} (no QA pairs)")
            continue

        mode_label = "pdftriage_pipeline" if use_pipeline else "pdftriage"
        print(f"\n{'=' * 60}")
        print(f"Document: {doc_name} ({mode_label})")
        print(f"{'=' * 60}")

        structure = extract_structure(pdf_path, use_pipeline=use_pipeline)
        questions = qa_data[doc_name]["questions"]
        print(f"  {len(questions)} questions, {len(structure.sections)} sections, {len(structure.tables)} tables")

        hits = 0
        per_question = []
        total_tokens = 0

        for q in questions:
            t0 = time.time()
            result = triage_answer(q["question"], structure, verbose=False)
            elapsed = time.time() - t0
            answer = result["answer"]

            hit = any(kw.lower() in answer.lower() for kw in q["expected_keywords"])
            hits += hit
            total_tokens += result["total_tokens"]
            status = "HIT" if hit else "MISS"

            tools = ", ".join(tc["function"] for tc in result["tool_calls"])
            print(f"  {status}  {q['id']:<10} {q['question'][:45]:<47} "
                  f"tools=[{tools}]  {elapsed:.1f}s")

            per_question.append({
                "id": q["id"],
                "recall@1": hit,
                "recall@3": hit,
                "recall@5": hit,
                "recall@10": hit,
                "tool_calls": result["tool_calls"],
                "tokens": result["total_tokens"],
            })

        accuracy = hits / len(questions) if questions else 0
        print(f"\n  Accuracy: {hits}/{len(questions)} ({accuracy:.0%}), tokens: {total_tokens}")

        all_doc_results.append({
            "document": doc_name,
            "num_chunks": len(structure.tables) + len(structure.sections),
            "avg_chunk_tokens": 0,
            "mrr": 0.0,
            "recall@1": round(accuracy, 3),
            "recall@3": round(accuracy, 3),
            "recall@5": round(accuracy, 3),
            "recall@10": round(accuracy, 3),
            "per_question": per_question,
            "total_tokens": total_tokens,
        })

    # Aggregate
    if not all_doc_results:
        return []

    retrieval_label = "pdftriage_pipeline" if use_pipeline else "pdftriage"
    agg = {
        "chunker": "pdftriage",
        "parser": "pipeline" if use_pipeline else "pymupdf4llm",
        "retrieval": retrieval_label,
        "num_docs": len(all_doc_results),
        "avg_num_chunks": round(np.mean([r["num_chunks"] for r in all_doc_results]), 1),
        "avg_chunk_tokens": 0,
        "mrr": 0.0,
    }
    for k in [1, 3, 5, 10]:
        key = f"recall@{k}"
        agg[key] = round(np.mean([r[key] for r in all_doc_results]), 3)
    agg["per_document"] = all_doc_results

    return [agg]


def run_evaluation(
    parser: str,
    pdf_paths: list[Path],
    qa_path: Path,
    retrieval_mode: str = "dense",
    embedding_model: str = "text-embedding-3-small",
    include_contextual: bool = False,
    llm_eval: bool = False,
    chunker_filter: list[str] | None = None,
    force_parse: bool = False,
) -> list[dict]:
    """Run all chunkers across all documents."""
    # PDFTriage is a completely different path — no chunking
    if retrieval_mode in ("pdftriage", "pdftriage_pipeline"):
        return run_pdftriage_evaluation(
            pdf_paths, qa_path,
            use_pipeline=(retrieval_mode == "pdftriage_pipeline"),
        )

    qa_data = load_qa_pairs(qa_path)
    embedder = Embedder(embedding_model)
    chunkers = get_all_chunkers(include_contextual=include_contextual)
    if chunker_filter:
        chunkers = [c for c in chunkers if c.name in chunker_filter]
        if not chunkers:
            print(f"  ERROR: No chunkers matched filter {chunker_filter}")
            return []

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
            markdown = load_markdown(doc_name, parser, pdf_path, force_parse=force_parse)
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
                llm_eval=llm_eval,
            )
            result["document"] = doc_name
            result["parser"] = parser
            result["retrieval"] = retrieval_mode
            result["chunk_time"] = round(time.time() - t0, 3)
            all_results[chunker.name].append(result)

            line = (f"  {chunker.name:<30} "
                    f"chunks={result['num_chunks']:<4} "
                    f"avg_tok={result['avg_chunk_tokens']:<7} "
                    f"R@1={result['recall@1']:.3f} "
                    f"R@5={result['recall@5']:.3f} "
                    f"MRR={result['mrr']:.3f}")
            if llm_eval:
                line += f" LLM@5={result['llm_recall@5']:.3f}"
            print(line)

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
            "mrr": round(np.mean([r["mrr"] for r in doc_results]), 3),
        }
        for k in [1, 3, 5, 10]:
            key = f"recall@{k}"
            agg[key] = round(np.mean([r[key] for r in doc_results]), 3)
        if llm_eval:
            agg["llm_recall@5"] = round(np.mean([r["llm_recall@5"] for r in doc_results]), 3)
        agg["per_document"] = doc_results
        aggregated.append(agg)

    return aggregated


def print_comparison_table(results: list[dict]):
    retrieval = results[0]["retrieval"] if results else "dense"
    has_llm = any("llm_recall@5" in r for r in results)

    print(f"\n{'=' * 110}")
    print(f"{'CHUNKING STRATEGY COMPARISON (' + retrieval + ')':^110}")
    print(f"{'=' * 110}")
    header = (f"{'Strategy':<30} {'Parser':<15} {'Chunks':>7} {'Avg Tok':>8} "
              f"{'R@1':>6} {'R@3':>6} {'R@5':>6} {'R@10':>6} {'MRR':>6}")
    if has_llm:
        header += f" {'LLM@5':>6}"
    print(header)
    print("-" * len(header))

    for r in sorted(results, key=lambda x: x.get("mrr", 0), reverse=True):
        line = (f"{r['chunker']:<30} {r['parser']:<15} "
                f"{r['avg_num_chunks']:>7.0f} {r['avg_chunk_tokens']:>8.1f} "
                f"{r['recall@1']:>6.3f} {r['recall@3']:>6.3f} "
                f"{r['recall@5']:>6.3f} {r['recall@10']:>6.3f} "
                f"{r.get('mrr', 0):>6.3f}")
        if has_llm:
            line += f" {r.get('llm_recall@5', 0):>6.3f}"
        print(line)


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
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"{parser}_{retrieval}_{ts}"

    json_path = output_dir / f"results_{suffix}.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    csv_path = output_dir / f"summary_{suffix}.csv"
    has_llm = any("llm_recall@5" in r for r in results)
    with open(csv_path, "w") as f:
        headers = ["strategy", "parser", "retrieval", "num_chunks", "avg_tokens",
                    "recall@1", "recall@3", "recall@5", "recall@10", "mrr"]
        if has_llm:
            headers.append("llm_recall@5")
        f.write(",".join(headers) + "\n")
        for r in sorted(results, key=lambda x: x.get("mrr", 0), reverse=True):
            row = [
                r["chunker"], r["parser"], r["retrieval"],
                str(r["avg_num_chunks"]), str(r["avg_chunk_tokens"]),
                str(r["recall@1"]), str(r["recall@3"]),
                str(r["recall@5"]), str(r["recall@10"]),
                str(r.get("mrr", 0)),
            ]
            if has_llm:
                row.append(str(r.get("llm_recall@5", "")))
            f.write(",".join(row) + "\n")

    # Save per-strategy detail files for debugging
    detail_dir = output_dir / f"details_{suffix}"
    detail_dir.mkdir(parents=True, exist_ok=True)
    for r in results:
        for doc_r in r.get("per_document", []):
            doc_name = doc_r.get("document", "unknown")
            chunker_name = r["chunker"]
            detail = {
                "chunker": chunker_name,
                "document": doc_name,
                "parser": r["parser"],
                "retrieval": r["retrieval"],
                "num_chunks": doc_r["num_chunks"],
                "mrr": doc_r.get("mrr", 0),
                **{k: doc_r[k] for k in doc_r if k.startswith("recall@")},
            }
            if "llm_recall@5" in doc_r:
                detail["llm_recall@5"] = doc_r["llm_recall@5"]
            detail["questions"] = doc_r.get("per_question", [])
            detail_path = detail_dir / f"{chunker_name}_{doc_name}.json"
            with open(detail_path, "w") as f:
                json.dump(detail, f, indent=2, default=str)

    print(f"\nResults saved to {json_path} and {csv_path}")
    print(f"Per-strategy details saved to {detail_dir}/")


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

    has_llm = any("llm_recall@5" in r for r in results)

    header_row = "| Strategy | Chunks | Avg Tok | R@1 | R@3 | R@5 | R@10 | MRR |"
    sep_row = "|----------|:------:|:-------:|:---:|:---:|:---:|:----:|:---:|"
    if has_llm:
        header_row += " LLM@5 |"
        sep_row += ":-----:|"

    lines = [
        f"\n---\n",
        f"## Run: {timestamp} | {parser} + {retrieval}\n",
        f"**Documents**: {', '.join(sorted(docs))}\n",
        f"",
        header_row,
        sep_row,
    ]

    for r in sorted(results, key=lambda x: (x.get("mrr", 0), x["recall@5"]), reverse=True):
        row = (f"| {r['chunker']} | {r['avg_num_chunks']:.0f} | {r['avg_chunk_tokens']:.0f} | "
               f"{r['recall@1']:.3f} | {r['recall@3']:.3f} | {r['recall@5']:.3f} | "
               f"{r['recall@10']:.3f} | {r.get('mrr', 0):.3f} |")
        if has_llm:
            row += f" {r.get('llm_recall@5', 0):.3f} |"
        lines.append(row)

    lines.append("")

    with open(md_path, "a") as f:
        f.write("\n".join(lines))

    print(f"Appended to {md_path}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate chunking strategies")
    parser.add_argument("--parser", choices=["pymupdf_fast", "pymupdf4llm", "pipeline"],
                        required=True)
    parser.add_argument("--retrieval",
                        choices=["dense", "bm25", "hybrid",
                                 "turbopuffer", "turbopuffer_bm25", "turbopuffer_hybrid",
                                 "pdftriage", "pdftriage_pipeline"],
                        default="hybrid",
                        help="Retrieval mode (default: hybrid)")
    parser.add_argument("--contextual", action="store_true",
                        help="Include contextual retrieval variants (requires OpenAI API)")
    parser.add_argument("--docs", nargs="+", type=Path,
                        default=[
                            Path("docs/VAM-3852AO.pdf"),
                            Path("docs/hubspot-q4.pdf"),
                            Path("docs/hubspot-deck.pdf"),
                            Path("docs/2023_report_40_pages.pdf"),
                            Path("docs/10Q.pdf"),
                            Path("docs/kiski.pdf"),
                            Path("docs/report.pdf"),
                        ])
    parser.add_argument("--qa", type=Path,
                        default=Path("experiments/chunking/qa_pairs.json"))
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--output-dir", type=Path,
                        default=Path("experiments/chunking/results"))
    parser.add_argument("--per-doc", action="store_true",
                        help="Show per-document breakdown")
    parser.add_argument("--llm-eval", action="store_true",
                        help="Run LLM-based answer evaluation on top-5 chunks (uses gpt-4.1-mini)")
    parser.add_argument("--chunkers", nargs="+", type=str, default=None,
                        help="Only run these chunkers (e.g. --chunkers chonkie_512 page_level)")
    parser.add_argument("--force-parse", action="store_true",
                        help="Re-parse PDFs even if cached output exists (pipeline parser)")
    args = parser.parse_args()

    results = run_evaluation(
        parser=args.parser,
        pdf_paths=args.docs,
        qa_path=args.qa,
        retrieval_mode=args.retrieval,
        embedding_model=args.embedding_model,
        include_contextual=args.contextual,
        llm_eval=args.llm_eval,
        chunker_filter=args.chunkers,
        force_parse=args.force_parse,
    )

    print_comparison_table(results)
    if args.per_doc:
        print_per_document_table(results)
    save_results(results, args.output_dir, args.parser, args.retrieval)
    append_to_comparison_md(results, args.parser, args.retrieval)


if __name__ == "__main__":
    main()
