#!/usr/bin/env python3
"""
slugify_topic.py - Generate a filesystem-safe slug from a study object description.

Usage:
    python3 slugify_topic.py "NTT optimization for Poseidon hash"
    → ntt_optimization_for_poseidon_hash
"""

import re
import sys
import unicodedata


def slugify(text: str, max_length: int = 60) -> str:
    """Convert a description to a filesystem-safe slug using underscores."""
    # Normalize unicode
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    # Lowercase
    text = text.lower()
    # Replace non-alphanumeric with underscores
    text = re.sub(r"[^a-z0-9]+", "_", text)
    # Collapse multiple underscores
    text = re.sub(r"_+", "_", text)
    # Strip leading/trailing underscores
    text = text.strip("_")
    # Truncate
    if len(text) > max_length:
        text = text[:max_length].rstrip("_")
    return text


def main():
    if len(sys.argv) < 2:
        print("Usage: slugify_topic.py \"description\"", file=sys.stderr)
        sys.exit(1)

    description = " ".join(sys.argv[1:])
    print(slugify(description))


if __name__ == "__main__":
    main()
