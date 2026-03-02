#!/usr/bin/env python3
"""
download_papers.py - Download a PDF from a URL into biblioteca/.

Handles arXiv, IACR ePrint, and general URLs.
Uses only stdlib (urllib) — no external dependencies.

Usage:
    python3 download_papers.py --url "https://arxiv.org/abs/2301.01234" --folder ntt
    python3 download_papers.py --url "https://eprint.iacr.org/2023/123" --folder criptografia --name "paper-name"
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

BIBLIO_DIR = Path.home() / "Documents" / "claudio" / "biblioteca"
TIMEOUT = 30  # seconds
MAX_SIZE_MB = 50


def normalize_url(url: str) -> str:
    """Convert abstract page URLs to direct PDF download URLs."""
    # arXiv: abs/XXXX.XXXXX → pdf/XXXX.XXXXX.pdf
    arxiv_match = re.match(r"https?://arxiv\.org/abs/(\d+\.\d+)(v\d+)?", url)
    if arxiv_match:
        arxiv_id = arxiv_match.group(1)
        version = arxiv_match.group(2) or ""
        return f"https://arxiv.org/pdf/{arxiv_id}{version}.pdf"

    # IACR ePrint: eprint.iacr.org/YYYY/NNN → eprint.iacr.org/YYYY/NNN.pdf
    eprint_match = re.match(r"https?://eprint\.iacr\.org/(\d{4}/\d+)$", url)
    if eprint_match:
        return f"https://eprint.iacr.org/{eprint_match.group(1)}.pdf"

    return url


def derive_filename(url: str, name: Optional[str] = None) -> str:
    """Derive a sensible filename from URL or explicit name."""
    if name:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "-", name).strip("-")
        if not safe.lower().endswith(".pdf"):
            safe += ".pdf"
        return safe

    # Try to extract from URL path
    path = url.rstrip("/").split("/")[-1]
    path = re.sub(r"\?.*$", "", path)  # strip query params

    if not path.lower().endswith(".pdf"):
        # arXiv IDs, ePrint numbers, etc.
        safe = re.sub(r"[^a-zA-Z0-9._-]", "-", path).strip("-")
        return f"{safe}.pdf" if safe else "download.pdf"

    return path


def download(url: str, folder: str, name: Optional[str] = None) -> dict:
    """Download a PDF and save to biblioteca/{folder}/."""
    target_dir = BIBLIO_DIR / folder
    target_dir.mkdir(parents=True, exist_ok=True)

    pdf_url = normalize_url(url)
    filename = derive_filename(pdf_url, name)
    target_path = target_dir / filename

    # Check for duplicates
    if target_path.exists():
        return {
            "status": "skipped",
            "reason": "file already exists",
            "path": str(target_path),
            "size_bytes": target_path.stat().st_size,
        }

    try:
        req = urllib.request.Request(pdf_url, headers={
            "User-Agent": "Mozilla/5.0 (research-tool; academic use)",
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            content_type = response.headers.get("Content-Type", "")
            data = response.read()

            # Size check
            if len(data) > MAX_SIZE_MB * 1024 * 1024:
                return {
                    "status": "error",
                    "error": f"File too large: {len(data) / 1024 / 1024:.1f}MB (max {MAX_SIZE_MB}MB)",
                    "url": url,
                }

            # Basic PDF validation
            if not data[:5] == b"%PDF-" and "pdf" not in content_type.lower():
                return {
                    "status": "error",
                    "error": f"Not a PDF (content-type: {content_type})",
                    "url": url,
                }

            target_path.write_bytes(data)

        return {
            "status": "downloaded",
            "path": str(target_path),
            "size_bytes": len(data),
            "url": url,
            "folder": folder,
        }

    except urllib.error.HTTPError as e:
        return {"status": "error", "error": f"HTTP {e.code}: {e.reason}", "url": url}
    except urllib.error.URLError as e:
        return {"status": "error", "error": f"URL error: {e.reason}", "url": url}
    except TimeoutError:
        return {"status": "error", "error": f"Timeout after {TIMEOUT}s", "url": url}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}", "url": url}


def main():
    parser = argparse.ArgumentParser(description="Download a PDF into biblioteca/")
    parser.add_argument("--url", "-u", required=True, help="URL to download")
    parser.add_argument("--folder", "-f", required=True, help="Target folder in biblioteca/")
    parser.add_argument("--name", "-n", default=None, help="Custom filename (optional)")
    args = parser.parse_args()

    result = download(args.url, args.folder, args.name)
    print(json.dumps(result, indent=2))

    if result["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
