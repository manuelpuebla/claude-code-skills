#!/usr/bin/env python3
"""
study_all.py - Index all PDFs in the entire biblioteca.

1. Iterates all folders with PDFs
2. Calls study_folder for each
3. Generates _global_topic_index.md
4. Builds concept graph
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    INDICES_DIR, GLOBAL_INDEX_PATH,
    create_gemini_client, get_pdf_folders, folder_index_path,
)
from study_folder import study_folder
from build_graph import build_graph

GEMINI_MODEL = "gemini-2.0-flash"

GLOBAL_INDEX_PROMPT = """You are creating a master index for a research library organized by topic.

Given folder indices from different categories, produce a unified global topic index.

Output format (markdown):

# Biblioteca: Global Topic Index

## Overview
{2-3 sentences about the library's scope and coverage}

## Categories

{For each category/folder:}
### {Category Name}
- **Documents**: {count}
- **Scope**: {1-2 sentences}
- **Key Topics**: {comma-separated}

## Cross-Category Topic Map

{Group topics that appear across multiple categories}

| Topic | Categories | Key Documents |
|-------|------------|---------------|
| {topic} | {cat1}, {cat2} | {doc1}, {doc2} |

## Research Pathways

{Suggest 3-5 research pathways through the library, each a sequence of categories/documents for different goals}

### Pathway 1: {Goal}
{Ordered list of documents/categories to read}

IMPORTANT:
- Use actual document names and topics from the summaries
- Focus on cross-cutting themes
- Keep output between 1500-4000 tokens
"""


def study_all(force: bool = False, verbose: bool = False, full_graph: bool = False) -> dict:
    """Index everything: all folders, global index, concept graph."""
    folders = get_pdf_folders()

    if not folders:
        return {"status": "error", "error": "No PDF folders found in biblioteca"}

    print(f"Found {len(folders)} folders with PDFs", file=sys.stderr)

    # Phase 1: Index each folder
    folder_results = {}
    total_indexed = 0
    total_skipped = 0
    total_errors = 0

    for i, folder in enumerate(folders, 1):
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"[{i}/{len(folders)}] Indexing folder: {folder}/", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

        result = study_folder(folder, force=force, verbose=verbose)
        folder_results[folder] = result

        if result.get("status") == "completed":
            total_indexed += result.get("indexed", 0)
            total_skipped += result.get("skipped", 0)
            total_errors += result.get("errors", 0)
        else:
            print(f"  ERROR: {result.get('error', 'unknown')}", file=sys.stderr)

    # Phase 2: Generate global topic index
    print(f"\n{'='*60}", file=sys.stderr)
    print("Generating global topic index...", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    folder_indices = []
    for folder in folders:
        idx = folder_index_path(folder)
        if idx.exists():
            folder_indices.append(f"### Category: {folder}\n{idx.read_text()}")

    if folder_indices:
        combined = "\n\n---\n\n".join(folder_indices)
        prompt = f"""{GLOBAL_INDEX_PROMPT}

## Folder Indices ({len(folder_indices)} categories):

{combined}
"""
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
                GLOBAL_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
                GLOBAL_INDEX_PATH.write_text(response.text)
                print(f"Global index written: {GLOBAL_INDEX_PATH}", file=sys.stderr)
            else:
                print("WARNING: Gemini returned no response for global index", file=sys.stderr)
        except Exception as e:
            print(f"WARNING: Failed to generate global index: {e}", file=sys.stderr)

    # Phase 3: Build concept graph
    print(f"\n{'='*60}", file=sys.stderr)
    print("Building concept graph...", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    graph_result = build_graph(verbose=verbose, full=full_graph)

    return {
        "status": "completed",
        "folders_processed": len(folders),
        "total_indexed": total_indexed,
        "total_skipped": total_skipped,
        "total_errors": total_errors,
        "global_index": str(GLOBAL_INDEX_PATH) if GLOBAL_INDEX_PATH.exists() else None,
        "graph": graph_result,
    }


def main():
    parser = argparse.ArgumentParser(description="Index all PDFs in the biblioteca")
    parser.add_argument("--force", "-f", action="store_true",
                        help="Re-index even if already indexed")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed progress")
    parser.add_argument("--full-graph", action="store_true",
                        help="Force full graph rebuild (ignore incremental cache)")
    args = parser.parse_args()

    result = study_all(force=args.force, verbose=args.verbose, full_graph=args.full_graph)
    print(json.dumps(result, indent=2))

    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
