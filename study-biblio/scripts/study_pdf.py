#!/usr/bin/env python3
"""
study_pdf.py - Process ONE PDF into a structured summary.

Flow:
1. Extract text from PDF using PyMuPDF (fitz)
2. Apply sampling strategy for large documents (>50 pages)
3. Send extracted text to Gemini Flash for summarization
4. Write summary .md to indices/<folder>/<slug>.md
5. Update manifest
6. Output minimal JSON to stdout

IMPORTANT: Raw PDF text never enters Claude's context.
All processing happens in this separate Python process.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF

# Add parent dir to path for utils
sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    BIBLIO_DIR, INDICES_DIR,
    create_gemini_client, hash_pdf, is_indexed,
    load_manifest, rel_path, save_manifest, slugify, summary_path,
)

# Gemini Flash for fast, cheap extraction
GEMINI_MODEL = "gemini-2.0-flash"

# Sampling thresholds
MAX_PAGES_FULL = 50       # Read all pages if <= this
SAMPLE_PAGES_LARGE = 30   # Sample this many pages from large docs
MAX_CHARS_PER_PAGE = 4000 # Truncate individual pages

SUMMARY_SYSTEM_PROMPT = """You are an academic indexer. Given extracted text from a PDF document, produce a structured summary for a research index.

Output format (markdown):

# {Title}

**Authors**: {authors or "Unknown"}
**Year**: {year or "Unknown"}
**Type**: {paper|textbook|thesis|technical-report|slides|notes}
**Pages**: {approximate page count}

## Abstract / Overview
{2-4 sentences capturing the main contribution or topic}

## Key Concepts
{Bulleted list of 5-15 key concepts, techniques, or algorithms discussed}

## Mathematical Objects
{Bulleted list of key mathematical objects: groups, fields, polynomials, transforms, etc. If none, write "N/A"}

## Dependencies (Prerequisite Knowledge)
{Bulleted list of concepts the reader should know BEFORE reading this. E.g., "modular arithmetic", "polynomial rings", "FFT"}

## Applications
{Bulleted list of where these techniques are applied}

## Sections
{List of major sections/chapters with page ranges. Format: "- **p.X-Y**: Section title — brief description of content"}
{Use the PDF's table of contents if provided. Otherwise, infer sections from the extracted text page markers.}
{For short papers (<15 pages): list 3-6 sections}
{For long documents (>50 pages): list 8-15 major sections/chapters, skip subsections}

## Related Topics
{Bulleted list of related research areas or papers}

IMPORTANT:
- Be precise and technical. This index is for a mathematician/cryptographer.
- Extract ACTUAL content, not generic descriptions.
- Key Concepts should be specific enough to distinguish this paper from others.
- The Sections list MUST include page numbers so the reader knows WHERE to find each topic.
- Keep total output between 700-2500 tokens.
"""


def extract_toc(doc) -> str:
    """Extract table of contents from PDF outline/bookmarks.

    Returns formatted TOC string, or empty string if none.
    """
    toc = doc.get_toc()  # [[level, title, page], ...]
    if not toc:
        return ""

    lines = ["## PDF Table of Contents (from bookmarks)"]
    for level, title, page in toc:
        indent = "  " * (level - 1)
        lines.append(f"{indent}- p.{page}: {title}")
    return "\n".join(lines)


def extract_text(pdf_path: Path) -> tuple[str, int, str]:
    """Extract text from PDF using PyMuPDF.

    Returns (extracted_text, total_pages, toc_string).
    Uses sampling strategy for large documents.
    """
    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)

    # Extract TOC from PDF bookmarks
    toc = extract_toc(doc)

    if total_pages <= MAX_PAGES_FULL:
        # Read all pages
        pages_to_read = range(total_pages)
    else:
        # Sampling strategy for large documents:
        # - First 10 pages (intro, abstract, TOC)
        # - Last 5 pages (conclusion, references)
        # - Evenly spaced pages from the middle
        first_n = 10
        last_n = 5
        middle_count = SAMPLE_PAGES_LARGE - first_n - last_n

        first_pages = list(range(min(first_n, total_pages)))
        last_pages = list(range(max(total_pages - last_n, first_n), total_pages))

        middle_start = first_n
        middle_end = total_pages - last_n
        if middle_count > 0 and middle_end > middle_start:
            step = max(1, (middle_end - middle_start) // middle_count)
            middle_pages = list(range(middle_start, middle_end, step))[:middle_count]
        else:
            middle_pages = []

        pages_to_read = sorted(set(first_pages + middle_pages + last_pages))

    chunks = []
    for page_num in pages_to_read:
        page = doc[page_num]
        text = page.get_text()
        if text.strip():
            # Truncate very long pages
            if len(text) > MAX_CHARS_PER_PAGE:
                text = text[:MAX_CHARS_PER_PAGE] + "\n[... page truncated ...]"
            chunks.append(f"--- Page {page_num + 1}/{total_pages} ---\n{text}")

    doc.close()

    extracted = "\n\n".join(chunks)
    return extracted, total_pages, toc


def summarize_with_gemini(client, text: str, pdf_name: str, toc: str = "") -> str:
    """Send extracted text to Gemini Flash for summarization."""
    toc_section = ""
    if toc:
        toc_section = f"\n{toc}\n"

    prompt = f"""{SUMMARY_SYSTEM_PROMPT}

## Document
Filename: {pdf_name}
{toc_section}
## Extracted Text
{text}

Generate the structured summary now."""

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={
                "temperature": 0.2,
                "max_output_tokens": 3072,
            }
        )
        if response is None or response.text is None:
            return f"ERROR: Gemini returned no response for {pdf_name}"
        return response.text
    except Exception as e:
        return f"ERROR summarizing {pdf_name}: {type(e).__name__}: {e}"


def process_pdf(pdf_path: Path, force: bool = False) -> dict:
    """Process a single PDF: extract, summarize, save.

    Returns a result dict with status info.
    """
    pdf_path = pdf_path.resolve()

    if not pdf_path.exists():
        return {"status": "error", "error": f"File not found: {pdf_path}"}

    if not pdf_path.suffix.lower() == '.pdf':
        return {"status": "error", "error": f"Not a PDF: {pdf_path}"}

    # Check if within biblioteca
    try:
        rp = rel_path(pdf_path)
    except ValueError:
        return {"status": "error", "error": f"PDF not in biblioteca: {pdf_path}"}

    # Hash and check manifest
    pdf_hash = hash_pdf(pdf_path)
    manifest = load_manifest()

    if not force and is_indexed(manifest, rp, pdf_hash):
        return {
            "status": "skipped",
            "path": rp,
            "reason": "already indexed (same hash)",
        }

    # Extract text
    t0 = time.time()
    print(f"Extracting text from: {pdf_path.name}", file=sys.stderr)
    text, total_pages, toc = extract_text(pdf_path)
    t_extract = time.time() - t0

    if not text.strip():
        return {
            "status": "error",
            "path": rp,
            "error": "No text extracted (possibly scanned/image-only PDF)",
        }

    toc_info = f", TOC: {len(toc)} chars" if toc else ", no TOC"
    print(f"  Extracted {len(text)} chars from {total_pages} pages in {t_extract:.1f}s{toc_info}",
          file=sys.stderr)

    # Summarize with Gemini
    t1 = time.time()
    print(f"  Summarizing with {GEMINI_MODEL}...", file=sys.stderr)
    client = create_gemini_client()
    summary = summarize_with_gemini(client, text, pdf_path.name, toc=toc)
    t_summarize = time.time() - t1

    if summary.startswith("ERROR"):
        return {"status": "error", "path": rp, "error": summary}

    # Write summary to disk
    out_path = summary_path(pdf_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(summary)

    print(f"  Summary written: {out_path.relative_to(INDICES_DIR)} ({len(summary)} chars, {t_summarize:.1f}s)",
          file=sys.stderr)

    # Update manifest
    manifest.setdefault("pdfs", {})[rp] = {
        "sha256": pdf_hash,
        "summary_path": str(out_path.relative_to(INDICES_DIR)),
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "pages": total_pages,
        "size_bytes": pdf_path.stat().st_size,
    }
    save_manifest(manifest)

    return {
        "status": "indexed",
        "path": rp,
        "summary_path": str(out_path.relative_to(INDICES_DIR)),
        "pages": total_pages,
        "extract_time": round(t_extract, 1),
        "summarize_time": round(t_summarize, 1),
        "summary_chars": len(summary),
    }


def main():
    parser = argparse.ArgumentParser(description="Study a single PDF and generate summary")
    parser.add_argument("pdf_path", type=str, help="Path to the PDF file")
    parser.add_argument("--force", "-f", action="store_true",
                        help="Re-index even if already indexed")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path).resolve()
    result = process_pdf(pdf_path, force=args.force)

    # Output minimal JSON to stdout (for orchestration)
    print(json.dumps(result, indent=2))

    # Exit code
    if result["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
