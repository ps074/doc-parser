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

### Test PDFPlumber (Full)

```bash
python parsers/pdfplumber/full.py docs/VAM-3852AO.pdf
```

### Test PDFPlumber (Basic)

```bash
python parsers/pdfplumber/basic.py docs/VAM-3852AO.pdf
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

### Test Docling (Basic)

```bash
python parsers/docling/basic.py docs/VAM-3852AO.pdf
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
├── pdfplumber/
│   ├── VAM-3852AO/VAM-3852AO.md
│   └── basic/VAM-3852AO/VAM-3852AO.md
├── unstructured/VAM-3852AO/VAM-3852AO.md
└── docling/
    ├── smolvlm/VAM-3852AO/VAM-3852AO.md
    ├── granite/VAM-3852AO/VAM-3852AO.md
    ├── basic/VAM-3852AO/VAM-3852AO.md
    ├── ollama-simple/VAM-3852AO/VAM-3852AO.md
    ├── ollama-verbose/VAM-3852AO/VAM-3852AO.md
    └── ollama-hybrid/VAM-3852AO/VAM-3852AO.md
```

---

## Pipeline Parser

The main parsing pipeline classifies pages by complexity and routes to the appropriate model:

```bash
# Dry run (see classification + cost estimate, no API calls)
python parsers/pipeline.py docs/VAM-3852AO.pdf --dry-run

# Run with Vertex AI
python parsers/pipeline.py docs/VAM-3852AO.pdf --vertex

# Run with direct Anthropic API
python parsers/pipeline.py docs/VAM-3852AO.pdf
```

Page complexity routing:
- **SKIP/SIMPLE** → pypdfium2 text extraction (free, instant)
- **MODERATE** → GPT-4.1-mini vision
- **COMPLEX/CRITICAL** → Claude Sonnet vision

---

## Chunking Experiment

Evaluates 11 chunking strategies across 2 parsers (pymupdf_fast, pipeline) and multiple retrieval backends. Located in `experiments/chunking/`.

### Setup

```bash
pip install sentence-transformers tiktoken rank_bm25 turbopuffer
```

Required env vars for TurboPuffer retrieval:
```bash
export TURBOPUFFER_API_KEY="your-key"
export OPENAI_API_KEY="your-key"  # for text-embedding-3-small
```

### Chunking Strategies

| # | Strategy | Description |
|---|----------|-------------|
| 1 | `page_level` | Each page = 1 chunk. Simplest baseline. |
| 2 | `fixed_256` | Fixed 256-token chunks, split on sentence boundaries. |
| 3 | `fixed_512` | Fixed 512-token chunks. |
| 4 | `fixed_512_overlap102` | 512-token chunks with 20% overlap (102 tokens). |
| 5 | `recursive` | Recursive splitting on `\n\n` → `\n` → `. ` → ` ` (target 512 tokens). |
| 6 | `heading_based` | Split on markdown headings (#/##/###), sub-split if >1024 tokens. |
| 7 | `table_aware` | Tables kept as atomic chunks, surrounding text chunked at 512 tokens. |
| 8 | `element_type` | Separate tables, chart descriptions, and text as distinct typed chunks. |
| 9 | `semantic` | Sentence embeddings → cosine similarity breakpoints for topic boundaries. |
| 10 | `structure_aware` | Heading hierarchy prepended to each chunk (e.g. `[Annual Performance > Sector Breakdown]`). Tables kept atomic. |
| 11 | `contextual_*` | Wraps any base chunker — uses GPT-4.1-mini to generate a 1-2 sentence context prepended to each chunk before embedding (Anthropic's contextual retrieval approach). |

### Retrieval Modes

| Mode | Backend | Embeddings | Keyword Search |
|------|---------|-----------|----------------|
| `dense` | Local (numpy) | all-MiniLM-L6-v2 | No |
| `bm25` | Local (rank_bm25) | No | BM25 |
| `hybrid` | Local | all-MiniLM-L6-v2 | BM25 + RRF fusion |
| `turbopuffer` | TurboPuffer | text-embedding-3-small | No |
| `turbopuffer_bm25` | TurboPuffer | No | BM25 |
| `turbopuffer_hybrid` | TurboPuffer | text-embedding-3-small | BM25 + RRF fusion |

### Running the Evaluation

```bash
# Local dense retrieval (default) — fast, no API calls for retrieval
python experiments/chunking/eval_chunking.py --parser pymupdf_fast

# Local hybrid (BM25 + dense) — best local option
python experiments/chunking/eval_chunking.py --parser pymupdf_fast --retrieval hybrid

# TurboPuffer hybrid — best overall (requires API keys)
python experiments/chunking/eval_chunking.py --parser pymupdf_fast --retrieval turbopuffer_hybrid

# Pipeline parser
python experiments/chunking/eval_chunking.py --parser pipeline --retrieval turbopuffer_hybrid

# Include contextual retrieval variants (makes LLM calls to contextualize chunks)
python experiments/chunking/eval_chunking.py --parser pymupdf_fast --retrieval hybrid --contextual

# Specific documents only
python experiments/chunking/eval_chunking.py --parser pymupdf_fast --retrieval hybrid \
  --docs docs/VAM-3852AO.pdf docs/hubspot-q4.pdf

# Per-document breakdown
python experiments/chunking/eval_chunking.py --parser pymupdf_fast --retrieval hybrid --per-doc
```

### Evaluation Metrics

- **Recall@k**: Does the expected answer keyword appear in the top-k retrieved chunks?
- Tested at k=1, 3, 5, 10 across 38 questions on 4 financial documents
- Question types: factual, table_lookup, chart_reading, table_reasoning

### Test Documents

| Document | Pages | Type |
|----------|-------|------|
| `VAM-3852AO.pdf` | 2 | S&P 500 index factsheet |
| `hubspot-q4.pdf` | 10 | Quarterly earnings press release |
| `hubspot-deck.pdf` | 26 | Investor presentation (chart-heavy) |
| `2023_report_40_pages.pdf` | 40 | 10-K annual filing |

### TurboPuffer Storage

Chunks are stored in TurboPuffer namespaces with the pattern:
```
chunking_exp__{parser}__{chunker}__{doc_name}
```

Each namespace contains chunks with:
- **vector**: OpenAI text-embedding-3-small (1536-dim)
- **text**: BM25-indexed full text
- **page_num**, **chunk_type**, **strategy**: metadata attributes

### Key Results

| Configuration | R@1 | R@5 | R@10 |
|--------------|:---:|:---:|:----:|
| Baseline (fixed_512_overlap + local dense) | 0.454 | 0.867 | 0.938 |
| + Local hybrid (BM25 + dense) | 0.614 | 0.969 | 0.969 |
| + TurboPuffer hybrid (OpenAI emb + BM25) | 0.733 | 0.950 | 1.000 |
| Best (element_type + pymupdf + TurboPuffer) | **0.852** | **0.975** | **1.000** |

### Output Files

Results are saved to `experiments/chunking/results/`:
```
results/
├── results_{parser}_{retrieval}.json    # Full results with per-question detail
└── summary_{parser}_{retrieval}.csv     # Aggregated comparison table
```

### File Structure

```
experiments/chunking/
├── chunkers.py        # 11 chunking strategies (Chunk dataclass, utilities, all chunkers)
├── embedder.py        # Local embedding (sentence-transformers) + BM25 + hybrid scoring
├── store.py           # TurboPuffer integration (upsert, vector/BM25/hybrid query)
├── eval_chunking.py   # Main evaluation script
├── qa_pairs.json      # 38 Q&A pairs across 4 documents
└── results/           # Output JSON + CSV files
```

---

## Documentation

- **FINAL_SUMMARY.md** - Summary comparison
- **PARSER_COMPARISON.md** - Detailed technical analysis
