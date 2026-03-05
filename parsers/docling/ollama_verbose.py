#!/usr/bin/env python3
"""Docling + Ollama (verbose financial analyst prompt) parser."""
import argparse
import time
from pathlib import Path
from typing import Any
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions, PictureDescriptionApiOptions,
    TableStructureOptions, TableFormerMode
)
from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import ImageRefMode

OLLAMA_URL = "http://localhost:11434"
PICTURE_OPTIONS = PictureDescriptionApiOptions(
    url=f"{OLLAMA_URL}/v1/chat/completions",
    params=dict[str, Any](model="qwen3-vl:2b", seed=42, max_completion_tokens=512),
    prompt="Act as a senior financial analyst. Explain what you see in the image and what it means for the financial statements.",
    timeout=600
)

def parse_document(pdf_path: Path) -> str:
    """Parse PDF with Ollama (verbose prompt) image descriptions."""
    options = PdfPipelineOptions(
        enable_remote_services=True,
        do_ocr=False, do_table_structure=True,
        generate_picture_images=True, do_picture_description=True,
        table_structure_options=TableStructureOptions(mode=TableFormerMode.ACCURATE),
        picture_description_options=PICTURE_OPTIONS
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
    parser = argparse.ArgumentParser(description="Parse PDFs with Docling + Ollama (verbose)")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("-o", "--output", help="Output file path")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    output_dir = Path("output/docling/ollama-verbose") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else output_dir / f"{input_path.stem}.md"

    print(f"Parsing: {input_path.name} (VLM: Ollama qwen3-vl:2b - verbose prompt)")
    start_time = time.time()
    content = parse_document(input_path)
    parse_time = time.time() - start_time

    image_count = content.count("### Image ")
    avg_time = round(parse_time / image_count, 2) if image_count > 0 else 0

    perf_header = f"""# Docling + Ollama (Verbose) Performance

**Document:** {input_path.name}
**VLM Backend:** Ollama qwen3-vl:2b
**Prompt:** Verbose ("Act as a senior financial analyst...")
**Max Tokens:** 512
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
