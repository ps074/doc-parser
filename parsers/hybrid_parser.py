#!/usr/bin/env python3
"""
Hybrid PDF parser: PyMuPDF for text/tables + LLM only for charts/images.

PyMuPDF extracts 100% of text and table data instantly.
LLM is called ONLY for pages with charts/images that need visual description.
"""
import asyncio
import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz
from openai import AsyncOpenAI

from config import MAX_TOKENS_CHART_DESCRIPTION, DEFAULT_DPI, DEFAULT_FAST_MODEL
from page_classifier import classify_document, Complexity


CHART_PROMPT = """\
This page contains charts/graphs. The text and table data have already been extracted.
Your ONLY job is to describe the visual elements (charts, graphs, diagrams, images).

For each chart, output:
```chart
Type: [bar/line/pie/area/waterfall/scatter]
Title: [exact title]
X-axis: [label]
Y-axis: [label]
Data: [key data points and values visible on the chart]
Legend: [entries]
Annotations: [any callouts or labels]
```

For images/logos:
```image
[description]
```

Do NOT extract any text or tables — those are already handled. ONLY describe visual elements."""


@dataclass
class HybridPageResult:
    page_num: int
    text: str              # PyMuPDF raw text
    tables_md: str         # PyMuPDF tables as markdown
    chart_descriptions: str  # LLM chart descriptions (empty if no charts)
    combined_md: str       # Final combined markdown
    had_charts: bool
    llm_time: float        # 0 if no LLM call


def extract_page_content(doc: fitz.Document, page_num: int) -> dict:
    """Extract text and tables from a page using PyMuPDF."""
    page = doc[page_num - 1]

    # Extract raw text
    text = page.get_text("text")

    # Extract tables
    tabs = page.find_tables()
    tables_md = ""
    for i, tab in enumerate(tabs.tables):
        df = tab.to_pandas()
        tables_md += f"\n{df.to_markdown(index=False)}\n"

    # Check for charts/images (from classifier signals)
    drawings = page.get_drawings()
    images = page.get_images(full=True)

    significant_images = 0
    for img in images:
        try:
            img_info = doc.extract_image(img[0])
            if img_info and img_info.get("width", 0) > 100 and img_info.get("height", 0) > 100:
                significant_images += 1
        except Exception:
            pass

    # Chart detection: colored rectangles or curves
    rect_count = 0
    curve_count = 0
    colors = set()
    for d in drawings:
        color = d.get("color")
        fill = d.get("fill")
        if color:
            colors.add(tuple(color) if isinstance(color, (list, tuple)) else color)
        if fill:
            colors.add(tuple(fill) if isinstance(fill, (list, tuple)) else fill)
        for item in d.get("items", []):
            if item[0] == "re":
                rect_count += 1
            elif item[0] == "c":
                curve_count += 1

    has_charts = (
        (rect_count > 10 and len(colors) > 3) or
        (curve_count > 10 and len(colors) > 2) or
        (significant_images > 0 and len(drawings) > 20)
    )

    return {
        "text": text,
        "tables_md": tables_md,
        "has_charts": has_charts,
        "table_count": len(tabs.tables),
    }


def format_page_md(page_num: int, text: str, tables_md: str, chart_desc: str) -> str:
    """Combine PyMuPDF text + tables + LLM chart descriptions into final markdown."""
    parts = [f"<!-- page: {page_num} -->"]

    if text.strip():
        parts.append(text.strip())

    if tables_md.strip():
        parts.append("\n" + tables_md.strip())

    if chart_desc.strip():
        parts.append("\n" + chart_desc.strip())

    return "\n\n".join(parts)


async def describe_charts(
    client: AsyncOpenAI,
    image_bytes: bytes,
    page_num: int,
) -> str:
    """Send page image to LLM to describe ONLY charts/images."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    response = await client.chat.completions.create(
        model=DEFAULT_FAST_MODEL,
        max_tokens=MAX_TOKENS_CHART_DESCRIPTION,
        messages=[
            {"role": "system", "content": "You describe charts and visual elements in document pages. Be precise with data values."},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": CHART_PROMPT},
            ]},
        ],
    )
    return response.choices[0].message.content


async def parse_document(
    pdf_path: Path,
    dpi: int = 150,
    max_concurrent: int = 20,
) -> list[HybridPageResult]:
    """Parse PDF using hybrid approach: PyMuPDF + LLM for charts only."""
    total_start = time.time()

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    mat = fitz.Matrix(dpi / 72, dpi / 72)

    print(f"\n[Stage 1] PyMuPDF extraction ({total_pages} pages)...")
    stage_start = time.time()

    # Extract all text + tables (instant)
    page_data = {}
    chart_pages = []
    for i in range(total_pages):
        pn = i + 1
        data = extract_page_content(doc, pn)
        page_data[pn] = data
        if data["has_charts"]:
            chart_pages.append(pn)

    print(f"  Done in {time.time() - stage_start:.2f}s")
    print(f"  Pages with charts: {len(chart_pages)} → need LLM")
    print(f"  Pages without charts: {total_pages - len(chart_pages)} → PyMuPDF only (no LLM)")

    # Render chart pages to images
    chart_images = {}
    if chart_pages:
        print(f"\n[Stage 2] Rendering {len(chart_pages)} chart pages...")
        for pn in chart_pages:
            page = doc[pn - 1]
            pix = page.get_pixmap(matrix=mat)
            chart_images[pn] = pix.tobytes("png")

    doc.close()

    # Send chart pages to LLM in parallel
    chart_descriptions = {}
    if chart_pages:
        print(f"\n[Stage 3] Describing charts via LLM ({len(chart_pages)} pages in parallel)...")
        stage_start = time.time()

        client = AsyncOpenAI()
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_chart(pn):
            async with semaphore:
                start = time.time()
                desc = await describe_charts(client, chart_images[pn], pn)
                elapsed = time.time() - start
                print(f"  page {pn} chart described in {elapsed:.1f}s")
                return pn, desc, elapsed

        tasks = [process_chart(pn) for pn in chart_pages]
        results = await asyncio.gather(*tasks)

        for pn, desc, elapsed in results:
            chart_descriptions[pn] = (desc, elapsed)

        print(f"  All charts done in {time.time() - stage_start:.1f}s")

    # Combine results
    print(f"\n[Stage 4] Combining results...")
    all_results = []
    for pn in range(1, total_pages + 1):
        data = page_data[pn]
        chart_desc = ""
        llm_time = 0.0
        had_charts = pn in chart_descriptions

        if had_charts:
            chart_desc, llm_time = chart_descriptions[pn]

        combined = format_page_md(pn, data["text"], data["tables_md"], chart_desc)

        all_results.append(HybridPageResult(
            page_num=pn,
            text=data["text"],
            tables_md=data["tables_md"],
            chart_descriptions=chart_desc,
            combined_md=combined,
            had_charts=had_charts,
            llm_time=llm_time,
        ))

    total_time = time.time() - total_start

    # Summary
    llm_pages = sum(1 for r in all_results if r.had_charts)
    free_pages = total_pages - llm_pages
    max_llm = max((r.llm_time for r in all_results), default=0)
    print(f"\n{'=' * 60}")
    print(f"Hybrid parse complete: {total_pages} pages in {total_time:.1f}s")
    print(f"  PyMuPDF only (free):  {free_pages} pages")
    print(f"  LLM for charts:       {llm_pages} pages")
    print(f"  Slowest LLM call:     {max_llm:.1f}s")

    return all_results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Hybrid PDF parser: PyMuPDF + LLM for charts")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("-o", "--output-dir", help="Output directory")
    parser.add_argument("--dpi", type=int, default=150, help="DPI for chart page rendering (default: 150)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    output_dir = Path(args.output_dir) if args.output_dir else Path("output/hybrid") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    results = asyncio.run(parse_document(input_path, dpi=args.dpi))

    # Save combined markdown
    combined = "\n\n---\n\n".join(r.combined_md for r in results)
    md_path = output_dir / f"{input_path.stem}.md"
    md_path.write_text(combined)
    print(f"\nSaved to: {md_path}")

    # Save metadata
    meta = {
        "document": input_path.name,
        "total_pages": len(results),
        "chart_pages": [r.page_num for r in results if r.had_charts],
        "free_pages": [r.page_num for r in results if not r.had_charts],
        "per_page": [
            {"page": r.page_num, "had_charts": r.had_charts, "llm_time": round(r.llm_time, 2)}
            for r in results
        ],
    }
    meta_path = output_dir / "metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2))

    return 0


if __name__ == "__main__":
    exit(main())
