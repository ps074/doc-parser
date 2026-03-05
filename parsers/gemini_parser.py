#!/usr/bin/env python3
"""Google Document AI parser - v1 (stable) and v1beta3 (beta with annotations)."""
import argparse, os, json
from pathlib import Path
from dotenv import load_dotenv
from google.cloud import documentai, documentai_v1beta3
from google.api_core.client_options import ClientOptions
from google.protobuf.json_format import MessageToDict

load_dotenv()

class GeminiParser:
    def __init__(self, project_id=None, location="us", processor_id=None,
                 processor_version=None, enable_chunking=False, use_beta=False):
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.processor_id = processor_id or os.getenv("DOCUMENT_AI_PROCESSOR_ID")
        self.processor_version = processor_version or os.getenv(
            "DOCUMENT_AI_PROCESSOR_VERSION", "pretrained-layout-parser-v1.5-2025-08-25"
        )
        self.enable_chunking = enable_chunking
        self.use_beta = use_beta

        if not self.project_id or not self.processor_id:
            raise ValueError("Set GOOGLE_CLOUD_PROJECT and DOCUMENT_AI_PROCESSOR_ID")

        self.api = documentai_v1beta3 if use_beta else documentai
        self.client = self.api.DocumentProcessorServiceClient(
            client_options=ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        )
        self.processor_name = self.client.processor_version_path(
            self.project_id, location, self.processor_id, self.processor_version
        )

    def parse_pdf(self, pdf_path: str, output_format="markdown") -> str:
        """Parse PDF with Google Document AI."""
        pdf_file = Path(pdf_path)
        if not pdf_file.exists() or pdf_file.suffix.lower() != '.pdf':
            raise ValueError(f"Invalid PDF: {pdf_path}")

        print(f"Parsing: {pdf_file.name}")

        # Configure layout parser
        config = {"return_images": True, "return_bounding_boxes": True}

        if self.use_beta:
            config.update({
                "enable_table_annotation": True,
                "enable_image_annotation": True,
                "enable_image_extraction": True,
            })

        if self.enable_chunking:
            config["chunking_config"] = self.api.ProcessOptions.LayoutConfig.ChunkingConfig(
                chunk_size=1024, include_ancestor_headings=True
            )

        # Process document
        result = self.client.process_document(self.api.ProcessRequest(
            name=self.processor_name,
            raw_document=self.api.RawDocument(
                content=pdf_file.read_bytes(), mime_type="application/pdf"
            ),
            process_options=self.api.ProcessOptions(
                layout_config=self.api.ProcessOptions.LayoutConfig(**config)
            )
        ))

        doc = result.document

        # Convert to requested format
        if output_format == "json":
            return json.dumps(MessageToDict(doc._pb), indent=2)
        elif output_format == "text":
            return doc.text
        elif output_format == "chunks":
            return self._to_chunks(doc)
        else:
            return self._to_markdown(MessageToDict(doc._pb))

    def _to_markdown(self, doc_dict: dict) -> str:
        """Convert to markdown."""
        lines = []

        def extract_cell_text(cell):
            return ' '.join([
                blk['textBlock']['text'].strip()
                for blk in cell.get('blocks', [])
                if 'textBlock' in blk and blk['textBlock'].get('text', '').strip()
            ])

        def process_block(block):
            if 'textBlock' in block:
                tb = block['textBlock']
                if text := tb.get('text', '').strip():
                    btype = tb.get('type', 'paragraph')
                    if btype in ['header', 'heading-1']:
                        lines.append(f"# {text}\n")
                    elif btype == 'heading-2':
                        lines.append(f"## {text}\n")
                    elif btype == 'heading-3':
                        lines.append(f"### {text}\n")
                    elif btype == 'heading-4':
                        lines.append(f"#### {text}\n")
                    else:
                        lines.append(f"{text}\n")

                for nested in tb.get('blocks', []):
                    process_block(nested)

            elif 'imageBlock' in block:
                img_text = block['imageBlock'].get('imageText', '')
                lines.append(f"\n**[Image]**\n*{img_text}*\n" if img_text else "\n**[Image]**\n")

            elif 'tableBlock' in block:
                table = block['tableBlock']
                lines.append("\n")

                header_rows = table.get('headerRows', [])
                body_rows = table.get('bodyRows', [])

                # Headers
                if header_rows:
                    for row in header_rows:
                        cells = [extract_cell_text(c) for c in row.get('cells', [])]
                        if cells:
                            lines.append('| ' + ' | '.join(cells) + ' |')
                            lines.append('| ' + ' | '.join(['---'] * len(cells)) + ' |')
                elif body_rows:
                    cells = [extract_cell_text(c) for c in body_rows[0].get('cells', [])]
                    if cells:
                        lines.append('| ' + ' | '.join(cells) + ' |')
                        lines.append('| ' + ' | '.join(['---'] * len(cells)) + ' |')
                    body_rows = body_rows[1:]

                # Body
                for row in body_rows:
                    cells = [extract_cell_text(c) for c in row.get('cells', [])]
                    if cells:
                        lines.append('| ' + ' | '.join(cells) + ' |')
                lines.append("")

        for block in doc_dict.get('documentLayout', {}).get('blocks', []):
            process_block(block)

        return "\n".join(lines) if lines else "# Document\n\n(No content extracted)"

    def _to_chunks(self, doc) -> str:
        """Convert to RAG chunks."""
        if not hasattr(doc, 'chunked_document') or not doc.chunked_document.chunks:
            return "No chunks. Use --enable-chunking flag."

        lines = [f"# RAG Chunks\n\nTotal: {len(doc.chunked_document.chunks)}\n"]
        for i, chunk in enumerate(doc.chunked_document.chunks):
            lines.append(f"\n## Chunk {i}\n{chunk.content}\n")
            if chunk.page_span:
                pages = [f"{s.page_start}-{s.page_end}" for s in chunk.page_span]
                lines.append(f"**Pages:** {', '.join(pages)}\n")
        return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Google Document AI Layout Parser")
    parser.add_argument("input", help="PDF file path")
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument("--format", choices=["markdown", "text", "json", "chunks"],
                       default="json", help="Output format")
    parser.add_argument("--beta", action="store_true",
                       help="Use v1beta3 API (table/image annotations)")
    parser.add_argument("--enable-chunking", action="store_true", help="RAG-ready chunks")
    parser.add_argument("--project-id", help="Google Cloud project ID")
    parser.add_argument("--processor-id", help="Document AI processor ID")
    parser.add_argument("--processor-version", help="Processor version")
    parser.add_argument("--location", default="us", help="Processor location")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {args.input} not found")
        return 1

    try:
        doc_parser = GeminiParser(
            project_id=args.project_id, location=args.location,
            processor_id=args.processor_id, processor_version=args.processor_version,
            enable_chunking=args.enable_chunking, use_beta=args.beta
        )

        content = doc_parser.parse_pdf(str(input_path), args.format)

        # Save output
        output_dir = Path("output/gemini") / input_path.stem
        output_dir.mkdir(parents=True, exist_ok=True)

        ext_map = {"markdown": ".md", "text": ".txt", "json": ".json", "chunks": ".txt"}
        ext = ext_map.get(args.format, ".json")
        output_path = Path(args.output) if args.output else output_dir / f"{input_path.stem}{ext}"

        output_path.write_text(content, encoding='utf-8')
        print(f"Saved to: {output_path}")
        print(f"Parsed {len(content)} characters")
        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1

if __name__ == "__main__":
    exit(main())
