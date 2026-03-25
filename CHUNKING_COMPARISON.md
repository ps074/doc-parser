# Chunking Strategy Comparison

## Run: 2026-03-18

**Documents**: VAM-3852AO (2p factsheet), hubspot-q4 (10p earnings), hubspot-deck (26p investor deck), 2023_report_40_pages (40p 10-K filing)
**Questions**: 38 Q&A pairs (factual, table_lookup, chart_reading, table_reasoning)
**Embedding models**: all-MiniLM-L6-v2 (local), text-embedding-3-small (TurboPuffer)

### Top Configurations (all 4 docs, 38 questions)


| Rank | Strategy                     | Parser   | Retrieval   | Chunks | Avg Tok | R@1       | R@3   | R@5   | R@10  |
| ---- | ---------------------------- | -------- | ----------- | ------ | ------- | --------- | ----- | ----- | ----- |
| 1    | element_type                 | pymupdf  | tpuf_hybrid | 40     | 563     | **0.852** | 0.925 | 0.975 | 1.000 |
| 2    | recursive                    | pymupdf  | tpuf_hybrid | 41     | 322     | 0.771     | 0.950 | 0.950 | 1.000 |
| 3    | page_level                   | pymupdf  | tpuf_hybrid | 20     | 728     | 0.758     | 0.925 | 0.975 | 1.000 |
| 4    | structure_aware              | pymupdf  | tpuf_hybrid | 44     | 395     | 0.758     | 0.888 | 0.969 | 0.969 |
| 5    | fixed_512_overlap            | pymupdf  | tpuf_hybrid | 40     | 355     | 0.733     | 0.950 | 0.950 | 1.000 |
| 6    | heading_based                | pymupdf  | tpuf_hybrid | 28     | 429     | 0.717     | 0.888 | 0.969 | 0.969 |
| 7    | fixed_512                    | pymupdf  | tpuf_hybrid | 38     | 330     | 0.708     | 0.919 | 0.950 | 1.000 |
| 8    | table_aware                  | pymupdf  | tpuf_hybrid | 58     | 267     | 0.708     | 0.919 | 0.950 | 1.000 |
| 9    | fixed_256                    | pymupdf  | tpuf_hybrid | 67     | 191     | 0.688     | 0.950 | 0.975 | 1.000 |
| 10   | fixed_256                    | pymupdf  | hybrid      | 67     | 191     | 0.702     | 0.954 | 0.975 | 1.000 |
| 11   | semantic                     | pipeline | tpuf_hybrid | 93     | 161     | 0.690     | 0.894 | 0.975 | 1.000 |
| 12   | page_level                   | pipeline | tpuf_hybrid | 11     | 2562    | 0.671     | 0.969 | 0.969 | 0.969 |
| 13   | structure_aware              | pipeline | tpuf_hybrid | 50     | 262     | 0.664     | 0.894 | 1.000 | 1.000 |
| 14   | contextual_fixed_512_overlap | pymupdf  | hybrid      | 40     | 402     | 0.646     | 0.927 | 0.948 | 0.969 |
| 15   | element_type                 | pymupdf  | hybrid      | 40     | 563     | 0.644     | 0.846 | 0.919 | 0.969 |


### By Retrieval Mode

#### Local Dense (all-MiniLM-L6-v2 cosine similarity)


| Strategy          | Parser   | Chunks | Avg Tok | R@1   | R@3   | R@5   | R@10  |
| ----------------- | -------- | ------ | ------- | ----- | ----- | ----- | ----- |
| fixed_512_overlap | pymupdf  | 40     | 355     | 0.454 | 0.769 | 0.867 | 0.938 |
| element_type      | pymupdf  | 40     | 563     | 0.454 | 0.621 | 0.846 | 0.917 |
| page_level        | pymupdf  | 20     | 728     | 0.423 | 0.662 | 0.867 | 0.938 |
| page_level        | pipeline | 11     | 2562    | 0.423 | 0.819 | 0.906 | 0.906 |
| table_aware       | pymupdf  | 58     | 267     | 0.404 | 0.640 | 0.790 | 0.892 |
| fixed_256         | pymupdf  | 67     | 191     | 0.398 | 0.702 | 0.856 | 0.975 |
| recursive         | pymupdf  | 41     | 322     | 0.392 | 0.681 | 0.810 | 0.892 |
| structure_aware   | pymupdf  | 44     | 395     | 0.423 | 0.662 | 0.867 | 0.938 |
| heading_based     | pymupdf  | 28     | 429     | 0.340 | 0.719 | 0.764 | 0.923 |
| semantic          | pymupdf  | 112    | 109     | 0.317 | 0.712 | 0.754 | 0.919 |


#### Local Hybrid (all-MiniLM-L6-v2 + BM25 + RRF)


| Strategy                     | Parser   | Chunks | Avg Tok | R@1   | R@3   | R@5   | R@10  |
| ---------------------------- | -------- | ------ | ------- | ----- | ----- | ----- | ----- |
| fixed_256                    | pymupdf  | 67     | 191     | 0.702 | 0.954 | 0.975 | 1.000 |
| contextual_fixed_512_overlap | pymupdf  | 40     | 402     | 0.646 | 0.927 | 0.948 | 0.969 |
| element_type                 | pymupdf  | 40     | 563     | 0.644 | 0.846 | 0.919 | 0.969 |
| fixed_512_overlap            | pymupdf  | 40     | 355     | 0.614 | 0.888 | 0.969 | 0.969 |
| recursive                    | pymupdf  | 41     | 322     | 0.614 | 0.779 | 0.912 | 0.969 |
| page_level                   | pipeline | 11     | 2562    | 0.589 | 0.906 | 0.938 | 0.938 |
| fixed_512_overlap            | pipeline | 39     | 442     | 0.592 | 0.700 | 0.823 | 0.869 |
| page_level                   | pymupdf  | 20     | 728     | 0.571 | 0.867 | 0.919 | 0.969 |
| structure_aware              | pymupdf  | 44     | 395     | 0.556 | 0.846 | 0.912 | 1.000 |
| contextual_structure_aware   | pymupdf  | 44     | 441     | 0.542 | 0.788 | 0.902 | 0.979 |


#### TurboPuffer Hybrid (text-embedding-3-small + BM25 + RRF)


| Strategy          | Parser   | Chunks | Avg Tok | R@1   | R@3   | R@5   | R@10  |
| ----------------- | -------- | ------ | ------- | ----- | ----- | ----- | ----- |
| element_type      | pymupdf  | 40     | 563     | 0.852 | 0.925 | 0.975 | 1.000 |
| recursive         | pymupdf  | 41     | 322     | 0.771 | 0.950 | 0.950 | 1.000 |
| page_level        | pymupdf  | 20     | 728     | 0.758 | 0.925 | 0.975 | 1.000 |
| structure_aware   | pymupdf  | 44     | 395     | 0.758 | 0.888 | 0.969 | 0.969 |
| fixed_512_overlap | pymupdf  | 40     | 355     | 0.733 | 0.950 | 0.950 | 1.000 |
| heading_based     | pymupdf  | 28     | 429     | 0.717 | 0.888 | 0.969 | 0.969 |
| fixed_512         | pymupdf  | 38     | 330     | 0.708 | 0.919 | 0.950 | 1.000 |
| table_aware       | pymupdf  | 58     | 267     | 0.708 | 0.919 | 0.950 | 1.000 |
| semantic          | pipeline | 93     | 161     | 0.690 | 0.894 | 0.975 | 1.000 |
| fixed_256         | pymupdf  | 67     | 191     | 0.688 | 0.950 | 0.975 | 1.000 |
| page_level        | pipeline | 11     | 2562    | 0.671 | 0.969 | 0.969 | 0.969 |
| structure_aware   | pipeline | 50     | 262     | 0.664 | 0.894 | 1.000 | 1.000 |
| heading_based     | pipeline | 34     | 363     | 0.627 | 0.788 | 0.950 | 1.000 |
| fixed_512_overlap | pipeline | 39     | 442     | 0.606 | 0.875 | 0.925 | 1.000 |
| semantic          | pymupdf  | 112    | 109     | 0.594 | 0.860 | 0.975 | 0.975 |
| element_type      | pipeline | 37     | 363     | 0.581 | 0.848 | 0.979 | 1.000 |


### Per-Document Breakdown (Best Config: element_type + pymupdf + TurboPuffer hybrid)


| Document             | Pages | Questions | R@1   | R@3   | R@5   | R@10  |
| -------------------- | ----- | --------- | ----- | ----- | ----- | ----- |
| VAM-3852AO           | 2     | 8         | 1.000 | 1.000 | 1.000 | 1.000 |
| hubspot-q4           | 10    | 10        | 0.700 | 0.700 | 0.900 | 1.000 |
| hubspot-deck         | 26    | 12        | 0.833 | 1.000 | 1.000 | 1.000 |
| 2023_report_40_pages | 40    | 8         | 0.875 | 1.000 | 1.000 | 1.000 |


### Progression Summary


| Configuration                                        | R@1       | R@5       | R@10      | Delta R@1 |
| ---------------------------------------------------- | --------- | --------- | --------- | --------- |
| Baseline (fixed_512_overlap + pymupdf + local dense) | 0.454     | 0.867     | 0.938     | —         |
| + Local hybrid retrieval (BM25 + dense RRF)          | 0.614     | 0.969     | 0.969     | +35%      |
| + Contextual retrieval (LLM context prepended)       | 0.646     | 0.948     | 0.969     | +42%      |
| + TurboPuffer + OpenAI embeddings                    | 0.733     | 0.950     | 1.000     | +61%      |
| Best (element_type + pymupdf + TurboPuffer hybrid)   | **0.852** | **0.975** | **1.000** | **+88%**  |


### Key Findings

1. **Retrieval mode matters more than chunking strategy.** Switching from dense-only to hybrid (BM25+dense) improved R@1 by 35% across all chunkers. BM25 catches exact financial numbers that dense embeddings miss.
2. **OpenAI text-embedding-3-small >> all-MiniLM-L6-v2.** TurboPuffer with OpenAI embeddings outperformed local sentence-transformers across every chunker, adding another 20-30% R@1 improvement.
3. **element_type chunking is the best strategy for financial docs.** Separating tables, chart descriptions, and text into typed chunks gives the retriever focused content to match against. R@1=0.852 with TurboPuffer hybrid.
4. **PyMuPDF consistently outperforms pipeline for retrieval.** Raw extracted text has higher keyword density than LLM-reformulated prose, making BM25 more effective. Pipeline's advantage (chart descriptions, visual understanding) is offset by keyword dilution.
5. **structure_aware + pipeline achieves perfect R@5.** When the pipeline's richer content is chunked with heading context prepended, it hits R@5=1.000 and R@10=1.000 on TurboPuffer.
6. **Contextual retrieval helps but is expensive.** Prepending LLM-generated context improved R@3 from 0.888→0.927 on the best base chunker, but adds API cost per chunk.
7. **semantic chunking is inconsistent.** Works well on large docs (R@1=0.875 on 40p 10-K with pipeline+TurboPuffer) but poorly on structured financial tables (R@1=0.300 on hubspot-q4).
8. **page_level is the simplest high-performer.** With TurboPuffer hybrid, page_level gets R@1=0.758 with only 20 chunks — best simplicity/performance ratio.

---

## Run: 2026-03-18 10:47 | pymupdf_fast + dense

**Documents**: VAM-3852AO


| Strategy             | Chunks | Avg Tok | R@1   | R@3   | R@5   | R@10  |
| -------------------- | ------ | ------- | ----- | ----- | ----- | ----- |
| page_level           | 2      | 762     | 0.875 | 1.000 | 1.000 | 1.000 |
| fixed_256            | 7      | 216     | 0.875 | 1.000 | 1.000 | 1.000 |
| fixed_512_overlap102 | 4      | 412     | 0.875 | 1.000 | 1.000 | 1.000 |
| structure_aware      | 7      | 218     | 0.875 | 1.000 | 1.000 | 1.000 |
| fixed_512            | 4      | 380     | 0.750 | 1.000 | 1.000 | 1.000 |
| recursive            | 4      | 380     | 0.750 | 1.000 | 1.000 | 1.000 |
| table_aware          | 6      | 253     | 0.750 | 1.000 | 1.000 | 1.000 |
| element_type         | 5      | 304     | 0.750 | 1.000 | 1.000 | 1.000 |
| heading_based        | 6      | 253     | 0.375 | 1.000 | 1.000 | 1.000 |
| semantic             | 17     | 87      | 0.250 | 0.875 | 0.875 | 1.000 |


---

## Run: 2026-03-19 12:05 | pymupdf_fast + hybrid

**Documents**: 10Q, 2023_report_40_pages, VAM-3852AO, hubspot-deck, hubspot-q4, kiski, report


| Strategy             | Chunks | Avg Tok | R@1   | R@3   | R@5   | R@10  |
| -------------------- | ------ | ------- | ----- | ----- | ----- | ----- |
| page_level           | 37     | 1115    | 0.533 | 0.842 | 0.900 | 0.929 |
| element_type         | 122    | 445     | 0.564 | 0.765 | 0.886 | 0.929 |
| fixed_512_overlap102 | 102    | 392     | 0.548 | 0.811 | 0.886 | 0.932 |
| fixed_512            | 94     | 371     | 0.510 | 0.775 | 0.886 | 0.946 |
| fixed_256            | 172    | 207     | 0.583 | 0.838 | 0.882 | 0.968 |
| semantic             | 270    | 122     | 0.386 | 0.788 | 0.857 | 0.893 |
| heading_based        | 68     | 489     | 0.523 | 0.777 | 0.854 | 0.946 |
| structure_aware      | 134    | 339     | 0.500 | 0.769 | 0.854 | 0.932 |
| table_aware          | 162    | 246     | 0.449 | 0.737 | 0.854 | 0.918 |
| recursive            | 104    | 347     | 0.537 | 0.745 | 0.836 | 0.929 |


---

## Run: 2026-03-19 13:35 | pymupdf_fast + hybrid

**Documents**: 10Q, 2023_report_40_pages, VAM-3852AO, hubspot-deck, hubspot-q4, kiski, report


| Strategy             | Chunks | Avg Tok | R@1   | R@3   | R@5   | R@10  |
| -------------------- | ------ | ------- | ----- | ----- | ----- | ----- |
| page_level           | 37     | 1115    | 0.610 | 0.877 | 0.918 | 0.982 |
| fixed_512            | 94     | 371     | 0.554 | 0.846 | 0.889 | 0.982 |
| fixed_512_overlap102 | 102    | 392     | 0.552 | 0.861 | 0.889 | 0.968 |
| structure_aware      | 134    | 339     | 0.630 | 0.825 | 0.882 | 0.946 |
| recursive            | 104    | 347     | 0.604 | 0.800 | 0.875 | 0.982 |
| table_aware          | 162    | 246     | 0.568 | 0.832 | 0.875 | 0.954 |
| element_type         | 122    | 445     | 0.696 | 0.843 | 0.871 | 0.964 |
| fixed_256            | 172    | 207     | 0.542 | 0.764 | 0.861 | 0.968 |
| heading_based        | 68     | 489     | 0.629 | 0.836 | 0.854 | 0.964 |
| semantic             | 268    | 124     | 0.546 | 0.695 | 0.843 | 0.907 |


---

## Run: 2026-03-19 15:49 | pymupdf4llm + hybrid

**Documents**: 10Q, 2023_report_40_pages, VAM-3852AO, hubspot-deck, hubspot-q4, kiski, report


| Strategy             | Chunks | Avg Tok | R@1   | R@3   | R@5   | R@10  |
| -------------------- | ------ | ------- | ----- | ----- | ----- | ----- |
| page_level           | 1      | 32443   | 1.000 | 1.000 | 1.000 | 1.000 |
| heading_based        | 78     | 372     | 0.564 | 0.818 | 0.882 | 0.968 |
| element_type         | 44     | 1631    | 0.502 | 0.830 | 0.882 | 0.943 |
| structure_aware      | 96     | 364     | 0.398 | 0.804 | 0.882 | 0.925 |
| fixed_512            | 67     | 459     | 0.533 | 0.736 | 0.879 | 0.943 |
| table_aware          | 77     | 456     | 0.473 | 0.752 | 0.852 | 0.914 |
| fixed_256            | 137    | 229     | 0.426 | 0.756 | 0.838 | 0.914 |
| fixed_512_overlap102 | 78     | 478     | 0.467 | 0.705 | 0.832 | 0.921 |
| recursive            | 80     | 394     | 0.544 | 0.807 | 0.821 | 0.943 |
| semantic             | 132    | 334     | 0.430 | 0.749 | 0.817 | 0.893 |


---

## Run: 2026-03-20 07:45 | pymupdf4llm + hybrid

**Documents**: 10Q, 2023_report_40_pages, VAM-3852AO, hubspot-deck, hubspot-q4, kiski, report


| Strategy             | Chunks | Avg Tok | R@1   | R@3   | R@5   | R@10  |
| -------------------- | ------ | ------- | ----- | ----- | ----- | ----- |
| page_level           | 37     | 1005    | 0.594 | 0.861 | 0.939 | 1.000 |
| fixed_256            | 153    | 195     | 0.402 | 0.754 | 0.871 | 0.929 |
| table_aware          | 98     | 360     | 0.513 | 0.800 | 0.870 | 0.900 |
| semantic             | 174    | 249     | 0.439 | 0.756 | 0.870 | 0.911 |
| structure_aware      | 122    | 290     | 0.476 | 0.738 | 0.868 | 0.911 |
| recursive            | 96     | 317     | 0.579 | 0.761 | 0.854 | 0.929 |
| fixed_512            | 83     | 361     | 0.561 | 0.807 | 0.850 | 0.957 |
| fixed_512_overlap102 | 89     | 380     | 0.540 | 0.764 | 0.836 | 0.957 |
| element_type         | 78     | 501     | 0.471 | 0.736 | 0.835 | 0.929 |
| heading_based        | 104    | 291     | 0.511 | 0.756 | 0.832 | 0.911 |


---

## Run: 2026-03-20 13:27 | pymupdf4llm + pdftriage

**Documents**: 10Q, 2023_report_40_pages, VAM-3852AO, hubspot-deck, hubspot-q4, kiski, report


| Strategy  | Chunks | Avg Tok | R@1   | R@3   | R@5   | R@10  |
| --------- | ------ | ------- | ----- | ----- | ----- | ----- |
| pdftriage | 85     | 0       | 0.619 | 0.619 | 0.619 | 0.619 |


---

## Run: 2026-03-20 13:40 | pipeline + pdftriage_pipeline

**Documents**: 10Q, 2023_report_40_pages, VAM-3852AO, hubspot-deck, hubspot-q4, kiski


| Strategy  | Chunks | Avg Tok | R@1   | R@3   | R@5   | R@10  |
| --------- | ------ | ------- | ----- | ----- | ----- | ----- |
| pdftriage | 57     | 0       | 0.622 | 0.622 | 0.622 | 0.622 |


---

## Run: 2026-03-23 13:00 | pipeline + hybrid

**Documents**: 10Q, 2023_report_40_pages, VAM-3852AO, hubspot-deck, hubspot-q4, kiski, report


| Strategy             | Chunks | Avg Tok | R@1   | R@3   | R@5   | R@10  |
| -------------------- | ------ | ------- | ----- | ----- | ----- | ----- |
| page_level           | 20     | 7388    | 0.656 | 0.900 | 0.900 | 0.964 |
| fixed_512            | 75     | 436     | 0.598 | 0.806 | 0.867 | 0.925 |
| fixed_512_overlap102 | 84     | 436     | 0.605 | 0.820 | 0.861 | 0.925 |
| heading_based        | 69     | 401     | 0.523 | 0.768 | 0.850 | 0.882 |
| recursive            | 97     | 352     | 0.549 | 0.802 | 0.835 | 0.954 |
| element_type         | 84     | 355     | 0.419 | 0.698 | 0.812 | 0.911 |
| chonkie_512          | 118    | 255     | 0.521 | 0.748 | 0.808 | 0.882 |
| semantic             | 175    | 187     | 0.512 | 0.704 | 0.804 | 0.896 |
| structure_aware      | 106    | 273     | 0.548 | 0.768 | 0.800 | 0.896 |
| table_aware          | 113    | 260     | 0.480 | 0.733 | 0.798 | 0.925 |
| fixed_256            | 144    | 219     | 0.501 | 0.687 | 0.777 | 0.885 |



---

## Run: 2026-03-23 14:32 | pipeline + hybrid

**Documents**: 10Q, 2023_report_40_pages, VAM-3852AO, hubspot-deck, hubspot-q4, kiski, report


| Strategy | Chunks | Avg Tok | R@1 | R@3 | R@5 | R@10 | MRR |
|----------|:------:|:-------:|:---:|:---:|:---:|:----:|:---:|
| page_level | 34 | 1201 | 0.717 | 0.839 | 0.918 | 0.982 | 0.799 |
| structure_aware | 103 | 302 | 0.639 | 0.754 | 0.829 | 0.939 | 0.726 |
| fixed_512_overlap102 | 89 | 407 | 0.573 | 0.835 | 0.925 | 0.968 | 0.717 |
| recursive | 105 | 312 | 0.550 | 0.831 | 0.889 | 0.968 | 0.695 |
| heading_based | 73 | 394 | 0.549 | 0.785 | 0.875 | 0.982 | 0.695 |
| table_aware | 117 | 266 | 0.515 | 0.777 | 0.879 | 0.939 | 0.674 |
| element_type | 91 | 374 | 0.551 | 0.712 | 0.825 | 0.954 | 0.663 |
| chonkie_512 | 123 | 262 | 0.512 | 0.756 | 0.861 | 0.939 | 0.662 |
| semantic | 182 | 188 | 0.510 | 0.736 | 0.857 | 0.954 | 0.647 |

---

## Run: 2026-03-23 16:32 | pipeline + hybrid

**Documents**: 10Q, 2023_report_40_pages, VAM-3852AO, hubspot-deck, hubspot-q4, kiski, report


| Strategy | Chunks | Avg Tok | R@1 | R@3 | R@5 | R@10 | MRR | LLM@5 |
|----------|:------:|:-------:|:---:|:---:|:---:|:----:|:---:|:-----:|
| page_level | 34 | 1201 | 0.717 | 0.839 | 0.918 | 0.982 | 0.799 | 0.863 |
| chonkie_512 | 123 | 262 | 0.512 | 0.756 | 0.861 | 0.939 | 0.662 | 0.794 |

---

## Run: 2026-03-23 16:51 | pipeline + hybrid

**Documents**: 10Q, 2023_report_40_pages, VAM-3852AO, hubspot-deck, hubspot-q4, kiski, report


| Strategy | Chunks | Avg Tok | R@1 | R@3 | R@5 | R@10 | MRR | LLM@5 |
|----------|:------:|:-------:|:---:|:---:|:---:|:----:|:---:|:-----:|
| chonkie_512 | 123 | 262 | 0.512 | 0.756 | 0.861 | 0.939 | 0.662 | 0.794 |

---

## Run: 2026-03-23 17:27 | pipeline + hybrid

**Documents**: 10Q, 2023_report_40_pages, VAM-3852AO, hubspot-deck, hubspot-q4, kiski, report


| Strategy | Chunks | Avg Tok | R@1 | R@3 | R@5 | R@10 | MRR | LLM@5 |
|----------|:------:|:-------:|:---:|:---:|:---:|:----:|:---:|:-----:|
| chonkie_512 | 122 | 261 | 0.544 | 0.774 | 0.875 | 0.982 | 0.686 | 0.823 |

---

## Run: 2026-03-23 20:16 | pipeline + hybrid

**Documents**: 10Q, 2023_report_40_pages, VAM-3852AO, hubspot-deck, hubspot-q4, kiski, report


| Strategy | Chunks | Avg Tok | R@1 | R@3 | R@5 | R@10 | MRR | LLM@5 |
|----------|:------:|:-------:|:---:|:---:|:---:|:----:|:---:|:-----:|
| chonkie_512 | 114 | 280 | 0.612 | 0.780 | 0.893 | 0.968 | 0.728 | 0.911 |

---

## Run: 2026-03-24 09:36 | pipeline + hybrid

**Documents**: 10Q, 2023_report_40_pages, VAM-3852AO, hubspot-deck, hubspot-q4, kiski, report


| Strategy | Chunks | Avg Tok | R@1 | R@3 | R@5 | R@10 | MRR |
|----------|:------:|:-------:|:---:|:---:|:---:|:----:|:---:|
| page_level | 34 | 1176 | 0.602 | 0.837 | 0.936 | 0.982 | 0.740 |
| fixed_512_overlap102 | 88 | 401 | 0.591 | 0.835 | 0.907 | 0.954 | 0.730 |
| chonkie_512 | 115 | 283 | 0.547 | 0.769 | 0.893 | 0.954 | 0.697 |
| recursive | 103 | 327 | 0.559 | 0.808 | 0.849 | 0.954 | 0.694 |
| structure_aware | 107 | 291 | 0.600 | 0.690 | 0.814 | 0.907 | 0.693 |
| heading_based | 75 | 385 | 0.538 | 0.796 | 0.875 | 0.954 | 0.684 |
| table_aware | 123 | 258 | 0.539 | 0.763 | 0.850 | 0.939 | 0.679 |
| semantic | 187 | 180 | 0.569 | 0.764 | 0.843 | 0.911 | 0.677 |
| element_type | 97 | 349 | 0.479 | 0.681 | 0.785 | 0.939 | 0.617 |

---

## Run: 2026-03-25 11:10 | pipeline + hybrid

**Documents**: 


| Strategy | Chunks | Avg Tok | R@1 | R@3 | R@5 | R@10 | MRR |
|----------|:------:|:-------:|:---:|:---:|:---:|:----:|:---:|

---

## Run: 2026-03-25 11:13 | pipeline + hybrid

**Documents**: meta_10q


| Strategy | Chunks | Avg Tok | R@1 | R@3 | R@5 | R@10 | MRR | LLM@5 |
|----------|:------:|:-------:|:---:|:---:|:---:|:----:|:---:|:-----:|
| chonkie_512 | 293 | 290 | 0.533 | 0.867 | 0.867 | 1.000 | 0.683 | 0.867 |
