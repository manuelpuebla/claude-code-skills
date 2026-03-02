#!/usr/bin/env python3
"""
Utility functions for study-biblio skill.

Provides: manifest management, PDF hashing, path helpers, slugify, walk_pdfs.
"""

import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Iterator

# === Path constants ===

BIBLIO_DIR = Path.home() / "Documents" / "claudio" / "biblioteca"
INDICES_DIR = BIBLIO_DIR / "indices"
MANIFEST_PATH = INDICES_DIR / "manifest.json"
GLOBAL_INDEX_PATH = INDICES_DIR / "_global_topic_index.md"
CONCEPT_GRAPH_PATH = INDICES_DIR / "_concept_graph.json"

# Folders to skip when walking the biblioteca
SKIP_FOLDERS = {"indices", "videos", "transcripciones"}

# === Manifest ===

def load_manifest() -> dict:
    """Load the indexing manifest from disk.

    Structure:
    {
        "version": 1,
        "pdfs": {
            "<relative_path>": {
                "sha256": "...",
                "summary_path": "...",
                "indexed_at": "...",
                "pages": N,
                "size_bytes": N
            }
        }
    }
    """
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"version": 1, "pdfs": {}}


def save_manifest(manifest: dict) -> None:
    """Save the manifest to disk."""
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


def is_indexed(manifest: dict, rel_path: str, current_hash: str) -> bool:
    """Check if a PDF is already indexed with the same hash."""
    entry = manifest.get("pdfs", {}).get(rel_path)
    if not entry:
        return False
    return entry.get("sha256") == current_hash


# === Hashing ===

def hash_pdf(path: Path) -> str:
    """Compute SHA256 hash of a PDF file (first 1MB for speed)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        # Read first 1MB - sufficient for change detection
        data = f.read(1024 * 1024)
        h.update(data)
        # Also include file size for extra discrimination
        f.seek(0, 2)
        h.update(str(f.tell()).encode())
    return h.hexdigest()


# === Slugify ===

def slugify(name: str) -> str:
    """Convert a PDF filename to a safe slug for the summary .md file.

    Example: "POSEIDON - A New Hash (Grassi, domain-separation).pdf"
             -> "poseidon-a-new-hash-grassi-domain-separation"
    """
    # Remove extension
    name = re.sub(r'\.pdf$', '', name, flags=re.IGNORECASE)
    # Normalize unicode
    name = unicodedata.normalize('NFKD', name)
    name = name.encode('ascii', 'ignore').decode('ascii')
    # Replace non-alphanumeric with hyphens
    name = re.sub(r'[^a-zA-Z0-9]+', '-', name)
    # Collapse multiple hyphens
    name = re.sub(r'-+', '-', name)
    # Strip leading/trailing hyphens, lowercase
    name = name.strip('-').lower()
    # Truncate to reasonable length
    if len(name) > 80:
        name = name[:80].rstrip('-')
    return name


# === Path helpers ===

def rel_path(pdf_path: Path) -> str:
    """Get path relative to BIBLIO_DIR."""
    return str(pdf_path.relative_to(BIBLIO_DIR))


def summary_path(pdf_path: Path) -> Path:
    """Get the expected summary .md path for a PDF.

    biblioteca/ntt/foo.pdf -> indices/ntt/foo-slug.md
    """
    folder = pdf_path.parent.relative_to(BIBLIO_DIR)
    slug = slugify(pdf_path.name)
    return INDICES_DIR / folder / f"{slug}.md"


def folder_index_path(folder_rel: str) -> Path:
    """Get the _folder_index.md path for a folder."""
    return INDICES_DIR / folder_rel / "_folder_index.md"


# === Walk PDFs ===

def walk_pdfs(root: Path = None) -> Iterator[Path]:
    """Yield all PDF files in the biblioteca, skipping SKIP_FOLDERS."""
    root = root or BIBLIO_DIR
    for dirpath, dirnames, filenames in os.walk(root):
        # Filter out skip folders in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_FOLDERS]
        for f in sorted(filenames):
            if f.lower().endswith('.pdf'):
                yield Path(dirpath) / f


def get_pdf_folders(root: Path = None) -> list[str]:
    """Get list of folder relative paths that contain PDFs."""
    root = root or BIBLIO_DIR
    folders = set()
    for pdf in walk_pdfs(root):
        folder = pdf.parent.relative_to(BIBLIO_DIR)
        folders.add(str(folder))
    return sorted(folders)


# === Gemini client ===

def create_gemini_client():
    """Create Google GenAI client with API key (reuses collab-qa pattern)."""
    from google import genai

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        env_paths = [
            Path.home() / ".env",
            Path.home() / "lean4-agent-orchestra" / ".env",
            Path.home() / "Documents" / "claudio" / ".env",
        ]
        for env_path in env_paths:
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if line.startswith("GOOGLE_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break
            if api_key:
                break

    if not api_key:
        print("ERROR: GOOGLE_API_KEY not found", file=sys.stderr)
        print("Set GOOGLE_API_KEY env var or add to ~/.env", file=sys.stderr)
        sys.exit(1)

    return genai.Client(api_key=api_key)


if __name__ == "__main__":
    # Quick self-test
    import sys
    print(f"BIBLIO_DIR: {BIBLIO_DIR}")
    print(f"INDICES_DIR: {INDICES_DIR}")
    print(f"Exists: {BIBLIO_DIR.exists()}")

    pdfs = list(walk_pdfs())
    print(f"Total PDFs: {len(pdfs)}")

    folders = get_pdf_folders()
    print(f"Folders with PDFs: {folders}")

    if pdfs:
        sample = pdfs[0]
        print(f"\nSample: {sample.name}")
        print(f"  Slug: {slugify(sample.name)}")
        print(f"  Rel:  {rel_path(sample)}")
        print(f"  Sum:  {summary_path(sample)}")
        print(f"  Hash: {hash_pdf(sample)[:16]}...")
