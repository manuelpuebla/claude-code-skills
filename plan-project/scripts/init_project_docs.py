#!/usr/bin/env python3
"""Initialize or extend project documentation from approved plan data.

Creates or updates dag.json, ARCHITECTURE.md, and BENCHMARKS.md.
Input: JSON plan structure (from stdin or --plan file).

Behavior:
  - No files exist  → creates everything from scratch
  - Files exist     → extends: adds new phases, preserves existing content
  - --force         → overwrites everything (destructive)

Usage:
    # Fresh project
    python3 init_project_docs.py --project /path --name "Project" --version v1.0.0 --plan plan.json

    # New version on existing project (after bump-version)
    python3 init_project_docs.py --project /path --name "Project" --version v1.2.0 --plan plan.json

    # Pipe from stdin
    echo '{"phases": [...]}' | python3 init_project_docs.py --project . --name "Project" --version v1.0.0

Plan JSON format:
{
  "phases": [
    {
      "id": "fase1",
      "name": "Fase 1: Core",
      "description": "What this phase delivers",
      "nodes": [
        {
          "id": "F1.1",
          "name": "Node name",
          "type": "FUNDACIONAL",
          "files": ["Src/File.lean"],
          "deps": [],
          "blocks": ["F1.2"]
        }
      ],
      "blocks": [
        {"id": "B1", "name": "Bloque 1", "nodes": ["F1.1", "F1.2"]}
      ]
    }
  ],
  "rubric": {
    "correctness": ["Zero sorry", "lake build passes"],
    "performance": ["Target description"],
    "quality": ["No anti-patterns"]
  }
}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


TYPE_ABBREV = {
    "FUNDACIONAL": "FUND",
    "CRITICO": "CRIT",
    "PARALELO": "PAR",
    "HOJA": "HOJA",
}


# ─── DAG building ────────────────────────────────────────────────────────────


def build_new_phases(plan: dict) -> list[dict]:
    """Build dag phase structures from plan phases."""
    phases = []
    for phase in plan.get("phases", []):
        nodes = []
        for node in phase.get("nodes", []):
            # Count properties for this node from plan
            node_props = [
                p for p in plan.get("properties", [])
                if p.get("node") == node["id"]
            ]
            nr_count = sum(
                1 for p in node_props
                if "not yet runnable" in p.get("stub", "").lower()
                or "NOT_YET_RUNNABLE" in p.get("stub", "")
            )

            nodes.append({
                "id": node["id"],
                "name": node.get("name", node["id"]),
                "type": node.get("type", "HOJA"),
                "status": "pending",
                "files": node.get("files", []),
                "deps": node.get("deps", []),
                "blocks": node.get("blocks", []),
                "metrics": {
                    "loc": 0,
                    "theorems": 0,
                    "lemmas": 0,
                    "defs": 0,
                    "sorry": 0,
                },
                "properties": {
                    "total": len(node_props),
                    "passing": 0,
                    "failing": 0,
                    "not_runnable": nr_count,
                },
            })

        blocks = []
        for block in phase.get("blocks", []):
            blocks.append({
                "id": block["id"],
                "name": block.get("name", block["id"]),
                "nodes": block.get("nodes", []),
                "status": "pending",
                "closed_at": None,
            })

        phases.append({
            "id": phase["id"],
            "name": phase.get("name", phase["id"]),
            "status": "pending",
            "nodes": nodes,
            "blocks": blocks,
        })

    return phases


def build_dag_fresh(plan: dict, project_name: str, version: str) -> dict:
    """Build a complete dag.json from scratch."""
    phases = build_new_phases(plan)
    total_nodes = sum(len(p["nodes"]) for p in phases)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "version": version,
        "project": project_name,
        "phases": phases,
        "meta": {
            "created": now,
            "updated": now,
            "total_nodes": total_nodes,
            "completed_nodes": 0,
        },
    }


def populate_dag(existing: dict, plan: dict, version: str) -> tuple[dict, list[dict]]:
    """Write new phases into dag.json (expected empty after bump).

    Returns (updated_dag, new_phases). Detects ID conflicts as safety check.
    """
    new_phases = build_new_phases(plan)

    # Safety: check for ID conflicts with any residual phases
    existing_node_ids = {
        n["id"] for p in existing["phases"] for n in p["nodes"]
    }
    new_node_ids = {n["id"] for p in new_phases for n in p["nodes"]}
    conflicts = existing_node_ids & new_node_ids
    if conflicts:
        print(f"ERROR: Node IDs already exist in dag.json: {', '.join(sorted(conflicts))}", file=sys.stderr)
        print("  Run `update_docs.py --bump-version` first to archive old phases.", file=sys.stderr)
        sys.exit(1)

    existing["phases"] = new_phases  # replace, not extend
    existing["version"] = version
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing["meta"]["updated"] = now
    existing["meta"]["total_nodes"] = sum(len(p["nodes"]) for p in new_phases)
    existing["meta"]["completed_nodes"] = 0

    return existing, new_phases


# ─── Rendering ───────────────────────────────────────────────────────────────


def render_phase_section(phase: dict, plan_phase: dict | None, version: str) -> str:
    """Render a single phase section for ARCHITECTURE.md."""
    lines = []
    lines.append(f"### {phase['name']}")
    lines.append("")

    if plan_phase and plan_phase.get("description"):
        lines.append(f"**Contents**: {plan_phase['description']}")
        lines.append("")

    # Files from nodes
    all_files = []
    for node in phase["nodes"]:
        for f in node.get("files", []):
            if f not in all_files:
                all_files.append(f)

    if all_files:
        lines.append("**Files**:")
        for f in all_files:
            lines.append(f"- `{f}`")
        lines.append("")

    # DAG table
    lines.append(f"#### DAG ({version})")
    lines.append("")
    lines.append("| Nodo | Tipo | Deps | Status |")
    lines.append("|------|------|------|--------|")

    for node in phase["nodes"]:
        abbr = TYPE_ABBREV.get(node["type"], node["type"][:4])
        deps = ", ".join(node["deps"]) if node["deps"] else "—"
        lines.append(f"| {node['id']} {node['name']} | {abbr} | {deps} | {node['status']} |")

    lines.append("")

    # Formal Properties table (natural-language, from plan)
    if plan_phase:
        plan_properties = plan_phase.get("_properties", [])
        if plan_properties:
            lines.append(f"#### Formal Properties ({version})")
            lines.append("")
            lines.append("| Nodo | Propiedad | Tipo | Prioridad |")
            lines.append("|------|-----------|------|-----------|")
            for prop in plan_properties:
                lines.append(
                    f"| {prop.get('node', '?')} | {prop.get('description', '?')} "
                    f"| {prop.get('type', '?')} | {prop.get('priority', '?')} |"
                )
            lines.append("")
            lines.append("> **Nota**: Propiedades en lenguaje natural (intención de diseño).")
            lines.append("> Los stubs ejecutables están en BENCHMARKS.md § Formal Properties.")
            lines.append("")

    # Blocks
    if phase["blocks"]:
        lines.append("#### Bloques")
        lines.append("")
        for block in phase["blocks"]:
            check = "x" if block["status"] == "completed" else " "
            node_list = ", ".join(block["nodes"])
            closed = f" — closed {block['closed_at']}" if block.get("closed_at") else ""
            lines.append(f"- [{check}] **{block['name']}**: {node_list}{closed}")
        lines.append("")

    return "\n".join(lines)


def render_architecture_fresh(dag: dict, plan: dict) -> str:
    """Render complete ARCHITECTURE.md from scratch."""
    lines = []
    project = dag["project"]
    version = dag["version"]

    lines.append(f"# {project}: Architecture")
    lines.append("")
    lines.append(f"## Current Version: {version}")
    lines.append("")

    all_properties = plan.get("properties", [])
    for phase in dag["phases"]:
        plan_phase = next(
            (p for p in plan.get("phases", []) if p["id"] == phase["id"]),
            None,
        )
        # Attach properties relevant to this phase's nodes
        if plan_phase:
            phase_node_ids = {n["id"] for n in phase["nodes"]}
            plan_phase["_properties"] = [
                p for p in all_properties if p.get("node") in phase_node_ids
            ]
        lines.append(render_phase_section(phase, plan_phase, version))

    lines.append("---")
    lines.append("")
    lines.append("## Previous Versions")
    lines.append("")
    lines.append("(none)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Lessons (current)")
    lines.append("")
    lines.append("Project-specific lessons learned during current version.")
    lines.append("Generalized lessons should be migrated to `~/Documents/claudio/lecciones/lean4/`.")
    lines.append("")

    return "\n".join(lines)


def populate_architecture(arch_path: Path, new_phases: list[dict], plan: dict, version: str) -> None:
    """Write new phase sections into clean active area of ARCHITECTURE.md.

    Expects active area to be empty (after bump-version).
    Preserves Previous Versions and Lessons sections.
    """
    content = arch_path.read_text(encoding="utf-8")

    # Build new phase sections
    all_properties = plan.get("properties", [])
    new_sections = ""
    for phase in new_phases:
        plan_phase = next(
            (p for p in plan.get("phases", []) if p["id"] == phase["id"]),
            None,
        )
        if plan_phase:
            phase_node_ids = {n["id"] for n in phase["nodes"]}
            plan_phase["_properties"] = [
                p for p in all_properties if p.get("node") in phase_node_ids
            ]
        new_sections += render_phase_section(phase, plan_phase, version) + "\n"

    # Insert after "## Current Version: vX.Y.Z\n" line, before "---\n...## Previous"
    cv_pattern = re.compile(r"(## Current Version: [^\n]+\n)\n*")
    match = cv_pattern.search(content)
    if match:
        insert_pos = match.end()
        # Find the next --- before Previous Versions
        pv_sep = content.find("---\n\n## Previous Versions", insert_pos)
        pv_bare = content.find("## Previous Versions", insert_pos)

        if pv_sep >= 0:
            # Replace empty space between version header and separator
            content = content[:insert_pos] + "\n" + new_sections + content[pv_sep:]
        elif pv_bare >= 0:
            content = content[:insert_pos] + "\n" + new_sections + "---\n\n" + content[pv_bare:]
        else:
            content = content[:insert_pos] + "\n" + new_sections
    else:
        # No version header found, append
        content = content.rstrip() + "\n\n" + new_sections

    arch_path.write_text(content, encoding="utf-8")


def render_benchmarks_fresh(dag: dict, plan: dict) -> str:
    """Render complete BENCHMARKS.md from scratch."""
    lines = []
    project = dag["project"]
    version = dag["version"]

    lines.append(f"# {project} Benchmarks ({version})")
    lines.append("")

    rubric = plan.get("rubric", {})
    lines.append("## Criteria")
    lines.append("")
    lines.append("Rubric generated by `/benchmark-qa --strict` during planning.")
    lines.append("This section is written ONCE and not modified during execution.")
    lines.append("")

    if rubric.get("correctness"):
        lines.append("### Correctness")
        for item in rubric["correctness"]:
            lines.append(f"- {item}")
        lines.append("")

    if rubric.get("performance"):
        lines.append("### Performance")
        for item in rubric["performance"]:
            lines.append(f"- {item}")
        lines.append("")

    if rubric.get("quality"):
        lines.append("### Quality")
        for item in rubric["quality"]:
            lines.append(f"- {item}")
        lines.append("")

    if not rubric:
        lines.append("### Correctness")
        lines.append("- Zero sorry, zero axiom, zero admit")
        lines.append("- `lake build` passes with zero warnings")
        lines.append("- All dependent modules compile")
        lines.append("")
        lines.append("### Performance")
        lines.append("- (define targets after `/benchmark-qa --strict`)")
        lines.append("")
        lines.append("### Quality")
        lines.append("- No anti-patterns (native_decide, simp[*])")
        lines.append("- Doc comments on public API")
        lines.append("")

    lines.append("---")
    lines.append("")

    # Formal Properties section (executable SlimCheck stubs)
    properties = plan.get("properties", [])
    lines.append("## Formal Properties")
    lines.append("")
    if properties:
        lines.append("Executable SlimCheck stubs per node. Generated during planning from the")
        lines.append("natural-language properties in ARCHITECTURE.md § Formal Properties.")
        lines.append("Written ONCE per version, not modified during execution.")
        lines.append("")

        # Group by node
        nodes_seen = []
        props_by_node = {}
        for prop in properties:
            nid = prop.get("node", "?")
            if nid not in props_by_node:
                props_by_node[nid] = []
                nodes_seen.append(nid)
            props_by_node[nid].append(prop)

        for nid in nodes_seen:
            # Find node name from dag
            node_name = nid
            for phase in dag.get("phases", []):
                for node in phase.get("nodes", []):
                    if node["id"] == nid:
                        node_name = f"{nid} {node['name']}"
                        break

            lines.append(f"### {node_name}")
            lines.append("")
            lines.append("```lean")
            for prop in props_by_node[nid]:
                priority = prop.get("priority", "P1")
                ptype = prop.get("type", "UNKNOWN")
                desc = prop.get("description", "")
                stub = prop.get("stub", "")
                lines.append(f"-- {priority}, {ptype}: {desc}")
                if stub:
                    lines.append(stub)
                lines.append("")
            lines.append("```")
            lines.append("")
    else:
        lines.append("(no properties defined — generate with `/plan-project` Paso 6c)")
        lines.append("")

    lines.append("> **Nota**: Los stubs requieren `import Mathlib.Testing.SlimCheck`.")
    lines.append("> Tipos custom necesitan instancias `SampleableExt` + `Shrinkable`.")
    lines.append("> Stubs son advisory — no bloquean cierre de nodo, pero se reportan en cobertura.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Current Results")
    lines.append("")
    lines.append("(no blocks closed yet)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Previous Results")
    lines.append("")
    lines.append("(none)")
    lines.append("")

    return "\n".join(lines)


def populate_benchmarks(bench_path: Path, plan: dict, version: str) -> None:
    """Write new rubric into BENCHMARKS.md Criteria section.

    After bump-version, Criteria contains a placeholder. This replaces it
    with the new version's rubric from the plan.
    """
    content = bench_path.read_text(encoding="utf-8")

    rubric = plan.get("rubric", {})
    if not rubric:
        return  # No rubric in plan, leave placeholder

    # Build new criteria content
    criteria_lines = []
    criteria_lines.append("## Criteria")
    criteria_lines.append("")
    criteria_lines.append("Rubric generated by `/benchmark-qa --strict` during planning.")
    criteria_lines.append("This section is written ONCE and not modified during execution.")
    criteria_lines.append("")

    if rubric.get("correctness"):
        criteria_lines.append("### Correctness")
        for item in rubric["correctness"]:
            criteria_lines.append(f"- {item}")
        criteria_lines.append("")

    if rubric.get("performance"):
        criteria_lines.append("### Performance")
        for item in rubric["performance"]:
            criteria_lines.append(f"- {item}")
        criteria_lines.append("")

    if rubric.get("quality"):
        criteria_lines.append("### Quality")
        for item in rubric["quality"]:
            criteria_lines.append(f"- {item}")
        criteria_lines.append("")

    new_criteria = "\n".join(criteria_lines)

    # Replace the Criteria section (from "## Criteria" to the next "---")
    cri_idx = content.find("## Criteria")
    if cri_idx >= 0:
        # Find next --- separator after criteria
        sep_idx = content.find("\n---\n", cri_idx)
        if sep_idx >= 0:
            content = content[:cri_idx] + new_criteria + content[sep_idx:]
        else:
            content = content[:cri_idx] + new_criteria + "\n---\n" + content[cri_idx:]
    else:
        # No criteria section, insert after title
        first_nl = content.find("\n")
        if first_nl >= 0:
            content = content[:first_nl + 1] + "\n" + new_criteria + "\n---\n" + content[first_nl + 1:]

    bench_path.write_text(content, encoding="utf-8")


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Initialize or extend project docs from approved plan"
    )
    parser.add_argument("--project", required=True, help="Project root path")
    parser.add_argument("--name", required=True, help="Project display name")
    parser.add_argument("--version", default="v1.0.0", help="Version tag")
    parser.add_argument("--plan", help="Path to plan JSON file (default: stdin)")
    parser.add_argument("--force", action="store_true", help="Overwrite all existing files")
    parser.add_argument("--check", action="store_true",
                        help="Check only: exit 0 if docs need creation, exit 2 if already populated")
    args = parser.parse_args()

    project_path = Path(args.project).resolve()
    if not project_path.is_dir():
        print(f"ERROR: Project path does not exist: {project_path}", file=sys.stderr)
        sys.exit(1)

    # Load plan
    if args.plan:
        with open(args.plan, "r", encoding="utf-8") as f:
            plan = json.load(f)
    else:
        plan = json.load(sys.stdin)

    dag_path = project_path / "dag.json"
    arch_path = project_path / "ARCHITECTURE.md"
    bench_path = project_path / "BENCHMARKS.md"

    files_exist = dag_path.exists() or arch_path.exists() or bench_path.exists()

    # ── Check mode: detect if docs already cover this plan ───────────────
    if args.check:
        if not dag_path.exists():
            print("CHECK: no dag.json — docs need creation")
            sys.exit(0)

        with open(dag_path, "r", encoding="utf-8") as f:
            existing = json.load(f)

        # If dag has no phases (post-bump), docs need populating
        if not existing["phases"]:
            print("CHECK: dag.json empty (post-bump) — docs need populating")
            sys.exit(0)

        # If dag already has phases, check if plan phases are already there
        existing_phase_ids = {p["id"] for p in existing["phases"]}
        plan_phase_ids = {p["id"] for p in plan.get("phases", [])}
        new_ids = plan_phase_ids - existing_phase_ids

        if new_ids:
            print(f"CHECK: new phases not in dag.json ({', '.join(sorted(new_ids))}) — docs need creation")
            sys.exit(0)
        else:
            print(f"CHECK: all plan phases already in dag.json — no action needed")
            sys.exit(2)

    # ── Force: overwrite everything ──────────────────────────────────────
    if args.force or not files_exist:
        dag = build_dag_fresh(plan, args.name, args.version)

        with open(dag_path, "w", encoding="utf-8") as f:
            json.dump(dag, f, indent=2, ensure_ascii=False)
            f.write("\n")

        arch_content = render_architecture_fresh(dag, plan)
        with open(arch_path, "w", encoding="utf-8") as f:
            f.write(arch_content)

        bench_content = render_benchmarks_fresh(dag, plan)
        with open(bench_path, "w", encoding="utf-8") as f:
            f.write(bench_content)

        total = dag["meta"]["total_nodes"]
        phases = len(dag["phases"])
        blocks = sum(len(p["blocks"]) for p in dag["phases"])
        mode = "CREATED" if not files_exist else "OVERWRITTEN (--force)"

        print(f"INIT_DOCS [{mode}]: {args.name} {args.version}")
        print(f"  dag.json:        {total} nodes, {phases} phases, {blocks} blocks")
        print(f"  ARCHITECTURE.md: {len(arch_content.splitlines())} lines")
        print(f"  BENCHMARKS.md:   {len(bench_content.splitlines())} lines")
        print(f"  Location:        {project_path}")
        return

    # ── Populate: write new version content into clean active sections ──
    if not dag_path.exists():
        print("ERROR: dag.json missing. Use --force to recreate all.", file=sys.stderr)
        sys.exit(1)

    with open(dag_path, "r", encoding="utf-8") as f:
        existing_dag = json.load(f)

    # Safety: warn if old phases still present (bump not run)
    if existing_dag["phases"]:
        old_nodes = sum(len(p["nodes"]) for p in existing_dag["phases"])
        if old_nodes > 0:
            print(f"WARNING: dag.json still has {old_nodes} nodes from {existing_dag['version']}.", file=sys.stderr)
            print(f"  Run `update_docs.py --bump-version {args.version}` first to archive.", file=sys.stderr)
            sys.exit(1)

    # Populate dag.json with new phases
    updated_dag, new_phases = populate_dag(existing_dag, plan, args.version)

    with open(dag_path, "w", encoding="utf-8") as f:
        json.dump(updated_dag, f, indent=2, ensure_ascii=False)
        f.write("\n")

    new_node_count = sum(len(p["nodes"]) for p in new_phases)
    new_block_count = sum(len(p["blocks"]) for p in new_phases)

    # Populate ARCHITECTURE.md
    if arch_path.exists():
        populate_architecture(arch_path, new_phases, plan, args.version)
        arch_lines = len(arch_path.read_text(encoding="utf-8").splitlines())
    else:
        arch_content = render_architecture_fresh(updated_dag, plan)
        with open(arch_path, "w", encoding="utf-8") as f:
            f.write(arch_content)
        arch_lines = len(arch_content.splitlines())

    # Populate BENCHMARKS.md with new rubric
    if bench_path.exists():
        populate_benchmarks(bench_path, plan, args.version)
    else:
        bench_content = render_benchmarks_fresh(updated_dag, plan)
        with open(bench_path, "w", encoding="utf-8") as f:
            f.write(bench_content)

    print(f"INIT_DOCS [POPULATED]: {args.name} {args.version}")
    print(f"  dag.json:        {new_node_count} nodes, {len(new_phases)} phases, {new_block_count} blocks")
    print(f"  ARCHITECTURE.md: {arch_lines} lines ({len(new_phases)} phase sections)")
    print(f"  BENCHMARKS.md:   new rubric written")
    print(f"  Location:        {project_path}")


if __name__ == "__main__":
    main()
