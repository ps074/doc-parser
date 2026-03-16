#!/usr/bin/env python3
"""Docling + HybridChunker - token-aware chunks using OpenAI tokenizer, no AI."""
import argparse
import json
import time
from pathlib import Path

import tiktoken
from pydantic import PrivateAttr
from docling.chunking import HybridChunker
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions, TableStructureOptions, TableFormerMode
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer


class TiktokenTokenizer(BaseTokenizer):
    """Tokenizer wrapper for OpenAI's tiktoken (text-embedding-3-small uses cl100k_base)."""

    _max_tokens: int = PrivateAttr()
    _encoding: object = PrivateAttr()

    def __init__(self, max_tokens: int = 512, **kwargs):
        super().__init__(**kwargs)
        self._max_tokens = max_tokens
        self._encoding = tiktoken.get_encoding("cl100k_base")

    def get_max_tokens(self) -> int:
        return self._max_tokens

    def count_tokens(self, text: str) -> int:
        return len(self._encoding.encode(text))

    def get_tokenizer(self):
        return self._encoding


def print_summary(chunk_data, parse_time, chunk_time, input_name, max_tokens):
    """Print a summary table of chunks."""
    total = len(chunk_data)
    if total == 0:
        print("No chunks produced.")
        return

    token_counts = [c["token_count"] for c in chunk_data]
    char_counts = [c["char_count"] for c in chunk_data]
    avg_tokens = sum(token_counts) / total

    print(f"\n{'=' * 80}")
    print(f"  HybridChunker Summary — {input_name}")
    print(f"{'=' * 80}")
    print(f"  Tokenizer:     tiktoken cl100k_base (text-embedding-3-small)")
    print(f"  Max tokens:    {max_tokens}")
    print(f"  Parse time:    {round(parse_time, 2)}s")
    print(f"  Chunk time:    {round(chunk_time, 4)}s")
    print(f"  Total time:    {round(parse_time + chunk_time, 2)}s")
    print(f"  Total chunks:  {total}")
    print(f"  Avg tokens:    {round(avg_tokens)}")
    print(f"  Min tokens:    {min(token_counts)}")
    print(f"  Max tokens:    {max(token_counts)}")
    print(f"  Avg chars:     {round(sum(char_counts) / total)}")
    print(f"{'=' * 80}")

    print(f"\n{'#':<5} {'Tokens':<8} {'Chars':<8} {'Headings':<35} {'Preview'}")
    print(f"{'-'*5} {'-'*8} {'-'*8} {'-'*35} {'-'*35}")
    for c in chunk_data:
        headings = " > ".join(c["headings"]) if c["headings"] else "(none)"
        if len(headings) > 33:
            headings = headings[:30] + "..."
        preview = c["text"][:32].replace("\n", " ")
        if len(c["text"]) > 32:
            preview += "..."
        print(f"{c['chunk_id']:<5} {c['token_count']:<8} {c['char_count']:<8} {headings:<35} {preview}")


def main():
    parser = argparse.ArgumentParser(description="Docling + HybridChunker (OpenAI tokenizer)")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument("--max-tokens", type=int, default=512,
                        help="Max tokens per chunk (default: 512)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    output_dir = Path("output/docling/chunker-hybrid") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else output_dir / f"{input_path.stem}.json"

    print(f"Parsing: {input_path.name} (Docling + HybridChunker)")
    print(f"Tokenizer: tiktoken cl100k_base (text-embedding-3-small)")
    print(f"Max tokens: {args.max_tokens}")

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
    tokenizer = TiktokenTokenizer(max_tokens=args.max_tokens)
    chunker = HybridChunker(tokenizer=tokenizer, merge_peers=True)
    chunks = list(chunker.chunk(doc))

    encoding = tiktoken.get_encoding("cl100k_base")
    chunk_data = []
    for i, chunk in enumerate(chunks):
        contextualized = chunker.contextualize(chunk)
        token_count = len(encoding.encode(chunk.text))
        ctx_token_count = len(encoding.encode(contextualized))
        chunk_data.append({
            "chunk_id": i,
            "text": chunk.text,
            "contextualized_text": contextualized,
            "char_count": len(chunk.text),
            "token_count": token_count,
            "contextualized_token_count": ctx_token_count,
            "headings": list(chunk.meta.headings) if chunk.meta.headings else [],
            "doc_items": [
                ref.self_ref for ref in chunk.meta.doc_items
            ] if chunk.meta.doc_items else [],
        })
    chunk_time = time.time() - chunk_start

    # Save
    output = {
        "document": input_path.name,
        "chunker": "HybridChunker",
        "config": {
            "tokenizer": "tiktoken/cl100k_base (text-embedding-3-small)",
            "max_tokens": args.max_tokens,
            "merge_peers": True,
        },
        "performance": {
            "parse_time_s": round(parse_time, 2),
            "chunk_time_s": round(chunk_time, 4),
            "total_time_s": round(parse_time + chunk_time, 2),
        },
        "total_chunks": len(chunk_data),
        "chunks": chunk_data,
    }
    output_path.write_text(json.dumps(output, indent=2))

    print_summary(chunk_data, parse_time, chunk_time, input_path.name, args.max_tokens)
    print(f"\nSaved to: {output_path}")
    return 0


if __name__ == "__main__":
    exit(main())
