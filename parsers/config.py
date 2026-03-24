"""
Centralized configuration for the PDF parsing pipeline.

All token limits, DPI settings, and model defaults live here
so there's one place to change them.
"""

# ---------------------------------------------------------------------------
# Output token limits for LLM calls
# ---------------------------------------------------------------------------

# Full page extraction (pipeline.py, vision_llm.py)
# Needs to be high — dense financial pages can produce long markdown
MAX_TOKENS_PAGE_EXTRACTION = 32768

# Chart/image description (hybrid_parser.py)
# Charts need moderate output — data points, trends, labels
MAX_TOKENS_CHART_DESCRIPTION = 4096

# Query answering (query_router.py)
# Answers are typically short but can include table data
MAX_TOKENS_QUERY_ANSWER = 4096

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

# DPI for rendering PDF pages to images for vision LLMs
# 200 DPI = 1700x2200 pixels for letter-size, good balance of quality vs cost
DEFAULT_DPI = 200

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

DEFAULT_VISION_MODEL = "claude-sonnet-4-20250514"
DEFAULT_FAST_MODEL = "gpt-4.1-mini"
