#!/usr/bin/env python3
"""Analyze Document AI chunks and generate a summary table."""
import json
import sys
from pathlib import Path

def analyze_chunks(json_path):
    with open(json_path, 'r') as f:
        data = json.load(f)

    if 'chunkedDocument' not in data or 'chunks' not in data['chunkedDocument']:
        print("No chunks found in the JSON file.")
        return

    chunks = data['chunkedDocument']['chunks']

    # Print header
    print("┌" + "─" * 7 + "┬" + "─" * 20 + "┬" + "─" * 13 + "┬" + "─" * 12 + "┬" + "─" * 11 + "┬" + "─" * 60 + "┐")
    print(f"│ {'Chunk':<5} │ {'Content Type':<18} │ {'Text Length':<11} │ {'Has Images':<10} │ {'Page Span':<9} │ {'Description':<58} │")
    print("├" + "─" * 7 + "┼" + "─" * 20 + "┼" + "─" * 13 + "┼" + "─" * 12 + "┼" + "─" * 11 + "┼" + "─" * 60 + "┤")

    for chunk in chunks:
        chunk_id = chunk.get('chunkId', 'N/A')
        content = chunk.get('content', '')
        text_len = len(content)

        # Determine content type
        content_type = "Text only"
        has_images = "No"

        # Check source blocks for images/tables
        source_blocks = chunk.get('sourceBlockIds', [])
        if len(source_blocks) > 0:
            # This is a simplified check - would need to cross-reference with documentLayout
            # to determine actual content type
            if 'image' in content.lower() or 'figure' in content.lower():
                content_type = "Text + Images"
                has_images = "Yes"
            elif 'table' in content.lower() or '|' in content:
                content_type = "Text + Table"

        # Get page span
        page_span = "N/A"
        if 'pageSpan' in chunk and chunk['pageSpan']:
            ps = chunk['pageSpan']
            page_start = ps.get('pageStart', 0)
            page_end = ps.get('pageEnd', 0)
            page_span = f"{page_start}-{page_end}"

        # Get description (first 50 chars of content)
        description = content.strip()[:55]
        if len(content) > 55:
            description += "..."
        description = description.replace('\n', ' ').replace('\r', '')

        print(f"│ {chunk_id:<5} │ {content_type:<18} │ {text_len:<11} │ {has_images:<10} │ {page_span:<9} │ {description:<58} │")

    print("└" + "─" * 7 + "┴" + "─" * 20 + "┴" + "─" * 13 + "┴" + "─" * 12 + "┴" + "─" * 11 + "┴" + "─" * 60 + "┘")
    print(f"\nTotal chunks: {len(chunks)}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_chunks.py <json_file>")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    if not json_path.exists():
        print(f"Error: {json_path} not found")
        sys.exit(1)

    analyze_chunks(json_path)
