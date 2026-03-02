#!/usr/bin/env python3
"""tidy_project.py - Reformat ARCHITECTURE.md and BENCHMARKS.md to standard template.

Reads existing project documentation in heterogeneous formats, extracts structure
(phases, nodes, blocks, lessons), and rewrites files in the format defined by
DOCUMENTATION_TEMPLATE.md.

Usage:
    python3 tidy_project.py --project /path/to/project [--version v1.0.0] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SAVE_LESSONS_SCRIPT = Path.home() / "Documents/claudio/lecciones/scripts/save_lessons.py"

TYPE_ABBREV = {
    "FUNDACIONAL": "FUND",
    "CRITICO": "CRIT",
    "PARALELO": "PAR",
    "HOJA": "HOJA",
}

TYPE_NORMALIZE = {
    "FUND": "FUNDACIONAL", "CRIT": "CRITICO", "PAR": "PARALELO",
    "HOJA": "HOJA", "FUNDACIONAL": "FUNDACIONAL", "CRITICO": "CRITICO",
    "PARALELO": "PARALELO", "INTERMEDIO": "PARALELO",
    "INDEPENDIENTE": "HOJA",
}


# ─── Section splitting ─────────────────────────────────────────────────────


def split_sections(content: str, level: int = 2) -> list[tuple[str, str]]:
    """Split markdown into sections by header level.
    Returns [(header, body), ...]. Leading content has header=""."""
    prefix = "#" * level + " "
    lines = content.split("\n")
    sections: list[tuple[str, str]] = []
    current_header = ""
    current_lines: list[str] = []

    for line in lines:
        # Match exact level: starts with prefix but next char is NOT #
        if line.startswith(prefix) and (len(line) == len(prefix) or line[len(prefix)] != "#"):
            if current_header or current_lines:
                sections.append((current_header, "\n".join(current_lines)))
            current_header = line[len(prefix):].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_header or current_lines:
        sections.append((current_header, "\n".join(current_lines)))

    # Strip trailing --- separators from bodies to avoid duplication on re-render
    cleaned: list[tuple[str, str]] = []
    for header, body in sections:
        body = re.sub(r'(\n---\s*)+$', '', body.rstrip())
        cleaned.append((header, body))
    return cleaned


# ─── Phase detection ───────────────────────────────────────────────────────


def _clean_phase_name(raw: str) -> str:
    """Strip trailing annotations like (COMPLETE), [COMPLETE, v1.0.0], etc."""
    name = re.sub(r'\s*\([^)]*\)\s*$', '', raw).strip()
    name = re.sub(r'\s*\[[^\]]*\]\s*$', '', name).strip()
    return name


def detect_phase(header: str) -> tuple[str, str] | None:
    """Detect phase from header. Returns (id, name) or None."""
    # Fase N: Name or Fase N — Name (with colon, em dash, en dash, hyphen)
    m = re.match(
        r'^(?:Fase|Phase)\s+(\d+(?:\.\d+)?)\s*[:\u2014\u2013\-]\s*(.+)$',
        header, re.IGNORECASE,
    )
    if m:
        name = _clean_phase_name(m.group(2))
        return m.group(1), name

    # Fase N — Name (space-separated dash)
    m = re.match(
        r'^(?:Fase|Phase)\s+(\d+(?:\.\d+)?)\s+[\u2014\u2013\-]+\s+(.+)$',
        header, re.IGNORECASE,
    )
    if m:
        name = _clean_phase_name(m.group(2))
        return m.group(1), name

    # Numbered sections: "N. Name"
    m = re.match(r'^(\d+)\.\s+(.+)$', header)
    if m:
        return m.group(1), _clean_phase_name(m.group(2))

    return None


def detect_phase_status(header: str, body: str) -> str:
    """Detect phase status from header/body."""
    text = (header + " " + body[:300]).upper()
    if "COMPLETE" in text or "\u2713" in header:
        return "completed"
    if "IN PROGRESS" in text or "IN_PROGRESS" in text:
        return "in_progress"
    return "pending"


# ─── Node table parsing ───────────────────────────────────────────────────


def parse_node_table(content: str) -> list[dict]:
    """Parse markdown table with node classification data.

    Handles:
    - | Node | ID | Class | Rationale |   (LeanScribe)
    - | Nodo | Tipo | Deps | Status |     (standard template)
    """
    nodes: list[dict] = []
    lines = content.split("\n")
    header_cols: list[str] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break  # end of table
            continue

        # Separator row
        if re.match(r'^\|[\s\-:|]+\|$', stripped):
            in_table = True
            continue

        cells = [c.strip() for c in stripped.split("|")[1:-1]]

        if not header_cols:
            header_cols = [c.lower() for c in cells]
            # Validate this is a node table
            has_node_col = any(
                h in ("node", "nodo", "name") for h in header_cols
            )
            has_type_col = any(
                h in ("class", "tipo", "type", "id") for h in header_cols
            )
            if not (has_node_col or has_type_col):
                header_cols = []  # reset, not a node table
                continue
            continue

        if len(cells) < 2:
            continue

        node = _parse_node_row(cells, header_cols)
        if node:
            nodes.append(node)

    return nodes


def _parse_node_row(cells: list[str], headers: list[str]) -> dict | None:
    """Parse a single node table row."""
    col_map: dict[str, int] = {}
    for i, h in enumerate(headers):
        hl = h.strip()
        if hl in ("node", "nodo", "name"):
            col_map["name"] = i
        elif hl == "id":
            col_map["id"] = i
        elif hl in ("class", "tipo", "type"):
            col_map["type"] = i
        elif hl in ("deps", "dependencies", "dependencias"):
            col_map["deps"] = i
        elif hl in ("status", "estado"):
            col_map["status"] = i

    def get(field: str, default: str = "") -> str:
        idx = col_map.get(field)
        return cells[idx].strip() if idx is not None and idx < len(cells) else default

    name_raw = get("name")
    id_raw = get("id")

    # Template format: "N2.1 Union-Find" or "F1S2 UnionFind" in Nodo column
    if not id_raw and name_raw:
        m = re.match(r'^((?:N|F)\d+(?:[.S]\d+)?)\s+(.+)$', name_raw)
        if m:
            id_raw, name_raw = m.group(1), m.group(2)

    if not id_raw and not name_raw:
        return None

    node_type = get("type", "HOJA").upper().strip()
    node_type = TYPE_NORMALIZE.get(node_type, node_type)

    deps_raw = get("deps")
    deps: list[str] = []
    if deps_raw and deps_raw not in ("\u2014", "-", "--", ""):
        deps = [d.strip() for d in re.split(r'[,;]', deps_raw) if d.strip()]

    status = get("status", "pending").lower()
    if "\u2713" in status or "complete" in status:
        status = "completed"
    elif "progress" in status:
        status = "in_progress"
    else:
        status = "pending"

    return {
        "id": id_raw or name_raw,
        "name": name_raw or id_raw,
        "type": node_type,
        "deps": deps,
        "status": status,
    }


# ─── Block parsing ────────────────────────────────────────────────────────


def parse_blocks(content: str) -> list[dict]:
    """Parse block definitions from content.

    Handles:
    - [ ] **Bloque N**: nodes       (template / progress tree checkbox)
    - **Bloque N: description**     (Orden de Trabajo bold)
    - **GATE: description**         (GATE pre-check)
    """
    blocks: list[dict] = []

    # Pattern 1: - [x] **Bloque N**: nodes (checkbox style)
    for m in re.finditer(
        r'-\s*\[([x ])\]\s*\*\*(?:Bloque|Block)\s+(\d+)\*?\*?\s*[:\-]?\s*(.+)',
        content,
    ):
        nodes_part = re.split(r'\s*[\u2014\u2013]\s*closed', m.group(3))[0]
        nodes = re.findall(r'N\d+(?:\.\d+)?', nodes_part)
        blocks.append({
            "id": f"B{m.group(2)}", "name": f"Bloque {m.group(2)}",
            "nodes": nodes,
            "status": "completed" if m.group(1) == "x" else "pending",
        })

    # Pattern 1b: - [x] **GATE**: ...
    for m in re.finditer(
        r'-\s*\[([x ])\]\s*\*\*GATE\*?\*?\s*[:\-]?\s*(.+)',
        content,
    ):
        nodes = re.findall(r'N\d+(?:\.\d+)?', m.group(2))
        if not any(b["id"] == "GATE" for b in blocks):
            blocks.insert(0, {
                "id": "GATE", "name": "GATE",
                "nodes": nodes,
                "status": "completed" if m.group(1) == "x" else "pending",
            })

    if blocks:
        return blocks

    # Pattern 2: **Bloque N: description** (bold without checkbox)
    for m in re.finditer(r'\*\*Bloque\s+(\d+)\s*:\s*(.+?)\*\*', content):
        nodes = re.findall(r'N\d+(?:\.\d+)?', m.group(2))
        blocks.append({
            "id": f"B{m.group(1)}", "name": f"Bloque {m.group(1)}",
            "nodes": nodes, "status": "pending",
        })

    # Pattern 2b: **GATE: description**
    if not any(b["id"] == "GATE" for b in blocks):
        for m in re.finditer(r'\*\*GATE\s*:\s*(.+?)\*\*', content):
            nodes = re.findall(r'N\d+(?:\.\d+)?', m.group(1))
            blocks.insert(0, {
                "id": "GATE", "name": "GATE",
                "nodes": nodes, "status": "pending",
            })

    return blocks


# ─── Lesson parsing ───────────────────────────────────────────────────────


def extract_keywords_from_text(text: str) -> list[str]:
    """Extract meaningful keywords from text."""
    stop = {
        "para", "cuando", "antes", "usar", "como", "caso", "puede", "solo",
        "tipo", "tipos", "sobre", "este", "esta", "lean", "with", "from",
        "that", "then", "else", "have", "the", "and", "not", "los", "las",
        "del", "por", "una", "que", "mas", "sin", "son", "sea", "always",
        "never", "use", "was", "were", "been", "being", "each", "every",
    }
    words = re.findall(r'[a-zA-Z_]\w{2,}', text.lower())
    return [w for w in words if w not in stop][:5]


def parse_lessons(content: str) -> list[dict]:
    """Extract lessons from content.

    Handles:
    - ### L-NNN: Title            (standard format)
    - **L-N: Title.** body        (LeanScribe inline format)
    - Bullet-point lessons under "Lessons" headers
    """
    lessons: list[dict] = []

    # Pattern 1: ### L-NNN: Title
    for m in re.finditer(r'^###\s+L-\d+\s*:\s*(.+)$', content, re.MULTILINE):
        title = m.group(1).strip()
        start = m.end()
        next_h = re.search(r'^#{2,3}\s', content[start:], re.MULTILINE)
        end = start + next_h.start() if next_h else len(content)
        body = content[start:end].strip()
        lessons.append({
            "title": title, "body": body,
            "keywords": extract_keywords_from_text(title),
        })

    if lessons:
        return lessons

    # Pattern 2: **L-N: Title.** body (inline, no ### header)
    for m in re.finditer(
        r'\*\*L-\d+\s*:\s*(.+?)\.\*\*\s*\n(.+?)(?=\n\*\*L-\d+\s*:|\n---|\n##|\Z)',
        content, re.DOTALL,
    ):
        title = m.group(1).strip()
        body = m.group(2).strip()
        lessons.append({
            "title": title, "body": body,
            "keywords": extract_keywords_from_text(title),
        })

    if lessons:
        return lessons

    # Pattern 3: Bullet-point lessons under "Lessons" sub-headers
    for m in re.finditer(
        r'[Ll]essons?\s*\n((?:\s*[-*]\s+.+\n?)+)', content,
    ):
        bullets = re.findall(r'[-*]\s+(.+)', m.group(1))
        for bullet in bullets:
            parts = bullet.split(":", 1)
            title = parts[0].strip()[:80]
            body = parts[1].strip() if len(parts) > 1 else bullet.strip()
            lessons.append({
                "title": title, "body": body,
                "keywords": extract_keywords_from_text(title),
            })

    return lessons


# ─── Utility ──────────────────────────────────────────────────────────────


def extract_files(content: str) -> list[str]:
    """Extract file paths mentioned in content."""
    files: list[str] = []
    for m in re.finditer(r'`([^`]+\.(?:lean|py|c|h|rs|toml))`', content):
        f = m.group(1).strip()
        if f not in files:
            files.append(f)
    return files


def detect_version(content: str) -> str | None:
    """Detect version from content."""
    # Explicit Current Version header
    m = re.search(r'Current Version\s*:\s*(v[\d.]+)', content)
    if m:
        return m.group(1)
    # Tag reference
    m = re.search(r'tag\s+(v[\d.]+)', content)
    if m:
        return m.group(1)
    # Bold version in tables (version history): **vN.N.N** or **vN.N**
    bold = re.findall(r'\*\*v(\d+\.\d+(?:\.\d+)?)\*\*', content)
    if bold:
        bold.sort(key=lambda v: [int(x) for x in v.split(".")])
        return f"v{bold[-1]}"
    # Any vN.N.N, but exclude toolchain versions (v4.x typically Lean/Mathlib)
    versions = re.findall(r'v(\d+\.\d+\.\d+)', content)
    project_versions = [v for v in versions if not v.startswith("4.")]
    if project_versions:
        project_versions.sort(key=lambda v: [int(x) for x in v.split(".")])
        return f"v{project_versions[-1]}"
    if versions:
        versions.sort(key=lambda v: [int(x) for x in v.split(".")])
        return f"v{versions[-1]}"
    return None


def _parse_version_history_table(body: str) -> list[dict]:
    """Parse a markdown table with Version | Date | Highlights columns."""
    entries: list[dict] = []
    for line in body.split("\n"):
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        ver = cells[0].strip("* ")
        # Skip header row
        if ver.lower() in ("version", "versión", "ver"):
            continue
        entries.append({
            "version": ver,
            "date": cells[1].strip(),
            "highlights": cells[2].strip(),
        })
    return entries


# ─── Architecture parser ──────────────────────────────────────────────────


def parse_architecture(content: str) -> dict:
    """Parse ARCHITECTURE.md into structured data."""
    result: dict = {
        "name": "", "version": None, "phases": [],
        "lessons": [], "previous_versions": "",
        "version_history": [],  # [{version, date, highlights}] — parsed from table
        "legacy_content": [],   # [(header, body)] — unmapped sections preserved
    }

    # Title — handle both "Name: Architecture" and "Name — Architecture"
    m = re.match(
        r'^#\s+(.+?)\s*[:\u2014\u2013\-]\s*Architecture\s*$',
        content, re.MULTILINE,
    )
    if not m:
        m = re.match(r'^#\s+(.+?)\s*$', content, re.MULTILINE)
    if m:
        name = m.group(1).strip().rstrip(":").strip()
        # Strip trailing "Architecture" if it was part of the title without separator
        if name.lower().endswith("architecture"):
            name = name[:-len("architecture")].rstrip(" :\u2014\u2013\-").strip()
        result["name"] = name or (m.group(1).strip() if m else "Project")

    result["version"] = detect_version(content)

    sections = split_sections(content, level=2)

    phase_sections: list[tuple[str, str, str, str]] = []  # (id, name, body, status)
    node_sections: list[tuple[str | None, str]] = []       # (phase_id, body)
    block_sections: list[tuple[str | None, str]] = []      # (phase_id, body)
    progress_body: str | None = None
    lessons_body: str | None = None
    previous_body: str | None = None

    for header, body in sections:
        hl = header.lower()

        # Version History table (summary of all versions)
        if "version history" in hl or "historial de version" in hl:
            result["version_history"] = _parse_version_history_table(body)
            continue

        # Previous Versions (detailed content from older versions)
        if "previous version" in hl or "versiones anterior" in hl:
            previous_body = body.strip()
            continue

        # Current Version (may contain phase sub-sections)
        if "current version" in hl:
            for sh, sb in split_sections(body, level=3):
                pi = detect_phase(sh)
                if pi:
                    phase_sections.append(
                        (pi[0], pi[1], sb, detect_phase_status(sh, sb))
                    )
            continue

        # Lessons section
        if "lecciones" in hl or ("lessons" in hl and "applicable" not in hl):
            lessons_body = body
            continue

        # Progress tree
        if "progress" in hl or "\u00e1rbol" in hl:
            progress_body = body
            continue

        # Node classification (standalone section)
        if "node classification" in hl or "clasificaci\u00f3n de nodo" in hl:
            pr = re.search(r'Fase\s+(\d+(?:\.\d+)?)', header)
            node_sections.append((pr.group(1) if pr else None, body))
            continue

        # Orden de Trabajo / Execution blocks
        if "orden" in hl or "trabajo" in hl:
            pr = re.search(r'Fase\s+(\d+(?:\.\d+)?)', header)
            block_sections.append((pr.group(1) if pr else None, body))
            continue

        # Fases del Proyecto container
        if "fases del proyecto" in hl or "project phases" in hl:
            for sh, sb in split_sections(body, level=3):
                pi = detect_phase(sh)
                if pi:
                    phase_sections.append(
                        (pi[0], pi[1], sb, detect_phase_status(sh, sb))
                    )
            continue

        # Direct phase at ## level
        pi = detect_phase(header)
        if pi:
            phase_sections.append(
                (pi[0], pi[1], body, detect_phase_status(header, body))
            )
            continue

        # Check body for embedded node classification sub-headers
        nc_match = re.search(
            r'###?\s*[Nn]ode\s+[Cc]lassification\s*\(?([^)\n]*)\)?',
            body,
        )
        if nc_match:
            # Extract phase ref from the classification header itself
            pr = re.search(r'Fase\s+(\d+(?:\.\d+)?)', nc_match.group(1))
            if not pr:
                pr = re.search(r'Fase\s+(\d+(?:\.\d+)?)', header)
            node_sections.append((pr.group(1) if pr else None, body))
            continue

        # Everything else: preserve as legacy content
        if header.strip():
            result["legacy_content"].append((header, body))

    # ── Build phases dict ──────────────────────────────────────────────
    phases: dict[str, dict] = {}
    for pid, pname, body, status in phase_sections:
        # Description: paragraphs before first ###, table, **Files**, or ####
        desc_lines: list[str] = []
        for line in body.split("\n"):
            if (line.startswith("### ") or line.startswith("#### ")
                    or line.startswith("| ") or line.startswith("**Files**")):
                break
            desc_lines.append(line)
        description = "\n".join(desc_lines).strip()
        # Clean status annotations from description
        description = re.sub(
            r'\(COMPLETE[D]?\)|\(PLANNED[^)]*\)|\(IN PROGRESS\)',
            '', description, flags=re.IGNORECASE,
        ).strip()
        # Strip **Contents**: prefix if present (avoids duplication on re-tidy)
        description = re.sub(
            r'^\*\*Contents\*\*:\s*', '', description,
        ).strip()

        phases[pid] = {
            "id": pid, "name": f"Fase {pid}: {pname}",
            "description": description, "files": extract_files(body),
            "nodes": parse_node_table(body), "blocks": parse_blocks(body),
            "status": status,
        }

    # ── Associate standalone node tables ─────────────────────────────
    for pid, body in node_sections:
        nodes = parse_node_table(body)
        if not nodes:
            continue
        target = pid if pid and pid in phases else None
        if not target and phases:
            target = list(phases.keys())[-1]
        if target and target in phases:
            existing = {n["id"] for n in phases[target]["nodes"]}
            for n in nodes:
                if n["id"] not in existing:
                    phases[target]["nodes"].append(n)
        elif pid and pid not in phases:
            phases[pid] = {
                "id": pid, "name": f"Fase {pid}", "description": "",
                "files": [], "nodes": nodes, "blocks": [], "status": "pending",
            }

    # ── Associate standalone block sections ──────────────────────────
    for pid, body in block_sections:
        blocks = parse_blocks(body)
        if not blocks:
            continue
        target = pid if pid and pid in phases else None
        if not target and phases:
            target = list(phases.keys())[-1]
        if target and target in phases:
            existing = {b["id"] for b in phases[target]["blocks"]}
            for b in blocks:
                if b["id"] not in existing:
                    phases[target]["blocks"].append(b)

    # ── Update from progress tree ────────────────────────────────────
    if progress_body:
        _update_from_progress(phases, progress_body)

    # ── Parse lessons ────────────────────────────────────────────────
    if lessons_body:
        result["lessons"] = parse_lessons(lessons_body)

    # Also check inline lessons in phase bodies
    for _, _, body, _ in phase_sections:
        for lesson in parse_lessons(body):
            if not any(l["title"] == lesson["title"] for l in result["lessons"]):
                result["lessons"].append(lesson)

    result["phases"] = list(phases.values())
    result["previous_versions"] = previous_body or ""

    return result


def _update_from_progress(phases: dict, content: str):
    """Update phase/block/node status from progress tree."""
    # Phase status: Fase N [COMPLETE] / [PLANNED]
    for m in re.finditer(
        r'Fase\s+(\d+(?:\.\d+)?)\s*\[(\w+(?:\s+\w+)?)\]', content,
    ):
        pid = m.group(1)
        st = m.group(2).upper()
        if pid in phases:
            if "COMPLETE" in st:
                phases[pid]["status"] = "completed"
            elif "PROGRESS" in st:
                phases[pid]["status"] = "in_progress"

    # Block status: B1: ... ✓  or  GATE: ... ✓  (progress tree code block)
    for m in re.finditer(r'(?:B(\d+)|GATE):\s*[^\n]*?\u2713', content):
        bid = f"B{m.group(1)}" if m.group(1) else "GATE"
        for phase in phases.values():
            for block in phase["blocks"]:
                if block["id"] == bid:
                    block["status"] = "completed"

    # Node status: N\d+: ... ✓
    for m in re.finditer(r'(N\d+):\s*[^\n]*?\u2713', content):
        nid = m.group(1)
        for phase in phases.values():
            for node in phase["nodes"]:
                if node["id"] == nid:
                    node["status"] = "completed"

    # Also handle checkbox format: - [x] **Bloque N**: ...
    for m in re.finditer(
        r'-\s*\[([x ])\]\s*\*\*(?:Bloque|Block)\s+(\d+)\*?\*?', content,
    ):
        bid = f"B{m.group(2)}"
        for phase in phases.values():
            for block in phase["blocks"]:
                if block["id"] == bid:
                    block["status"] = "completed" if m.group(1) == "x" else "pending"


# ─── Benchmarks parser ────────────────────────────────────────────────────


def parse_benchmarks(content: str) -> dict:
    """Parse BENCHMARKS.md into structured data."""
    result: dict = {
        "name": "", "version": None, "criteria": "",
        "results": [], "previous": "",
    }

    m = re.match(
        r'^#\s+(.+?)\s*[\u2014\u2013\-]\s*[Bb]enchmarks?\s*(?:\((.+?)\))?\s*$',
        content, re.MULTILINE,
    )
    if not m:
        m = re.match(
            r'^#\s+(.+?)(?:\s*[Bb]enchmarks?)?\s*(?:\((.+?)\))?\s*$',
            content, re.MULTILINE,
        )
    if m:
        result["name"] = m.group(1).strip()
        if m.group(2):
            result["version"] = m.group(2).strip()
    if not result["version"]:
        result["version"] = detect_version(content)

    sections = split_sections(content, level=2)

    for header, body in sections:
        hl = header.lower()

        if "previous" in hl:
            result["previous"] = body.strip()
            continue

        # Criteria sections (may be per-phase: "Fase 1 Criteria")
        if "criteria" in hl or "criterio" in hl:
            if result["criteria"]:
                result["criteria"] += f"\n\n### {header}\n\n{body.strip()}"
            else:
                result["criteria"] = body.strip()
            continue

        if "current result" in hl:
            # Container section — parse sub-sections as individual results
            for sh, sb in split_sections(body, level=3):
                pi = detect_phase(sh)
                if pi:
                    result["results"].append({
                        "name": f"Fase {pi[0]}: {pi[1]}",
                        "content": sb.strip(),
                        "phase_linked": True,
                    })
                elif sh.strip():
                    result["results"].append({
                        "name": sh, "content": sb.strip(),
                        "phase_linked": False,
                    })
            continue

        # Phase-named results
        pi = detect_phase(header)
        if pi:
            result["results"].append({
                "name": f"Fase {pi[0]}: {pi[1]}",
                "content": body.strip(),
                "phase_linked": True,
            })
            continue

        # Any other named section → orphan result (not linked to a phase)
        if header:
            result["results"].append({
                "name": header, "content": body.strip(),
                "phase_linked": False,
            })

    return result


# ─── DAG generation ────────────────────────────────────────────────────────


def build_dag(parsed: dict, version: str) -> dict:
    """Build dag.json from parsed architecture data."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    dag_phases: list[dict] = []
    for phase in parsed["phases"]:
        nodes: list[dict] = []
        for node in phase.get("nodes", []):
            # Compute which nodes this node blocks
            blocking = [
                o["id"] for o in phase.get("nodes", [])
                if node["id"] in o.get("deps", [])
            ]
            nodes.append({
                "id": node["id"],
                "name": node.get("name", node["id"]),
                "type": node.get("type", "HOJA"),
                "status": node.get("status", "pending"),
                "files": [],
                "deps": node.get("deps", []),
                "blocks": blocking,
                "metrics": {
                    "loc": 0, "theorems": 0, "lemmas": 0, "defs": 0, "sorry": 0,
                },
            })

        blocks: list[dict] = []
        for block in phase.get("blocks", []):
            blocks.append({
                "id": block["id"],
                "name": block.get("name", block["id"]),
                "nodes": block.get("nodes", []),
                "status": block.get("status", "pending"),
                "closed_at": None,
            })

        dag_phases.append({
            "id": f"fase{phase['id']}",
            "name": phase["name"],
            "status": phase.get("status", "pending"),
            "nodes": nodes,
            "blocks": blocks,
        })

    total = sum(len(p["nodes"]) for p in dag_phases)
    completed = sum(
        1 for p in dag_phases for n in p["nodes"]
        if n["status"] == "completed"
    )

    return {
        "version": version,
        "project": parsed.get("name", "unknown"),
        "phases": dag_phases,
        "meta": {
            "created": now, "updated": now,
            "total_nodes": total, "completed_nodes": completed,
        },
    }


# ─── Rendering ─────────────────────────────────────────────────────────────


def render_architecture(parsed: dict, version: str) -> str:
    """Render ARCHITECTURE.md in standard template format."""
    lines = [
        f"# {parsed.get('name', 'Project')}: Architecture",
        "",
        f"## Current Version: {version}",
        "",
    ]

    for phase in parsed["phases"]:
        lines.append(f"### {phase['name']}")
        lines.append("")

        if phase.get("description"):
            lines.append(f"**Contents**: {phase['description']}")
            lines.append("")

        if phase.get("files"):
            lines.append("**Files**:")
            for f in phase["files"]:
                lines.append(f"- `{f}`")
            lines.append("")

        # DAG table
        if phase.get("nodes"):
            lines.append(f"#### DAG ({version})")
            lines.append("")
            lines.append("| Nodo | Tipo | Deps | Status |")
            lines.append("|------|------|------|--------|")
            for node in phase["nodes"]:
                abbr = TYPE_ABBREV.get(node["type"], node["type"][:4])
                deps = ", ".join(node["deps"]) if node.get("deps") else "\u2014"
                st = node.get("status", "pending")
                check = " \u2713" if st == "completed" else ""
                lines.append(
                    f"| {node['id']} {node['name']} | {abbr} | {deps} | {st}{check} |"
                )
            lines.append("")

        # Blocks
        if phase.get("blocks"):
            lines.append("#### Bloques")
            lines.append("")
            for block in phase["blocks"]:
                check = "x" if block.get("status") == "completed" else " "
                nlist = ", ".join(block.get("nodes", []))
                lines.append(f"- [{check}] **{block['name']}**: {nlist}")
            lines.append("")

        lines.extend(["---", ""])

    # ── Version History table ────────────────────────────────────────
    lines.extend(["## Version History", ""])
    vh = parsed.get("version_history", [])
    if vh:
        lines.append("| Version | Date | Highlights |")
        lines.append("|---------|------|------------|")
        for entry in vh:
            v = entry["version"]
            d = entry.get("date", "")
            h = entry.get("highlights", "")
            lines.append(f"| **{v}** | {d} | {h} |")
    else:
        lines.append("| Version | Date | Highlights |")
        lines.append("|---------|------|------------|")
        lines.append(f"| **{version}** | | (current) |")
    lines.extend(["", "---", ""])

    # ── Previous Versions (full phases + DAGs, newest first) ──────
    lines.extend(["## Previous Versions", ""])
    if parsed.get("previous_versions"):
        lines.append(parsed["previous_versions"])
    else:
        lines.append("(none)")
    lines.extend(["", "---", ""])

    # ── Legacy Content (unmapped sections) ────────────────────────
    if parsed.get("legacy_content"):
        lines.extend(["## Legacy Content (pre-structured)", ""])
        lines.append(
            "> Sections from the original documentation that were not mapped "
            "to any phase. Preserved for reference."
        )
        lines.append("")
        for hdr, body in parsed["legacy_content"]:
            lines.extend([f"### {hdr}", "", body.strip(), ""])
        lines.extend(["---", ""])

    # No lessons section — lessons live in ~/Documents/claudio/lecciones/lean4/
    # References to L-NNN IDs are added by main() after save_lessons returns IDs.

    text = "\n".join(lines)
    # Final cleanup: collapse consecutive --- separators
    text = re.sub(r'(\n---\s*\n)\s*---\s*\n', r'\1', text)
    return text


def render_benchmarks(parsed_b: dict, parsed_a: dict, version: str) -> str:
    """Render BENCHMARKS.md in standard template format."""
    name = parsed_b.get("name") or parsed_a.get("name", "Project")
    lines = [f"# {name} Benchmarks ({version})", ""]

    lines.extend(["## Criteria", ""])
    lines.append(parsed_b.get("criteria") or "(no criteria defined)")
    lines.extend(["", "---", ""])

    linked = [r for r in parsed_b.get("results", []) if r.get("phase_linked", True)]
    orphans = [r for r in parsed_b.get("results", []) if not r.get("phase_linked", True)]

    lines.extend(["## Current Results", ""])
    if linked:
        for r in linked:
            lines.extend([f"### {r['name']}", "", r["content"], ""])
    else:
        lines.append("(no results yet)")
    lines.extend(["", "---", ""])

    if orphans:
        lines.extend([
            "## Legacy Results (pre-structured)", "",
            "> Benchmark results not linked to any identified phase. "
            "Preserved for reference.",
            "",
        ])
        for r in orphans:
            lines.extend([f"### {r['name']}", "", r["content"], ""])
        lines.extend(["---", ""])

    lines.extend(["## Previous Results", ""])
    lines.append(parsed_b.get("previous") or "(none)")
    lines.append("")

    text = "\n".join(lines)
    # Final cleanup: collapse consecutive --- separators
    text = re.sub(r'(\n---\s*\n)\s*---\s*\n', r'\1', text)
    return text


# ─── Lesson extraction ────────────────────────────────────────────────────


def extract_and_save_lessons(lessons: list[dict]) -> dict:
    """Save lessons via save_lessons.py, return result summary."""
    if not lessons:
        return {}
    if not SAVE_LESSONS_SCRIPT.exists():
        print(
            f"WARNING: save_lessons.py not found at {SAVE_LESSONS_SCRIPT}",
            file=sys.stderr,
        )
        return {}

    try:
        r = subprocess.run(
            [
                "python3", str(SAVE_LESSONS_SCRIPT),
                "--lessons", json.dumps(lessons, ensure_ascii=False),
            ],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            return json.loads(r.stdout)
        else:
            print(f"WARNING: save_lessons.py failed: {r.stderr}", file=sys.stderr)
            return {}
    except Exception as e:
        print(f"WARNING: save_lessons.py error: {e}", file=sys.stderr)
        return {}


# ─── Main ──────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(
        description="Reformat ARCHITECTURE.md and BENCHMARKS.md to standard template",
    )
    ap.add_argument("--project", required=True, help="Project root path")
    ap.add_argument("--version", help="Version (auto-detected if not specified)")
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Show changes without writing files",
    )
    ap.add_argument(
        "--legacy-phase", action="store_true",
        help="Create synthetic Fase 0 for unmapped content in messy projects",
    )
    args = ap.parse_args()

    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"ERROR: Not a directory: {project}", file=sys.stderr)
        sys.exit(1)

    arch_path = project / "ARCHITECTURE.md"
    bench_path = project / "BENCHMARKS.md"
    dag_path = project / "dag.json"

    # Also check docs/ subdirectory for BENCHMARKS.md
    if not bench_path.exists() and (project / "docs" / "BENCHMARKS.md").exists():
        bench_path = project / "docs" / "BENCHMARKS.md"

    if not arch_path.exists():
        print(f"ERROR: No ARCHITECTURE.md in {project}", file=sys.stderr)
        sys.exit(1)

    # ── Parse ────────────────────────────────────────────────────────
    print(f"TIDY: Parsing {arch_path}")
    parsed_arch = parse_architecture(arch_path.read_text(encoding="utf-8"))

    parsed_bench = None
    if bench_path.exists():
        print(f"TIDY: Parsing {bench_path}")
        parsed_bench = parse_benchmarks(bench_path.read_text(encoding="utf-8"))

    version = args.version or parsed_arch.get("version") or "v1.0.0"

    # ── Legacy phase (synthetic Fase 0) ──────────────────────────────
    if args.legacy_phase and parsed_arch.get("legacy_content"):
        legacy_desc_parts = []
        for hdr, body in parsed_arch["legacy_content"]:
            legacy_desc_parts.append(f"**{hdr}**: {body.strip()[:200]}")
        legacy_phase = {
            "id": "0",
            "name": "Fase 0: Foundation (pre-structured)",
            "description": "Unmapped content from pre-structured documentation.",
            "files": [],
            "nodes": [{
                "id": "N0",
                "name": "Pre-structured work",
                "type": "FUNDACIONAL",
                "deps": [],
                "status": "completed",
            }],
            "blocks": [],
            "status": "completed",
        }
        parsed_arch["phases"].insert(0, legacy_phase)

    # ── Summary ──────────────────────────────────────────────────────
    total_nodes = sum(len(p.get("nodes", [])) for p in parsed_arch["phases"])
    total_blocks = sum(len(p.get("blocks", [])) for p in parsed_arch["phases"])

    print(f"\n{'=' * 60}")
    print(f"Project:  {parsed_arch.get('name', '(unknown)')}")
    print(f"Version:  {version}")
    print(f"Phases:   {len(parsed_arch['phases'])}")
    print(f"Nodes:    {total_nodes}")
    print(f"Blocks:   {total_blocks}")
    print(f"Lessons:  {len(parsed_arch['lessons'])}")
    if parsed_arch.get("legacy_content"):
        print(f"Legacy sections: {len(parsed_arch['legacy_content'])}")
    if parsed_bench:
        print(f"Bench sections: {len(parsed_bench.get('results', []))}")
    print(f"{'=' * 60}")

    for phase in parsed_arch["phases"]:
        n = len(phase.get("nodes", []))
        b = len(phase.get("blocks", []))
        print(f"  {phase['name']}: {phase.get('status', '?')} ({n} nodes, {b} blocks)")
        for node in phase.get("nodes", []):
            st = node.get("status", "?")
            print(f"    {node['id']} {node['name']} [{node['type']}] {st}")

    if parsed_arch["lessons"]:
        print(f"\nLessons detected:")
        for lesson in parsed_arch["lessons"]:
            print(f"  - {lesson['title'][:70]}")

    # ── Dry run ──────────────────────────────────────────────────────
    if args.dry_run:
        rendered_arch = render_architecture(parsed_arch, version)
        print(
            f"\n--- ARCHITECTURE.md preview "
            f"({len(rendered_arch.splitlines())} lines) ---"
        )
        for line in rendered_arch.splitlines()[:40]:
            print(f"  {line}")
        if len(rendered_arch.splitlines()) > 40:
            print(f"  ... ({len(rendered_arch.splitlines()) - 40} more lines)")

        if parsed_bench:
            rendered_bench = render_benchmarks(parsed_bench, parsed_arch, version)
            print(
                f"\n--- BENCHMARKS.md preview "
                f"({len(rendered_bench.splitlines())} lines) ---"
            )
            for line in rendered_bench.splitlines()[:30]:
                print(f"  {line}")
            if len(rendered_bench.splitlines()) > 30:
                print(
                    f"  ... ({len(rendered_bench.splitlines()) - 30} more lines)"
                )

        if not dag_path.exists() and parsed_arch["phases"]:
            dag = build_dag(parsed_arch, version)
            print(f"\n--- dag.json preview ({dag['meta']['total_nodes']} nodes) ---")
            preview = json.dumps(dag, indent=2, ensure_ascii=False)
            for line in preview.splitlines()[:25]:
                print(f"  {line}")
            if len(preview.splitlines()) > 25:
                print(f"  ... ({len(preview.splitlines()) - 25} more lines)")

        print("\n[DRY RUN] No files written.")
        return

    # ── Backup originals ─────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    bak_arch = arch_path.with_suffix(f".{ts}.bak")
    shutil.copy2(arch_path, bak_arch)
    print(f"\nBackup: {arch_path.name} \u2192 {bak_arch.name}")

    if bench_path.exists():
        bak_bench = bench_path.with_suffix(f".{ts}.bak")
        shutil.copy2(bench_path, bak_bench)
        print(f"Backup: {bench_path.name} \u2192 {bak_bench.name}")

    # ── Extract and save lessons ─────────────────────────────────────
    saved_ids: list[str] = []
    if parsed_arch["lessons"]:
        print(f"\nSaving {len(parsed_arch['lessons'])} lessons...")
        save_result = extract_and_save_lessons(parsed_arch["lessons"])
        if save_result:
            print(f"  {json.dumps(save_result, indent=2, ensure_ascii=False)[:300]}")
            for l in save_result.get("lessons", []):
                if l.get("id"):
                    saved_ids.append(l["id"])

    # ── Generate dag.json ────────────────────────────────────────────
    if not dag_path.exists() and parsed_arch["phases"]:
        dag = build_dag(parsed_arch, version)
        dag_path.write_text(
            json.dumps(dag, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(
            f"\nGenerated: dag.json "
            f"({dag['meta']['total_nodes']} nodes, {len(dag['phases'])} phases)"
        )
    elif dag_path.exists():
        print(f"\nSkipped: dag.json already exists")

    # ── Write ARCHITECTURE.md ────────────────────────────────────────
    rendered_arch = render_architecture(parsed_arch, version)
    # Append lesson references (IDs only, content lives in lecciones/)
    if saved_ids:
        rendered_arch += f"\n> Lecciones: {', '.join(saved_ids)} — `~/Documents/claudio/lecciones/lean4/`\n"
    arch_path.write_text(rendered_arch, encoding="utf-8")
    print(f"Written: ARCHITECTURE.md ({len(rendered_arch.splitlines())} lines)")

    # ── Write BENCHMARKS.md ──────────────────────────────────────────
    if parsed_bench:
        rendered_bench = render_benchmarks(parsed_bench, parsed_arch, version)
        bench_path.write_text(rendered_bench, encoding="utf-8")
        print(f"Written: BENCHMARKS.md ({len(rendered_bench.splitlines())} lines)")

    print(f"\nTIDY COMPLETE: {parsed_arch.get('name', project.name)}")


if __name__ == "__main__":
    main()
