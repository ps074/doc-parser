#!/usr/bin/env python3
"""Optimized Docling parser with feature toggles and GPU acceleration."""
import argparse
import time
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption


def parse_document(
    pdf_path: Path,
    use_ocr: bool = False,
    use_tables: bool = False,
    use_gpu: bool = False
) -> str:
    """Parse PDF with optimized Docling settings.

    Args:
        pdf_path: Path to PDF file
        use_ocr: Enable OCR (slower, needed for scanned PDFs)
        use_tables: Enable table structure extraction (slower)
        use_gpu: Enable GPU acceleration (MPS for Apple Silicon, CUDA for NVIDIA)
    """
    # Configure pipeline options
    pipeline_options = PdfPipelineOptions(
        do_ocr=use_ocr,
        do_table_structure=use_tables,
        do_code_enrichment=False,
        do_formula_enrichment=False,
        generate_page_images=False,
        generate_picture_images=False,
    )

    # Add GPU acceleration if requested
    if use_gpu:
        from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
        # Try MPS (Apple Silicon) first, fall back to CUDA
        try:
            import torch
            if torch.backends.mps.is_available():
                pipeline_options.accelerator_options = AcceleratorOptions(
                    device=AcceleratorDevice.MPS
                )
            elif torch.cuda.is_available():
                pipeline_options.accelerator_options = AcceleratorOptions(
                    device=AcceleratorDevice.CUDA
                )
            else:
                print("Warning: GPU requested but not available, using CPU")
        except ImportError:
            print("Warning: torch not available, using CPU")

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    result = converter.convert(pdf_path)
    return result.document.export_to_markdown()


def main():
    parser = argparse.ArgumentParser(
        description="Parse PDFs with optimized Docling (disable features, GPU support)"
    )
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument("--ocr", action="store_true", help="Enable OCR (slower)")
    parser.add_argument("--tables", action="store_true", help="Enable table extraction (slower)")
    parser.add_argument("--gpu", action="store_true", help="Enable GPU acceleration (MPS/CUDA)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    output_dir = Path("output/docling/optimized") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        Path(args.output) if args.output
        else output_dir / f"{input_path.stem}.md"
    )

    print(f"Parsing: {input_path.name} (Docling Optimized)")
    print(f"OCR: {args.ocr}, Tables: {args.tables}, GPU: {args.gpu}")

    start_time = time.time()
    content = parse_document(
        input_path,
        use_ocr=args.ocr,
        use_tables=args.tables,
        use_gpu=args.gpu
    )
    parse_time = time.time() - start_time

    output_path.write_text(content)
    print(f"Saved to: {output_path}")
    print(f"Parse time: {round(parse_time, 2)}s")
    return 0


if __name__ == "__main__":
    exit(main())
