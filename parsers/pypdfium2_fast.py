#!/usr/bin/env python3
"""Fast PDF text extraction using pypdfium2 (C-based, no ML)."""
import argparse
import time
from pathlib import Path

import pypdfium2 as pdfium


def parse_document(pdf_path: Path) -> str:
    """Extract text from all pages using pypdfium2."""
    doc = pdfium.PdfDocument(pdf_path)
    pages = []
    for i in range(len(doc)):
        page = doc[i]
        text = page.get_textpage().get_text_range()
        pages.append(f"## Page {i + 1}\n\n{text}")
        page.close()
    doc.close()
    return "\n\n---\n\n".join(pages)


def main():
    parser = argparse.ArgumentParser(description="Fast PDF parsing with pypdfium2")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("-o", "--output", help="Output file path")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    output_dir = Path("output/pypdfium2-fast") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else output_dir / f"{input_path.stem}.md"

    print(f"Parsing: {input_path.name} (pypdfium2 fast)")
    start_time = time.time()
    content = parse_document(input_path)
    parse_time = time.time() - start_time

    output_path.write_text(content)
    print(f"Saved to: {output_path}")
    print(f"Parse time: {round(parse_time, 2)}s")
    return 0


if __name__ == "__main__":
    exit(main())
