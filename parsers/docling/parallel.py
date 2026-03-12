#!/usr/bin/env python3
"""Parallelized Docling parser with page chunking."""
import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import List, Tuple

import pdfplumber
from docling.document_converter import DocumentConverter


def get_page_count(pdf_path: Path) -> int:
    """Get total page count from PDF."""
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


def create_chunks(total_pages: int, chunk_size: int) -> List[Tuple[int, int]]:
    """Split pages into chunks. Returns list of (start, end) tuples with 1-based indexing."""
    chunks = []
    for start in range(1, total_pages + 1, chunk_size):
        end = min(start + chunk_size - 1, total_pages)
        chunks.append((start, end))
    return chunks


def process_chunk(pdf_path: Path, page_range: Tuple[int, int]) -> str:
    """Process a single page range chunk."""
    converter = DocumentConverter()
    result = converter.convert(pdf_path, page_range=page_range)
    return result.document.export_to_markdown()


def parse_document_parallel(
    pdf_path: Path,
    chunk_size: int = 20,
    max_workers: int = 2
) -> str:
    """Parse PDF with parallel page chunking.

    Args:
        pdf_path: Path to PDF file
        chunk_size: Number of pages per chunk (default: 20)
        max_workers: Maximum parallel workers (default: 2)

    Returns:
        Markdown content from all pages
    """
    # Step 1: Get total pages
    total_pages = get_page_count(pdf_path)

    if total_pages == 0:
        return ""

    # Step 2: Create chunks
    chunks = create_chunks(total_pages, chunk_size)

    # Step 3: Process chunks in parallel
    results = {}
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_chunk = {
            executor.submit(process_chunk, pdf_path, chunk): chunk
            for chunk in chunks
        }

        for future in as_completed(future_to_chunk):
            chunk = future_to_chunk[future]
            try:
                results[chunk[0]] = future.result()  # Key by start page
            except Exception as e:
                print(f"Error processing pages {chunk[0]}-{chunk[1]}: {e}", file=sys.stderr)
                raise

    # Step 4: Merge in page order
    merged = []
    for chunk in sorted(chunks, key=lambda x: x[0]):
        merged.append(results[chunk[0]])

    return "\n\n".join(merged)


def main():
    parser = argparse.ArgumentParser(
        description="Parse PDFs with parallelized Docling"
    )
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=20,
        help="Pages per chunk (default: 20)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Max parallel workers (default: 2)"
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    output_dir = Path("output/docling/parallel") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        Path(args.output) if args.output
        else output_dir / f"{input_path.stem}.md"
    )

    print(f"Parsing: {input_path.name} (Docling Parallel)")
    print(f"Chunk size: {args.chunk_size} pages, Workers: {args.workers}")

    start_time = time.time()
    content = parse_document_parallel(
        input_path,
        chunk_size=args.chunk_size,
        max_workers=args.workers
    )
    parse_time = time.time() - start_time

    output_path.write_text(content)
    print(f"Saved to: {output_path}")
    print(f"Parse time: {round(parse_time, 2)}s")
    return 0


if __name__ == "__main__":
    exit(main())
