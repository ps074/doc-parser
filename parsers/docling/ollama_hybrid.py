#!/usr/bin/env python3
"""Docling + Ollama (hybrid - parallel VLM processing) parser."""
import argparse
import time
import base64
import re
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Tuple
from io import BytesIO

from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableStructureOptions,
    TableFormerMode
)
from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import ImageRefMode

# Configuration
OLLAMA_URL = "http://localhost:11434"
VLM_MODEL = "qwen3-vl:2b"
VLM_PROMPT = """You are a senior financial analyst. Analyze this image from a financial document.

Provide ONLY your final analysis in this format:

**Image Content:**
[What you see - charts, tables, logos, text, etc.]

**Financial Implications:**
[What this means for financial statements, risks, opportunities]

IMPORTANT: Start immediately with the analysis. NO "Let me think", "First", "Got it", "Wait", or reasoning steps.
"""
MAX_TOKENS = 2048
TIMEOUT = 600


def clean_reasoning_artifacts(text: str) -> str:
    """Remove common reasoning artifacts from VLM output."""
    # Remove common reasoning prefixes at start of lines
    patterns = [
        r'^(Got it,? |Let me |Wait,? |Okay,? |First,? |So,? |Now,? |Alright,? )',
        r'^(I need to |I should |I can see |I\'ll |Let\'s )',
    ]

    for pattern in patterns:
        text = re.sub(pattern, '', text, flags=re.MULTILINE | re.IGNORECASE)

    # Remove incomplete trailing sentences (common with cut-offs)
    lines = text.split('\n')
    if lines and len(lines[-1].strip()) < 50 and not lines[-1].strip().endswith(('.', '!', '?', ':', '%', ')')):
        # Last line is short and doesn't end with punctuation - likely cut off
        lines = lines[:-1]

    return '\n'.join(lines).strip()


def call_ollama_vlm(image_data: bytes, image_index: int) -> Tuple[int, str]:
    """Call Ollama VLM API for a single image. Returns (index, description)."""
    try:
        # Convert image bytes to base64
        base64_image = base64.b64encode(image_data).decode('utf-8')

        # Prepare API request (using OpenAI-compatible chat completions API)
        payload = {
            "model": VLM_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VLM_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                        }
                    ]
                }
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": 0.1,  # Lower temperature for more focused output
            "seed": 42
        }

        # Call Ollama OpenAI-compatible API
        response = requests.post(
            f"{OLLAMA_URL}/v1/chat/completions",
            json=payload,
            timeout=TIMEOUT
        )
        response.raise_for_status()

        # Extract description from chat completions response
        response_data = response.json()
        message = response_data["choices"][0]["message"]

        # Qwen3-VL may put response in 'reasoning' field instead of 'content'
        description = message.get("content", "").strip()
        if not description and "reasoning" in message:
            description = message["reasoning"].strip()

        if not description:
            print(f"  ⚠ Warning: Empty description for image {image_index}")
            description = "[No description generated]"
        else:
            # Post-process to remove reasoning artifacts
            description = clean_reasoning_artifacts(description)

        return (image_index, description)

    except Exception as e:
        print(f"  ✗ Error processing image {image_index}: {e}")
        return (image_index, f"[Error: {str(e)}]")


def parse_document(pdf_path: Path) -> Tuple[str, float, float, int, float]:
    """Parse PDF with hybrid approach: fast text/tables + parallel VLM.

    Returns:
        (content, parse_time, vlm_time, image_count, sequential_estimate)
    """

    # STEP 1: Fast parsing WITHOUT VLM
    print("Step 1: Parsing text and tables (no VLM)...")
    step1_start = time.time()

    options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        generate_picture_images=True,   # Extract images
        do_picture_description=False,   # NO VLM during parsing
        table_structure_options=TableStructureOptions(mode=TableFormerMode.ACCURATE)
    )

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    result = converter.convert(pdf_path)
    doc = result.document

    step1_time = time.time() - step1_start
    print(f"  ✓ Text/tables parsed in {round(step1_time, 2)}s")

    # STEP 2: Extract images
    print("Step 2: Extracting images...")
    images = []
    if hasattr(doc, 'pictures') and doc.pictures:
        for pic in doc.pictures:
            if hasattr(pic, 'get_image'):
                img_pil = pic.get_image(doc)
                if img_pil:
                    # Convert PIL image to JPEG bytes
                    img_bytes = BytesIO()
                    # Convert to RGB if needed (JPEG doesn't support transparency)
                    if img_pil.mode in ('RGBA', 'LA', 'P'):
                        img_pil = img_pil.convert('RGB')
                    img_pil.save(img_bytes, format='JPEG', quality=95)
                    images.append(img_bytes.getvalue())

    print(f"  ✓ Extracted {len(images)} images")

    # STEP 3: Process images in PARALLEL
    descriptions = {}
    step3_time = 0
    if images:
        print(f"Step 3: Processing {len(images)} images in parallel with Ollama VLM...")
        step3_start = time.time()

        with ThreadPoolExecutor(max_workers=min(len(images), 8)) as executor:
            futures = {
                executor.submit(call_ollama_vlm, img_data, idx): idx
                for idx, img_data in enumerate(images, 1)
            }

            for future in as_completed(futures):
                idx, desc = future.result()
                descriptions[idx] = desc
                print(f"  ✓ Image {idx}/{len(images)} completed")

        step3_time = time.time() - step3_start
        print(f"  ✓ All images processed in {round(step3_time, 2)}s (parallel)")

    # STEP 4: Export markdown and combine
    print("Step 4: Combining results...")
    md = doc.export_to_markdown(
        image_mode=ImageRefMode.PLACEHOLDER,
        image_placeholder="[IMAGE]",
        page_break_placeholder="<!-- page_break -->"
    )

    # Replace [IMAGE] placeholders with VLM descriptions in-place
    if descriptions:
        result_md = md
        for idx in sorted(descriptions.keys()):
            # Replace first occurrence of [IMAGE] with the description
            result_md = result_md.replace(
                '[IMAGE]',
                f'<image_description>\n{descriptions[idx]}\n</image_description>',
                1  # Replace only first occurrence
            )
        md = result_md

    # Estimate sequential time (avg 85s per image based on ollama-verbose benchmarks)
    sequential_estimate = step1_time + (len(images) * 85.0) if images else step1_time

    return md, step1_time, step3_time, len(images), sequential_estimate


def main():
    parser = argparse.ArgumentParser(description="Parse PDFs with Docling + Ollama (hybrid parallel)")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("-o", "--output", help="Output file path")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    output_dir = Path("output/docling/ollama-hybrid") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else output_dir / f"{input_path.stem}.md"

    print(f"\nParsing: {input_path.name}")
    print(f"VLM Backend: Ollama {VLM_MODEL} (parallel processing)")
    print(f"Prompt: {VLM_PROMPT[:50]}...")
    print("-" * 80)

    total_start = time.time()
    content, parse_time, vlm_time, image_count, sequential_estimate = parse_document(input_path)
    total_time = time.time() - total_start

    avg_time = round(vlm_time / image_count, 2) if image_count > 0 else 0
    speedup = round(sequential_estimate / total_time, 1) if total_time > 0 else 1.0

    perf_header = f"""# Docling + Ollama (Hybrid Parallel) Performance

**Document:** {input_path.name}
**VLM Backend:** Ollama {VLM_MODEL} (parallel processing)
**Prompt:** Enhanced financial analyst (anti-reasoning)
**Max Tokens:** {MAX_TOKENS}
**Text/Table Parse Time:** {round(parse_time, 2)}s
**VLM Processing Time:** {round(vlm_time, 2)}s (parallel)
**Total Parse Time:** {round(total_time, 2)}s
**Est. Sequential Time:** {round(sequential_estimate, 2)}s
**Images Processed:** {image_count}
**Avg Time/Image:** {avg_time}s
**Speedup:** {speedup}x vs sequential
**Output Size:** {len(content)} chars

---

"""
    content = perf_header + content

    output_path.write_text(content)
    print("-" * 80)
    print(f"\n✓ Saved to: {output_path}")
    print(f"✓ Total time: {round(total_time, 2)}s")
    print(f"  - Text/tables: {round(parse_time, 2)}s")
    print(f"  - VLM (parallel): {round(vlm_time, 2)}s for {image_count} images")
    print(f"  - Estimated sequential: {round(sequential_estimate, 2)}s")
    print(f"  - Speedup: {speedup}x")
    return 0


if __name__ == "__main__":
    exit(main())
