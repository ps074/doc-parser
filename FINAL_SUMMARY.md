# PDF Parser Comparison

## Parser Overview


| Parser                             | Formats                             | Tables | Images         | Go Integration | Limitations             | Cost/1k pages |
| ---------------------------------- | ----------------------------------- | ------ | -------------- | -------------- | ----------------------- | ------------- |
| **Document AI**                    | PDF, HTML, DOCX, PPTX, XLSX         | ⭐⭐⭐⭐⭐  | ⭐⭐⭐⭐ AI        | ⭐ Native GoSDK | 15 pages, 20 MB (sync)  | $10 - 30      |
| **PDFPlumber**                     | PDF only                            | ⭐⭐⭐⭐   | ❌ None         | Python service | No scanned PDFs, no OCR | Free          |
| **Unstructured**                   | PDF, DOCX, PPTX, HTML, Images, +60  | ⭐⭐⭐    | ❌ Placeholder  | Python service | None significant        | Free          |
| **Docling + SmolVLM**              | PDF, DOCX, PPTX, XLSX, HTML, Images | ⭐⭐⭐⭐   | ❌ Hallucinates | Python service | VLM quality poor        | Free          |
| **Docling + Granite**              | PDF, DOCX, PPTX, XLSX, HTML, Images | ⭐⭐⭐⭐   | ❌ Gibberish    | Python service | VLM quality poor        | Free          |
| **Docling + Ollama (qwen3-vl:2b)** | PDF, DOCX, PPTX, XLSX, HTML, Images | ⭐⭐⭐⭐   | ⭐⭐⭐⭐⭐ VLM      | Python service | Slow inference          | Free          |


---

## Performance Comparison

**Test Document:** VAM-3852AO.pdf (2 pages, 4 images, 1 table)  
**Date:** March 5, 2026
**Test Environment:** MacBook (Darwin 24.6.0)

### Results


| Parser/Backend                             | Latency  | Tables      | Images         | Overall Quality | Notes                                      |
| ------------------------------------------ | -------- | ----------- | -------------- | --------------- | ------------------------------------------ |
| **PDFPlumber**                             | 0.4s ⚡⚡⚡ | ✅ Good      | ❌ None         | 85%             | No image understanding                     |
| **Docling + SmolVLM**                      | 17s ⚡⚡   | ✅ Good      | ❌ Hallucinates | 50%             | Wrong facts: S&P 500 → "chemical industry" |
| **Docling + Granite**                      | 20s ⚡⚡   | ✅ Good      | ❌ Gibberish    | 40%             | Output: "H chart h h WO.1..."              |
| **Document AI**                            | 23s ⚡    | ✅ Excellent | ✅ Good         | 95%             | Best overall                               |
| **Unstructured**                           | 29s ⚡    | ⚠️ Basic    | ❌ Placeholder  | 75%             | Poor formatting                            |
| **Docling + Ollama qwen3-vl:2b (simple)**  | 30-45s   | ✅ Good      | ✅ Good         | 90%             | Fast, concise descriptions                 |
| **Docling + Ollama qwen3-vl:2b (hybrid)**  | 12-27s ⚡⚡ | ✅ Good      | ✅ Excellent    | 90%             | Parallel processing, verbose prompt        |
| **Docling + Ollama qwen3-vl:2b (verbose)** | 261s     | ✅ Good      | ✅ Excellent    | 90%             | Slow, detailed analysis                    |


---

## Recommendation for arcana-ai

**Use Document AI (Native Go SDK)**

```go
import documentai "cloud.google.com/go/documentai/apiv1"

parser := NewGeminiParser(ctx, "arcana-stage-363819", "us", processorID)
doc := parser.ParsePDF(ctx, pdfBytes)
```

**Why:**

- ✅ Already in your project: `cloud.google.com/go/documentai v1.41.0`
- ✅ Best quality (95%+)
- ✅ No Python needed
- ✅ Production-ready

**Cost:** $10-30/1k pages

---

## Sources

- [Google Cloud Document AI Limits](https://docs.cloud.google.com/document-ai/limits)
- [Google Cloud Document AI Supported Files](https://docs.cloud.google.com/document-ai/docs/file-types)
- [Unstructured.io Supported File Types](https://docs.unstructured.io/ui/supported-file-types)
- [Docling Supported Formats](https://docling-project.github.io/docling/usage/supported_formats/)
- [pdfplumber PyPI](https://pypi.org/project/pdfplumber/)

