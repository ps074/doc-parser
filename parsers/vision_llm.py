#!/usr/bin/env python3
"""
Vision LLM parser: Render PDF pages as images → feed to multimodal LLM.
Uses Claude's vision to extract text, tables, charts with full fidelity.
"""
import argparse
import base64
import time
from io import BytesIO
from pathlib import Path

import fitz  # PyMuPDF for rendering
import anthropic


SYSTEM_PROMPT = """You are a precision document parser. Your job is to convert a document page image into perfectly structured markdown. You must capture EVERY detail — no summarizing, no skipping, no paraphrasing.

## Rules

1. **Extract ALL text exactly as written.** Do not rephrase, summarize, or omit anything. Every word, number, symbol, date, footnote, disclaimer, and fine print must appear in your output.

2. **Tables:** Reproduce as markdown tables with exact values. Preserve column headers, row labels, units, and alignment. If a table spans complex merged cells, use the closest markdown representation and add a note.

3. **Charts/Graphs:** Describe in detail inside an <image_description> tag:
   - Chart type (bar, line, pie, waterfall, etc.)
   - Axis labels, units, and scale
   - ALL data points, values, and labels visible on the chart
   - Legend entries
   - Trends, comparisons, and any annotations on the chart
   - Colors if they encode meaning (e.g., green = positive, red = negative)

4. **Images/Logos/Icons:** Describe what is shown inside an <image_description> tag. Include brand names, logos, icons, and decorative elements.

5. **Structure:** Use markdown hierarchy that matches the visual hierarchy:
   - `#` for main titles
   - `##` for section headers
   - `###` for subsections
   - `**bold**` for emphasized text
   - Bullet lists and numbered lists as they appear
   - Blockquotes for callouts or highlighted text

6. **Headers/Footers:** Include page headers, footers, page numbers, and document IDs. Mark them as:
   <!-- header: [content] -->
   <!-- footer: [content] -->

7. **Footnotes:** Include all footnotes and superscript references. Place them at the end of the page section with their reference numbers.

8. **Mathematical formulas:** Use LaTeX notation inside $...$ or $$...$$.

9. **Multi-column layouts:** Merge into a single flow, reading left column first then right column (standard reading order). Indicate column breaks if relevant.

10. **DO NOT:**
    - Add any commentary or analysis
    - Say "this page contains" or "the document shows"
    - Skip disclaimers, legal text, or fine print
    - Round or approximate any numbers
    - Add information that is not on the page"""


USER_PROMPT_SINGLE = """Extract ALL content from this document page into structured markdown. Capture every word, number, table, chart, and image exactly as shown. Leave nothing out."""


USER_PROMPT_WITH_CONTEXT = """Extract ALL content from this document page into structured markdown. Capture every word, number, table, chart, and image exactly as shown. Leave nothing out.

Context from previous pages for continuity:
- Document title: {doc_title}
- Current section: {current_section}
- Page {page_num} of {total_pages}"""


def render_page_to_image(pdf_path: Path, page_num: int, dpi: int = 200) -> bytes:
    """Render a PDF page to PNG bytes."""
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    # Higher DPI = better quality for LLM vision
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def parse_page_with_vision(
    client: anthropic.Anthropic,
    image_bytes: bytes,
    page_num: int,
    total_pages: int,
    model: str = "claude-sonnet-4-20250514",
) -> str:
    """Send a page image to Claude and get markdown extraction."""
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    message = client.messages.create(
        model=model,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64_image,
                        },
                    },
                    {
                        "type": "text",
                        "text": USER_PROMPT_SINGLE,
                    },
                ],
            }
        ],
    )

    return message.content[0].text


def parse_document(
    pdf_path: Path,
    model: str = "claude-sonnet-4-20250514",
    dpi: int = 200,
    page_range: tuple = None,
) -> str:
    """Parse entire PDF using vision LLM.

    Args:
        pdf_path: Path to PDF
        model: Claude model to use
        dpi: Resolution for page rendering (150=fast, 200=balanced, 300=max quality)
        page_range: Optional (start, end) 1-based page range
    """
    client = anthropic.Anthropic()

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    if page_range:
        start, end = page_range
        pages_to_process = range(start - 1, min(end, total_pages))
    else:
        pages_to_process = range(total_pages)

    results = []
    for page_idx in pages_to_process:
        page_num = page_idx + 1
        print(f"  Processing page {page_num}/{total_pages}...", end=" ", flush=True)

        page_start = time.time()
        image_bytes = render_page_to_image(pdf_path, page_idx, dpi=dpi)
        render_time = time.time() - page_start

        parse_start = time.time()
        md = parse_page_with_vision(client, image_bytes, page_num, total_pages, model)
        parse_time = time.time() - parse_start

        results.append(f"<!-- Page {page_num} -->\n\n{md}")
        print(f"render={render_time:.1f}s, parse={parse_time:.1f}s")

    return "\n\n---\n\n".join(results)


def main():
    parser = argparse.ArgumentParser(
        description="Parse PDF using Vision LLM (Claude)"
    )
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-20250514",
        help="Claude model (default: claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="Render DPI (150=fast, 200=balanced, 300=max). Default: 200",
    )
    parser.add_argument(
        "--pages",
        help="Page range, e.g., '1-5' or '3' (default: all)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    page_range = None
    if args.pages:
        if "-" in args.pages:
            start, end = args.pages.split("-")
            page_range = (int(start), int(end))
        else:
            p = int(args.pages)
            page_range = (p, p)

    output_dir = Path("output/vision-llm") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        Path(args.output) if args.output else output_dir / f"{input_path.stem}.md"
    )

    print(f"Parsing: {input_path.name} (Vision LLM: {args.model})")
    print(f"DPI: {args.dpi}, Pages: {args.pages or 'all'}")
    print("-" * 60)

    start_time = time.time()
    content = parse_document(
        input_path, model=args.model, dpi=args.dpi, page_range=page_range
    )
    total_time = time.time() - start_time

    output_path.write_text(content)
    print("-" * 60)
    print(f"Saved to: {output_path}")
    print(f"Total time: {round(total_time, 2)}s")
    return 0


if __name__ == "__main__":
    exit(main())
