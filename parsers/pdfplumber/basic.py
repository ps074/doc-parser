#!/usr/bin/env python3
"""Basic PDFPlumber parser - just text and tables."""
import argparse
import time
from pathlib import Path

def parse_pdf(file_path: Path) -> str:
    """Parse PDF with basic pdfplumber - text and tables only."""
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("Install with: pip install pdfplumber")

    lines = []

    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            lines.append(f"## Page {page_num}\n")

            # Extract tables with single strategy (lines-based)
            tables = page.extract_tables({
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "intersection_tolerance": 5,
                "snap_tolerance": 5
            })

            # Format tables in markdown
            if tables:
                for table_num, table in enumerate(tables, 1):
                    if table and table[0]:
                        lines.append(f"\n### Table {table_num}\n")
                        header = table[0]
                        lines.append("| " + " | ".join([str(c or "").strip() for c in header]) + " |")
                        lines.append("| " + " | ".join(["---"] * len(header)) + " |")
                        for row in table[1:]:
                            if row:
                                lines.append("| " + " | ".join([str(c or "").strip() for c in row]) + " |")
                        lines.append("\n")

            # Extract text (no layout mode for faster processing)
            text = page.extract_text()
            if text:
                lines.append(f"{text}\n")

    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Parse PDFs with basic PDFPlumber")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("-o", "--output", help="Output file path")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    output_dir = Path("output/pdfplumber/basic") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else output_dir / f"{input_path.stem}.md"

    print(f"Parsing: {input_path.name} (Basic PDFPlumber)")
    start_time = time.time()
    content = parse_pdf(input_path)
    parse_time = time.time() - start_time

    output_path.write_text(content)
    print(f"Saved to: {output_path}")
    print(f"Parse time: {round(parse_time, 2)}s")
    return 0

if __name__ == "__main__":
    exit(main())
