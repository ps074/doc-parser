#!/usr/bin/env python3
"""
Chunking strategies for PDF markdown output.

Strategies: page_level, fixed_size, recursive, heading_based, table_aware,
element_type, semantic, structure_aware, chonkie, contextual.

Handles output from pymupdf_fast ("## Page N"), pymupdf4llm/pipeline
("<!-- page: N -->"), or plain markdown.
"""
import re
from dataclasses import dataclass, field
from enum import Enum

import tiktoken

_enc = tiktoken.encoding_for_model("gpt-3.5-turbo")


class ChunkType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    CHART_DESCRIPTION = "chart_description"
    MIXED = "mixed"


@dataclass
class Chunk:
    text: str
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def split_into_pages(markdown: str) -> list[tuple[int, str]]:
    """Split markdown into (page_num, page_text) tuples.

    Handles:
      - pymupdf_fast: "## Page N" headers with "---" separators
      - pipeline: "<!-- page: N -->" markers or "---" separated blocks
    """
    # Try <!-- page: N --> markers first
    page_marker = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
    markers = list(page_marker.finditer(markdown))
    if markers:
        pages = []
        for i, m in enumerate(markers):
            pn = int(m.group(1))
            start = m.end()
            end = markers[i + 1].start() if i + 1 < len(markers) else len(markdown)
            pages.append((pn, markdown[start:end].strip()))
        return pages

    # Try ## Page N headers (pymupdf_fast output)
    page_header = re.compile(r"^## Page (\d+)\s*$", re.MULTILINE)
    headers = list(page_header.finditer(markdown))
    if headers:
        pages = []
        for i, m in enumerate(headers):
            pn = int(m.group(1))
            start = m.end()
            end = headers[i + 1].start() if i + 1 < len(headers) else len(markdown)
            pages.append((pn, markdown[start:end].strip()))
        return pages

    # Fallback: no page markers found. Treat entire document as page 1.
    # The "---" separators in pipeline LLM output are section breaks, not pages.
    return [(1, markdown.strip())]


def classify_block(text: str) -> ChunkType:
    """Classify a text block by content type."""
    stripped = text.strip()
    if not stripped:
        return ChunkType.TEXT

    # Table: has pipe-separated rows with a separator line
    lines = stripped.split("\n")
    pipe_lines = [l for l in lines if "|" in l]
    sep_lines = [l for l in lines if re.match(r"^\s*\|[\s\-:|]+\|\s*$", l)]
    if len(pipe_lines) >= 3 and sep_lines:
        return ChunkType.TABLE

    # Chart description: paragraph following a chart-related heading
    chart_kw = ["chart", "graph", "trend", "growth rate", "compound annual",
                "performance chart", "the chart shows", "the graph shows"]
    lower = stripped.lower()
    if any(kw in lower for kw in chart_kw) and len(stripped) > 100:
        return ChunkType.CHART_DESCRIPTION

    return ChunkType.TEXT


def split_into_elements(page_text: str) -> list[tuple[ChunkType, str]]:
    """Split a page into typed elements (tables, chart descs, text blocks).

    Tables are detected by pipe syntax and kept as atomic units.
    """
    elements = []
    current_lines = []
    in_table = False

    for line in page_text.split("\n"):
        is_pipe = bool(re.match(r"^\s*\|", line))

        if is_pipe and not in_table:
            # Flush current text block
            text = "\n".join(current_lines).strip()
            if text:
                elements.append((classify_block(text), text))
            current_lines = [line]
            in_table = True
        elif is_pipe and in_table:
            current_lines.append(line)
        elif not is_pipe and in_table:
            # End of table
            table_text = "\n".join(current_lines).strip()
            if table_text:
                elements.append((ChunkType.TABLE, table_text))
            current_lines = [line]
            in_table = False
        else:
            current_lines.append(line)

    # Flush remaining
    remaining = "\n".join(current_lines).strip()
    if remaining:
        if in_table:
            elements.append((ChunkType.TABLE, remaining))
        else:
            elements.append((classify_block(remaining), remaining))

    return elements


def _split_text_by_tokens(text: str, chunk_size: int, overlap: int = 0) -> list[str]:
    """Split text into token-sized chunks, breaking on sentence/line boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+|\n\n+|\n(?=[-#*|])", text)
    sentences = [s for s in sentences if s.strip()]

    chunks = []
    current = []
    current_tokens = 0

    for sent in sentences:
        sent_tokens = count_tokens(sent)
        if current_tokens + sent_tokens > chunk_size and current:
            chunks.append("\n".join(current))
            # Handle overlap: keep last few sentences
            if overlap > 0:
                overlap_parts = []
                overlap_tokens = 0
                for s in reversed(current):
                    t = count_tokens(s)
                    if overlap_tokens + t > overlap:
                        break
                    overlap_parts.insert(0, s)
                    overlap_tokens += t
                current = overlap_parts
                current_tokens = overlap_tokens
            else:
                current = []
                current_tokens = 0
        current.append(sent)
        current_tokens += sent_tokens

    if current:
        chunks.append("\n".join(current))

    return chunks


# ---------------------------------------------------------------------------
# Chunkers
# ---------------------------------------------------------------------------

class PageLevelChunker:
    name = "page_level"

    def chunk(self, markdown: str) -> list[Chunk]:
        pages = split_into_pages(markdown)
        return [
            Chunk(text=text, metadata={
                "page_num": pn,
                "chunk_type": ChunkType.MIXED,
                "strategy": self.name,
            })
            for pn, text in pages if text.strip()
        ]


class FixedSizeTokenChunker:
    def __init__(self, chunk_size: int = 512, overlap: int = 0):
        self.chunk_size = chunk_size
        self.overlap = overlap
        suffix = f"_overlap{overlap}" if overlap else ""
        self.name = f"fixed_{chunk_size}{suffix}"

    def chunk(self, markdown: str) -> list[Chunk]:
        pages = split_into_pages(markdown)
        chunks = []
        for pn, ptext in pages:
            parts = _split_text_by_tokens(ptext, self.chunk_size, self.overlap)
            for part in parts:
                chunks.append(Chunk(text=part, metadata={
                    "page_num": pn,
                    "chunk_type": ChunkType.MIXED,
                    "strategy": self.name,
                }))
        return chunks


class RecursiveChunker:
    name = "recursive"

    def __init__(self, chunk_size: int = 512,
                 separators: list[str] | None = None):
        self.chunk_size = chunk_size
        self.separators = separators or ["\n\n", "\n", ". ", " "]

    def _recursive_split(self, text: str, sep_idx: int = 0) -> list[str]:
        if count_tokens(text) <= self.chunk_size:
            return [text] if text.strip() else []

        if sep_idx >= len(self.separators):
            # Last resort: hard split by tokens
            return _split_text_by_tokens(text, self.chunk_size)

        sep = self.separators[sep_idx]
        parts = text.split(sep)
        result = []
        current = ""

        for part in parts:
            candidate = current + sep + part if current else part
            if count_tokens(candidate) <= self.chunk_size:
                current = candidate
            else:
                if current:
                    result.extend(self._recursive_split(current, sep_idx + 1)
                                  if count_tokens(current) > self.chunk_size
                                  else [current])
                current = part

        if current:
            result.extend(self._recursive_split(current, sep_idx + 1)
                          if count_tokens(current) > self.chunk_size
                          else [current])
        return result

    def chunk(self, markdown: str) -> list[Chunk]:
        pages = split_into_pages(markdown)
        chunks = []
        for pn, ptext in pages:
            parts = self._recursive_split(ptext)
            for part in parts:
                if part.strip():
                    chunks.append(Chunk(text=part.strip(), metadata={
                        "page_num": pn,
                        "chunk_type": ChunkType.MIXED,
                        "strategy": self.name,
                    }))
        return chunks


class HeadingBasedChunker:
    name = "heading_based"

    def __init__(self, max_chunk_tokens: int = 1024):
        self.max_chunk_tokens = max_chunk_tokens

    def chunk(self, markdown: str) -> list[Chunk]:
        pages = split_into_pages(markdown)
        chunks = []

        for pn, ptext in pages:
            # Split on heading lines
            sections = re.split(r"(?=^#{1,3}\s)", ptext, flags=re.MULTILINE)

            for section in sections:
                section = section.strip()
                if not section:
                    continue

                if count_tokens(section) > self.max_chunk_tokens:
                    # Sub-split large sections
                    parts = _split_text_by_tokens(section, self.max_chunk_tokens)
                    for part in parts:
                        chunks.append(Chunk(text=part, metadata={
                            "page_num": pn,
                            "chunk_type": classify_block(part),
                            "strategy": self.name,
                        }))
                else:
                    chunks.append(Chunk(text=section, metadata={
                        "page_num": pn,
                        "chunk_type": classify_block(section),
                        "strategy": self.name,
                    }))

        return chunks


class TableAwareChunker:
    name = "table_aware"

    def __init__(self, text_chunk_size: int = 512):
        self.text_chunk_size = text_chunk_size

    def chunk(self, markdown: str) -> list[Chunk]:
        pages = split_into_pages(markdown)
        chunks = []

        for pn, ptext in pages:
            elements = split_into_elements(ptext)

            for ctype, etext in elements:
                if ctype == ChunkType.TABLE:
                    # Tables are always atomic
                    chunks.append(Chunk(text=etext, metadata={
                        "page_num": pn,
                        "chunk_type": ChunkType.TABLE,
                        "strategy": self.name,
                    }))
                else:
                    # Text blocks get chunked by token size
                    if count_tokens(etext) > self.text_chunk_size:
                        parts = _split_text_by_tokens(etext, self.text_chunk_size)
                        for part in parts:
                            chunks.append(Chunk(text=part, metadata={
                                "page_num": pn,
                                "chunk_type": classify_block(part),
                                "strategy": self.name,
                            }))
                    else:
                        chunks.append(Chunk(text=etext, metadata={
                            "page_num": pn,
                            "chunk_type": ctype,
                            "strategy": self.name,
                        }))

        return chunks


class ElementTypeChunker:
    name = "element_type"

    def chunk(self, markdown: str) -> list[Chunk]:
        pages = split_into_pages(markdown)
        chunks = []

        for pn, ptext in pages:
            elements = split_into_elements(ptext)

            for ctype, etext in elements:
                if not etext.strip():
                    continue
                # Each element is its own chunk, typed
                chunks.append(Chunk(text=etext, metadata={
                    "page_num": pn,
                    "chunk_type": ctype,
                    "strategy": self.name,
                }))

        return chunks


class SemanticChunker:
    name = "semantic"

    def __init__(self, breakpoint_threshold: float = 0.3,
                 min_chunk_tokens: int = 64, max_chunk_tokens: int = 512):
        self.breakpoint_threshold = breakpoint_threshold
        self.min_chunk_tokens = min_chunk_tokens
        self.max_chunk_tokens = max_chunk_tokens
        self._model = None

    def _get_model(self):
        if self._model is None:
            from experiments.chunking.embedder import Embedder
            self._model = Embedder()
        return self._model

    def chunk(self, markdown: str) -> list[Chunk]:
        import numpy as np
        pages = split_into_pages(markdown)
        chunks = []

        for pn, ptext in pages:
            elements = split_into_elements(ptext)

            # Tables go as atomic chunks
            text_parts = []
            for ctype, etext in elements:
                if ctype == ChunkType.TABLE:
                    chunks.append(Chunk(text=etext, metadata={
                        "page_num": pn,
                        "chunk_type": ChunkType.TABLE,
                        "strategy": self.name,
                    }))
                else:
                    text_parts.append(etext)

            full_text = "\n\n".join(text_parts)
            if not full_text.strip():
                continue

            # Split into sentences
            sentences = re.split(r"(?<=[.!?])\s+|\n\n+", full_text)
            sentences = [s.strip() for s in sentences if s.strip()]

            if len(sentences) <= 1:
                chunks.append(Chunk(text=full_text.strip(), metadata={
                    "page_num": pn,
                    "chunk_type": ChunkType.TEXT,
                    "strategy": self.name,
                }))
                continue

            # Embed sentences and find breakpoints
            model = self._get_model()
            embeddings = model.embed_texts(sentences)

            # Cosine similarity between consecutive sentences
            similarities = []
            for i in range(len(embeddings) - 1):
                a = embeddings[i]
                b = embeddings[i + 1]
                sim = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10)
                similarities.append(sim)

            # Find breakpoints where similarity drops
            if similarities:
                mean_sim = np.mean(similarities)
                std_sim = np.std(similarities)
                threshold = mean_sim - self.breakpoint_threshold * std_sim
            else:
                threshold = 0.5

            # Group sentences into chunks
            current_sentences = [sentences[0]]
            for i, sent in enumerate(sentences[1:]):
                sim = similarities[i]
                current_text = " ".join(current_sentences + [sent])
                tok_count = count_tokens(current_text)

                # Break if: similarity drops below threshold AND we have enough tokens
                # OR we exceed max tokens
                if tok_count > self.max_chunk_tokens:
                    chunk_text = " ".join(current_sentences)
                    chunks.append(Chunk(text=chunk_text, metadata={
                        "page_num": pn,
                        "chunk_type": ChunkType.TEXT,
                        "strategy": self.name,
                    }))
                    current_sentences = [sent]
                elif sim < threshold and count_tokens(" ".join(current_sentences)) >= self.min_chunk_tokens:
                    chunk_text = " ".join(current_sentences)
                    chunks.append(Chunk(text=chunk_text, metadata={
                        "page_num": pn,
                        "chunk_type": ChunkType.TEXT,
                        "strategy": self.name,
                    }))
                    current_sentences = [sent]
                else:
                    current_sentences.append(sent)

            if current_sentences:
                chunk_text = " ".join(current_sentences)
                chunks.append(Chunk(text=chunk_text, metadata={
                    "page_num": pn,
                    "chunk_type": ChunkType.TEXT,
                    "strategy": self.name,
                }))

        return chunks


class StructureAwareChunker:
    """Structure-aware chunking: keeps heading hierarchy with content.

    Each chunk gets its parent heading chain prepended so it's self-contained.
    Tables are kept atomic. Text under a heading stays together up to max_tokens.
    """
    name = "structure_aware"

    def __init__(self, max_chunk_tokens: int = 1024):
        self.max_chunk_tokens = max_chunk_tokens

    def chunk(self, markdown: str) -> list[Chunk]:
        pages = split_into_pages(markdown)
        chunks = []

        for pn, ptext in pages:
            # Parse heading hierarchy
            heading_stack = []  # [(level, text), ...]
            sections = []  # [(heading_context, content, chunk_type)]

            current_content_lines = []

            for line in ptext.split("\n"):
                heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
                if heading_match:
                    # Flush current content
                    content = "\n".join(current_content_lines).strip()
                    if content:
                        ctx = " > ".join(h[1] for h in heading_stack) if heading_stack else ""
                        sections.append((ctx, content, classify_block(content)))
                    current_content_lines = []

                    # Update heading stack
                    level = len(heading_match.group(1))
                    heading_text = heading_match.group(2).strip()
                    # Pop headings at same or deeper level
                    while heading_stack and heading_stack[-1][0] >= level:
                        heading_stack.pop()
                    heading_stack.append((level, heading_text))
                else:
                    current_content_lines.append(line)

            # Flush final content
            content = "\n".join(current_content_lines).strip()
            if content:
                ctx = " > ".join(h[1] for h in heading_stack) if heading_stack else ""
                sections.append((ctx, content, classify_block(content)))

            # Build chunks from sections
            for heading_ctx, content, ctype in sections:
                if not content:
                    continue

                # Split elements within this section to keep tables atomic
                elements = split_into_elements(content)
                for etype, etext in elements:
                    if not etext.strip():
                        continue
                    if heading_ctx:
                        chunk_text = f"[{heading_ctx}]\n\n{etext}"
                    else:
                        chunk_text = etext

                    if count_tokens(chunk_text) > self.max_chunk_tokens and etype != ChunkType.TABLE:
                        parts = _split_text_by_tokens(chunk_text, self.max_chunk_tokens)
                        for part in parts:
                            chunks.append(Chunk(text=part, metadata={
                                "page_num": pn,
                                "chunk_type": etype,
                                "strategy": self.name,
                                "heading": heading_ctx,
                            }))
                    else:
                        chunks.append(Chunk(text=chunk_text, metadata={
                            "page_num": pn,
                            "chunk_type": etype,
                            "strategy": self.name,
                            "heading": heading_ctx,
                        }))

        return chunks


class ContextualChunker:
    """Wrapper that contextualizes chunks from any base chunker using an LLM.

    Prepends a short LLM-generated context to each chunk before embedding,
    following Anthropic's contextual retrieval approach.
    """

    def __init__(self, base_chunker, model: str = "gpt-4.1-mini"):
        self.base_chunker = base_chunker
        self.model = model
        self.name = f"contextual_{base_chunker.name}"
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI()
        return self._client

    def _contextualize_chunk(self, chunk_text: str, full_document: str) -> str:
        """Generate a short context for a chunk using the full document."""
        client = self._get_client()

        # Truncate document if too large (keep first + last parts)
        doc_tokens = count_tokens(full_document)
        if doc_tokens > 12000:
            # Keep first 8000 tokens worth + last 2000 tokens worth
            lines = full_document.split("\n")
            first_part = []
            tok = 0
            for line in lines:
                t = count_tokens(line)
                if tok + t > 8000:
                    break
                first_part.append(line)
                tok += t
            last_part = []
            tok = 0
            for line in reversed(lines):
                t = count_tokens(line)
                if tok + t > 2000:
                    break
                last_part.insert(0, line)
                tok += t
            full_document = "\n".join(first_part) + "\n\n[...]\n\n" + "\n".join(last_part)

        response = client.chat.completions.create(
            model=self.model,
            max_tokens=128,
            temperature=0,
            messages=[
                {"role": "user", "content": (
                    f"<document>\n{full_document}\n</document>\n\n"
                    f"Here is a chunk from this document:\n"
                    f"<chunk>\n{chunk_text}\n</chunk>\n\n"
                    f"Give a short succinct context (1-2 sentences) to situate "
                    f"this chunk within the overall document. Include the document "
                    f"subject, company name, time period, and section if apparent. "
                    f"Answer only with the context, nothing else."
                )},
            ],
        )
        return response.choices[0].message.content.strip()

    def chunk(self, markdown: str) -> list[Chunk]:
        """Chunk using base chunker, then contextualize each chunk."""
        base_chunks = self.base_chunker.chunk(markdown)
        if not base_chunks:
            return []

        print(f"    Contextualizing {len(base_chunks)} chunks via {self.model}...")
        contextualized = []
        for i, c in enumerate(base_chunks):
            try:
                context = self._contextualize_chunk(c.text, markdown)
                new_text = f"{context}\n\n{c.text}"
            except Exception as e:
                print(f"    Warning: contextualization failed for chunk {i}: {e}")
                new_text = c.text

            contextualized.append(Chunk(
                text=new_text,
                metadata={**c.metadata, "strategy": self.name, "has_context": True},
            ))

        return contextualized


class ChonkieChunker:
    """Wrapper around parsers/chunker.py to fit the eval framework.

    Uses Chonkie's RecursiveChunker for text and TableChunker for tables.
    """

    def __init__(self, chunk_size: int = 512, table_chunk_size: int = 512):
        self.chunk_size = chunk_size
        self.table_chunk_size = table_chunk_size
        self.name = f"chonkie_{chunk_size}"
        self._chunker_mod = None

    def _get_chunker(self):
        if self._chunker_mod is None:
            from parsers.chunker import chunk_markdown as _cm
            self._chunker_mod = _cm
        return self._chunker_mod

    def chunk(self, markdown: str) -> list[Chunk]:
        chunk_markdown = self._get_chunker()
        raw_chunks = chunk_markdown(
            markdown,
            chunk_size=self.chunk_size,
            table_chunk_size=self.table_chunk_size,
        )
        return [
            Chunk(text=c.text, metadata={
                "page_num": c.page_num,
                "chunk_type": ChunkType.TABLE if c.chunk_type == "table" else ChunkType.TEXT,
                "strategy": self.name,
            })
            for c in raw_chunks
        ]


def get_all_chunkers(include_contextual: bool = False, include_chonkie: bool = True) -> list:
    """Return all chunking strategies.

    Args:
        include_contextual: If True, include contextual retrieval variants
            (requires LLM API calls, slower and costs money).
        include_chonkie: If True, include Chonkie-based chunker.
    """
    chunkers = [
        PageLevelChunker(),
        FixedSizeTokenChunker(chunk_size=512, overlap=102),
        RecursiveChunker(chunk_size=512),
        HeadingBasedChunker(),
        TableAwareChunker(text_chunk_size=512),
        ElementTypeChunker(),
        SemanticChunker(),
        StructureAwareChunker(),
    ]

    if include_chonkie:
        chunkers.append(ChonkieChunker(chunk_size=512))

    if include_contextual:
        # Contextualize the best-performing base chunkers
        chunkers.extend([
            ContextualChunker(FixedSizeTokenChunker(chunk_size=512, overlap=102)),
            ContextualChunker(StructureAwareChunker()),
        ])

    return chunkers
