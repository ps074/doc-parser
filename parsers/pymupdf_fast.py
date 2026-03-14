#!/usr/bin/env python3
"""Tier 2 parser: PyMuPDF - text + tables + images metadata, C-based speed."""
import argparse
import time
from pathlib import Path

import fitz  # PyMuPDF


def parse_document(pdf_path: Path) -> str:
    """Extract text, tables, and image metadata from PDF using PyMuPDF."""
    doc = fitz.open(pdf_path)
    pages = []

    for i, page in enumerate(doc, 1):
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

        text_content = []
        for block in blocks:
            if block["type"] == 0:  # text block
                lines = []
                for line in block["lines"]:
                    spans = line["spans"]
                    if not spans:
                        continue
                    line_text = "".join(s["text"] for s in spans)
                    # Detect headings by font size
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
            elif block["type"] == 1:  # image block
                w = block.get("width", 0)
                h = block.get("height", 0)
                text_content.append(f"[IMAGE ({w}x{h})]")

        # Extract tables
        tables = page.find_tables()
        table_markdowns = []
        for table in tables:
            data = table.extract()
            if data and data[0]:
                header = "| " + " | ".join(str(c or "") for c in data[0]) + " |"
                sep = "| " + " | ".join("---" for _ in data[0]) + " |"
                rows = "\n".join(
                    "| " + " | ".join(str(c or "") for c in row) + " |"
                    for row in data[1:]
                )
                table_markdowns.append(f"{header}\n{sep}\n{rows}")

        page_md = f"## Page {i}\n\n" + "\n\n".join(text_content)
        if table_markdowns:
            page_md += "\n\n### Tables\n\n" + "\n\n".join(table_markdowns)

        pages.append(page_md)

    doc.close()
    return "\n\n---\n\n".join(pages)


def main():
    parser = argparse.ArgumentParser(description="Tier 2: PyMuPDF parser (text + tables)")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("-o", "--output", help="Output file path")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    output_dir = Path("output/pymupdf") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else output_dir / f"{input_path.stem}.md"

    print(f"Parsing: {input_path.name} (PyMuPDF - Tier 2)")
    start_time = time.time()
    content = parse_document(input_path)
    parse_time = time.time() - start_time

    output_path.write_text(content)
    print(f"Saved to: {output_path}")
    print(f"Parse time: {round(parse_time, 2)}s")
    return 0


if __name__ == "__main__":
    exit(main())
