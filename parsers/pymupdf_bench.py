#!/usr/bin/env python3
"""Benchmark PyMuPDF variants: raw, layout, OCR, tables, and combinations."""
import argparse
import time
from pathlib import Path

import fitz  # PyMuPDF


def variant_raw_text(pdf_path: Path) -> str:
    """Fastest: just get_text('text')."""
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc, 1):
        text = page.get_text("text")
        pages.append(f"## Page {i}\n\n{text}")
    doc.close()
    return "\n\n---\n\n".join(pages)


def variant_blocks(pdf_path: Path) -> str:
    """Text blocks with heading detection by font size."""
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc, 1):
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        text_content = []
        for block in blocks:
            if block["type"] == 0:
                lines = []
                for line in block["lines"]:
                    spans = line["spans"]
                    if not spans:
                        continue
                    line_text = "".join(s["text"] for s in spans)
                    max_size = max(s["size"] for s in spans)
                    is_bold = any("bold" in s["font"].lower() for s in spans)
                    if max_size >= 16 and is_bold:
                        line_text = f"# {line_text.strip()}"
                    elif max_size >= 14 and is_bold:
                        line_text = f"## {line_text.strip()}"
                    elif max_size >= 12 and is_bold:
                        line_text = f"### {line_text.strip()}"
                    lines.append(line_text)
                text_content.append("\n".join(lines))
            elif block["type"] == 1:
                text_content.append(f"[IMAGE ({block.get('width', 0)}x{block.get('height', 0)})]")
        pages.append(f"## Page {i}\n\n" + "\n\n".join(text_content))
    doc.close()
    return "\n\n---\n\n".join(pages)


def variant_blocks_tables(pdf_path: Path) -> str:
    """Text blocks + table extraction."""
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc, 1):
        text = page.get_text("text")

        tables = page.find_tables()
        table_md = []
        for table in tables:
            data = table.extract()
            if data and data[0]:
                header = "| " + " | ".join(str(c or "") for c in data[0]) + " |"
                sep = "| " + " | ".join("---" for _ in data[0]) + " |"
                rows = "\n".join(
                    "| " + " | ".join(str(c or "") for c in row) + " |"
                    for row in data[1:]
                )
                table_md.append(f"{header}\n{sep}\n{rows}")

        page_content = f"## Page {i}\n\n{text}"
        if table_md:
            page_content += "\n\n### Tables\n\n" + "\n\n".join(table_md)
        pages.append(page_content)
    doc.close()
    return "\n\n---\n\n".join(pages)


def variant_pymupdf4llm(pdf_path: Path) -> str:
    """pymupdf4llm layout-aware markdown conversion."""
    import pymupdf4llm
    return pymupdf4llm.to_markdown(str(pdf_path))


def variant_pymupdf4llm_tables(pdf_path: Path) -> str:
    """pymupdf4llm with table extraction forced on."""
    import pymupdf4llm
    return pymupdf4llm.to_markdown(str(pdf_path), show_progress=False)


def variant_ocr(pdf_path: Path) -> str:
    """PyMuPDF with OCR via Tesseract on each page."""
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc, 1):
        # Try normal text first; if empty, use OCR
        text = page.get_text("text")
        if not text.strip():
            tp = page.get_textpage_ocr(flags=fitz.TEXT_PRESERVE_WHITESPACE, full=True)
            text = page.get_text("text", textpage=tp)
        pages.append(f"## Page {i}\n\n{text}")
    doc.close()
    return "\n\n---\n\n".join(pages)


VARIANTS = {
    "raw_text": ("Raw text (get_text)", variant_raw_text),
    "blocks": ("Blocks + heading detection", variant_blocks),
    "blocks_tables": ("Blocks + tables (find_tables)", variant_blocks_tables),
    "pymupdf4llm": ("pymupdf4llm (layout-aware MD)", variant_pymupdf4llm),
    "pymupdf4llm_tables": ("pymupdf4llm + tables", variant_pymupdf4llm_tables),
    "ocr": ("OCR fallback (Tesseract)", variant_ocr),
}


def main():
    parser = argparse.ArgumentParser(description="Benchmark PyMuPDF variants")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument(
        "--variants",
        nargs="*",
        default=list(VARIANTS.keys()),
        choices=list(VARIANTS.keys()),
        help="Which variants to run",
    )
    args = parser.parse_args()

    pdf_path = Path(args.input)
    if not pdf_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    print(f"Benchmarking: {pdf_path.name}")
    print(f"Variants: {', '.join(args.variants)}")
    print("=" * 80)

    results = []
    for key in args.variants:
        label, func = VARIANTS[key]
        print(f"\n>>> {label}...")
        try:
            start = time.time()
            content = func(pdf_path)
            elapsed = time.time() - start

            # Save output
            output_dir = Path(f"output/pymupdf-bench/{key}") / pdf_path.stem
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{pdf_path.stem}.md"
            output_path.write_text(content)

            words = len(content.split())
            chars = len(content)
            print(f"    Time: {elapsed:.2f}s | Words: {words:,} | Chars: {chars:,}")
            print(f"    Saved: {output_path}")
            results.append((key, label, elapsed, words, chars))
        except Exception as e:
            print(f"    FAILED: {e}")
            results.append((key, label, -1, 0, 0))

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"{'Variant':<35} {'Time':>8} {'Words':>10} {'Chars':>12}")
    print("-" * 70)
    for key, label, elapsed, words, chars in results:
        t = f"{elapsed:.2f}s" if elapsed >= 0 else "FAILED"
        print(f"{label:<35} {t:>8} {words:>10,} {chars:>12,}")

    print()
    return 0


if __name__ == "__main__":
    exit(main())
