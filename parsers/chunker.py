#!/usr/bin/env python3
"""
Chunker: splits pipeline markdown output into retrieval-ready chunks.

Uses Chonkie's RecursiveChunker for text and TableChunker for tables,
producing chunks with page numbers and type metadata.

Usage:
    from chunker import chunk_document

    chunks = chunk_document("output/pipeline/hubspot-q4/hubspot-q4.md")
    # or pass markdown directly:
    chunks = chunk_markdown(markdown_str)
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from chonkie import RecursiveChunker, TableChunker


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class ChunkType:
    TEXT = "text"
    TABLE = "table"


@dataclass
class Chunk:
    text: str
    chunk_type: str
    page_num: int | None = None
    token_count: int = 0
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Page splitting (handles pipeline output formats)
# ---------------------------------------------------------------------------

_PAGE_MARKER = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
_PAGE_HEADER = re.compile(r"^## Page (\d+)\s*$", re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    """Strip all ```markdown ... ``` code fences from LLM output."""
    # Remove all opening ```markdown / ```md / ``` fences
    text = re.sub(r"```(?:markdown|md)?\s*\n", "", text)
    # Remove all closing ``` on their own line
    text = re.sub(r"\n```\s*(?=\n|$)", "", text)
    return text.strip()


def _split_into_pages(markdown: str) -> list[tuple[int, str]]:
    """Split markdown into (page_num, page_text) tuples."""
    # Try <!-- page: N --> markers first (pipeline.py output)
    markers = list(_PAGE_MARKER.finditer(markdown))
    if markers:
        pages = []
        # Content before the first marker is page 1
        pre_text = markdown[:markers[0].start()].strip()
        pre_text = re.sub(r"^---\s*", "", pre_text)
        pre_text = re.sub(r"\s*---\s*$", "", pre_text)
        pre_text = _strip_code_fences(pre_text)
        if pre_text:
            pages.append((1, pre_text))
        for i, m in enumerate(markers):
            pn = int(m.group(1))
            start = m.end()
            end = markers[i + 1].start() if i + 1 < len(markers) else len(markdown)
            text = markdown[start:end].strip()
            # Remove leading/trailing --- separators and code fences
            text = re.sub(r"^---\s*", "", text)
            text = re.sub(r"\s*---\s*$", "", text)
            text = _strip_code_fences(text)
            if text:
                pages.append((pn, text))
        return pages

    # Try ## Page N headers (pymupdf_fast output)
    headers = list(_PAGE_HEADER.finditer(markdown))
    if headers:
        pages = []
        for i, m in enumerate(headers):
            pn = int(m.group(1))
            start = m.end()
            end = headers[i + 1].start() if i + 1 < len(headers) else len(markdown)
            text = markdown[start:end].strip()
            text = re.sub(r"^---\s*", "", text)
            text = re.sub(r"\s*---\s*$", "", text)
            text = _strip_code_fences(text)
            if text:
                pages.append((pn, text))
        return pages

    # Fallback: entire document as page 1
    return [(1, _strip_code_fences(markdown.strip()))]


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------

def _extract_tables_and_text(page_text: str) -> list[tuple[str, str]]:
    """Split page text into (type, content) segments: 'table' or 'text'.

    When a table is preceded by a heading or short context line (e.g. a title
    like "## Beta Adj Exposure ($)"), that context is prepended to the table
    so chunkers keep the title with the table data.
    """
    lines = page_text.split("\n")
    segments = []
    current_lines = []
    in_table = False

    for line in lines:
        is_pipe = line.strip().startswith("|")

        if is_pipe and not in_table:
            # Flush text — but check if the tail is a table title/heading
            text = "\n".join(current_lines).strip()
            if text:
                # Pull trailing heading/context lines that belong with the table
                text_lines = text.split("\n")
                table_prefix_lines = []
                while text_lines:
                    candidate = text_lines[-1].strip()
                    # A heading, bold line, or short label (< 100 chars) right
                    # above the table is likely its title
                    is_heading = candidate.startswith("#")
                    is_bold = candidate.startswith("**") and candidate.endswith("**")
                    is_short_label = 0 < len(candidate) < 100 and not candidate.startswith("|")
                    if is_heading or is_bold or is_short_label:
                        table_prefix_lines.insert(0, text_lines.pop())
                    else:
                        break

                remaining_text = "\n".join(text_lines).strip()
                if remaining_text:
                    segments.append(("text", remaining_text))

                # Prepend context to the table
                if table_prefix_lines:
                    current_lines = table_prefix_lines + [line]
                else:
                    current_lines = [line]
            else:
                current_lines = [line]
            in_table = True
        elif is_pipe and in_table:
            current_lines.append(line)
        elif not is_pipe and in_table:
            # End of table
            table_text = "\n".join(current_lines).strip()
            if table_text:
                segments.append(("table", table_text))
            current_lines = [line]
            in_table = False
        else:
            current_lines.append(line)

    # Flush remaining
    remaining = "\n".join(current_lines).strip()
    if remaining:
        segments.append(("table" if in_table else "text", remaining))

    return segments


# ---------------------------------------------------------------------------
# Core chunking
# ---------------------------------------------------------------------------

def chunk_markdown(
    markdown: str,
    chunk_size: int = 512,
    table_chunk_size: int = 512,
    min_chunk_chars: int = 24,
) -> list[Chunk]:
    """
    Chunk pipeline markdown into retrieval-ready pieces.

    - Text segments: RecursiveChunker with markdown-aware splitting
    - Table segments: TableChunker that preserves headers across splits

    Args:
        markdown: Full markdown string (from pipeline or pymupdf_fast)
        chunk_size: Max tokens per text chunk
        table_chunk_size: Max tokens per table chunk
        min_chunk_chars: Minimum characters per chunk (filters noise)

    Returns:
        List of Chunk objects with page numbers and type metadata
    """
    text_chunker = RecursiveChunker(
        tokenizer="o200k_base",
        chunk_size=chunk_size,
        min_characters_per_chunk=min_chunk_chars,
    )
    table_chunker = TableChunker(
        tokenizer="o200k_base",
        chunk_size=table_chunk_size,
    )

    pages = _split_into_pages(markdown)
    all_chunks = []

    for page_num, page_text in pages:
        segments = _extract_tables_and_text(page_text)

        for seg_type, seg_text in segments:
            # Strip bold markers before sending to Chonkie so ** doesn't
            # interfere with table row parsing, but keep original text in output
            clean_text = seg_text.replace("**", "")

            if seg_type == "table":
                try:
                    chonkie_chunks = table_chunker.chunk(clean_text)
                except Exception:
                    # Fallback: treat malformed table as a single chunk
                    chonkie_chunks = text_chunker.chunk(clean_text)

                for cc in chonkie_chunks:
                    all_chunks.append(Chunk(
                        text=cc.text,
                        chunk_type=ChunkType.TABLE,
                        page_num=page_num,
                        token_count=cc.token_count,
                    ))
            else:
                chonkie_chunks = text_chunker.chunk(clean_text)
                for cc in chonkie_chunks:
                    all_chunks.append(Chunk(
                        text=cc.text,
                        chunk_type=ChunkType.TEXT,
                        page_num=page_num,
                        token_count=cc.token_count,
                    ))

    return all_chunks


def chunk_document(
    md_path: str | Path,
    **kwargs,
) -> list[Chunk]:
    """Chunk a pipeline output markdown file."""
    md_path = Path(md_path)
    markdown = md_path.read_text()
    return chunk_markdown(markdown, **kwargs)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Chunk pipeline markdown for RAG")
    parser.add_argument("input", help="Path to markdown file (pipeline output)")
    parser.add_argument("-o", "--output", help="Output JSON path (default: alongside input as *_chunks.json)")
    parser.add_argument("--chunk-size", type=int, default=512, help="Max tokens per text chunk")
    parser.add_argument("--table-chunk-size", type=int, default=512, help="Max tokens per table chunk")
    parser.add_argument("--show-tables", action="store_true", help="Only show table chunks")
    parser.add_argument("--no-save", action="store_true", help="Print only, don't save to file")
    args = parser.parse_args()

    input_path = Path(args.input)
    chunks = chunk_document(
        input_path,
        chunk_size=args.chunk_size,
        table_chunk_size=args.table_chunk_size,
    )

    table_count = sum(1 for c in chunks if c.chunk_type == ChunkType.TABLE)
    text_count = len(chunks) - table_count
    avg_tokens = sum(c.token_count for c in chunks) / len(chunks) if chunks else 0

    print(f"Chunks: {len(chunks)} (text: {text_count}, tables: {table_count})")
    print(f"Avg tokens: {avg_tokens:.0f}")
    print(f"Token range: {min(c.token_count for c in chunks)}-{max(c.token_count for c in chunks)}")
    print()

    for i, chunk in enumerate(chunks):
        if args.show_tables and chunk.chunk_type != ChunkType.TABLE:
            continue
        preview = chunk.text[:150].replace("\n", " ")
        print(f"  {i:>3} [page {chunk.page_num}, {chunk.chunk_type}, {chunk.token_count} tok]: {preview}...")

    # Save chunks to JSON
    if not args.no_save:
        if args.output:
            out_path = Path(args.output)
        else:
            out_path = input_path.parent / f"{input_path.stem}_chunks.json"

        out_data = {
            "source": str(input_path),
            "chunk_size": args.chunk_size,
            "table_chunk_size": args.table_chunk_size,
            "total_chunks": len(chunks),
            "text_chunks": text_count,
            "table_chunks": table_count,
            "chunks": [
                {
                    "id": i,
                    "text": c.text,
                    "chunk_type": c.chunk_type,
                    "page_num": c.page_num,
                    "token_count": c.token_count,
                }
                for i, c in enumerate(chunks)
            ],
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out_data, indent=2))
        print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    main()
