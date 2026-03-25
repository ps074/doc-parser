#!/usr/bin/env python3
"""
Complete PDF parsing pipeline.

Classify → Group → Render → OCR → Vision LLM (parallel) → Merge

Optimized for LATENCY:
  - All work items fire in parallel (not batched by model tier)
  - Rate-limited calls fall back to next available model
  - pypdfium2 OCR runs on ALL pages as baseline text
  - LLM output replaces entire page content (not a supplement)
"""
import argparse
import asyncio
import base64
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import anthropic
import pymupdf as fitz
import pypdfium2 as pdfium
from openai import AsyncOpenAI

from config import MAX_TOKENS_PAGE_EXTRACTION, DEFAULT_DPI
from page_classifier import (
    Complexity,
    PageClassification,
    PageGroup,
    classify_document,
    MODEL_ROUTING,
)

# --- Vertex AI config ---

VERTEX_PROJECT = "arcana-stage-363819"
VERTEX_REGION = "global"

# Vertex AI uses different model names
VERTEX_MODEL_MAP = {
    "claude-sonnet-4-20250514": "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001": "claude-haiku-4-5",
    "claude-opus-4-20250514": "claude-opus-4-5",
}

def to_vertex_model(model: str) -> str:
    return VERTEX_MODEL_MAP.get(model, model)

# --- Prompts ---

SYSTEM_PROMPT = """\
Extract this document page into structured markdown optimized for RAG retrieval.

RULES:
1. TABLES: Reproduce as proper markdown tables with headers. Every number must be exact.
2. CHARTS: Write a semantic summary paragraph describing what the chart SHOWS and what \
insights it reveals. Include key data points and trends. Users will search for insights \
like "what was the gross exposure trend?" — your description must answer such queries. \
Do NOT list axis labels mechanically.
3. TEXT: Preserve all text, headings, footnotes exactly.
4. NUMBERS: Never round or approximate.
5. Be concise but complete — every data point matters, no commentary.
6. NEVER stop early. NEVER add notes about content being "cut off", "truncated", \
"incomplete", "abrupt", or any similar commentary. Extract EVERY line of text visible \
on the page, all the way to the very last line. Pages in press releases and financial \
documents often end mid-sentence — this is normal (the sentence continues on the next \
page). Simply output the text exactly as it appears, even if incomplete. If text is \
hard to read, use the OCR cross-reference provided."""


def _build_user_prompt(
    page_nums: list[int],
    total_pages: int,
    ocr_texts: list[str],
    classification_reasons: list[str],
) -> str:
    """Build the user prompt with OCR text as cross-reference hint."""
    parts = []

    # Main instruction
    if len(page_nums) == 1:
        parts.append(
            f"Extract ALL content from page {page_nums[0]} of {total_pages} "
            f"into structured markdown. Capture every word, number, table, "
            f"chart, and visual element exactly as shown. Leave nothing out."
        )
    else:
        parts.append(
            f"These are pages {page_nums[0]}-{page_nums[-1]} of {total_pages}. "
            f"They contain a TABLE that spans across these pages. "
            f"Reconstruct the COMPLETE table using headers from the first page "
            f"and continuation data from subsequent pages. Also extract all "
            f"other content (text, charts, footnotes) from every page. "
            f"Leave nothing out."
        )

    # OCR text as cross-reference — send full text so the model can
    # cross-reference numbers and values even at the bottom of the page
    for i, (pn, ocr) in enumerate(zip(page_nums, ocr_texts)):
        if ocr.strip():
            parts.append(
                f"\n<ocr_text page=\"{pn}\">\n"
                f"Complete text from PDF text layer for cross-referencing numbers "
                f"and values. Image is the source of truth for layout. "
                f"Make sure to extract ALL text including content at the bottom "
                f"of the page.\n\n"
                f"{ocr}\n"
                f"</ocr_text>"
            )

    # Classification context
    if classification_reasons:
        parts.append(
            f"\n<classification_hints>\n"
            f"Page analysis detected: {'; '.join(classification_reasons)}\n"
            f"Pay special attention to these elements.\n"
            f"</classification_hints>"
        )

    return "\n".join(parts)


# --- Data structures ---

@dataclass
class WorkItem:
    """A unit of work: one or more pages to process in a single LLM call."""
    pages: list[int]            # 1-based page numbers
    images: list[bytes]         # rendered PNG bytes per page
    ocr_texts: list[str]        # pypdfium2 text per page
    model: str                  # target model
    complexity: Complexity
    group_id: int | None        # if part of a cross-page group
    reasons: list[str]          # classification reasons


@dataclass
class PageResult:
    """Result for a page (or group of pages)."""
    pages: list[int]
    markdown: str
    model_used: str
    complexity: Complexity
    processing_time: float
    fallback_used: bool = False


# --- Model fallback chain ---

FALLBACK_CHAIN = {
    # Direct API model names
    "claude-sonnet-4-20250514": ["claude-haiku-4-5-20251001"],
    "claude-haiku-4-5-20251001": [],
    # Vertex AI model names
    "claude-sonnet-4-6": ["claude-haiku-4-5"],
    "claude-haiku-4-5": [],
    # OpenAI model names
    "gpt-4.1-mini": ["claude-haiku-4-5-20251001"],
}

def is_openai_model(model: str) -> bool:
    return model.startswith("gpt-")


def _strip_code_fences(text: str) -> str:
    """Strip ```markdown ... ``` code fences that LLMs wrap around output."""
    import re
    stripped = text.strip()
    # Match opening ```markdown (or ```md, or just ```) and closing ```
    stripped = re.sub(r"^```(?:markdown|md)?\s*\n", "", stripped)
    stripped = re.sub(r"\n```\s*$", "", stripped)
    return stripped.strip()


# --- Core processing ---

def render_pages(pdf_path: Path, page_nums: list[int], dpi: int = 200) -> list[bytes]:
    """Render multiple pages to PNG bytes."""
    doc = fitz.open(pdf_path)
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    images = []
    for pn in page_nums:
        page = doc[pn - 1]  # 0-based
        pix = page.get_pixmap(matrix=mat)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


def extract_ocr_texts(pdf_path: Path, page_nums: list[int]) -> list[str]:
    """Extract text from pages using pypdfium2."""
    doc = pdfium.PdfDocument(pdf_path)
    texts = []
    for pn in page_nums:
        page = doc[pn - 1]
        text = page.get_textpage().get_text_range()
        texts.append(text)
        page.close()
    doc.close()
    return texts


async def _call_anthropic(client, model, content, system):
    """Make an Anthropic API call using streaming (required for large max_tokens)."""
    result_text = ""
    stop_reason = None
    async with client.messages.stream(
        model=model, max_tokens=MAX_TOKENS_PAGE_EXTRACTION, system=system,
        messages=[{"role": "user", "content": content}],
    ) as stream:
        async for text in stream.text_stream:
            result_text += text
        response = await stream.get_final_message()
        stop_reason = response.stop_reason
    if stop_reason == "max_tokens":
        print(f"  WARNING: Anthropic response truncated (hit {MAX_TOKENS_PAGE_EXTRACTION} token limit)")
    return result_text


async def _call_openai(openai_client, model, images, user_prompt, system):
    """Make an OpenAI API call."""
    oai_content = []
    for img_bytes in images:
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        oai_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })
    oai_content.append({"type": "text", "text": user_prompt})

    response = await openai_client.chat.completions.create(
        model=model, max_tokens=MAX_TOKENS_PAGE_EXTRACTION,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": oai_content},
        ],
    )
    if response.choices[0].finish_reason == "length":
        print(f"  WARNING: OpenAI response truncated (hit {MAX_TOKENS_PAGE_EXTRACTION} token limit)")
    return response.choices[0].message.content


async def process_work_item(
    clients: dict,
    item: WorkItem,
    total_pages: int,
    semaphore: asyncio.Semaphore,
    pipeline_start: float,
) -> PageResult:
    """Process a single work item with fallback on rate limits."""

    async with semaphore:
        launched_at = time.time() - pipeline_start
        start = time.time()

        status = f"pages {item.pages}" if len(item.pages) > 1 else f"page {item.pages[0]}"
        model_short = item.model.split("-")[1] if "-" in item.model else item.model
        print(f"  Started {status} → {model_short} at t+{launched_at:.1f}s")

        user_prompt = _build_user_prompt(
            item.pages, total_pages, item.ocr_texts, item.reasons
        )

        # Build Anthropic content format (used for Claude models)
        anthropic_content = []
        for img_bytes in item.images:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            anthropic_content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": b64},
            })
        anthropic_content.append({"type": "text", "text": user_prompt})

        # Try target model, then fallbacks
        models_to_try = [item.model] + FALLBACK_CHAIN.get(item.model, [])
        fallback_used = False
        model_used = item.model
        result_markdown = ""

        for i, model in enumerate(models_to_try):
            try:
                if is_openai_model(model):
                    result_markdown = await _call_openai(
                        clients["openai"], model, item.images, user_prompt, SYSTEM_PROMPT
                    )
                else:
                    result_markdown = await _call_anthropic(
                        clients["anthropic"], model, anthropic_content, SYSTEM_PROMPT
                    )
                model_used = model
                fallback_used = i > 0
                break
            except (anthropic.RateLimitError, Exception) as e:
                if "rate" in str(e).lower() and i < len(models_to_try) - 1:
                    next_model = models_to_try[i + 1]
                    print(f"  Rate limited on {model} for {status}, falling back to {next_model}")
                    continue
                elif i < len(models_to_try) - 1:
                    next_model = models_to_try[i + 1]
                    print(f"  Error on {model} for {status}: {str(e)[:60]}, falling back to {next_model}")
                    continue
                else:
                    raise

        # Strip code fences that LLMs often wrap around markdown output
        result_markdown = _strip_code_fences(result_markdown)

        # Add page markers for consistent downstream parsing
        if len(item.pages) == 1:
            result_markdown = f"<!-- page: {item.pages[0]} -->\n\n{result_markdown}"
        else:
            # Multi-page group: single marker with the first page number
            page_label = ", ".join(str(p) for p in item.pages)
            result_markdown = f"<!-- page: {item.pages[0]} -->\n<!-- pages: {page_label} -->\n\n{result_markdown}"

        elapsed = time.time() - start
        model_short = model_used.split("-")[1] if "-" in model_used else model_used
        fb = f" (fallback: {model_used})" if fallback_used else ""
        print(f"  Done {status} → {model_short} in {elapsed:.1f}s{fb}")

        return PageResult(
            pages=item.pages,
            markdown=result_markdown,
            model_used=model_used,
            complexity=item.complexity,
            processing_time=elapsed,
            fallback_used=fallback_used,
        )


def process_simple_pages(
    pdf_path: Path,
    classifications: list[PageClassification],
) -> list[PageResult]:
    """Process SIMPLE/SKIP pages with pypdfium2 only (no LLM)."""
    simple_pages = [
        c for c in classifications
        if c.complexity in (Complexity.SIMPLE, Complexity.SKIP)
    ]
    if not simple_pages:
        return []

    page_nums = [c.page_num for c in simple_pages]
    texts = extract_ocr_texts(pdf_path, page_nums)

    results = []
    for c, text in zip(simple_pages, texts):
        md = f"<!-- page: {c.page_num} -->\n\n{text}"
        results.append(PageResult(
            pages=[c.page_num],
            markdown=md,
            model_used="pypdfium2",
            complexity=c.complexity,
            processing_time=0.0,
        ))
    return results


def build_work_items(
    pdf_path: Path,
    classifications: list[PageClassification],
    groups: list[PageGroup],
    dpi: int = DEFAULT_DPI,
) -> list[WorkItem]:
    """Build work items from classifications, respecting page groups."""
    # Track which pages are in a group
    grouped_pages = set()
    work_items = []

    # Build group work items first
    for group in groups:
        page_nums = group.pages
        grouped_pages.update(page_nums)

        images = render_pages(pdf_path, page_nums, dpi)
        ocr_texts = extract_ocr_texts(pdf_path, page_nums)

        # Collect all reasons from pages in the group
        reasons = []
        for c in classifications:
            if c.page_num in page_nums:
                reasons.extend(c.reasons)

        work_items.append(WorkItem(
            pages=page_nums,
            images=images,
            ocr_texts=ocr_texts,
            model=group.model,
            complexity=group.complexity,
            group_id=group.group_id,
            reasons=list(set(reasons)),
        ))

    # Build individual work items for non-grouped, non-simple pages
    for c in classifications:
        if c.page_num in grouped_pages:
            continue
        if c.complexity in (Complexity.SIMPLE, Complexity.SKIP):
            continue

        images = render_pages(pdf_path, [c.page_num], dpi)
        ocr_texts = extract_ocr_texts(pdf_path, [c.page_num])

        work_items.append(WorkItem(
            pages=[c.page_num],
            images=images,
            ocr_texts=ocr_texts,
            model=c.model,
            complexity=c.complexity,
            group_id=None,
            reasons=c.reasons,
        ))

    return work_items


# --- Main pipeline ---

async def run_pipeline(
    pdf_path: Path,
    dpi: int = DEFAULT_DPI,
    max_concurrent: int = 50,
    output_dir: Path | None = None,
    use_vertex: bool = False,
    no_groups: bool = False,
) -> list[PageResult]:
    """
    Run the complete parsing pipeline.

    1. Classify all pages (<2s)
    2. Group cross-page tables
    3. Process SIMPLE pages with pypdfium2 (instant)
    4. Render vision pages to images
    5. Fire ALL vision work items in parallel
    6. Merge results in page order
    """
    total_start = time.time()

    # --- Stage 1: Classify ---
    print(f"\n[Stage 1] Classifying pages...")
    stage_start = time.time()
    classifications, groups = classify_document(pdf_path)
    if no_groups:
        groups = []
        print(f"  Cross-page grouping DISABLED (--no-groups)")
    total_pages = len(classifications)
    print(f"  {total_pages} pages classified in {time.time() - stage_start:.2f}s")

    # Print summary
    by_tier = {}
    for c in classifications:
        by_tier.setdefault(c.complexity.value, []).append(c.page_num)
    for tier, pages in by_tier.items():
        print(f"  {tier}: {len(pages)} pages")
    if groups:
        for g in groups:
            print(f"  Group: pages {g.pages} (cross-page table)")

    # --- Stage 2: Process simple pages ---
    print(f"\n[Stage 2] Processing simple pages (pypdfium2)...")
    stage_start = time.time()
    simple_results = process_simple_pages(pdf_path, classifications)
    print(f"  {len(simple_results)} pages in {time.time() - stage_start:.2f}s")

    # --- Stage 3: Build & render vision work items ---
    print(f"\n[Stage 3] Rendering vision pages to images...")
    stage_start = time.time()
    work_items = build_work_items(pdf_path, classifications, groups, dpi)
    print(f"  {len(work_items)} work items ({sum(len(w.pages) for w in work_items)} pages) "
          f"rendered in {time.time() - stage_start:.2f}s")

    # --- Stage 4: Fire all vision calls in parallel ---
    vision_results = []
    if work_items:
        # Use max_concurrent or total work items, whichever is smaller
        effective_concurrent = min(max_concurrent, len(work_items))
        print(f"\n[Stage 4] Processing {len(work_items)} vision work items in parallel "
              f"(all {effective_concurrent} concurrent)...")

        # Create clients for all providers
        clients = {}
        if use_vertex:
            clients["anthropic"] = anthropic.AsyncAnthropicVertex(
                project_id=VERTEX_PROJECT,
                region=VERTEX_REGION,
            )
            # Remap Claude model names for Vertex
            for item in work_items:
                if not is_openai_model(item.model):
                    item.model = to_vertex_model(item.model)
            print(f"  Claude via Vertex AI ({VERTEX_REGION})")
        else:
            clients["anthropic"] = anthropic.AsyncAnthropic()
            print(f"  Claude via direct Anthropic API")

        # Check if any work items need OpenAI
        has_openai = any(is_openai_model(item.model) for item in work_items)
        if has_openai:
            clients["openai"] = AsyncOpenAI()
            print(f"  GPT via OpenAI API")

        semaphore = asyncio.Semaphore(effective_concurrent)
        stage4_start = time.time()

        tasks = [
            process_work_item(clients, item, total_pages, semaphore, stage4_start)
            for item in work_items
        ]
        vision_results = await asyncio.gather(*tasks)

    # --- Stage 5: Merge results in page order ---
    all_results = list(simple_results) + list(vision_results)
    # Sort by first page number in each result
    all_results.sort(key=lambda r: r.pages[0])

    total_time = time.time() - total_start

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print(f"Pipeline complete: {total_pages} pages in {total_time:.1f}s")
    print(f"  Simple (pypdfium2): {len(simple_results)} pages")
    print(f"  Vision (LLM):      {len(vision_results)} work items")

    fallbacks = sum(1 for r in vision_results if r.fallback_used)
    if fallbacks:
        print(f"  Fallbacks used:    {fallbacks}")

    models_used = {}
    for r in all_results:
        models_used[r.model_used] = models_used.get(r.model_used, 0) + len(r.pages)
    for model, count in sorted(models_used.items()):
        print(f"  {model}: {count} pages")

    # --- Save output ---
    if output_dir is None:
        output_dir = Path("output/pipeline") / pdf_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save combined markdown
    combined_md = "\n\n---\n\n".join(r.markdown for r in all_results)
    md_path = output_dir / f"{pdf_path.stem}.md"
    md_path.write_text(combined_md)
    print(f"\nMarkdown saved to: {md_path}")

    # Save metadata
    meta = {
        "document": pdf_path.name,
        "total_pages": total_pages,
        "total_time_seconds": round(total_time, 2),
        "pages": [
            {
                "pages": r.pages,
                "model": r.model_used,
                "complexity": r.complexity.value,
                "time": round(r.processing_time, 2),
                "fallback": r.fallback_used,
            }
            for r in all_results
        ],
        "groups": [
            {"pages": g.pages, "reason": g.reason}
            for g in groups
        ],
    }
    meta_path = output_dir / "metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"Metadata saved to: {meta_path}")

    # Mirror output to project root output dir (eval_chunking.py looks there)
    project_root = Path(__file__).resolve().parent.parent
    root_output_dir = project_root / "output" / "pipeline" / pdf_path.stem
    if root_output_dir.resolve() != output_dir.resolve():
        import shutil
        root_output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(md_path, root_output_dir / md_path.name)
        shutil.copy2(meta_path, root_output_dir / meta_path.name)
        print(f"Mirrored to: {root_output_dir}")

    return all_results


def main():
    parser = argparse.ArgumentParser(
        description="Complete PDF parsing pipeline with smart model routing"
    )
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("-o", "--output-dir", help="Output directory")
    parser.add_argument(
        "--dpi", type=int, default=DEFAULT_DPI,
        help=f"Render DPI for vision pages (default: {DEFAULT_DPI})",
    )
    parser.add_argument(
        "--max-concurrent", type=int, default=50,
        help="Max concurrent LLM calls (default: 50)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Classify and show plan without making LLM calls",
    )
    parser.add_argument(
        "--vertex", action="store_true",
        help="Use Vertex AI (global endpoint) instead of direct Anthropic API. Requires GOOGLE_APPLICATION_CREDENTIALS.",
    )
    parser.add_argument(
        "--no-groups", action="store_true",
        help="Disable cross-page grouping. Each page processed individually for speed.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    if args.dry_run:
        classifications, groups = classify_document(input_path)
        total = len(classifications)

        print(f"\nDry run: {input_path.name} ({total} pages)")
        print("=" * 60)

        simple = [c for c in classifications if c.complexity in (Complexity.SIMPLE, Complexity.SKIP)]
        vision = [c for c in classifications if c.complexity not in (Complexity.SIMPLE, Complexity.SKIP)]

        # Count work items
        grouped_pages = set()
        for g in groups:
            grouped_pages.update(g.pages)
        num_work_items = len(groups) + len([c for c in vision if c.page_num not in grouped_pages])

        print(f"\n  Simple pages (pypdfium2, free):  {len(simple)}")
        print(f"  Vision pages (LLM):              {len(vision)}")
        print(f"  Work items (API calls):           {num_work_items}")

        if groups:
            print(f"\n  Cross-page groups:")
            for g in groups:
                print(f"    Pages {g.pages} → 1 API call")

        # Cost estimate
        haiku_n = sum(1 for c in vision if c.model == "claude-haiku-4-5-20251001" and c.page_num not in grouped_pages)
        sonnet_n = sum(1 for c in vision if c.model == "claude-sonnet-4-20250514" and c.page_num not in grouped_pages)
        opus_n = sum(1 for c in vision if c.model == "claude-opus-4-20250514" and c.page_num not in grouped_pages)
        # Add group costs (use group's model)
        for g in groups:
            if g.model == "claude-haiku-4-5-20251001":
                haiku_n += len(g.pages)
            elif g.model == "claude-sonnet-4-20250514":
                sonnet_n += len(g.pages)
            else:
                opus_n += len(g.pages)

        cost = haiku_n * 0.003 + sonnet_n * 0.04 + opus_n * 0.20
        print(f"\n  Estimated cost: ~${cost:.2f}")
        print(f"    Haiku:  {haiku_n} pages × $0.003 = ${haiku_n * 0.003:.2f}")
        print(f"    Sonnet: {sonnet_n} pages × $0.04  = ${sonnet_n * 0.04:.2f}")
        print(f"    Opus:   {opus_n} pages × $0.20  = ${opus_n * 0.20:.2f}")

        print(f"\n  Run without --dry-run to execute.")
        return 0

    output_dir = Path(args.output_dir) if args.output_dir else None
    asyncio.run(run_pipeline(
        input_path,
        dpi=args.dpi,
        max_concurrent=args.max_concurrent,
        output_dir=output_dir,
        use_vertex=args.vertex,
        no_groups=args.no_groups,
    ))
    return 0


if __name__ == "__main__":
    exit(main())
