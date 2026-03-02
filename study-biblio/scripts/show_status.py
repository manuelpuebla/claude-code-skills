#!/usr/bin/env python3
"""
show_status.py - Show indexing status of the biblioteca.

Displays per-folder breakdown of indexed vs pending PDFs.
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    BIBLIO_DIR, INDICES_DIR, MANIFEST_PATH, CONCEPT_GRAPH_PATH,
    GLOBAL_INDEX_PATH, load_manifest, walk_pdfs, rel_path, hash_pdf,
)


def get_status() -> dict:
    """Compute indexing status."""
    manifest = load_manifest()
    indexed_pdfs = manifest.get("pdfs", {})

    # Walk all PDFs and categorize
    folders = defaultdict(lambda: {"total": 0, "indexed": 0, "pending": [], "stale": []})

    for pdf in walk_pdfs():
        rp = rel_path(pdf)
        folder = str(pdf.parent.relative_to(BIBLIO_DIR))
        folders[folder]["total"] += 1

        entry = indexed_pdfs.get(rp)
        if entry:
            # Check if hash still matches (detect modified PDFs)
            current_hash = hash_pdf(pdf)
            if entry.get("sha256") == current_hash:
                folders[folder]["indexed"] += 1
            else:
                folders[folder]["stale"].append(pdf.name)
        else:
            folders[folder]["pending"].append(pdf.name)

    return dict(folders)


def format_status(status: dict) -> str:
    """Format status for display."""
    lines = []
    lines.append("# Biblioteca Indexing Status\n")

    total_all = 0
    indexed_all = 0
    pending_all = 0
    stale_all = 0

    # Sort folders
    for folder in sorted(status.keys()):
        info = status[folder]
        total = info["total"]
        indexed = info["indexed"]
        pending = len(info["pending"])
        stale = len(info["stale"])

        total_all += total
        indexed_all += indexed
        pending_all += pending
        stale_all += stale

        pct = (indexed / total * 100) if total > 0 else 0
        bar_len = 20
        filled = int(pct / 100 * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)

        status_icon = "✓" if indexed == total else ("◐" if indexed > 0 else "○")
        lines.append(f"{status_icon} **{folder}**: [{bar}] {indexed}/{total} ({pct:.0f}%)")

        if stale:
            for name in stale:
                lines.append(f"    ⚠ stale: {name}")

    # Summary
    pct_all = (indexed_all / total_all * 100) if total_all > 0 else 0
    lines.insert(1, f"**Total**: {indexed_all}/{total_all} PDFs indexed ({pct_all:.0f}%)")
    if stale_all:
        lines.insert(2, f"**Stale**: {stale_all} PDFs modified since indexing")
    if pending_all:
        lines.insert(2, f"**Pending**: {pending_all} PDFs not yet indexed")
    lines.insert(2, "")

    # Check auxiliary files
    lines.append("")
    lines.append("## Auxiliary Files")
    lines.append(f"{'✓' if MANIFEST_PATH.exists() else '○'} manifest.json")
    lines.append(f"{'✓' if GLOBAL_INDEX_PATH.exists() else '○'} _global_topic_index.md")
    lines.append(f"{'✓' if CONCEPT_GRAPH_PATH.exists() else '○'} _concept_graph.json")

    # Check folder indices
    folder_indices = list(INDICES_DIR.rglob("_folder_index.md"))
    lines.append(f"{'✓' if folder_indices else '○'} Folder indices: {len(folder_indices)} generated")

    return "\n".join(lines)


def main():
    status = get_status()
    print(format_status(status))


if __name__ == "__main__":
    main()
