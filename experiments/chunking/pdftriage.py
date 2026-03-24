#!/usr/bin/env python3
"""
PDFTriage: Structure-aware document QA.

Instead of chunking + embedding, we:
1. Extract document structure (sections, tables, figures) as metadata
2. Give the LLM the structural metadata + callable fetch functions
3. LLM decides what to fetch, then answers

Based on: https://arxiv.org/pdf/2309.08872v1
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
import pymupdf4llm
from openai import OpenAI


# ---------------------------------------------------------------------------
# Step 1: Extract document structure
# ---------------------------------------------------------------------------

@dataclass
class TableInfo:
    id: int
    page: int
    caption: str
    content: str  # full table text


@dataclass
class SectionInfo:
    title: str
    level: int  # 1=h1, 2=h2, etc
    pages: list[int]


@dataclass
class DocumentStructure:
    path: str
    total_pages: int
    title: str
    sections: list[SectionInfo]
    tables: list[TableInfo]
    page_texts: dict[int, str]  # page_num -> text


def extract_structure(pdf_path: Path, use_pipeline: bool = False) -> DocumentStructure:
    """Extract document structure.

    Args:
        pdf_path: Path to PDF file.
        use_pipeline: If True, use pre-parsed pipeline output (vision LLM)
            for page text instead of pymupdf4llm. Produces cleaner tables.
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    # Get TOC for sections
    toc = doc.get_toc()  # [(level, title, page), ...]
    sections = []
    for level, title, page in toc:
        sections.append(SectionInfo(title=title, level=level, pages=[page]))

    doc.close()

    # Get per-page text
    page_texts = {}

    if use_pipeline:
        # Load from pipeline output (vision LLM markdown)
        pipeline_dir = pdf_path.parent.parent / "output" / "pipeline" / pdf_path.stem
        md_path = pipeline_dir / f"{pdf_path.stem}.md"
        if md_path.exists():
            md = md_path.read_text()
            # Split by page markers
            import re as _re
            page_marker = _re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
            markers = list(page_marker.finditer(md))
            if markers:
                for i, m in enumerate(markers):
                    pn = int(m.group(1))
                    start = m.end()
                    end = markers[i + 1].start() if i + 1 < len(markers) else len(md)
                    page_texts[pn] = md[start:end].strip()
            else:
                # No page markers — treat as single page
                page_texts[1] = md
        else:
            print(f"  Warning: pipeline output not found at {md_path}, falling back to pymupdf4llm")
            use_pipeline = False

    if not use_pipeline:
        # Use pymupdf4llm
        page_chunks = pymupdf4llm.to_markdown(
            str(pdf_path), page_chunks=True, show_progress=False,
        )
        for chunk in page_chunks:
            pn = chunk["metadata"]["page_number"]
            page_texts[pn] = chunk["text"]

    # If no TOC, build sections from headings in the markdown
    if not sections:
        sections = _extract_sections_from_markdown(page_texts)

    # Extract tables: find pipe-table blocks in each page's markdown
    tables = []
    table_id = 0
    for pn, text in sorted(page_texts.items()):
        page_tables = _extract_tables_from_page(text, pn)
        for caption, content in page_tables:
            tables.append(TableInfo(
                id=table_id, page=pn, caption=caption, content=content,
            ))
            table_id += 1

    # Document title
    title = ""
    if sections:
        title = sections[0].title
    if not title:
        # Try first heading in the text
        for pn in sorted(page_texts.keys()):
            for match in re.finditer(r"^#{1,3}\s+(.+)$", page_texts[pn], re.MULTILINE):
                title = match.group(1).replace("**", "").strip()
                break
            if title:
                break
    if not title:
        title = pdf_path.stem

    return DocumentStructure(
        path=str(pdf_path),
        total_pages=total_pages,
        title=title,
        sections=sections,
        tables=tables,
        page_texts=page_texts,
    )


def _extract_sections_from_markdown(page_texts: dict[int, str]) -> list[SectionInfo]:
    """Extract sections from markdown headings when no TOC is available."""
    sections = []
    for pn, text in sorted(page_texts.items()):
        for match in re.finditer(r"^(#{1,3})\s+(.+)$", text, re.MULTILINE):
            level = len(match.group(1))
            title = match.group(2).strip().replace("**", "")
            sections.append(SectionInfo(title=title, level=level, pages=[pn]))
    return sections


def _extract_tables_from_page(text: str, page_num: int) -> list[tuple[str, str]]:
    """Find pipe-table blocks in a page's markdown. Returns [(caption, content)].

    Builds captions by collecting ALL heading/context text above the table:
    e.g. "Consolidated Balance Sheets (in thousands) December 31, 2025 / 2024"
    """
    tables = []
    lines = text.split("\n")
    i = 0

    while i < len(lines):
        if lines[i].strip().startswith("|"):
            # Found a table start — collect all pipe lines
            table_lines = []

            # Look backward for caption: collect all non-empty text above until
            # we hit a blank-line gap, another table, or go back too far
            caption_parts = []
            blank_count = 0
            for j in range(i - 1, max(i - 15, -1), -1):
                line = lines[j].strip()
                if line.startswith("|"):
                    break  # hit another table
                if not line:
                    blank_count += 1
                    if blank_count >= 2:
                        break  # hit a real gap
                    continue
                # Clean markdown formatting
                clean = line.replace("#", "").replace("**", "").replace("_", "").strip()
                if clean:
                    caption_parts.insert(0, clean)

            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1

            content = "\n".join(table_lines)

            if caption_parts:
                caption = " — ".join(caption_parts)
            else:
                # Fallback: extract meaningful label from first column's <br> content
                if "|" in content:
                    first_cell = content.split("|")[1]
                    labels = [s.strip() for s in first_cell.split("<br>") if s.strip()]
                    # Find a label that looks like a title (not a number)
                    title_labels = [l for l in labels if not re.match(r'^[\$\d,.\-\(\)]+$', l)]
                    if title_labels:
                        caption = title_labels[0][:80]
                    else:
                        caption = labels[0][:80] if labels else f"Table on page {page_num}"
                else:
                    caption = f"Table on page {page_num}"

            tables.append((caption, content))
        else:
            i += 1

    return tables


# ---------------------------------------------------------------------------
# Step 2: Build metadata prompt for the LLM
# ---------------------------------------------------------------------------

def build_metadata_prompt(structure: DocumentStructure) -> str:
    """Convert document structure into a text representation for the LLM."""
    parts = [
        f"Document: {structure.title}",
        f"Total pages: {structure.total_pages}",
    ]

    if structure.sections:
        parts.append("\nSections:")
        for s in structure.sections:
            indent = "  " * (s.level - 1)
            pages_str = ", ".join(str(p) for p in s.pages)
            parts.append(f"{indent}- {s.title} (page {pages_str})")

    if structure.tables:
        parts.append(f"\nTables ({len(structure.tables)}):")
        for t in structure.tables:
            parts.append(f"  - Table {t.id}: \"{t.caption}\" (page {t.page})")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Step 3: Fetch functions
# ---------------------------------------------------------------------------

def fetch_pages(structure: DocumentStructure, pages: list[int]) -> str:
    """Get text from specific pages."""
    result = []
    for pn in pages:
        text = structure.page_texts.get(pn, "")
        if text:
            result.append(f"--- Page {pn} ---\n{text}")
    return "\n\n".join(result) if result else "No content found for those pages."


def fetch_section(structure: DocumentStructure, section_title: str) -> str:
    """Get text from a section by title (fuzzy match)."""
    title_lower = section_title.lower()
    # Find matching section
    best_match = None
    for s in structure.sections:
        if title_lower in s.title.lower() or s.title.lower() in title_lower:
            best_match = s
            break

    if not best_match:
        return f"Section '{section_title}' not found."

    # Get pages for this section (until next section at same or higher level)
    section_idx = structure.sections.index(best_match)
    start_page = best_match.pages[0]
    end_page = structure.total_pages

    for s in structure.sections[section_idx + 1:]:
        if s.level <= best_match.level:
            end_page = s.pages[0] - 1
            break

    return fetch_pages(structure, list(range(start_page, end_page + 1)))


def fetch_table(structure: DocumentStructure, table_id: int) -> str:
    """Get a specific table by ID."""
    for t in structure.tables:
        if t.id == table_id:
            return f"Table {t.id}: \"{t.caption}\" (page {t.page})\n\n{t.content}"
    return f"Table {table_id} not found."


def fetch_table_by_caption(structure: DocumentStructure, caption: str) -> str:
    """Get a table by caption (fuzzy match)."""
    caption_lower = caption.lower()
    for t in structure.tables:
        if caption_lower in t.caption.lower() or t.caption.lower() in caption_lower:
            return f"Table {t.id}: \"{t.caption}\" (page {t.page})\n\n{t.content}"
    return f"No table matching '{caption}' found."


# ---------------------------------------------------------------------------
# Step 4: LLM triage agent
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "fetch_pages",
            "description": "Get the full text content from specific page numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pages": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of page numbers to fetch (1-indexed).",
                    }
                },
                "required": ["pages"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_section",
            "description": "Get the text content of a document section by its title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "section_title": {
                        "type": "string",
                        "description": "The title of the section to fetch.",
                    }
                },
                "required": ["section_title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_table",
            "description": "Get a specific table by its ID number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {
                        "type": "integer",
                        "description": "The table ID to fetch.",
                    }
                },
                "required": ["table_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_table_by_caption",
            "description": "Get a table by searching for its caption/title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "caption": {
                        "type": "string",
                        "description": "The caption or title of the table to search for.",
                    }
                },
                "required": ["caption"],
            },
        },
    },
]

SYSTEM_PROMPT = """\
You are a document question answering system. You answer questions by \
fetching relevant content from the document using the available tools.

You will be given the document's structural metadata (sections, tables, \
page count). Use this to decide which tool to call to get the content \
needed to answer the question.

Strategy:
- For questions about specific data/numbers, fetch the relevant table or page.
- For questions about a topic, fetch the relevant section.
- You may call multiple tools if needed.
- After fetching content, answer the question based on what you retrieved.
- Be precise with numbers — never round or approximate."""


def triage_answer(
    question: str,
    structure: DocumentStructure,
    model: str = "gpt-4.1-mini",
    max_turns: int = 3,
    verbose: bool = False,
) -> dict:
    """Run PDFTriage: LLM reads metadata, calls fetch functions, answers."""
    client = OpenAI()
    metadata = build_metadata_prompt(structure)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Document metadata:\n\n{metadata}\n\nQuestion: {question}"},
    ]

    tool_calls_made = []

    for turn in range(max_turns):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        msg = response.choices[0].message

        if msg.tool_calls:
            messages.append(msg)

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments)

                if verbose:
                    print(f"  Tool call: {fn_name}({fn_args})")

                # Execute the function
                if fn_name == "fetch_pages":
                    result = fetch_pages(structure, fn_args["pages"])
                elif fn_name == "fetch_section":
                    result = fetch_section(structure, fn_args["section_title"])
                elif fn_name == "fetch_table":
                    result = fetch_table(structure, fn_args["table_id"])
                elif fn_name == "fetch_table_by_caption":
                    result = fetch_table_by_caption(structure, fn_args["caption"])
                else:
                    result = f"Unknown function: {fn_name}"

                # Truncate if too long
                if len(result) > 12000:
                    result = result[:12000] + "\n\n[... truncated]"

                tool_calls_made.append({
                    "function": fn_name,
                    "args": fn_args,
                    "result_length": len(result),
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            # No more tool calls — we have the final answer
            return {
                "answer": msg.content,
                "tool_calls": tool_calls_made,
                "turns": turn + 1,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            }

    # Max turns reached — get final answer without tools
    response = client.chat.completions.create(
        model=model,
        messages=messages,
    )
    return {
        "answer": response.choices[0].message.content,
        "tool_calls": tool_calls_made,
        "turns": max_turns,
        "total_tokens": response.usage.total_tokens if response.usage else 0,
    }


# ---------------------------------------------------------------------------
# CLI for quick testing
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="PDFTriage: Structure-aware document QA")
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("question", help="Question to answer")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    print(f"Extracting structure from {pdf_path}...")
    structure = extract_structure(pdf_path)

    print(f"\nDocument: {structure.title}")
    print(f"Pages: {structure.total_pages}")
    print(f"Sections: {len(structure.sections)}")
    print(f"Tables: {len(structure.tables)}")

    print(f"\nMetadata:")
    print(build_metadata_prompt(structure))

    print(f"\nQuestion: {args.question}")
    print(f"{'='*60}")

    result = triage_answer(args.question, structure, model=args.model, verbose=args.verbose)

    print(f"\nAnswer: {result['answer']}")
    print(f"\nTool calls: {len(result['tool_calls'])}")
    for tc in result['tool_calls']:
        print(f"  {tc['function']}({tc['args']}) → {tc['result_length']} chars")
    print(f"Turns: {result['turns']}")
    print(f"Total tokens: {result['total_tokens']}")


if __name__ == "__main__":
    main()
