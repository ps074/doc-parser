#!/usr/bin/env python3
"""Unstructured.io parser - 65+ file types with table/image extraction."""
import argparse, json
from pathlib import Path
from unstructured.partition.auto import partition

def parse_document(file_path: str, strategy: str = "fast") -> tuple[list, Path]:
    """Parse document and return elements + image dir."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    img_dir = Path("output/unstructured") / file_path.stem / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    print(f"Parsing: {file_path.name} (strategy: {strategy})")

    try:
        elements = partition(
            filename=str(file_path), strategy=strategy,
            skip_infer_table_types=[], extract_images_in_pdf=True,
            extract_image_block_types=["Image", "Table"],
            extract_image_block_output_dir=str(img_dir), languages=["eng"]
        )
    except Exception as e:
        if "tesseract" in str(e).lower() and strategy in ["hi_res", "auto"]:
            print(f"Warning: Tesseract not found, falling back to 'fast' strategy")
            elements = partition(
                filename=str(file_path), strategy="fast",
                skip_infer_table_types=[], extract_images_in_pdf=True,
                extract_image_block_types=["Image", "Table"],
                extract_image_block_output_dir=str(img_dir), languages=["eng"]
            )
        else:
            raise

    print(f"Extracted {len(elements)} elements")
    return elements, img_dir.parent

def to_markdown(elements: list) -> str:
    """Convert elements to markdown."""
    lines = []
    for el in elements:
        el_type, text = type(el).__name__, getattr(el, 'text', '')
        if not text:
            continue

        if 'Title' in el_type:
            lines.append(f"# {text}\n")
        elif 'Header' in el_type or 'Heading' in el_type:
            lines.append(f"## {text}\n")
        elif 'ListItem' in el_type:
            lines.append(f"- {text}")
        elif 'Table' in el_type:
            lines.append(f"\n**[Table]**\n```\n{text}\n```\n")
        elif 'Image' in el_type:
            lines.append("\n**[Image]**\n")
        else:
            lines.append(f"{text}\n")
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Parse documents with Unstructured.io")
    parser.add_argument("input", help="Path to document file")
    parser.add_argument("--strategy", choices=["auto", "fast", "hi_res", "ocr_only"],
                       default="fast", help="Parsing strategy")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    try:
        elements, output_dir = parse_document(str(input_path), args.strategy)

        # Save markdown and JSON
        md_content = to_markdown(elements)
        json_content = json.dumps([el.to_dict() for el in elements], indent=2)

        (output_dir / f"{input_path.stem}.md").write_text(md_content)
        (output_dir / f"{input_path.stem}.json").write_text(json_content)

        print(f"Saved to: {output_dir}")
        print(f"  - {input_path.stem}.md ({len(md_content)} chars)")
        print(f"  - {input_path.stem}.json ({len(json_content)} chars)")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1

if __name__ == "__main__":
    exit(main())
