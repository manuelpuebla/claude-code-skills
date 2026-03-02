#!/usr/bin/env python3
"""Update project documentation (dag.json, ARCHITECTURE.md, BENCHMARKS.md).

Modes:
  --done NODE_ID        Mark node completed, update metrics from verify_node JSON
  --close-block BLOCK_ID  Close a block, append benchmark results to BENCHMARKS.md
  --sync-arch           Sync ARCHITECTURE.md DAG tables from dag.json
  --bump-version VER    Archive current version, start new version
  --status              Show current DAG status summary

Usage:
    python3 update_docs.py --project /path --done F1.1 --metrics '{"loc":450,"theorems":12}'
    python3 update_docs.py --project /path --close-block B1 --result result.json --lessons '[...]'
    python3 update_docs.py --project /path --sync-arch
    python3 update_docs.py --project /path --bump-version v2.0.0
    python3 update_docs.py --project /path --status
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import uuid

SAVE_LESSONS_SCRIPT = Path.home() / "Documents/claudio/lecciones/scripts/save_lessons.py"

TELEGRAM_FLAG = Path("/tmp/claude-telegram-active")
TELEGRAM_NOTIFY_DIR = Path("/tmp/claude-telegram/notify")


def telegram_notify(event: str, project: Path, **kwargs) -> None:
    """Write a notification JSON for the Telegram bridge (if active)."""
    if not TELEGRAM_FLAG.exists():
        return
    TELEGRAM_NOTIFY_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "event": event,
        "session_id": os.environ.get("CLAUDE_SESSION_ID", "?"),
        "cwd": str(project),
        **kwargs,
    }
    notify_path = TELEGRAM_NOTIFY_DIR / f"{uuid.uuid4()}.json"
    notify_path.write_text(json.dumps(data, ensure_ascii=False))


def load_dag(project: Path) -> dict:
    """Load dag.json from project root."""
    dag_path = project / "dag.json"
    if not dag_path.exists():
        print(f"ERROR: dag.json not found in {project}", file=sys.stderr)
        sys.exit(1)
    with open(dag_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_dag(project: Path, dag: dict) -> None:
    """Save dag.json to project root."""
    dag["meta"]["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dag["meta"]["completed_nodes"] = sum(
        1
        for phase in dag["phases"]
        for node in phase["nodes"]
        if node["status"] == "completed"
    )
    dag_path = project / "dag.json"
    with open(dag_path, "w", encoding="utf-8") as f:
        json.dump(dag, f, indent=2, ensure_ascii=False)
        f.write("\n")


def find_node(dag: dict, node_id: str) -> Optional[dict]:
    """Find a node by ID across all phases."""
    for phase in dag["phases"]:
        for node in phase["nodes"]:
            if node["id"] == node_id:
                return node
    return None


def find_block(dag: dict, block_id: str) -> Optional[dict]:
    """Find a block by ID across all phases."""
    for phase in dag["phases"]:
        for block in phase["blocks"]:
            if block["id"] == block_id:
                return block
    return None


# ─── --done: Mark node completed ─────────────────────────────────────────────


def cmd_done(project: Path, node_id: str, metrics_json: Optional[str]) -> None:
    """Mark a node as completed and update its metrics."""
    dag = load_dag(project)
    node = find_node(dag, node_id)

    if not node:
        print(f"ERROR: Node '{node_id}' not found in dag.json", file=sys.stderr)
        sys.exit(1)

    if node["status"] == "completed":
        print(f"WARNING: Node '{node_id}' already completed", file=sys.stderr)

    node["status"] = "completed"

    if metrics_json:
        try:
            metrics = json.loads(metrics_json)
        except json.JSONDecodeError:
            # Try as file path
            with open(metrics_json, "r", encoding="utf-8") as f:
                metrics = json.load(f)

        for key in ["loc", "theorems", "lemmas", "defs", "sorry"]:
            if key in metrics:
                node["metrics"][key] = metrics[key]

    # Update phase status
    for phase in dag["phases"]:
        if all(n["status"] == "completed" for n in phase["nodes"]):
            phase["status"] = "completed"
        elif any(n["status"] in ("in_progress", "completed") for n in phase["nodes"]):
            phase["status"] = "in_progress"

    save_dag(project, dag)
    sync_architecture(project, dag)

    total = dag["meta"]["total_nodes"]
    done = dag["meta"]["completed_nodes"]
    print(f"DONE: {node_id} marked completed ({done}/{total} nodes)")
    print(f"  Metrics: {json.dumps(node['metrics'])}")

    telegram_notify(
        "node_complete",
        project,
        node_id=node_id,
        node_name=node.get("name", node_id),
        metrics=node.get("metrics", {}),
        progress_done=done,
        progress_total=total,
    )


# ─── --close-block: Close block + append benchmarks ─────────────────────────


def save_block_lessons(lessons_json: str) -> None:
    """Persist lessons extracted during QA via save_lessons.py."""
    if not SAVE_LESSONS_SCRIPT.exists():
        print("WARNING: save_lessons.py not found, skipping lesson save", file=sys.stderr)
        return

    result = subprocess.run(
        [sys.executable, str(SAVE_LESSONS_SCRIPT), "--lessons", lessons_json],
        capture_output=True, text=True, timeout=30,
    )

    if result.returncode != 0:
        print(f"WARNING: save_lessons.py failed: {result.stderr[:300]}", file=sys.stderr)
        return

    try:
        output = json.loads(result.stdout)
        saved = output.get("lessons", [])
        if saved:
            print(f"  LESSONS: {len(saved)} saved")
            for lesson in saved:
                print(f"    {lesson['id']} → {lesson['file']}:{lesson['section']} — {lesson['title']}")
        else:
            print("  LESSONS: none to save")
    except json.JSONDecodeError:
        print("  LESSONS: saved (could not parse output)", file=sys.stderr)


def cmd_close_block(
    project: Path, block_id: str,
    result_json: Optional[str], lessons_json: Optional[str],
) -> None:
    """Close a block and append benchmark results to BENCHMARKS.md."""
    dag = load_dag(project)
    block = find_block(dag, block_id)

    if not block:
        print(f"ERROR: Block '{block_id}' not found in dag.json", file=sys.stderr)
        sys.exit(1)

    # Verify all nodes in block are completed
    incomplete = []
    for nid in block["nodes"]:
        node = find_node(dag, nid)
        if node and node["status"] != "completed":
            incomplete.append(nid)

    if incomplete:
        print(f"ERROR: Block '{block_id}' has incomplete nodes: {', '.join(incomplete)}", file=sys.stderr)
        print("  Complete all nodes before closing the block.", file=sys.stderr)
        sys.exit(1)

    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    block["status"] = "completed"
    block["closed_at"] = now_date

    save_dag(project, dag)
    sync_architecture(project, dag)

    # Append benchmark results to BENCHMARKS.md
    result = None
    if result_json:
        try:
            result = json.loads(result_json)
        except json.JSONDecodeError:
            with open(result_json, "r", encoding="utf-8") as f:
                result = json.load(f)

    append_benchmark_result(project, dag, block, result)

    # Save lessons extracted during QA
    if lessons_json:
        save_block_lessons(lessons_json)

    print(f"CLOSED: {block_id} ({block['name']})")
    print(f"  Nodes: {', '.join(block['nodes'])}")
    print(f"  Date: {now_date}")


def append_benchmark_result(
    project: Path, dag: dict, block: dict, result: Optional[dict]
) -> None:
    """Append a block's benchmark results to BENCHMARKS.md."""
    bench_path = project / "BENCHMARKS.md"
    if not bench_path.exists():
        print("WARNING: BENCHMARKS.md not found, skipping result append", file=sys.stderr)
        return

    content = bench_path.read_text(encoding="utf-8")
    version = dag["version"]
    now_date = block.get("closed_at", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    # Collect metrics from nodes
    total_loc = 0
    total_thm = 0
    total_lem = 0
    total_def = 0
    total_sorry = 0
    node_names = []
    for nid in block["nodes"]:
        node = find_node(dag, nid)
        if node:
            m = node.get("metrics", {})
            total_loc += m.get("loc", 0)
            total_thm += m.get("theorems", 0)
            total_lem += m.get("lemmas", 0)
            total_def += m.get("defs", 0)
            total_sorry += m.get("sorry", 0)
            node_names.append(f"{node['id']} {node['name']}")

    # Build result section
    section = []
    section.append(f"### {block['name']} ({version})")
    section.append("")
    status_str = result.get("status", "PASS") if result else "PASS"
    section.append(f"**Closed**: {now_date} | **Status**: {status_str}")
    section.append("")

    # 1. What is tested and why
    section.append("#### 1. What is tested and why")
    section.append("")
    if result and result.get("description"):
        section.append(result["description"])
    else:
        section.append(f"Nodes covered: {', '.join(node_names)}.")
    section.append("")

    # 2. Performance
    section.append("#### 2. Performance")
    section.append("")
    section.append("| Metric | Target | Actual | Status |")
    section.append("|--------|--------|--------|--------|")
    section.append(f"| LOC | — | {total_loc} | — |")
    section.append(f"| Theorems | — | {total_thm} | — |")
    section.append(f"| Lemmas | — | {total_lem} | — |")
    section.append(f"| Defs | — | {total_def} | — |")

    sorry_status = "PASS" if total_sorry == 0 else "FAIL"
    section.append(f"| Sorry count | 0 | {total_sorry} | {sorry_status} |")

    if result and result.get("metrics"):
        for key, val in result["metrics"].items():
            if key not in ("loc", "theorems", "lemmas", "defs", "sorry"):
                target = val.get("target", "—") if isinstance(val, dict) else "—"
                actual = val.get("actual", val) if isinstance(val, dict) else val
                st = val.get("status", "—") if isinstance(val, dict) else "—"
                section.append(f"| {key} | {target} | {actual} | {st} |")

    section.append("")

    # 3. Acceptability Analysis
    section.append("#### 3. Acceptability Analysis")
    section.append("")
    if result and result.get("acceptability"):
        section.append(result["acceptability"])
    else:
        if total_sorry == 0:
            section.append("- **Acceptable**: Meets minimum criteria (zero sorry, compiles)")
        else:
            section.append(f"- **Compromises integrity**: {total_sorry} sorry remaining")
    section.append("")

    # 4. Bugs, Warnings, Sorries
    section.append("#### 4. Bugs, Warnings, Sorries")
    section.append("")
    section.append("| Item | Location | Cause | Affected Nodes | Mitigation |")
    section.append("|------|----------|-------|----------------|------------|")

    if result and result.get("issues"):
        for issue in result["issues"]:
            section.append(
                f"| {issue.get('item', '?')} | {issue.get('location', '?')} "
                f"| {issue.get('cause', '?')} | {issue.get('affected', '?')} "
                f"| {issue.get('mitigation', '?')} |"
            )
    else:
        section.append("| (none) | — | — | — | — |")

    section.append("")

    block_text = "\n".join(section)

    # Insert after "## Current Results" heading, replacing placeholder if present
    placeholder = "(no blocks closed yet)"
    if placeholder in content:
        content = content.replace(placeholder, block_text)
    else:
        # Find "## Current Results" and append after existing blocks
        marker = "## Current Results"
        next_section = "## Previous Results"
        idx_current = content.find(marker)
        idx_prev = content.find(next_section)

        if idx_current >= 0 and idx_prev >= 0:
            # Insert before "## Previous Results"
            insert_point = idx_prev
            # Add separator
            content = content[:insert_point] + block_text + "\n" + content[insert_point:]
        elif idx_current >= 0:
            # No previous results section, append at end
            content = content.rstrip() + "\n\n" + block_text + "\n"
        else:
            # No current results section at all, append at end
            content = content.rstrip() + "\n\n## Current Results\n\n" + block_text + "\n"

    bench_path.write_text(content, encoding="utf-8")
    print(f"  BENCHMARKS.md: appended results for {block['name']}")


# ─── --sync-arch: Sync ARCHITECTURE.md from dag.json ────────────────────────


def sync_architecture(project: Path, dag: dict) -> None:
    """Sync ARCHITECTURE.md DAG tables and block checkmarks from dag.json.

    Matches tables by phase name (not position), so old phases without
    current-version DAG tables are safely skipped.
    """
    arch_path = project / "ARCHITECTURE.md"
    if not arch_path.exists():
        print("WARNING: ARCHITECTURE.md not found, skipping sync", file=sys.stderr)
        return

    content = arch_path.read_text(encoding="utf-8")
    version = dag["version"]

    type_abbrev = {
        "FUNDACIONAL": "FUND",
        "CRITICO": "CRIT",
        "PARALELO": "PAR",
        "HOJA": "HOJA",
    }

    dag_header_str = f"#### DAG ({version})"
    table_header = "| Nodo | Tipo | Deps | Status |"
    table_sep_pattern = re.compile(r"\|[-]+\|[-]+\|[-]+\|[-]+\|")

    # For each phase, find its section by name, then its DAG table
    for phase in dag["phases"]:
        phase_header = f"### {phase['name']}"
        phase_pos = content.find(phase_header)
        if phase_pos < 0:
            continue

        # Find the boundary of this phase section (next ### or ## header)
        phase_end = len(content)
        for boundary in ["\n### ", "\n## "]:
            bi = content.find(boundary, phase_pos + len(phase_header))
            if 0 <= bi < phase_end:
                phase_end = bi

        # Find DAG header within this phase section
        dag_pos = content.find(dag_header_str, phase_pos)
        if dag_pos < 0 or dag_pos >= phase_end:
            continue  # This phase has no current-version DAG table (old phase)

        # Find table structure
        th_pos = content.find(table_header, dag_pos)
        if th_pos < 0 or th_pos >= phase_end:
            continue

        sep_match = table_sep_pattern.search(content, th_pos + len(table_header))
        if not sep_match or sep_match.start() >= phase_end:
            continue

        # Find end of table rows
        table_start = sep_match.end()
        if table_start < len(content) and content[table_start] == "\n":
            table_start += 1

        table_end = table_start
        while table_end < len(content):
            line_end = content.find("\n", table_end)
            if line_end < 0:
                line_end = len(content)
            line = content[table_end:line_end]
            if not line.startswith("|"):
                break
            table_end = line_end + 1

        # Build replacement rows
        rows = []
        for node in phase["nodes"]:
            abbr = type_abbrev.get(node["type"], node["type"][:4])
            deps = ", ".join(node["deps"]) if node["deps"] else "—"
            mark = " ✓" if node["status"] == "completed" else ""
            rows.append(
                f"| {node['id']} {node['name']} | {abbr} | {deps} | {node['status']}{mark} |"
            )

        new_rows = "\n".join(rows) + "\n"
        content = content[:table_start] + new_rows + content[table_end:]

    # Update block checkmarks
    for phase in dag["phases"]:
        for block in phase["blocks"]:
            node_list = ", ".join(block["nodes"])
            old_pattern = re.compile(
                r"- \[[ x]\] \*\*" + re.escape(block["name"]) + r"\*\*: "
                + re.escape(node_list) + r"[^\n]*"
            )
            if block["status"] == "completed":
                closed = f" — closed {block['closed_at']}" if block.get("closed_at") else ""
                replacement = f"- [x] **{block['name']}**: {node_list}{closed}"
            else:
                replacement = f"- [ ] **{block['name']}**: {node_list}"

            content = old_pattern.sub(replacement, content)

    arch_path.write_text(content, encoding="utf-8")


# ─── --bump-version: Archive and start new version ──────────────────────────


def cmd_bump_version(project: Path, new_version: str) -> None:
    """Archive current version completely and clear active sections.

    After bump:
      - dag.json: empty phases, new version (old archived to dag.{old}.json)
      - ARCHITECTURE.md: all phase sections moved to Previous Versions,
        active area clean for new init
      - BENCHMARKS.md: criteria + results moved to Previous, active reset
    """
    dag = load_dag(project)
    old_version = dag["version"]
    project_name = dag["project"]

    if old_version == new_version:
        print(f"ERROR: New version '{new_version}' same as current", file=sys.stderr)
        sys.exit(1)

    # Archive old dag.json (complete copy)
    old_dag_path = project / f"dag.{old_version}.json"
    shutil.copy2(project / "dag.json", old_dag_path)
    print(f"  Archived: dag.json -> dag.{old_version}.json")

    old_phase_count = len(dag["phases"])
    old_node_count = dag["meta"]["total_nodes"]

    # ── ARCHITECTURE.md: move ALL current phase content to Previous ──────
    arch_path = project / "ARCHITECTURE.md"
    if arch_path.exists():
        content = arch_path.read_text(encoding="utf-8")

        # Extract everything between "## Current Version:" and "## Previous Versions"
        cv_marker = f"## Current Version: {old_version}"
        pv_marker = "## Previous Versions"
        cv_idx = content.find(cv_marker)
        pv_idx = content.find(pv_marker)

        if cv_idx >= 0 and pv_idx >= 0:
            # Content to archive = everything between version header and Previous
            after_cv = content.find("\n", cv_idx) + 1
            current_body = content[after_cv:pv_idx].strip().rstrip("-").strip()

            if current_body:
                # Insert archived content into Previous Versions
                after_pv = content.find("\n", pv_idx) + 1
                rest = content[after_pv:]
                if rest.startswith("\n(none)"):
                    rest = rest[7:]

                archived_block = f"\n### {old_version}\n\n{current_body}\n\n"

                # Rebuild: header + empty current + Previous with archived + Lessons
                content = (
                    content[:after_cv]
                    + "\n"  # empty current section
                    + content[pv_idx:pv_idx + len(pv_marker)] + "\n"
                    + archived_block
                    + rest
                )

            # Update version header
            content = content.replace(
                f"## Current Version: {old_version}",
                f"## Current Version: {new_version}",
            )

            # Clear lessons (current) — start fresh
            lessons_marker = "## Lessons (current)"
            li = content.find(lessons_marker)
            if li >= 0:
                after_lessons = content.find("\n", li) + 1
                # Find end of lessons section (next ## or end of file)
                next_section = len(content)
                ni = content.find("\n## ", after_lessons)
                if ni >= 0:
                    next_section = ni

                content = (
                    content[:after_lessons]
                    + "\nProject-specific lessons learned during current version.\n"
                    + "Generalized lessons should be migrated to `~/Documents/claudio/lecciones/lean4/`.\n"
                    + content[next_section:]
                )

        arch_path.write_text(content, encoding="utf-8")
        print(f"  ARCHITECTURE.md: archived {old_version} ({old_phase_count} phases), active section cleared")

    # ── BENCHMARKS.md: move criteria + results to Previous ───────────────
    bench_path = project / "BENCHMARKS.md"
    if bench_path.exists():
        content = bench_path.read_text(encoding="utf-8")

        # Extract everything between title and Previous Results
        criteria_marker = "## Criteria"
        current_marker = "## Current Results"
        prev_marker = "## Previous Results"

        cri_idx = content.find(criteria_marker)
        cur_idx = content.find(current_marker)
        pi = content.find(prev_marker)

        archived_parts = []

        # Archive criteria
        if cri_idx >= 0 and cur_idx >= 0:
            criteria_body = content[cri_idx:cur_idx].strip()
            if criteria_body:
                archived_parts.append(criteria_body)

        # Archive current results
        if cur_idx >= 0 and pi >= 0:
            results_body = content[cur_idx + len(current_marker):pi].strip()
            if results_body and results_body != "(no blocks closed yet)":
                archived_parts.append(f"## Results ({old_version})\n\n{results_body}")

        if archived_parts and pi >= 0:
            after_prev = content.find("\n", pi) + 1
            rest = content[after_prev:]
            if rest.startswith("\n(none)"):
                rest = rest[7:]

            archived_block = f"\n### {old_version}\n\n" + "\n\n".join(archived_parts) + "\n\n"

            # Rebuild: title + empty criteria + empty results + Previous with archived
            content = (
                f"# {project_name} Benchmarks ({new_version})\n\n"
                f"## Criteria\n\n"
                f"(pending — run `/benchmark-qa --strict` during planning)\n\n"
                f"---\n\n"
                f"## Current Results\n\n"
                f"(no blocks closed yet)\n\n"
                f"---\n\n"
                f"{prev_marker}\n"
                f"{archived_block}"
                + rest
            )
        else:
            # Fallback: just update title
            content = re.sub(
                r"# .+ Benchmarks \([^)]+\)",
                f"# {project_name} Benchmarks ({new_version})",
                content,
                count=1,
            )

        bench_path.write_text(content, encoding="utf-8")
        print(f"  BENCHMARKS.md: archived {old_version} criteria + results, active reset")

    # ── dag.json: clear phases, new version ──────────────────────────────
    dag["version"] = new_version
    dag["phases"] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dag["meta"]["updated"] = now
    dag["meta"]["total_nodes"] = 0
    dag["meta"]["completed_nodes"] = 0
    save_dag(project, dag)

    print(f"BUMP: {old_version} -> {new_version} ({old_node_count} nodes archived, dag.json cleared)")


# ─── --status: Show DAG status ──────────────────────────────────────────────


def cmd_status(project: Path) -> None:
    """Show current DAG status summary."""
    dag = load_dag(project)
    version = dag["version"]
    total = dag["meta"]["total_nodes"]
    done = dag["meta"]["completed_nodes"]

    print(f"PROJECT: {dag['project']} ({version})")
    print(f"PROGRESS: {done}/{total} nodes completed")
    print()

    for phase in dag["phases"]:
        phase_done = sum(1 for n in phase["nodes"] if n["status"] == "completed")
        phase_total = len(phase["nodes"])
        phase_mark = " ✓" if phase["status"] == "completed" else ""
        print(f"  {phase['name']}{phase_mark} ({phase_done}/{phase_total})")

        for block in phase["blocks"]:
            check = "x" if block["status"] == "completed" else " "
            print(f"    [{check}] {block['name']}: {', '.join(block['nodes'])}")

        for node in phase["nodes"]:
            status_icon = {
                "completed": "✓",
                "in_progress": "→",
                "pending": "·",
                "blocked": "✗",
            }.get(node["status"], "?")
            m = node.get("metrics", {})
            metrics_str = ""
            if node["status"] == "completed" and m.get("loc", 0) > 0:
                metrics_str = f" [{m['loc']}L {m.get('theorems',0)}T {m.get('sorry',0)}S]"
            print(f"      {status_icon} {node['id']} {node['name']}{metrics_str}")

        print()


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Update project documentation (dag.json, ARCHITECTURE.md, BENCHMARKS.md)"
    )
    parser.add_argument("--project", required=True, help="Project root path")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--done", metavar="NODE_ID", help="Mark node completed")
    group.add_argument("--close-block", metavar="BLOCK_ID", help="Close a block")
    group.add_argument("--sync-arch", action="store_true", help="Sync ARCHITECTURE.md from dag.json")
    group.add_argument("--bump-version", metavar="VERSION", help="Archive current, start new version")
    group.add_argument("--status", action="store_true", help="Show DAG status")

    parser.add_argument("--metrics", help="Node metrics JSON string or file path (for --done)")
    parser.add_argument("--result", help="Block result JSON string or file path (for --close-block)")
    parser.add_argument("--lessons", help="Lessons JSON array from QA (for --close-block)")

    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"ERROR: Project path does not exist: {project}", file=sys.stderr)
        sys.exit(1)

    if args.done:
        cmd_done(project, args.done, args.metrics)
    elif args.close_block:
        cmd_close_block(project, args.close_block, args.result, args.lessons)
    elif args.sync_arch:
        dag = load_dag(project)
        sync_architecture(project, dag)
        print(f"SYNC: ARCHITECTURE.md updated from dag.json")
    elif args.bump_version:
        cmd_bump_version(project, args.bump_version)
    elif args.status:
        cmd_status(project)


if __name__ == "__main__":
    main()
