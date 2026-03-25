# Architecture Diagrams

## 1. PDF Parsing Pipeline

```mermaid
flowchart TD
    PDF[PDF Input] --> Classifier[Page Classifier<br><i>page_classifier.py</i><br>PyMuPDF metadata, no LLM, &lt;1s]

    Classifier --> Skip[SKIP / SIMPLE]
    Classifier --> Moderate[MODERATE]
    Classifier --> Complex[COMPLEX / CRITICAL]

    Skip --> Pypdfium[pypdfium2<br>text extraction<br><i>free, instant</i>]
    Moderate --> GPT[gpt-4.1-mini<br>vision]
    Complex --> Claude[Claude Sonnet<br>vision]

    Classifier --> GroupDetect{Cross-page<br>table detected?}
    GroupDetect -->|Yes| MultiPage[Send grouped pages<br>in single LLM call]
    GroupDetect -->|No| SinglePage[Send page individually]
    MultiPage --> GPT
    MultiPage --> Claude
    SinglePage --> GPT
    SinglePage --> Claude

    GPT --> PostProcess[Post-process<br>- Strip code fences<br>- Add page markers]
    Claude --> PostProcess
    Pypdfium --> PageMarker[Add page marker<br><code>&lt;!-- page: N --&gt;</code>]

    PostProcess --> Merge[Merge in page order]
    PageMarker --> Merge

    Merge --> MDOutput[output/pipeline/doc/doc.md]
    Merge --> MetaOutput[output/pipeline/doc/metadata.json]

    style Skip fill:#e8f5e9
    style Moderate fill:#fff3e0
    style Complex fill:#fce4ec
    style MDOutput fill:#e3f2fd
    style MetaOutput fill:#e3f2fd
```

## 2. Chunking Pipeline

```mermaid
flowchart TD
    MD[Pipeline Markdown<br><code>doc.md</code>] --> SplitPages[Split by<br><code>&lt;!-- page: N --&gt;</code><br>markers]

    SplitPages --> PerPage[For each page]

    PerPage --> Separate[Separate tables vs text<br><i>_extract_tables_and_text</i>]

    Separate --> TextSeg[Text segments]
    Separate --> TableSeg[Table segments]

    TextSeg --> PrependCtx1[Prepend heading context<br>to adjacent tables]
    TableSeg --> PrependCtx2[Prepend heading/title<br>to table]

    PrependCtx1 --> StripBold1[Strip ** markers]
    PrependCtx2 --> StripBold2[Strip ** markers]

    StripBold1 --> RecursiveChunker[Chonkie<br>RecursiveChunker<br><i>o200k_base, 512 tok</i>]
    StripBold2 --> TableChunker[Chonkie<br>TableChunker<br><i>o200k_base, 512 tok</i><br>headers preserved]

    RecursiveChunker --> Chunks[Chunk objects]
    TableChunker --> Chunks

    Chunks --> Output[doc_chunks.json<br><i>.text, .chunk_type,<br>.page_num, .token_count</i>]

    style MD fill:#e3f2fd
    style RecursiveChunker fill:#f3e5f5
    style TableChunker fill:#f3e5f5
    style Output fill:#e3f2fd
```

## 3. Evaluation Pipeline

```mermaid
flowchart TD
    PDF[PDFs] --> LoadMD[Load markdown<br><i>cached or --force-parse</i>]
    QA[qa_pairs.json] --> Eval

    LoadMD --> Eval[For each chunker strategy]

    Eval --> C1[page_level]
    Eval --> C2[fixed_512_overlap]
    Eval --> C3[recursive]
    Eval --> C4[heading_based]
    Eval --> C5[table_aware]
    Eval --> C6[element_type]
    Eval --> C7[semantic]
    Eval --> C8[structure_aware]
    Eval --> C9[chonkie_512]

    C1 & C2 & C3 & C4 & C5 & C6 & C7 & C8 & C9 --> ChunkEmbed[Embed chunks<br><i>text-embedding-3-small</i><br>+ Build BM25 index]

    ChunkEmbed --> Retrieve[For each question:<br>Hybrid retrieve top-k<br><i>dense + BM25 RRF</i>]

    Retrieve --> Metrics[Compute metrics]

    Metrics --> Recall[Recall@1,3,5,10<br><i>keyword in top-k chunks</i>]
    Metrics --> MRR[MRR<br><i>rank of first chunk<br>with keyword</i>]
    Metrics --> LLMEval[LLM Answer Eval<br><i>--llm-eval flag</i><br>gpt-4.1-mini answers<br>from top-5 chunks]

    Recall & MRR & LLMEval --> Results

    Results --> JSON[results_{ts}.json]
    Results --> CSV[summary_{ts}.csv]
    Results --> Details[details_{ts}/<br>per-strategy per-doc<br>with retrieved chunks]
    Results --> Comparison[CHUNKING_COMPARISON.md]

    style C9 fill:#f3e5f5
    style LLMEval fill:#fff3e0
    style JSON fill:#e3f2fd
    style CSV fill:#e3f2fd
    style Details fill:#e3f2fd
```

## 4. End-to-End Flow

```mermaid
flowchart LR
    PDF[PDF] -->|pipeline.py| Parse[Parse]
    Parse -->|classify pages<br>route to models| MD[Markdown<br>+ page markers]
    MD -->|chunker.py| Chunk[Chunk]
    Chunk -->|RecursiveChunker<br>+ TableChunker| Chunks[Chunks<br>JSON]
    Chunks -->|embed + index| VectorDB[(Vector DB<br>+ BM25)]
    VectorDB -->|hybrid retrieve| TopK[Top-K<br>Chunks]
    TopK -->|LLM| Answer[Answer]

    style PDF fill:#fce4ec
    style MD fill:#e3f2fd
    style Chunks fill:#e3f2fd
    style Answer fill:#e8f5e9
```
