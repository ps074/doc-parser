#!/usr/bin/env python3
"""Extract base64-encoded images from Gemini UI annotation JSON files."""
import json, base64, argparse
from pathlib import Path

def extract_images(json_path: Path, output_dir: Path) -> tuple[list, dict]:
    """Extract all images from Gemini annotation JSON."""
    data = json.loads(json_path.read_text())
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted = []

    # Deep copy for structure (replace encoded content with placeholders)
    structure_data = json.loads(json.dumps(data))

    # Extract page images
    for idx, page in enumerate(data.get('pages', []), 1):
        if img := page.get('image', {}).get('content'):
            width, height = page['image'].get('width', 0), page['image'].get('height', 0)

            # Replace in structure JSON
            if idx-1 < len(structure_data.get('pages', [])):
                structure_data['pages'][idx-1]['image']['content'] = \
                    f"... (base64 image, {len(img)} chars) ..."

            # Decode and save
            img_data = base64.b64decode(img)
            img_path = output_dir / f"page_{idx}.png"
            img_path.write_bytes(img_data)

            extracted.append({
                'type': 'page_image', 'path': str(img_path),
                'size': len(img_data), 'dimensions': f"{width}x{height}"
            })
            print(f"Page {idx}: {img_path.name} ({len(img_data):,} bytes, {width}x{height})")

    # Extract blob assets
    for idx, blob in enumerate(data.get('blobAssets', []), 1):
        if content := blob.get('content'):
            mime_type = blob.get('mimeType', 'image/png')
            asset_id = blob.get('assetId', f'blob_{idx}')
            ext = mime_type.split('/')[-1] if '/' in mime_type else 'png'

            # Replace in structure JSON
            if idx-1 < len(structure_data.get('blobAssets', [])):
                structure_data['blobAssets'][idx-1]['content'] = \
                    f"... (base64 image, {len(content)} chars) ..."

            # Decode and save
            img_data = base64.b64decode(content)
            img_path = output_dir / f"{asset_id}.{ext}"
            img_path.write_bytes(img_data)

            extracted.append({
                'type': 'blob_asset', 'path': str(img_path),
                'size': len(img_data), 'mime_type': mime_type, 'asset_id': asset_id
            })
            print(f"Blob {idx}: {img_path.name} ({len(img_data):,} bytes, {mime_type})")

    return extracted, structure_data

def main():
    parser = argparse.ArgumentParser(description="Extract images from Gemini UI JSON")
    parser.add_argument("input", help="Path to annotation JSON file")
    parser.add_argument("-o", "--output", help="Output directory for images")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    # Default output: parent/filename/images (remove -LP-annotation suffix)
    output_dir = Path(args.output) if args.output else \
        input_path.parent / input_path.stem.replace('-LP-annotation', '') / "images"

    print(f"Extracting from: {input_path.name}")
    print(f"Output: {output_dir}\n")

    extracted, structure_data = extract_images(input_path, output_dir)

    # Save structure JSON (without base64 content)
    structure_path = input_path.parent / f"{input_path.stem}-structure.json"
    structure_path.write_text(json.dumps(structure_data, indent=2))
    print(f"\n✅ Structure JSON: {structure_path.name}")

    # Summary
    pages = sum(1 for e in extracted if e['type'] == 'page_image')
    blobs = sum(1 for e in extracted if e['type'] == 'blob_asset')
    total_size = sum(e['size'] for e in extracted)

    print(f"✅ Extracted {len(extracted)} images:")
    print(f"   Pages: {pages}, Blobs: {blobs}")
    print(f"   Total: {total_size:,} bytes")
    return 0

if __name__ == "__main__":
    exit(main())
