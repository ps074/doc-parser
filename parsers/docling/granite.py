#!/usr/bin/env python3
"""Docling + Granite Vision parser."""
import argparse
import time
from pathlib import Path
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions, granite_picture_description,
    TableStructureOptions, TableFormerMode
)
from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import ImageRefMode

def parse_document(pdf_path: Path) -> str:
    """Parse PDF with Granite Vision image descriptions."""
    options = PdfPipelineOptions(
        do_ocr=False, do_table_structure=True,
        generate_picture_images=True, do_picture_description=True,
        table_structure_options=TableStructureOptions(mode=TableFormerMode.ACCURATE),
        picture_description_options=granite_picture_description
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

    if hasattr(doc, 'pictures') and doc.pictures:
        md += "\n\n---\n\n## Image Descriptions (VLM)\n\n"
        for i, pic in enumerate(doc.pictures, 1):
            if hasattr(pic, 'meta') and pic.meta and hasattr(pic.meta, 'description'):
                desc = pic.meta.description
                if desc and desc.text:
                    md += f"### Image {i}\n**Model:** {desc.created_by}\n\n"
                    md += f"<image_description>\n{desc.text}\n</image_description>\n\n"

    return md

def main():
    parser = argparse.ArgumentParser(description="Parse PDFs with Docling + Granite Vision")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("-o", "--output", help="Output file path")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    output_dir = Path("output/docling/granite") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else output_dir / f"{input_path.stem}.md"

    print(f"Parsing: {input_path.name} (VLM: Granite-3.3-2B)")
    start_time = time.time()
    content = parse_document(input_path)
    parse_time = time.time() - start_time

    image_count = content.count("### Image ")
    avg_time = round(parse_time / image_count, 2) if image_count > 0 else 0

    perf_header = f"""# Docling + Granite Performance

**Document:** {input_path.name}
**VLM Backend:** Granite-3.3-2B
**Total Parse Time:** {round(parse_time, 2)}s
**Images Processed:** {image_count}
**Avg Time/Image:** {avg_time}s
**Output Size:** {len(content)} chars

---

"""
    content = perf_header + content

    output_path.write_text(content)
    print(f"Saved to: {output_path}")
    print(f"Parse time: {round(parse_time, 2)}s ({image_count} images, {avg_time}s/image)")
    return 0

if __name__ == "__main__":
    exit(main())
