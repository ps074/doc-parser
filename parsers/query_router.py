#!/usr/bin/env python3
"""
Smart query router for PDF RAG system.

Decides whether to answer from:
1. Pre-computed RAG chunks (instant)
2. Vision fallback on specific pages (8-15s)
3. Full document vision for broad queries (15-30s)

Architecture:
  Upload → pypdfium2 instant text (0.4s) → basic chunks available
        → Background: vision pipeline (79s) → enriched chunks replace basic
  Query → Router decides best approach based on query type + enrichment status
"""
import asyncio
import base64
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pymupdf as fitz
import pypdfium2 as pdfium


class EnrichmentStatus(str, Enum):
    PENDING = "pending"      # Only basic text available
    IN_PROGRESS = "in_progress"  # Background job running
    COMPLETE = "complete"    # Full enriched chunks available


class QueryStrategy(str, Enum):
    RAG_BASIC = "rag_basic"          # Answer from basic text chunks
    RAG_ENRICHED = "rag_enriched"    # Answer from enriched chunks (best)
    VISION_PAGES = "vision_pages"    # Send specific page images to LLM
    VISION_FULL = "vision_full"      # Send all page images for broad queries


@dataclass
class QueryResult:
    answer: str
    strategy_used: QueryStrategy
    pages_referenced: list[int]
    time_seconds: float
    confidence: str  # "high", "medium", "low"


@dataclass
class DocumentState:
    """Tracks the state of a document through the pipeline."""
    pdf_path: Path
    total_pages: int
    enrichment_status: EnrichmentStatus

    # Basic text (available instantly)
    page_texts: dict[int, str]  # page_num → raw text

    # Page images (rendered on demand, cached)
    page_images: dict[int, bytes]  # page_num → PNG bytes

    # Enriched chunks (available after background job)
    enriched_chunks: list[dict] | None  # [{text, page, metadata}, ...]

    # Page classification (available instantly)
    page_has_charts: dict[int, bool]


def ingest_document(pdf_path: Path) -> DocumentState:
    """
    Phase 1: Instant ingestion. Extract text from all pages using PyMuPDF.
    Returns immediately (<1s) with basic text available for RAG.
    """
    start = time.time()
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    page_texts = {}
    page_has_charts = {}

    for i in range(total_pages):
        page = doc[i]
        pn = i + 1
        page_texts[pn] = page.get_text("text")

        # Quick chart detection from drawings
        drawings = page.get_drawings()
        rects = sum(1 for d in drawings for item in d.get("items", []) if item[0] == "re")
        colors = set()
        for d in drawings:
            c = d.get("color")
            if c:
                colors.add(tuple(c) if isinstance(c, (list, tuple)) else c)
        page_has_charts[pn] = rects > 10 and len(colors) > 3

    doc.close()

    elapsed = time.time() - start
    print(f"Ingested {total_pages} pages in {elapsed:.2f}s (basic text ready)")

    return DocumentState(
        pdf_path=pdf_path,
        total_pages=total_pages,
        enrichment_status=EnrichmentStatus.PENDING,
        page_texts=page_texts,
        page_images={},
        enriched_chunks=None,
        page_has_charts=page_has_charts,
    )


def find_relevant_pages(state: DocumentState, query: str) -> list[int]:
    """Find which pages are most relevant to a query using basic text search."""
    query_lower = query.lower()
    query_words = set(query_lower.split())

    scored_pages = []
    for pn, text in state.page_texts.items():
        text_lower = text.lower()
        # Score by keyword matches
        score = sum(1 for word in query_words if word in text_lower)
        # Boost for exact phrase match
        if query_lower in text_lower:
            score += 5
        if score > 0:
            scored_pages.append((pn, score))

    scored_pages.sort(key=lambda x: x[1], reverse=True)
    return [pn for pn, _ in scored_pages[:3]]  # Top 3 pages


def classify_query(query: str) -> str:
    """Classify query type to determine routing strategy."""
    query_lower = query.lower()

    # Broad queries that need full document context
    broad_keywords = ["summarize", "summary", "overview", "main points",
                      "key takeaways", "what is this document about",
                      "tell me about", "describe the document"]
    if any(kw in query_lower for kw in broad_keywords):
        return "broad"

    # Chart/visual queries
    chart_keywords = ["chart", "graph", "trend", "exposure chart",
                      "shows", "visual", "plot", "diagram"]
    if any(kw in query_lower for kw in chart_keywords):
        return "chart"

    # Specific data lookups
    return "specific"


def get_page_image(state: DocumentState, page_num: int, dpi: int = 150) -> bytes:
    """Get or render a page image (cached)."""
    if page_num not in state.page_images:
        doc = fitz.open(state.pdf_path)
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        page = doc[page_num - 1]
        pix = page.get_pixmap(matrix=mat)
        state.page_images[page_num] = pix.tobytes("png")
        doc.close()
    return state.page_images[page_num]


async def answer_from_rag(state: DocumentState, query: str, pages: list[int]) -> str:
    """Answer using pre-computed enriched chunks."""
    if not state.enriched_chunks:
        return ""

    # Find relevant chunks
    query_lower = query.lower()
    relevant = []
    for chunk in state.enriched_chunks:
        if chunk.get("page") in pages or not pages:
            score = sum(1 for word in query_lower.split() if word in chunk["text"].lower())
            if score > 0:
                relevant.append((chunk, score))

    relevant.sort(key=lambda x: x[1], reverse=True)
    context = "\n\n".join(chunk["text"] for chunk, _ in relevant[:5])
    return context


async def answer_from_vision(
    state: DocumentState,
    query: str,
    pages: list[int],
    openai_client=None,
) -> str:
    """Send page images to LLM with the user's question."""
    from openai import AsyncOpenAI

    if openai_client is None:
        openai_client = AsyncOpenAI()

    content = []
    for pn in pages:
        img = get_page_image(state, pn)
        b64 = base64.b64encode(img).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })

    content.append({"type": "text", "text": query})

    response = await openai_client.chat.completions.create(
        model="gpt-4.1-mini",
        max_tokens=2048,
        messages=[
            {"role": "system", "content": "Answer the user's question about this document page(s). Be precise with numbers and data."},
            {"role": "user", "content": content},
        ],
    )
    return response.choices[0].message.content


async def route_query(
    state: DocumentState,
    query: str,
    openai_client=None,
) -> QueryResult:
    """
    Smart query router. Decides the best strategy based on:
    - Query type (specific vs broad vs chart)
    - Enrichment status (basic vs enriched)
    - Page relevance
    """
    start = time.time()
    query_type = classify_query(query)
    relevant_pages = find_relevant_pages(state, query)

    # Strategy selection
    if query_type == "broad":
        if state.enrichment_status == EnrichmentStatus.COMPLETE:
            # Use enriched chunks for summary
            context = await answer_from_rag(state, query, [])
            if context:
                answer = f"From enriched RAG:\n\n{context}"
                strategy = QueryStrategy.RAG_ENRICHED
                confidence = "high"
            else:
                # Fallback: send all page images
                all_pages = list(range(1, min(state.total_pages + 1, 21)))
                answer = await answer_from_vision(state, query, all_pages, openai_client)
                strategy = QueryStrategy.VISION_FULL
                confidence = "high"
        else:
            # No enrichment yet — send page images directly
            # For summary, send first few + last few pages
            pages = list(range(1, min(6, state.total_pages + 1)))
            if state.total_pages > 5:
                pages += list(range(max(6, state.total_pages - 2), state.total_pages + 1))
            answer = await answer_from_vision(state, query, pages, openai_client)
            strategy = QueryStrategy.VISION_FULL
            confidence = "medium"

    elif query_type == "chart":
        # Chart queries always need vision
        chart_pages = [pn for pn in relevant_pages if state.page_has_charts.get(pn, False)]
        if not chart_pages:
            # If no relevant chart pages found, try all chart pages
            chart_pages = [pn for pn, has in state.page_has_charts.items() if has][:3]
        if not chart_pages:
            chart_pages = relevant_pages[:2] or [1]

        if state.enrichment_status == EnrichmentStatus.COMPLETE:
            # Try enriched RAG first (has chart descriptions)
            context = await answer_from_rag(state, query, chart_pages)
            if context and len(context) > 100:
                answer = context
                strategy = QueryStrategy.RAG_ENRICHED
                confidence = "high"
            else:
                answer = await answer_from_vision(state, query, chart_pages, openai_client)
                strategy = QueryStrategy.VISION_PAGES
                confidence = "high"
        else:
            answer = await answer_from_vision(state, query, chart_pages, openai_client)
            strategy = QueryStrategy.VISION_PAGES
            confidence = "high"

    else:  # specific query
        if state.enrichment_status == EnrichmentStatus.COMPLETE:
            context = await answer_from_rag(state, query, relevant_pages)
            if context:
                answer = context
                strategy = QueryStrategy.RAG_ENRICHED
                confidence = "high"
            else:
                answer = await answer_from_vision(state, query, relevant_pages[:2] or [1], openai_client)
                strategy = QueryStrategy.VISION_PAGES
                confidence = "medium"
        else:
            # Basic text search
            if relevant_pages:
                # Check if basic text can answer it
                basic_context = "\n".join(
                    state.page_texts[pn][:1000] for pn in relevant_pages
                )
                if any(word in basic_context.lower() for word in query.lower().split()[:3]):
                    # Found keywords in basic text — try vision for structured answer
                    answer = await answer_from_vision(state, query, relevant_pages[:2], openai_client)
                    strategy = QueryStrategy.VISION_PAGES
                    confidence = "high"
                else:
                    answer = await answer_from_vision(state, query, [1], openai_client)
                    strategy = QueryStrategy.VISION_PAGES
                    confidence = "low"
            else:
                answer = await answer_from_vision(state, query, [1], openai_client)
                strategy = QueryStrategy.VISION_PAGES
                confidence = "low"

    elapsed = time.time() - start
    pages_used = relevant_pages if strategy != QueryStrategy.VISION_FULL else list(range(1, state.total_pages + 1))

    return QueryResult(
        answer=answer,
        strategy_used=strategy,
        pages_referenced=pages_used,
        time_seconds=elapsed,
        confidence=confidence,
    )


async def demo():
    """Demo the query router on report_new.pdf."""
    # Phase 1: Instant ingestion
    state = ingest_document(Path("report_new.pdf"))

    queries = [
        "What was the Sharpe ratio period to date?",
        "What does the gross exposure chart show?",
        "Summarize this report",
        "What are the top 5 contributors?",
        "What is the beta adjusted net for machinery?",
    ]

    print(f"\n{'='*60}")
    print(f"Status: {state.enrichment_status.value}")
    print(f"{'='*60}\n")

    from openai import AsyncOpenAI
    client = AsyncOpenAI()

    for q in queries:
        print(f"Q: {q}")
        result = await route_query(state, q, client)
        print(f"  Strategy: {result.strategy_used.value}")
        print(f"  Pages: {result.pages_referenced[:5]}")
        print(f"  Time: {result.time_seconds:.1f}s")
        print(f"  Confidence: {result.confidence}")
        print(f"  Answer: {result.answer[:200]}...")
        print()


if __name__ == "__main__":
    asyncio.run(demo())
