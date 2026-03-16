#!/usr/bin/env python3
"""Docling + HierarchicalChunker - structure-preserving chunks, no AI."""
import argparse
import json
import time
from pathlib import Path

from docling.chunking import HierarchicalChunker
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions, TableStructureOptions, TableFormerMode
)
from docling.document_converter import DocumentConverter, PdfFormatOption


def parse_and_chunk(pdf_path: Path):
    """Parse PDF with vanilla Docling, then chunk hierarchically."""
    # Step 1: Parse
    options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        generate_picture_images=False,
        do_picture_description=False,
        table_structure_options=TableStructureOptions(mode=TableFormerMode.ACCURATE),
    )
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    result = converter.convert(pdf_path)
    doc = result.document

    # Step 2: Chunk
    chunker = HierarchicalChunker(merge_list_items=True)
    chunks = list(chunker.chunk(doc))

    # Step 3: Serialize chunks
    chunk_data = []
    for i, chunk in enumerate(chunks):
        contextualized = chunker.contextualize(chunk)
        item = {
            "chunk_id": i,
            "text": chunk.text,
            "contextualized_text": contextualized,
            "char_count": len(chunk.text),
            "headings": list(chunk.meta.headings) if chunk.meta.headings else [],
            "doc_items": [
                ref.self_ref for ref in chunk.meta.doc_items
            ] if chunk.meta.doc_items else [],
        }
        chunk_data.append(item)

    return doc, chunk_data


def print_summary(chunk_data, parse_time, chunk_time, input_name):
    """Print a summary table of chunks."""
    total = len(chunk_data)
    if total == 0:
        print("No chunks produced.")
        return

    char_counts = [c["char_count"] for c in chunk_data]
    avg_chars = sum(char_counts) / total

    print(f"\n{'=' * 70}")
    print(f"  HierarchicalChunker Summary — {input_name}")
    print(f"{'=' * 70}")
    print(f"  Parse time:    {round(parse_time, 2)}s")
    print(f"  Chunk time:    {round(chunk_time, 4)}s")
    print(f"  Total time:    {round(parse_time + chunk_time, 2)}s")
    print(f"  Total chunks:  {total}")
    print(f"  Avg chars:     {round(avg_chars)}")
    print(f"  Min chars:     {min(char_counts)}")
    print(f"  Max chars:     {max(char_counts)}")
    print(f"{'=' * 70}")

    print(f"\n{'#':<5} {'Chars':<8} {'Headings':<40} {'Preview'}")
    print(f"{'-'*5} {'-'*8} {'-'*40} {'-'*40}")
    for c in chunk_data:
        headings = " > ".join(c["headings"]) if c["headings"] else "(none)"
        if len(headings) > 38:
            headings = headings[:35] + "..."
        preview = c["text"][:37].replace("\n", " ")
        if len(c["text"]) > 37:
            preview += "..."
        print(f"{c['chunk_id']:<5} {c['char_count']:<8} {headings:<40} {preview}")


def main():
    parser = argparse.ArgumentParser(description="Docling + HierarchicalChunker")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("-o", "--output", help="Output file path")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    output_dir = Path("output/docling/chunker-hierarchical") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else output_dir / f"{input_path.stem}.json"

    print(f"Parsing: {input_path.name} (Docling + HierarchicalChunker)")

    # Parse
    parse_start = time.time()
    options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        generate_picture_images=False,
        do_picture_description=False,
        table_structure_options=TableStructureOptions(mode=TableFormerMode.ACCURATE),
    )
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    result = converter.convert(input_path)
    doc = result.document
    parse_time = time.time() - parse_start

    # Chunk
    chunk_start = time.time()
    chunker = HierarchicalChunker(merge_list_items=True)
    chunks = list(chunker.chunk(doc))

    chunk_data = []
    for i, chunk in enumerate(chunks):
        contextualized = chunker.contextualize(chunk)
        chunk_data.append({
            "chunk_id": i,
            "text": chunk.text,
            "contextualized_text": contextualized,
            "char_count": len(chunk.text),
            "headings": list(chunk.meta.headings) if chunk.meta.headings else [],
            "doc_items": [
                ref.self_ref for ref in chunk.meta.doc_items
            ] if chunk.meta.doc_items else [],
        })
    chunk_time = time.time() - chunk_start

    # Save
    output = {
        "document": input_path.name,
        "chunker": "HierarchicalChunker",
        "config": {"merge_list_items": True},
        "performance": {
            "parse_time_s": round(parse_time, 2),
            "chunk_time_s": round(chunk_time, 4),
            "total_time_s": round(parse_time + chunk_time, 2),
        },
        "total_chunks": len(chunk_data),
        "chunks": chunk_data,
    }
    output_path.write_text(json.dumps(output, indent=2))

    print_summary(chunk_data, parse_time, chunk_time, input_path.name)
    print(f"\nSaved to: {output_path}")
    return 0


if __name__ == "__main__":
    exit(main())
