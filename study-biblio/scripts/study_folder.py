#!/usr/bin/env python3
"""
study_folder.py - Index all PDFs in a biblioteca folder.

1. Finds all PDFs in the specified folder
2. Calls study_pdf.process_pdf() for each unindexed one
3. Reads all per-PDF summaries
4. Calls Gemini to synthesize a _folder_index.md

Usage:
    python3 study_folder.py ntt
    python3 study_folder.py criptografia --force
    python3 study_folder.py finanzas/estadistica
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    BIBLIO_DIR, INDICES_DIR,
    create_gemini_client, folder_index_path, walk_pdfs,
    rel_path, summary_path, load_manifest,
)
from study_pdf import process_pdf

GEMINI_MODEL = "gemini-2.0-flash"

FOLDER_INDEX_PROMPT = """You are an academic librarian creating a folder index for a research library.

Given summaries of all PDFs in a folder, produce a unified folder index in markdown.

Output format:

# {Folder Name}: Folder Index

## Overview
{2-3 sentences describing what this collection covers}

## Documents ({count} papers)

{For each document, a compact entry:}
### {Title}
- **Authors**: {authors} | **Year**: {year} | **Type**: {type} | **Pages**: {pages}
- **Key contribution**: {1 sentence}
- **Topics**: {comma-separated list of 3-7 key topics}

## Topic Map
{Group documents by shared topics. Each topic lists which documents cover it.}

| Topic | Documents |
|-------|-----------|
| {topic} | {doc1}, {doc2}, ... |

## Reading Order (Suggested)
{Suggest a reading order based on prerequisite dependencies. List documents from foundational to advanced.}

IMPORTANT:
- Be precise and use the actual document contents, not generic descriptions.
- The topic map should help researchers find documents by concept.
- Keep total output between 1000-3000 tokens.
"""


def study_folder(folder_name: str, force: bool = False, verbose: bool = False) -> dict:
    """Index all PDFs in a folder and generate _folder_index.md.

    Args:
        folder_name: Relative path from biblioteca (e.g., "ntt", "finanzas/estadistica")
        force: Re-index even if already indexed
        verbose: Print detailed progress

    Returns:
        Result dict with counts and status.
    """
    folder_path = BIBLIO_DIR / folder_name

    if not folder_path.exists():
        return {"status": "error", "error": f"Folder not found: {folder_path}"}

    # Find all PDFs in this folder (non-recursive - only direct children)
    pdfs = [p for p in walk_pdfs(folder_path) if p.parent == folder_path]

    if not pdfs:
        return {"status": "error", "error": f"No PDFs found in {folder_name}/"}

    # Phase 1: Index individual PDFs
    results = {"indexed": 0, "skipped": 0, "errors": 0, "details": []}

    for i, pdf in enumerate(pdfs, 1):
        if verbose:
            print(f"\n[{i}/{len(pdfs)}] {pdf.name}", file=sys.stderr)

        result = process_pdf(pdf, force=force)
        results["details"].append(result)

        if result["status"] == "indexed":
            results["indexed"] += 1
        elif result["status"] == "skipped":
            results["skipped"] += 1
        else:
            results["errors"] += 1
            print(f"  ERROR: {result.get('error', 'unknown')}", file=sys.stderr)

    # Phase 2: Generate _folder_index.md from all summaries
    print(f"\nGenerating folder index for {folder_name}/...", file=sys.stderr)

    summaries = []
    for pdf in pdfs:
        sp = summary_path(pdf)
        if sp.exists():
            summaries.append(sp.read_text())

    if not summaries:
        results["folder_index"] = "skipped (no summaries available)"
        return results

    combined = "\n\n---\n\n".join(summaries)

    prompt = f"""{FOLDER_INDEX_PROMPT}

## Folder: {folder_name}
## Number of documents: {len(summaries)}

## Individual Summaries:

{combined}

Generate the folder index now."""

    client = create_gemini_client()
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={
                "temperature": 0.2,
                "max_output_tokens": 4096,
            }
        )
        if response and response.text:
            idx_path = folder_index_path(folder_name)
            idx_path.parent.mkdir(parents=True, exist_ok=True)
            idx_path.write_text(response.text)
            results["folder_index"] = str(idx_path.relative_to(INDICES_DIR))
            print(f"Folder index written: {results['folder_index']}", file=sys.stderr)
        else:
            results["folder_index"] = "error: Gemini returned no response"
    except Exception as e:
        results["folder_index"] = f"error: {type(e).__name__}: {e}"

    results["status"] = "completed"
    results["total"] = len(pdfs)
    return results


def main():
    parser = argparse.ArgumentParser(description="Index all PDFs in a biblioteca folder")
    parser.add_argument("folder", type=str,
                        help="Folder name relative to biblioteca (e.g., 'ntt', 'criptografia')")
    parser.add_argument("--force", "-f", action="store_true",
                        help="Re-index even if already indexed")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed progress")
    args = parser.parse_args()

    result = study_folder(args.folder, force=args.force, verbose=args.verbose)
    print(json.dumps(result, indent=2))

    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
