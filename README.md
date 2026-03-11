# PDF Parser Comparison

Test and compare 4 PDF parsers on financial documents.

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# For Ollama tests (optional)
ollama serve
ollama pull qwen3-vl:2b

# For Document AI (requires Google Cloud credentials)
export GOOGLE_CLOUD_PROJECT="arcana-stage-363819"
export DOCUMENT_AI_PROCESSOR_ID="your-processor-id"
```

---

## Run Tests

### Clear Previous Outputs

```bash
rm -rf output/*
```

### Test Document AI

```bash
python parsers/gemini_parser.py docs/VAM-3852AO.pdf --format json --beta
```

### Test PDFPlumber

```bash
python parsers/pdfplumber_parser.py docs/VAM-3852AO.pdf
```

### Test Unstructured

```bash
python parsers/unstructured_parser.py docs/VAM-3852AO.pdf
```

### Test Docling + SmolVLM

```bash
python parsers/docling/smolvlm.py docs/VAM-3852AO.pdf
```

### Test Docling + Granite

```bash
python parsers/docling/granite.py docs/VAM-3852AO.pdf
```

### Test Docling + Ollama (Simple - ~30s)

**Start Ollama first:**

```bash
ollama serve
```

**Then run:**

```bash
python parsers/docling/ollama_simple.py docs/VAM-3852AO.pdf
```

### Test Docling + Ollama (Verbose - ~261s)

```bash
python parsers/docling/ollama_verbose.py docs/VAM-3852AO.pdf
```

### Test Docling + Ollama (Hybrid - ~12-27s)

**Features:**
- Parallel VLM processing (4 workers max)
- In-place image descriptions (replaces `[IMAGE]` placeholders)
- Fast text/table parsing without VLM overhead

**Start Ollama first:**

```bash
ollama serve
```

**Then run:**

```bash
python parsers/docling/ollama_hybrid.py docs/VAM-3852AO.pdf
```

---

## Output

```
output/
├── gemini/VAM-3852AO/VAM-3852AO.json
├── pdfplumber/VAM-3852AO/VAM-3852AO.md
├── unstructured/VAM-3852AO/VAM-3852AO.md
└── docling/
    ├── smolvlm/VAM-3852AO/VAM-3852AO.md
    ├── granite/VAM-3852AO/VAM-3852AO.md
    ├── ollama-simple/VAM-3852AO/VAM-3852AO.md
    ├── ollama-verbose/VAM-3852AO/VAM-3852AO.md
    └── ollama-hybrid/VAM-3852AO/VAM-3852AO.md
```

---

## Documentation

- **FINAL_SUMMARY.md** - Summary comparison
- **PARSER_COMPARISON.md** - Detailed technical analysis

