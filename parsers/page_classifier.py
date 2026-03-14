#!/usr/bin/env python3
"""
Classify PDF pages by complexity to route to the right model.
Uses only PyMuPDF metadata — no LLM calls, runs in <1s.

Complexity levels (maps to model routing):
  - SKIP:     Blank/empty page, no processing needed
  - SIMPLE:   Text-only, maybe small icons → pypdfium2 (no LLM)
  - MODERATE: Tables OR simple images (logos, decorative) → Haiku
  - COMPLEX:  Charts, graphs, infographics → Sonnet
  - CRITICAL: Dense data tables + charts, scanned, financial data → Opus
"""
import argparse
import json
import re
import time
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path

import pymupdf as fitz


class Complexity(str, Enum):
    SKIP = "skip"
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    CRITICAL = "critical"


MODEL_ROUTING = {
    Complexity.SKIP: None,
    Complexity.SIMPLE: None,  # pypdfium2, no LLM needed
    Complexity.MODERATE: "gpt-4.1-mini",        # GPT-4.1 mini for moderate pages
    Complexity.COMPLEX: "claude-sonnet-4-20250514",  # Sonnet for complex (charts+tables)
    Complexity.CRITICAL: "claude-sonnet-4-20250514", # Sonnet for critical (max accuracy)
}


@dataclass
class PageSignals:
    """Raw signals extracted from a page via PyMuPDF."""
    text_chars: int = 0
    word_count: int = 0
    number_density: float = 0.0       # ratio of numeric tokens to total words
    font_count: int = 0               # number of distinct fonts
    font_size_range: float = 0.0      # max - min font size (layout complexity)
    significant_images: int = 0       # images > 100x100
    small_images: int = 0             # images <= 100x100 (icons, bullets)
    total_image_area_ratio: float = 0.0  # image area / page area
    drawing_count: int = 0            # vector drawing operations
    h_lines: int = 0                  # horizontal ruled lines
    v_lines: int = 0                  # vertical ruled lines
    rect_count: int = 0              # rectangles (filled regions, bars in charts)
    curve_count: int = 0             # curves (line charts, pie charts)
    color_count: int = 0             # distinct colors in drawings
    text_density: float = 0.0        # chars / page area
    # Cross-page table detection signals
    v_line_x_positions: list[float] = field(default_factory=list)  # x-coords of vertical lines
    table_starts_at_top: bool = False   # table lines in top 15% of page
    table_ends_at_bottom: bool = False  # table lines in bottom 15% of page
    first_text_is_heading: bool = False # page starts with a heading (section break)
    has_table: bool = False


@dataclass
class PageClassification:
    page_num: int
    complexity: Complexity
    model: str | None
    needs_vision: bool
    signals: PageSignals
    group_id: int | None = None  # pages in the same group are sent together to the LLM
    reasons: list[str] = field(default_factory=list)


@dataclass
class PageGroup:
    """A group of consecutive pages that should be processed together."""
    group_id: int
    pages: list[int]           # page numbers
    complexity: Complexity     # highest complexity in group
    model: str | None
    reason: str                # why these pages are grouped


def extract_signals(page: fitz.Page) -> PageSignals:
    """Extract all classification signals from a page using PyMuPDF."""
    signals = PageSignals()

    # --- Text signals ---
    text = page.get_text("text")
    signals.text_chars = len(text.strip())
    words = text.split()
    signals.word_count = len(words)

    # Number density: what fraction of words are numeric-heavy
    if words:
        numeric_words = sum(1 for w in words if re.search(r'\d', w))
        signals.number_density = numeric_words / len(words)

    # --- Font analysis (via dict extraction) ---
    fonts_seen = set()
    font_sizes = []
    try:
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block["type"] == 0:  # text block
                for line in block["lines"]:
                    for span in line["spans"]:
                        fonts_seen.add(span["font"])
                        font_sizes.append(span["size"])
    except Exception:
        pass

    signals.font_count = len(fonts_seen)
    if font_sizes:
        signals.font_size_range = max(font_sizes) - min(font_sizes)

    # --- Image signals ---
    rect = page.rect
    page_area = rect.width * rect.height
    images = page.get_images(full=True)
    total_image_area = 0

    for img in images:
        xref = img[0]
        try:
            img_info = page.parent.extract_image(xref)
            if img_info:
                w, h = img_info.get("width", 0), img_info.get("height", 0)
                if w > 100 and h > 100:
                    signals.significant_images += 1
                    total_image_area += w * h
                else:
                    signals.small_images += 1
        except Exception:
            signals.significant_images += 1

    signals.total_image_area_ratio = (total_image_area / page_area) if page_area > 0 else 0

    # --- Vector graphics signals ---
    drawings = page.get_drawings()
    signals.drawing_count = len(drawings)
    colors_seen = set()

    for d in drawings:
        color = d.get("color")
        fill = d.get("fill")
        if color:
            colors_seen.add(tuple(color) if isinstance(color, (list, tuple)) else color)
        if fill:
            colors_seen.add(tuple(fill) if isinstance(fill, (list, tuple)) else fill)

        for item in d.get("items", []):
            op = item[0]
            if op == "l":  # line
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) < 2:
                    signals.h_lines += 1
                elif abs(p1.x - p2.x) < 2:
                    signals.v_lines += 1
            elif op == "re":  # rectangle
                signals.rect_count += 1
            elif op == "c":  # curve (bezier)
                signals.curve_count += 1

    signals.color_count = len(colors_seen)
    signals.text_density = signals.text_chars / page_area if page_area > 0 else 0

    # --- Cross-page table signals ---
    # Collect x-positions of vertical lines (for column matching across pages)
    v_line_xs = set()
    page_height = rect.height
    table_y_positions = []

    for d in drawings:
        for item in d.get("items", []):
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.x - p2.x) < 2:  # vertical line
                    v_line_xs.add(round(p1.x, 0))
                    table_y_positions.extend([p1.y, p2.y])
                if abs(p1.y - p2.y) < 2:  # horizontal line
                    table_y_positions.extend([p1.y, p2.y])

    signals.v_line_x_positions = sorted(v_line_xs)
    signals.has_table = signals.h_lines >= 3 and signals.v_lines >= 2

    if table_y_positions and page_height > 0:
        min_y = min(table_y_positions)
        max_y = max(table_y_positions)
        signals.table_starts_at_top = min_y < page_height * 0.15
        signals.table_ends_at_bottom = max_y > page_height * 0.85

    # Check if page starts with a heading (indicates section break, not continuation)
    try:
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block["type"] == 0:
                for line in block["lines"]:
                    for span in line["spans"]:
                        if span["size"] > 14 or "Bold" in span["font"]:
                            signals.first_text_is_heading = True
                        break
                    break
                break
    except Exception:
        pass

    return signals


def classify_page(page: fitz.Page, page_num: int) -> PageClassification:
    """Classify a page into complexity level based on extracted signals."""
    signals = extract_signals(page)
    reasons = []

    # --- Score-based classification ---
    # Each signal contributes to a complexity score
    score = 0

    # BLANK PAGE
    if signals.text_chars < 20 and signals.significant_images == 0 and signals.drawing_count < 5:
        return PageClassification(
            page_num=page_num,
            complexity=Complexity.SKIP,
            model=MODEL_ROUTING[Complexity.SKIP],
            needs_vision=False,
            signals=signals,
            reasons=["blank or near-empty page"],
        )

    # SCANNED PAGE (image-only, no text layer)
    if signals.text_chars < 50 and (signals.significant_images > 0 or signals.drawing_count > 50):
        return PageClassification(
            page_num=page_num,
            complexity=Complexity.CRITICAL,
            model=MODEL_ROUTING[Complexity.CRITICAL],
            needs_vision=True,
            signals=signals,
            reasons=["scanned/image-only page, no text layer"],
        )

    # --- Chart detection ---
    # Charts have: many vector paths, curves, multiple colors, rectangles (bars)
    has_chart = False

    # Bar charts: many colored rectangles
    if signals.rect_count > 10 and signals.color_count > 3:
        score += 30
        has_chart = True
        reasons.append(f"likely bar/area chart ({signals.rect_count} rects, {signals.color_count} colors)")

    # Line/pie charts: curves + colors
    if signals.curve_count > 10 and signals.color_count > 2:
        score += 30
        has_chart = True
        reasons.append(f"likely line/pie chart ({signals.curve_count} curves, {signals.color_count} colors)")

    # General vector-heavy (infographics, diagrams)
    if signals.drawing_count > 50 and signals.color_count > 4:
        score += 20
        has_chart = True
        reasons.append(f"vector-heavy graphics ({signals.drawing_count} drawings, {signals.color_count} colors)")

    # --- Table detection ---
    has_table = False
    if signals.h_lines >= 3 and signals.v_lines >= 2:
        has_table = True
        score += 15
        reasons.append(f"table detected ({signals.h_lines}h x {signals.v_lines}v lines)")

    # --- Data density ---
    # Pages with lots of numbers are higher value (financial data)
    if signals.number_density > 0.3:
        score += 20
        reasons.append(f"high number density ({signals.number_density:.0%} numeric)")
    elif signals.number_density > 0.15:
        score += 10
        reasons.append(f"moderate number density ({signals.number_density:.0%} numeric)")

    # --- Image complexity ---
    if signals.significant_images > 0:
        if signals.total_image_area_ratio > 0.4:
            score += 25
            reasons.append(f"large images ({signals.total_image_area_ratio:.0%} of page)")
        else:
            score += 10
            reasons.append(f"images present ({signals.significant_images} significant)")

    # Small decorative images only (logos, icons)
    if signals.small_images > 0 and signals.significant_images == 0:
        score += 5
        reasons.append(f"decorative images only ({signals.small_images} small)")

    # --- Layout complexity ---
    if signals.font_count > 6:
        score += 10
        reasons.append(f"complex layout ({signals.font_count} fonts)")
    if signals.font_size_range > 15:
        score += 5
        reasons.append(f"varied typography ({signals.font_size_range:.0f}pt range)")

    # --- Combined signals (multiplicative) ---
    # Chart + numbers = financial chart (critical)
    if has_chart and signals.number_density > 0.15:
        score += 15
        reasons.append("chart with numeric data (financial visualization)")

    # Table + high number density = financial table (critical)
    if has_table and signals.number_density > 0.25:
        score += 15
        reasons.append("data-dense table (likely financial)")

    # --- Map score to complexity ---
    if score >= 50:
        complexity = Complexity.CRITICAL
    elif score >= 25:
        complexity = Complexity.COMPLEX
    elif score >= 10:
        complexity = Complexity.MODERATE
    else:
        complexity = Complexity.SIMPLE
        if not reasons:
            reasons.append("text-only page")

    needs_vision = complexity in (Complexity.MODERATE, Complexity.COMPLEX, Complexity.CRITICAL)

    return PageClassification(
        page_num=page_num,
        complexity=complexity,
        model=MODEL_ROUTING[complexity],
        needs_vision=needs_vision,
        signals=signals,
        reasons=reasons,
    )


def _columns_match(xs_a: list[float], xs_b: list[float], tolerance: float = 5.0) -> bool:
    """Check if two pages have matching vertical line x-positions (same table columns)."""
    if not xs_a or not xs_b:
        return False
    # Count how many x-positions from page A have a match in page B
    matches = 0
    for xa in xs_a:
        for xb in xs_b:
            if abs(xa - xb) < tolerance:
                matches += 1
                break
    # If >60% of columns match, it's likely the same table
    min_cols = min(len(xs_a), len(xs_b))
    return min_cols > 0 and (matches / min_cols) >= 0.6


def group_pages(classifications: list[PageClassification]) -> list[PageGroup]:
    """
    Detect cross-page tables and group consecutive pages that should be
    processed together by the same LLM call.

    Detection signals:
      1. Page N has table ending at bottom + Page N+1 has table starting at top
      2. Matching vertical line x-positions (same column structure)
      3. Page N+1 does NOT start with a heading (no section break)
    """
    if not classifications:
        return []

    groups: list[PageGroup] = []
    current_group_pages = [classifications[0].page_num]
    group_id = 0

    for i in range(1, len(classifications)):
        prev = classifications[i - 1]
        curr = classifications[i]

        is_continuation = False

        # Both pages have tables
        if prev.signals.has_table and curr.signals.has_table:
            # Signal 1: table spans the page boundary
            table_spans_boundary = (
                prev.signals.table_ends_at_bottom and curr.signals.table_starts_at_top
            )

            # Signal 2: matching column positions
            cols_match = _columns_match(
                prev.signals.v_line_x_positions,
                curr.signals.v_line_x_positions,
            )

            # Signal 3: no section break (no heading at top of next page)
            no_section_break = not curr.signals.first_text_is_heading

            # Need at least 2 of 3 signals to group
            confidence = sum([table_spans_boundary, cols_match, no_section_break])
            if confidence >= 2:
                is_continuation = True

        if is_continuation:
            current_group_pages.append(curr.page_num)
        else:
            # Finalize current group
            if len(current_group_pages) > 1:
                group_pages_list = [c for c in classifications if c.page_num in current_group_pages]
                highest = max(group_pages_list, key=lambda p: list(Complexity).index(p.complexity))
                group = PageGroup(
                    group_id=group_id,
                    pages=current_group_pages[:],
                    complexity=highest.complexity,
                    model=MODEL_ROUTING[highest.complexity],
                    reason=f"cross-page table spanning pages {current_group_pages[0]}-{current_group_pages[-1]}",
                )
                groups.append(group)
                for c in group_pages_list:
                    c.group_id = group_id
                group_id += 1

            current_group_pages = [curr.page_num]

    # Finalize last group
    if len(current_group_pages) > 1:
        group_pages_list = [c for c in classifications if c.page_num in current_group_pages]
        highest = max(group_pages_list, key=lambda p: list(Complexity).index(p.complexity))
        group = PageGroup(
            group_id=group_id,
            pages=current_group_pages[:],
            complexity=highest.complexity,
            model=MODEL_ROUTING[highest.complexity],
            reason=f"cross-page table spanning pages {current_group_pages[0]}-{current_group_pages[-1]}",
        )
        groups.append(group)
        for c in group_pages_list:
            c.group_id = group_id

    return groups


def classify_document(pdf_path: Path) -> tuple[list[PageClassification], list[PageGroup]]:
    """Classify all pages in a PDF and detect cross-page groups."""
    doc = fitz.open(pdf_path)
    results = []
    for i, page in enumerate(doc, 1):
        results.append(classify_page(page, i))
    doc.close()

    groups = group_pages(results)
    return results, groups


def print_summary(classifications: list[PageClassification], groups: list[PageGroup], pdf_name: str):
    """Print classification summary with model routing and page groups."""
    total = len(classifications)

    by_complexity = {}
    for c in Complexity:
        by_complexity[c] = [p for p in classifications if p.complexity == c]

    print(f"\nDocument: {pdf_name}")
    print(f"Total pages: {total}")
    print("=" * 90)

    # Summary table
    print(f"\n{'Complexity':<12} {'Model':<35} {'Count':>6} {'Pages'}")
    print("-" * 90)
    for c in Complexity:
        pages = by_complexity[c]
        model = MODEL_ROUTING[c] or "(no LLM - fast parse)"
        print(f"{c.value:<12} {model:<35} {len(pages):>6}   {_page_list(pages)}")

    # Cost estimate
    vision_pages = [p for p in classifications if p.needs_vision]
    haiku_pages = [p for p in classifications if p.complexity == Complexity.MODERATE]
    sonnet_pages = [p for p in classifications if p.complexity == Complexity.COMPLEX]
    opus_pages = [p for p in classifications if p.complexity == Complexity.CRITICAL]
    free_pages = total - len(vision_pages)

    print(f"\nProcessing Summary:")
    print("-" * 50)
    print(f"  Free (fast parse):    {free_pages:>4} pages")
    print(f"  Haiku (moderate):     {len(haiku_pages):>4} pages  ~${len(haiku_pages) * 0.003:.2f}")
    print(f"  Sonnet (complex):     {len(sonnet_pages):>4} pages  ~${len(sonnet_pages) * 0.04:.2f}")
    print(f"  Opus (critical):      {len(opus_pages):>4} pages  ~${len(opus_pages) * 0.20:.2f}")
    total_cost = len(haiku_pages) * 0.003 + len(sonnet_pages) * 0.04 + len(opus_pages) * 0.20
    print(f"  Estimated total cost: ~${total_cost:.2f}")

    # Cross-page groups
    if groups:
        print(f"\nCross-Page Table Groups ({len(groups)} detected):")
        print("-" * 90)
        for g in groups:
            model_short = {
                Complexity.MODERATE: "Haiku",
                Complexity.COMPLEX: "Sonnet",
                Complexity.CRITICAL: "Opus",
            }.get(g.complexity, "free")
            print(f"  Group {g.group_id}: pages {g.pages} → {model_short} ({g.reason})")
        print(f"\n  These page groups will be rendered as MULTI-PAGE IMAGES and sent")
        print(f"  together in a single LLM call to preserve table context.")
    else:
        print(f"\nNo cross-page tables detected.")

    # Detailed page breakdown (non-simple pages only)
    interesting = [p for p in classifications if p.complexity not in (Complexity.SKIP, Complexity.SIMPLE)]
    if interesting:
        print(f"\nPage Details (non-trivial pages):")
        print("-" * 90)
        print(f"{'Page':>5} {'Level':<10} {'Group':<7} {'Model':<15} {'Reasons'}")
        print("-" * 90)
        for p in interesting:
            model_short = {
                Complexity.MODERATE: "Haiku",
                Complexity.COMPLEX: "Sonnet",
                Complexity.CRITICAL: "Opus",
            }.get(p.complexity, "-")
            grp = str(p.group_id) if p.group_id is not None else "-"
            print(f"{p.page_num:>5} {p.complexity.value:<10} {grp:<7} {model_short:<15} {'; '.join(p.reasons)}")


def _page_list(pages: list[PageClassification]) -> str:
    """Format page numbers as compact ranges."""
    if not pages:
        return "-"
    nums = [p.page_num for p in pages]
    if len(nums) > 20:
        return f"{nums[0]}, {nums[1]}, {nums[2]}, ... {nums[-1]} ({len(nums)} total)"
    return ", ".join(str(n) for n in nums)


def main():
    parser = argparse.ArgumentParser(description="Classify PDF pages for model routing")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    start = time.time()
    classifications, groups = classify_document(input_path)
    elapsed = time.time() - start

    if args.json:
        output = {
            "pages": [asdict(c) for c in classifications],
            "groups": [asdict(g) for g in groups],
        }
        print(json.dumps(output, indent=2))
    else:
        print_summary(classifications, groups, input_path.name)
        print(f"\nClassification time: {elapsed:.2f}s")

    return 0


if __name__ == "__main__":
    exit(main())
