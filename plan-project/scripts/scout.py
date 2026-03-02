#!/usr/bin/env python3
"""
Scout - Code Map Generator (zero LLM cost)

Parses source files and generates a compact structural index (Code Map)
that eliminates the need for LLM agents to read full files repeatedly.

Cost: 0 LLM tokens. Output ~2-3K tokens enters context once.
Speed: milliseconds.
Deterministic: same files → same map.

Supported: Lean 4, Rust, Python, C/C++, generic fallback.

Usage:
  scout.py archivo.lean                    # Single file
  scout.py --dir ./src --ext .lean         # Directory scan
  scout.py --targets "name1,name2" f.lean  # Highlight specific declarations
  scout.py --pending-only --dir ./src      # Only files with sorry/TODO
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Declaration:
    name: str
    kind: str  # theorem, def, fn, class, struct, etc.
    line_start: int
    line_end: int
    signature: str
    pending: Optional[str] = None  # sorry, TODO, axiom, etc.
    internal_deps: List[str] = field(default_factory=list)


@dataclass
class FileMap:
    path: str
    language: str
    total_lines: int
    imports: List[str]
    declarations: List[Declaration]
    pending_count: int = 0


# ── Language Detection ──

EXT_MAP = {
    ".lean": "lean4",
    ".rs": "rust",
    ".py": "python",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".js": "javascript",
    ".ts": "typescript",
    ".go": "go",
    ".java": "java",
}


def detect_language(path: Path) -> str:
    return EXT_MAP.get(path.suffix.lower(), "unknown")


# ── Lean 4 Parser ──

_LEAN_IMPORT_RE = re.compile(r"^import\s+(.+)")
_LEAN_OPEN_RE = re.compile(r"^open\s+(.+)")
_LEAN_DECL_RE = re.compile(
    r"^(noncomputable\s+)?(theorem|lemma|def|instance|structure|class|inductive|abbrev|axiom)\s+(\S+)"
)
_SORRY_RE = re.compile(r"\bsorry\b")


def _lean_find_decl_end(lines: List[str], start: int) -> int:
    """Find end of a Lean 4 declaration starting at `start`."""
    end = start
    for j in range(start + 1, min(start + 300, len(lines))):
        line = lines[j]
        stripped = line.strip()
        # Empty line after content can be a boundary, but not always in Lean
        # Top-level declaration at column 0 = definite boundary
        if stripped and not line[0].isspace():
            # Continuation patterns (where, |, with, #, --, section, namespace, end)
            if stripped.startswith("|") or stripped.startswith("where") or stripped.startswith("with"):
                end = j
                continue
            if stripped.startswith("--") or stripped.startswith("#"):
                end = j
                continue
            if stripped.startswith("section") or stripped.startswith("namespace") or stripped.startswith("end"):
                return j - 1
            # Another declaration = boundary
            if _LEAN_DECL_RE.match(stripped):
                return j - 1
            # Any other non-indented line = boundary
            return j - 1
        end = j
    return end


def parse_lean4(path: Path, lines: List[str]) -> FileMap:
    imports = []
    declarations = []

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        # Imports
        m = _LEAN_IMPORT_RE.match(stripped)
        if m:
            imports.append(m.group(1).strip())
            i += 1
            continue

        # Opens
        m = _LEAN_OPEN_RE.match(stripped)
        if m:
            imports.append(f"open {m.group(1).strip()}")
            i += 1
            continue

        # Declarations
        m = _LEAN_DECL_RE.match(stripped)
        if m:
            kind = m.group(2)
            name = m.group(3).rstrip(":")
            end = _lean_find_decl_end(lines, i)

            # Signature: first line, truncated
            sig = stripped
            if len(sig) > 120:
                sig = sig[:117] + "..."

            # Check for sorry/axiom/TODO
            pending = None
            block = "\n".join(lines[i : end + 1])
            if kind == "axiom":
                pending = "axiom"
            elif _SORRY_RE.search(block):
                pending = "sorry"
            if "TODO" in block:
                pending = f"{pending}+TODO" if pending else "TODO"
            if "FIXME" in block:
                pending = f"{pending}+FIXME" if pending else "FIXME"

            declarations.append(
                Declaration(
                    name=name,
                    kind=kind,
                    line_start=i + 1,
                    line_end=end + 1,
                    signature=sig,
                    pending=pending,
                )
            )
            i = end + 1
            continue

        i += 1

    # Internal dependencies
    all_names = {d.name for d in declarations}
    for decl in declarations:
        block = "\n".join(lines[decl.line_start - 1 : decl.line_end])
        for name in all_names:
            if name != decl.name and re.search(r"\b" + re.escape(name) + r"\b", block):
                decl.internal_deps.append(name)

    return FileMap(
        path=str(path),
        language="lean4",
        total_lines=len(lines),
        imports=imports,
        declarations=declarations,
        pending_count=sum(1 for d in declarations if d.pending),
    )


# ── Rust Parser ──

_RUST_USE_RE = re.compile(r"^use\s+(.+);")
_RUST_MOD_RE = re.compile(r"^(pub\s+)?mod\s+(\w+)")
_RUST_DECL_RE = re.compile(
    r"^(pub\s+)?(async\s+)?(fn|struct|enum|trait|impl|type|const|static)\s+(\w+)"
)
_RUST_TODO_RE = re.compile(r"todo!\(\)|unimplemented!\(\)|TODO|FIXME")


def parse_rust(path: Path, lines: List[str]) -> FileMap:
    imports = []
    declarations = []

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        indent = len(lines[i]) - len(lines[i].lstrip()) if lines[i].strip() else 999

        # Use
        m = _RUST_USE_RE.match(stripped)
        if m and indent == 0:
            imports.append(m.group(1).strip())
            i += 1
            continue

        # Mod
        m = _RUST_MOD_RE.match(stripped)
        if m and indent == 0:
            imports.append(f"mod {m.group(2)}")
            i += 1
            continue

        # Declarations at top level
        m = _RUST_DECL_RE.match(stripped)
        if m and indent == 0:
            pub = "pub " if m.group(1) else ""
            kind = m.group(3)
            name = m.group(4)

            sig = stripped[:120] + ("..." if len(stripped) > 120 else "")

            # Find end by brace matching
            brace_depth = 0
            end = i
            for j in range(i, min(i + 500, len(lines))):
                brace_depth += lines[j].count("{") - lines[j].count("}")
                end = j
                if brace_depth == 0 and j > i:
                    break

            pending = None
            block = "\n".join(lines[i : end + 1])
            if _RUST_TODO_RE.search(block):
                pending = "TODO"

            declarations.append(
                Declaration(
                    name=f"{pub}{name}",
                    kind=kind,
                    line_start=i + 1,
                    line_end=end + 1,
                    signature=sig,
                    pending=pending,
                )
            )
            i = end + 1
            continue

        i += 1

    # Internal deps
    all_names = {d.name.replace("pub ", "") for d in declarations}
    for decl in declarations:
        block = "\n".join(lines[decl.line_start - 1 : decl.line_end])
        clean = decl.name.replace("pub ", "")
        for name in all_names:
            if name != clean and re.search(r"\b" + re.escape(name) + r"\b", block):
                decl.internal_deps.append(name)

    return FileMap(
        path=str(path),
        language="rust",
        total_lines=len(lines),
        imports=imports,
        declarations=declarations,
        pending_count=sum(1 for d in declarations if d.pending),
    )


# ── Python Parser ──

_PY_IMPORT_RE = re.compile(r"^(from\s+\S+\s+import\s+.+|import\s+.+)")
_PY_DECL_RE = re.compile(r"^(class|def|async\s+def)\s+(\w+)")
_PY_TODO_RE = re.compile(r"TODO|FIXME|NotImplementedError|\bpass\s*$")


def parse_python(path: Path, lines: List[str]) -> FileMap:
    imports = []
    declarations = []

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        indent = len(lines[i]) - len(lines[i].lstrip()) if lines[i].strip() else 999

        # Imports
        m = _PY_IMPORT_RE.match(stripped)
        if m and indent == 0:
            imports.append(m.group(1))
            i += 1
            continue

        # Top-level defs/classes
        m = _PY_DECL_RE.match(stripped)
        if m and indent == 0:
            kind = m.group(1).replace("async ", "")
            name = m.group(2)
            sig = stripped[:120] + ("..." if len(stripped) > 120 else "")

            # Find end: next non-indented, non-empty line
            end = i
            for j in range(i + 1, min(i + 500, len(lines))):
                if lines[j].strip() == "":
                    continue
                if not lines[j][0].isspace():
                    end = j - 1
                    break
                end = j

            pending = None
            block = "\n".join(lines[i : end + 1])
            if _PY_TODO_RE.search(block):
                pending = "TODO"

            declarations.append(
                Declaration(
                    name=name,
                    kind=kind,
                    line_start=i + 1,
                    line_end=end + 1,
                    signature=sig,
                    pending=pending,
                )
            )
            i = end + 1
            continue

        i += 1

    # Internal deps
    all_names = {d.name for d in declarations}
    for decl in declarations:
        block = "\n".join(lines[decl.line_start - 1 : decl.line_end])
        for name in all_names:
            if name != decl.name and re.search(r"\b" + re.escape(name) + r"\b", block):
                decl.internal_deps.append(name)

    return FileMap(
        path=str(path),
        language="python",
        total_lines=len(lines),
        imports=imports,
        declarations=declarations,
        pending_count=sum(1 for d in declarations if d.pending),
    )


# ── C/C++ Parser ──

_C_INCLUDE_RE = re.compile(r'^#include\s+[<"](.+)[>"]')
_C_FUNC_RE = re.compile(
    r"^(?:static\s+|extern\s+|inline\s+)*(?:const\s+)?\w[\w\s\*]+\s+(\w+)\s*\("
)
_C_STRUCT_RE = re.compile(r"^(typedef\s+)?(struct|enum|union)\s+(\w+)")


def parse_c(path: Path, lines: List[str]) -> FileMap:
    imports = []
    declarations = []

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        indent = len(lines[i]) - len(lines[i].lstrip()) if lines[i].strip() else 999

        # Includes
        m = _C_INCLUDE_RE.match(stripped)
        if m:
            imports.append(m.group(1))
            i += 1
            continue

        # Struct/enum/union
        m = _C_STRUCT_RE.match(stripped)
        if m and indent == 0:
            kind = m.group(2)
            name = m.group(3)
            sig = stripped[:120]

            brace_depth = 0
            end = i
            for j in range(i, min(i + 300, len(lines))):
                brace_depth += lines[j].count("{") - lines[j].count("}")
                end = j
                if brace_depth == 0 and j > i:
                    break

            pending = None
            block = "\n".join(lines[i : end + 1])
            if "TODO" in block or "FIXME" in block:
                pending = "TODO"

            declarations.append(
                Declaration(name=name, kind=kind, line_start=i + 1, line_end=end + 1,
                            signature=sig, pending=pending)
            )
            i = end + 1
            continue

        # Functions (heuristic: at column 0, has parens, followed by {)
        m = _C_FUNC_RE.match(stripped)
        if m and indent == 0 and not stripped.startswith("#") and not stripped.startswith("//"):
            name = m.group(1)
            # Skip if it's a common keyword false positive
            if name in ("if", "for", "while", "switch", "return", "sizeof", "typedef"):
                i += 1
                continue

            sig = stripped[:120]

            brace_depth = 0
            end = i
            found_brace = False
            for j in range(i, min(i + 500, len(lines))):
                brace_depth += lines[j].count("{") - lines[j].count("}")
                if "{" in lines[j]:
                    found_brace = True
                end = j
                if found_brace and brace_depth == 0:
                    break

            pending = None
            block = "\n".join(lines[i : end + 1])
            if "TODO" in block or "FIXME" in block:
                pending = "TODO"

            declarations.append(
                Declaration(name=name, kind="fn", line_start=i + 1, line_end=end + 1,
                            signature=sig, pending=pending)
            )
            i = end + 1
            continue

        i += 1

    return FileMap(
        path=str(path),
        language=detect_language(path),
        total_lines=len(lines),
        imports=imports,
        declarations=declarations,
        pending_count=sum(1 for d in declarations if d.pending),
    )


# ── Generic Fallback ──


def parse_generic(path: Path, lines: List[str]) -> FileMap:
    """Fallback: find TODO/FIXME markers only."""
    markers = []
    for i, line in enumerate(lines):
        if "TODO" in line or "FIXME" in line or "HACK" in line:
            markers.append(
                Declaration(
                    name=f"line_{i+1}",
                    kind="marker",
                    line_start=i + 1,
                    line_end=i + 1,
                    signature=line.strip()[:120],
                    pending="TODO/FIXME",
                )
            )

    return FileMap(
        path=str(path),
        language=detect_language(path),
        total_lines=len(lines),
        imports=[],
        declarations=markers,
        pending_count=len(markers),
    )


# ── Dispatcher ──

PARSERS = {
    "lean4": parse_lean4,
    "rust": parse_rust,
    "python": parse_python,
    "c": parse_c,
    "cpp": parse_c,
}


def parse_file(path: Path) -> FileMap:
    lang = detect_language(path)
    lines = path.read_text().splitlines()
    parser = PARSERS.get(lang, parse_generic)
    return parser(path, lines)


# ── Output Formatter ──

EXCLUDED_DIRS = {".lake", "node_modules", "target", "__pycache__", ".git", "build", "dist"}


def format_code_map(
    file_maps: List[FileMap],
    targets: Optional[List[str]] = None,
    context_lines: int = 5,
) -> str:
    output = []

    for fm in file_maps:
        output.append(f"---CODE MAP: {fm.path}---")
        output.append(f"LANGUAGE: {fm.language}")
        output.append(f"LINES: {fm.total_lines}")

        if fm.imports:
            output.append(f"IMPORTS: {', '.join(fm.imports[:15])}")
            if len(fm.imports) > 15:
                output.append(f"  ... and {len(fm.imports) - 15} more")
        else:
            output.append("IMPORTS: (none)")

        output.append(f"DECLARATIONS: {len(fm.declarations)}")
        output.append(f"PENDING: {fm.pending_count}")
        output.append("")

        # Declaration index table
        if fm.declarations:
            output.append("| Name | Type | Lines | Pending | Uses |")
            output.append("|------|------|-------|---------|------|")
            for d in fm.declarations:
                deps = ", ".join(d.internal_deps[:5]) if d.internal_deps else "-"
                if len(d.internal_deps) > 5:
                    deps += f" +{len(d.internal_deps)-5}"
                pending = d.pending or "-"
                output.append(
                    f"| {d.name} | {d.kind} | {d.line_start}-{d.line_end} | {pending} | {deps} |"
                )
            output.append("")

        # Detailed context for targets or pending items
        detail_decls = []
        if targets:
            detail_decls = [d for d in fm.declarations if d.name in targets]
        else:
            detail_decls = [d for d in fm.declarations if d.pending]

        if detail_decls:
            lines_content = Path(fm.path).read_text().splitlines()

            for d in detail_decls:
                output.append(f"### {d.name} ({d.kind}, line {d.line_start})")
                output.append(f"Signature: {d.signature}")
                if d.internal_deps:
                    output.append(f"Uses: {', '.join(d.internal_deps)}")

                start = max(0, d.line_start - 1 - context_lines)
                end = min(len(lines_content), d.line_end + context_lines)
                output.append("```")
                for j in range(start, end):
                    ln = lines_content[j]
                    is_marker = (
                        "sorry" in ln.split("--")[0]  # sorry not in comment
                        or "TODO" in ln
                        or "FIXME" in ln
                        or "todo!()" in ln
                        or "unimplemented!()" in ln
                    )
                    marker = " >>>" if is_marker else "    "
                    output.append(f"{j+1:4}{marker} {ln}")
                output.append("```")
                output.append("")

        output.append("---END CODE MAP---")
        output.append("")

    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(
        description="Scout - Code Map generator (zero LLM cost)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  scout.py archivo.lean                       # Single file
  scout.py --dir ./src --ext .lean            # Directory recursive
  scout.py --targets "thm1,thm2" archivo.lean # Highlight targets
  scout.py --pending-only --dir ./src         # Only pending items
  scout.py --context-lines 10 archivo.lean    # More context
""",
    )

    parser.add_argument("files", nargs="*", help="Source files to scan")
    parser.add_argument(
        "--targets", "-t", type=str, default="",
        help="Comma-separated declaration names to show detailed context for",
    )
    parser.add_argument(
        "--context-lines", "-c", type=int, default=5,
        help="Lines of context around pending items (default: 5)",
    )
    parser.add_argument(
        "--dir", "-d", type=str, default="",
        help="Directory to scan recursively",
    )
    parser.add_argument(
        "--ext", "-e", type=str, default="",
        help="File extension filter for --dir (e.g., .lean)",
    )
    parser.add_argument(
        "--pending-only", "-p", action="store_true",
        help="Only include files with pending items (sorry/TODO/FIXME)",
    )

    args = parser.parse_args()

    # Collect files
    files: List[Path] = []
    for f in args.files:
        p = Path(f)
        if p.exists():
            files.append(p)
        else:
            print(f"Warning: {f} not found", file=sys.stderr)

    if args.dir:
        d = Path(args.dir)
        if d.is_dir():
            if args.ext:
                files.extend(sorted(d.rglob(f"*{args.ext}")))
            else:
                for ext in EXT_MAP:
                    files.extend(sorted(d.rglob(f"*{ext}")))
        else:
            print(f"Warning: {args.dir} is not a directory", file=sys.stderr)

    if not files:
        print("Error: No files. Use positional args or --dir.", file=sys.stderr)
        sys.exit(1)

    # Filter build/cache directories
    files = [f for f in files if not any(ex in f.parts for ex in EXCLUDED_DIRS)]

    # Deduplicate
    seen = set()
    unique_files = []
    for f in files:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_files.append(f)
    files = unique_files

    # Parse
    file_maps = []
    for f in files:
        try:
            fm = parse_file(f)
            if args.pending_only and fm.pending_count == 0:
                continue
            file_maps.append(fm)
        except Exception as e:
            print(f"Warning: Could not parse {f}: {e}", file=sys.stderr)

    # Targets
    targets = (
        [t.strip() for t in args.targets.split(",") if t.strip()]
        if args.targets
        else None
    )

    # Output
    print(format_code_map(file_maps, targets=targets, context_lines=args.context_lines))

    # Summary to stderr
    total_decls = sum(len(fm.declarations) for fm in file_maps)
    total_pending = sum(fm.pending_count for fm in file_maps)
    print(
        f"\nScout: {len(file_maps)} files, {total_decls} declarations, {total_pending} pending",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
