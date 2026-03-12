#!/usr/bin/env python3
"""Basic Docling parser - just DocumentConverter().convert()."""
import argparse
import time
from pathlib import Path
from docling.document_converter import DocumentConverter

def parse_document(pdf_path: Path) -> str:
    """Parse PDF with basic Docling converter."""
    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    return result.document.export_to_markdown()

def main():
    parser = argparse.ArgumentParser(description="Parse PDFs with basic Docling")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("-o", "--output", help="Output file path")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    output_dir = Path("output/docling/basic") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else output_dir / f"{input_path.stem}.md"

    print(f"Parsing: {input_path.name} (Basic Docling)")
    start_time = time.time()
    content = parse_document(input_path)
    parse_time = time.time() - start_time

    output_path.write_text(content)
    print(f"Saved to: {output_path}")
    print(f"Parse time: {round(parse_time, 2)}s")
    return 0

if __name__ == "__main__":
    exit(main())
