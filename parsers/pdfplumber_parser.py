#!/usr/bin/env python3
"""pdfplumber parser - high-accuracy PDF text and table extraction."""
import argparse, json
from pathlib import Path

def parse_pdf(file_path: str, extract_tables=True, extract_images=True,
              extract_layout=True, save_images=True) -> tuple[dict, Path]:
    """Parse PDF with pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("Install with: pip install pdfplumber")

    file_path = Path(file_path)
    if not file_path.exists() or file_path.suffix.lower() != '.pdf':
        raise ValueError(f"Invalid PDF: {file_path}")

    output_dir = Path("output/pdfplumber") / file_path.stem
    img_dir = output_dir / "images" if save_images else None
    if img_dir:
        img_dir.mkdir(parents=True, exist_ok=True)

    print(f"Parsing: {file_path.name}")

    # Table extraction strategies
    table_strategies = [
        {"vertical_strategy": "lines", "horizontal_strategy": "lines",
         "intersection_tolerance": 5, "snap_tolerance": 5},
        {"vertical_strategy": "text", "horizontal_strategy": "text",
         "min_words_vertical": 3, "text_tolerance": 3}
    ]

    with pdfplumber.open(file_path) as pdf:
        print(f"Pages: {len(pdf.pages)}")
        data = {'metadata': pdf.metadata, 'pages': []}

        for page_num, page in enumerate(pdf.pages, 1):
            page_data = {
                'page_number': page_num, 'width': page.width, 'height': page.height,
                'text': page.extract_text(layout=extract_layout) or "",
                'tables': [], 'images': [], 'layout_elements': {}
            }

            # Extract tables (try both strategies)
            if extract_tables:
                for strategy in table_strategies:
                    page_data['tables'] = page.extract_tables(strategy)
                    if page_data['tables']:
                        print(f"  Page {page_num}: {len(page_data['tables'])} tables")
                        break

            # Extract images
            if extract_images and page.images:
                for img_idx, img in enumerate(page.images, 1):
                    img_data = {
                        'x0': img['x0'], 'y0': img['y0'], 'x1': img['x1'], 'y1': img['y1'],
                        'width': img['width'], 'height': img['height'],
                        'name': img.get('name', f'img_{page_num}_{img_idx}')
                    }

                    if save_images and img_dir:
                        try:
                            bbox = (img['x0'], img['y0'], img['x1'], img['y1'])
                            im = page.within_bbox(bbox).to_image()
                            img_path = img_dir / f"page{page_num}_img{img_idx}.png"
                            im.save(str(img_path))
                            img_data['saved_path'] = str(img_path)
                        except Exception as e:
                            print(f"  Warning: Could not save image {img_idx}: {e}")

                    page_data['images'].append(img_data)
                if page_data['images']:
                    print(f"  Page {page_num}: {len(page_data['images'])} images")

            # Extract layout information
            if extract_layout:
                try:
                    words = page.extract_words(
                        x_tolerance=3, y_tolerance=3, use_text_flow=True,
                        extra_attrs=["fontname", "size"]
                    )
                    page_data['layout_elements'] = {
                        'word_count': len(words) if words else 0,
                        'lines': len(page.lines) if page.lines else 0,
                        'rects': len(page.rects) if page.rects else 0
                    }
                except Exception as e:
                    print(f"  Warning: Layout extraction failed: {e}")

            data['pages'].append(page_data)

    return data, output_dir

def to_markdown(data: dict) -> str:
    """Convert parsed data to markdown."""
    lines = []

    # Metadata
    if metadata := data.get('metadata', {}):
        lines.append("# Document Metadata\n")
        lines.extend([f"- **{k}**: {v}" for k, v in metadata.items() if v])
        lines.append("\n---\n")

    # Pages
    for page in data['pages']:
        page_num = page['page_number']
        lines.append(f"## Page {page_num} ({page['width']:.0f}x{page['height']:.0f})\n")

        # Layout summary
        if layout := page.get('layout_elements'):
            lines.append(
                f"**Layout:** {layout.get('word_count', 0)} words, "
                f"{layout.get('lines', 0)} lines, {layout.get('rects', 0)} rects\n"
            )

        # Tables
        for table_num, table in enumerate(page.get('tables', []), 1):
            if table and table[0]:
                lines.append(f"\n### Table {table_num}\n")
                header = table[0]
                lines.append("| " + " | ".join([str(c or "").strip() for c in header]) + " |")
                lines.append("| " + " | ".join(["---"] * len(header)) + " |")
                for row in table[1:]:
                    if row:
                        lines.append("| " + " | ".join([str(c or "").strip() for c in row]) + " |")
                lines.append("\n")

        # Text
        if page['text']:
            lines.append(f"{page['text']}\n")

        # Images
        if images := page.get('images'):
            lines.append(f"\n**Images:** {len(images)} found")
            for img in images:
                saved = f" -> {Path(img['saved_path']).name}" if 'saved_path' in img else ""
                lines.append(f"- {img['name']} ({img['width']:.0f}x{img['height']:.0f}){saved}")
            lines.append("\n")

    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Parse PDFs with pdfplumber")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("--no-tables", action="store_true", help="Skip table extraction")
    parser.add_argument("--no-images", action="store_true", help="Skip image extraction")
    parser.add_argument("--no-layout", action="store_true", help="Skip layout analysis")
    parser.add_argument("--no-save-images", action="store_true", help="Don't save images")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    try:
        data, output_dir = parse_pdf(
            str(input_path),
            extract_tables=not args.no_tables,
            extract_images=not args.no_images,
            extract_layout=not args.no_layout,
            save_images=not args.no_save_images
        )

        # Save markdown and JSON
        md_content = to_markdown(data)
        json_content = json.dumps(data, indent=2)

        (output_dir / f"{input_path.stem}.md").write_text(md_content)
        (output_dir / f"{input_path.stem}.json").write_text(json_content)

        print(f"Saved to: {output_dir}")
        print(f"  - {input_path.stem}.md ({len(md_content)} chars)")
        print(f"  - {input_path.stem}.json ({len(json_content)} chars)")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())
