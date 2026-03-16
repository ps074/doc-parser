#!/usr/bin/env python3
"""Docling vanilla parser - text and tables only, no AI/VLM."""
import argparse
import time
from pathlib import Path
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions, TableStructureOptions, TableFormerMode
)
from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import ImageRefMode


def parse_document(pdf_path: Path) -> str:
    """Parse PDF with Docling - text and tables only, no VLM or OCR."""
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

    md = doc.export_to_markdown(
        image_mode=ImageRefMode.PLACEHOLDER, image_placeholder="[IMAGE]",
        page_break_placeholder="<!-- page_break -->"
    )

    return md


def main():
    parser = argparse.ArgumentParser(description="Parse PDFs with Docling (vanilla - no AI)")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("-o", "--output", help="Output file path")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    output_dir = Path("output/docling/vanilla") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else output_dir / f"{input_path.stem}.md"

    print(f"Parsing: {input_path.name} (Docling vanilla - no AI)")
    start_time = time.time()
    content = parse_document(input_path)
    parse_time = time.time() - start_time

    perf_header = f"""# Docling (Vanilla) Performance

**Document:** {input_path.name}
**Mode:** Text + tables only (no VLM, no OCR)
**Total Parse Time:** {round(parse_time, 2)}s
**Output Size:** {len(content)} chars

---

"""
    content = perf_header + content

    output_path.write_text(content)
    print(f"Saved to: {output_path}")
    print(f"Parse time: {round(parse_time, 2)}s")
    return 0


if __name__ == "__main__":
    exit(main())
