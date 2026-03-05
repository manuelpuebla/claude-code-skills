#!/usr/bin/env python3
"""
Load Lessons - Thin wrapper around query_lessons.py

Delegates all operations to the centralized query_lessons.py script,
which supports keyword, semantic, and hybrid search modes.

Usage:
    python3 load_lessons.py <domain> [options]

Domains:
    lean4   - Formal verification in Lean 4 (471+ lessons)

Options:
    --search, -s "text"     Keyword search
    --hybrid, -q "text"     Hybrid keyword+semantic search (recommended)
    --semantic "text"       Pure semantic search
    --problem, -p "text"    Problem lookup from quick-reference table
    --lesson, -l ID         Get specific lesson by ID (e.g., L-153)
    --section SEC           Get full section (e.g., §47)
    --related, -r ID        Show related lessons from graph
    --list                  List all sections and lesson counts
"""

import subprocess
import sys
from pathlib import Path

QUERY_SCRIPT = Path.home() / "Documents" / "claudio" / "lecciones" / "scripts" / "query_lessons.py"

DOMAINS = {"lean4"}


def run_query(*args: str) -> None:
    """Run query_lessons.py with given arguments, print output."""
    result = subprocess.run(
        [sys.executable, str(QUERY_SCRIPT), *args],
        capture_output=True, text=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode != 0 and result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    sys.exit(result.returncode)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Load Lean 4 lessons (delegates to query_lessons.py)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s lean4 --list                              # List sections
  %(prog)s lean4 -q "omega multiplication"            # Hybrid search (recommended)
  %(prog)s lean4 --semantic "nonlinear arithmetic"    # Semantic search
  %(prog)s lean4 -s "omega"                           # Keyword search
  %(prog)s lean4 -p "omega no funciona"               # Problem lookup
  %(prog)s lean4 -l L-153                             # Exact lesson
  %(prog)s lean4 -r L-153                             # Related lessons
        """,
    )

    parser.add_argument("domain", nargs="?", default=None,
                        help="Domain (lean4)")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("-q", "--hybrid", type=str,
                       help="Hybrid keyword+semantic search (recommended)")
    group.add_argument("--semantic", type=str,
                       help="Pure semantic search")
    group.add_argument("-s", "--search", type=str,
                       help="Keyword search")
    group.add_argument("-p", "--problem", type=str,
                       help="Problem lookup from quick-reference table")
    group.add_argument("-l", "--lesson", type=str,
                       help="Get specific lesson by ID")
    group.add_argument("--section", type=str,
                       help="Get full section")
    group.add_argument("-r", "--related", type=str,
                       help="Related lessons from graph")
    group.add_argument("--list", action="store_true",
                       help="List all sections")

    args = parser.parse_args()

    if not args.domain:
        print("Available domains: lean4")
        print(f"\nUsage: {parser.prog} <domain> [options]")
        print(f"Help:  {parser.prog} --help")
        return

    if args.domain.lower() not in DOMAINS:
        print(f"Error: domain '{args.domain}' not found. Available: {', '.join(DOMAINS)}")
        sys.exit(1)

    if not QUERY_SCRIPT.exists():
        print(f"Error: query_lessons.py not found at {QUERY_SCRIPT}", file=sys.stderr)
        sys.exit(1)

    # Delegate to query_lessons.py
    if args.hybrid:
        run_query("--hybrid", args.hybrid)
    elif args.semantic:
        run_query("--semantic", args.semantic)
    elif args.search:
        run_query("--search", args.search)
    elif args.problem:
        run_query("--problem", args.problem)
    elif args.lesson:
        run_query("--lesson", args.lesson)
    elif args.section:
        run_query("--section", args.section)
    elif args.related:
        run_query("--related", args.related)
    elif args.list:
        run_query("--list")
    else:
        run_query("--list")


if __name__ == "__main__":
    main()
