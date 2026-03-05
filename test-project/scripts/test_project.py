#!/usr/bin/env python3
"""test_project.py — Helper for /test-project skill.

Modes:
  --check      Validate prerequisites (dag.json, outsource, tests, API key)
  --aggregate  Read Tests/results.json + dag.json, generate report markdown
  --detect-version  Extract version from ARCHITECTURE.md

Supports both planning-format dag.json (with "phases") and declaration-format
dag.json (with "declarations" + "graph_edges"). Declaration dags are converted
to virtual phases automatically.

Usage:
  python3 test_project.py --check --project /path/to/project
  python3 test_project.py --aggregate --project /path/to/project
  python3 test_project.py --detect-version --project /path/to/project
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ─── Version Detection ───────────────────────────────────────────────────────

def detect_version(project: Path) -> str:
    """Extract version from ARCHITECTURE.md or git tags."""
    arch = project / "ARCHITECTURE.md"
    if arch.exists():
        try:
            content = arch.read_text(encoding="utf-8")
            m = re.search(
                r"(?:Current Version|version)[:\s]+(v\d+\.\d+(?:\.\d+)?)",
                content, re.IGNORECASE,
            )
            if m:
                return m.group(1)
        except (OSError, UnicodeDecodeError):
            pass

    # Fallback: git describe
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, timeout=5,
            cwd=str(project),
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return "unknown"


# ─── Test File Detection ─────────────────────────────────────────────────────

def _node_file_stems(node_id: str) -> list[str]:
    """Generate possible file stems for a node ID like N1.1."""
    clean = node_id.replace(".", "").replace(" ", "")
    dotted = node_id.replace(" ", "")
    underscored = node_id.replace(".", "_").replace(" ", "")
    dashed = node_id.replace(".", "-").replace(" ", "")
    return [clean, dotted, underscored, dashed,
            clean.lower(), dotted.lower(), underscored.lower(), dashed.lower()]


def detect_existing_tests(project: Path, nodes: list[dict]) -> dict:
    """For each node, check if property and integration test files exist.

    Returns: {node_id: {"properties": bool, "integration": bool}}
    """
    props_dir = project / "Tests" / "Properties"
    integ_dir = project / "Tests" / "Integration"

    props_files = set()
    integ_files = set()
    if props_dir.exists():
        props_files = {f.stem.lower() for f in props_dir.glob("*.lean")}
    if integ_dir.exists():
        integ_files = {f.stem.lower() for f in integ_dir.glob("*.lean")}

    result = {}
    for node in nodes:
        nid = node["id"]
        stems = _node_file_stems(nid)
        has_props = any(s in props_files for s in stems)
        has_integ = any(s in integ_files for s in stems)
        result[nid] = {"properties": has_props, "integration": has_integ}
    return result


# ─── Virtual Phases from Declaration DAG ─────────────────────────────────────

def _build_virtual_phases(dag: dict) -> list[dict]:
    """Convert a declaration-format dag.json into virtual phases.

    Groups declarations by file, topological-sorts files by inter-file
    dependencies, and creates virtual nodes.

    Returns a list of phase dicts compatible with the planning format.
    """
    declarations = dag.get("declarations", [])
    graph_edges = dag.get("graph_edges", {})
    if not declarations:
        return []

    # Index declarations by name for lookup
    decl_by_name: dict[str, dict] = {}
    for d in declarations:
        decl_by_name[d["name"]] = d

    # Group declarations by file (use relative filename as group key)
    file_groups: dict[str, list[dict]] = {}
    for d in declarations:
        fpath = d.get("file", "")
        # Use basename without extension as key
        fname = Path(fpath).stem if fpath else "unknown"
        file_groups.setdefault(fname, []).append(d)

    # Build inter-file dependency graph
    file_deps: dict[str, set[str]] = {f: set() for f in file_groups}
    for d in declarations:
        src_file = Path(d.get("file", "")).stem if d.get("file") else "unknown"
        for dep_name in graph_edges.get(d["name"], []):
            dep_decl = decl_by_name.get(dep_name)
            if dep_decl:
                dst_file = Path(dep_decl.get("file", "")).stem if dep_decl.get("file") else "unknown"
                if dst_file != src_file:
                    file_deps[src_file].add(dst_file)

    # Topological sort of files (Kahn's algorithm)
    in_degree = {f: 0 for f in file_groups}
    for f, deps in file_deps.items():
        for dep in deps:
            if dep in in_degree:
                in_degree[f] += 1  # f depends on dep

    # Actually, in_degree should count how many files point TO each file
    in_degree = {f: 0 for f in file_groups}
    reverse_deps: dict[str, set[str]] = {f: set() for f in file_groups}
    for f, deps in file_deps.items():
        for dep in deps:
            if dep in reverse_deps:
                reverse_deps[dep].add(f)
                in_degree[f] += 1  # f has dependency on dep

    queue = sorted([f for f, deg in in_degree.items() if deg == 0])
    sorted_files = []
    while queue:
        f = queue.pop(0)
        sorted_files.append(f)
        for dependent in sorted(reverse_deps.get(f, [])):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
    # Add any remaining files (cycles)
    for f in file_groups:
        if f not in sorted_files:
            sorted_files.append(f)

    # Classify node type based on declaration classifications
    def _classify_node(decls: list[dict]) -> str:
        kinds = {d.get("classification", "") for d in decls}
        if any("FUNDACIONAL" in k for k in kinds):
            return "FUNDACIONAL"
        if any("CRITICO" in k or "CRÍTICO" in k for k in kinds):
            return "CRITICO"
        has_sorry = any(d.get("has_sorry", False) for d in decls)
        if has_sorry:
            return "PARALELO"
        return "HOJA"

    # Build virtual nodes
    nodes = []
    for idx, fname in enumerate(sorted_files, 1):
        decls = file_groups[fname]
        # Get the original file path from first declaration
        orig_file = decls[0].get("file", f"{fname}.lean") if decls else f"{fname}.lean"
        # Make path relative to project
        rel_path = orig_file
        proj_path = dag.get("project_path", "")
        if proj_path and rel_path.startswith(proj_path):
            rel_path = rel_path[len(proj_path):].lstrip("/")

        n_theorems = sum(1 for d in decls if d.get("kind") in ("theorem", "lemma"))
        n_defs = sum(1 for d in decls if d.get("kind") == "def")
        n_sorry = sum(1 for d in decls if d.get("has_sorry", False))

        nodes.append({
            "id": f"N{idx}",
            "name": fname,
            "type": _classify_node(decls),
            "status": "completed" if n_sorry == 0 else "in_progress",
            "files": [rel_path],
            "deps": [f"N{sorted_files.index(dep) + 1}"
                     for dep in file_deps.get(fname, set())
                     if dep in sorted_files],
            "metrics": {
                "theorems": n_theorems,
                "defs": n_defs,
                "sorry": n_sorry,
                "declarations": len(decls),
            },
        })

    return [{
        "id": "virtual",
        "name": f"Virtual Phase ({len(nodes)} file groups)",
        "nodes": nodes,
    }]


# ─── TESTS_OUTSOURCE.md Validation ──────────────────────────────────────────

def validate_outsource(project: Path, dag_node_ids: list[str]) -> dict:
    """Strict validation of TESTS_OUTSOURCE.md format.

    Returns: {
        "valid": bool,
        "format_version": "new"|"old"|"unknown",
        "errors": [...],
        "warnings": [...],
        "sections_found": {...},
        "node_coverage": {"matched": [...], "missing": [...], "extra": [...]},
    }
    """
    result = {
        "valid": True,
        "format_version": "unknown",
        "errors": [],
        "warnings": [],
        "sections_found": {
            "metadata": False,
            "disclaimer": False,
            "instructions": False,
            "conventions": False,
            "execution": False,
            "rubric": False,
            "per_node_specs": False,
            "summary": False,
            "formal_bridge": False,
        },
        "node_coverage": {"matched": [], "missing": [], "extra": []},
        "node_count": 0,
        "properties_count": 0,
        "integration_count": 0,
    }

    outsource = project / "TESTS_OUTSOURCE.md"
    if not outsource.exists():
        result["valid"] = False
        result["errors"].append("TESTS_OUTSOURCE.md not found")
        return result

    try:
        content = outsource.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        result["valid"] = False
        result["errors"].append(f"Cannot read TESTS_OUTSOURCE.md: {e}")
        return result

    lines = content.split("\n")
    if len(lines) < 10:
        result["valid"] = False
        result["errors"].append(f"File too short ({len(lines)} lines)")
        return result

    # ── 1. Metadata block ──
    if lines[0].startswith("# Test Specifications:"):
        result["sections_found"]["metadata"] = True
        result["format_version"] = "new"
        # Check metadata fields
        has_generated = any(l.startswith("Generated:") for l in lines[:10])
        has_project = any(l.startswith("Project:") for l in lines[:10])
        has_toolchain = any(l.startswith("Toolchain:") for l in lines[:10])
        has_mathlib = any(l.startswith("Mathlib:") for l in lines[:10])
        if not all([has_generated, has_project, has_toolchain, has_mathlib]):
            missing = []
            if not has_generated: missing.append("Generated")
            if not has_project: missing.append("Project")
            if not has_toolchain: missing.append("Toolchain")
            if not has_mathlib: missing.append("Mathlib")
            result["warnings"].append(f"Metadata missing fields: {', '.join(missing)}")
    else:
        result["format_version"] = "old"
        result["warnings"].append("No standard metadata header — may be old format")

    # ── 2. Disclaimer ──
    disclaimer_found = any(
        l.strip().startswith(">") and ("leído" in l.lower() or "no contiene" in l.lower())
        for l in lines[:20]
    )
    result["sections_found"]["disclaimer"] = disclaimer_found
    if not disclaimer_found:
        result["warnings"].append("No disclaimer blockquote found")

    # ── 3. Instructions ──
    result["sections_found"]["instructions"] = bool(
        re.search(r"^## Instrucciones", content, re.MULTILINE)
    )
    result["sections_found"]["conventions"] = bool(
        re.search(r"^### Convenciones obligatorias", content, re.MULTILINE)
    )
    result["sections_found"]["execution"] = bool(
        re.search(r"^### Ejecuci[oó]n", content, re.MULTILINE)
    )
    if not result["sections_found"]["instructions"]:
        result["errors"].append("Missing '## Instrucciones' section")
        result["valid"] = False

    # ── 4. Rubric ──
    result["sections_found"]["rubric"] = bool(
        re.search(r"^## Criterios de rúbrica", content, re.MULTILINE)
    )
    benchmarks = project / "BENCHMARKS.md"
    if benchmarks.exists() and not result["sections_found"]["rubric"]:
        result["warnings"].append(
            "BENCHMARKS.md exists but no rubric section in outsource — weak coupling"
        )

    # ── 5. Per-node specs ──
    result["sections_found"]["per_node_specs"] = bool(
        re.search(r"^## Especificaciones por nodo", content, re.MULTILINE)
    )

    # Extract node IDs from outsource headers
    # Supports both formats:
    #   New: ### N26 — UnionFind
    #   Old: ### F1S2 — UnionFind   (legacy phase-based IDs)
    outsource_nodes = []
    node_header_re = re.compile(
        r"^### ([A-Z0-9][A-Za-z0-9.+*]*)\s*[—–-]\s*(.+)", re.MULTILINE
    )
    for m in node_header_re.finditer(content):
        outsource_nodes.append(m.group(1))
    result["node_count"] = len(outsource_nodes)

    if not outsource_nodes:
        result["errors"].append(
            "No node specification headers found (### ID — Name)"
        )
        result["valid"] = False
    else:
        # Check node coverage vs dag
        dag_ids = set(dag_node_ids)
        outsource_ids = set(outsource_nodes)
        result["node_coverage"]["matched"] = sorted(dag_ids & outsource_ids)
        result["node_coverage"]["missing"] = sorted(dag_ids - outsource_ids)
        result["node_coverage"]["extra"] = sorted(outsource_ids - dag_ids)

        if result["node_coverage"]["missing"]:
            result["warnings"].append(
                f"Nodes in dag but not in outsource: {result['node_coverage']['missing']}"
            )
        if result["node_coverage"]["extra"]:
            result["warnings"].append(
                f"Nodes in outsource but not in dag: {result['node_coverage']['extra']}"
            )

    # ── 6. Per-node spec quality ──
    # Check that each node has PROPERTIES and INTEGRATION sections
    properties_re = re.compile(r"\[P\d+\]\s+P[012]\s+\w+:", re.MULTILINE)
    integration_re = re.compile(r"\[T\d+\]\s+\w+:", re.MULTILINE)
    result["properties_count"] = len(properties_re.findall(content))
    result["integration_count"] = len(integration_re.findall(content))

    if result["properties_count"] == 0:
        result["errors"].append("No property specs found ([P{N}] P0|P1|P2 TYPE:)")
        result["valid"] = False
    if result["integration_count"] == 0:
        result["errors"].append("No integration test specs found ([T{N}] TYPE:)")
        result["valid"] = False

    # Check for Sketch/SampleableExt/Risk keys in properties
    has_sketch = "Sketch:" in content or "sketch:" in content
    has_sampleable = "SampleableExt:" in content or "Sampleable:" in content
    has_risk = "Risk:" in content or "risk:" in content
    if not has_sketch:
        result["warnings"].append("No 'Sketch:' keys found in property specs")
    if not has_sampleable:
        result["warnings"].append("No 'SampleableExt:' keys found in property specs")

    # Check for Setup/Check keys in integration tests
    has_setup = "Setup:" in content or "setup:" in content
    has_check = "Check:" in content or "check:" in content
    if not has_setup:
        result["warnings"].append("No 'Setup:' keys found in integration test specs")
    if not has_check:
        result["warnings"].append("No 'Check:' keys found in integration test specs")

    # ── 7. Summary table ──
    result["sections_found"]["summary"] = bool(
        re.search(r"^## Resumen", content, re.MULTILINE)
    )
    if not result["sections_found"]["summary"]:
        result["warnings"].append("No '## Resumen' table found")

    # ── 8. Formal Bridge ──
    result["sections_found"]["formal_bridge"] = bool(
        re.search(r"^## Formal Bridge Requirements", content, re.MULTILINE)
    )
    # Check if *Spec.lean files exist — if so, bridge should be present
    spec_files = list(project.rglob("*Spec.lean"))
    if spec_files and not result["sections_found"]["formal_bridge"]:
        result["warnings"].append(
            f"Found {len(spec_files)} *Spec.lean files but no Formal Bridge section — "
            "hypothesis coupling is missing"
        )

    return result


# ─── Prerequisites Check ─────────────────────────────────────────────────────

def _load_api_key() -> str | None:
    """Check for GOOGLE_API_KEY in env or ~/.env."""
    key = os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    env_file = Path.home() / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text().splitlines():
                if line.startswith("GOOGLE_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("'\"")
        except OSError:
            pass
    return None


def check_prerequisites(project: Path) -> dict:
    """Validate all prerequisites for testing. Returns structured dict."""
    result = {
        "project": str(project),
        "project_name": project.name,
        "version": detect_version(project),
        "dag_ok": False,
        "dag_format": "none",  # "planning", "declaration", "none"
        "dag_nodes": [],
        "outsource_exists": False,
        "outsource_validation": None,
        "api_key_available": False,
        "existing_test_files": {},
        "bridge_exists": False,
        "results_json_exists": False,
        "mathlib_available": False,
        "test_overlay_exists": False,
        "errors": [],
        "warnings": [],
        "exit_code": 0,
    }

    # Check dag.json
    dag_path = project / "dag.json"
    if not dag_path.exists():
        result["errors"].append("dag.json not found")
        result["exit_code"] = 3
    else:
        try:
            dag = json.loads(dag_path.read_text(encoding="utf-8"))
            if "phases" in dag:
                # Planning format — use directly
                result["dag_format"] = "planning"
                result["dag_ok"] = True
                nodes = []
                for phase in dag.get("phases", []):
                    for node in phase.get("nodes", []):
                        nodes.append({
                            "id": node["id"],
                            "name": node.get("name", ""),
                            "type": node.get("type", ""),
                            "files": node.get("files", []),
                            "phase": phase.get("id", ""),
                            "phase_name": phase.get("name", ""),
                        })
                result["dag_nodes"] = nodes
            elif "declarations" in dag:
                # Declaration format — generate virtual phases
                result["dag_format"] = "declaration"
                virtual_phases = _build_virtual_phases(dag)
                if virtual_phases:
                    result["dag_ok"] = True
                    result["warnings"].append(
                        "dag.json is declaration format — using virtual phases "
                        "(grouped by file). Consider running /tidy-project for "
                        "proper planning phases."
                    )
                    nodes = []
                    for phase in virtual_phases:
                        for node in phase.get("nodes", []):
                            nodes.append({
                                "id": node["id"],
                                "name": node.get("name", ""),
                                "type": node.get("type", ""),
                                "files": node.get("files", []),
                                "phase": phase.get("id", ""),
                                "phase_name": phase.get("name", ""),
                            })
                    result["dag_nodes"] = nodes
                    # Store virtual phases for aggregate to use
                    result["_virtual_phases"] = virtual_phases
                else:
                    result["errors"].append(
                        "dag.json has declarations but could not generate virtual phases"
                    )
                    result["exit_code"] = 3
            else:
                result["errors"].append(
                    "dag.json has neither 'phases' nor 'declarations' key"
                )
                result["exit_code"] = 3
        except (json.JSONDecodeError, OSError) as e:
            result["errors"].append(f"dag.json parse error: {e}")
            result["exit_code"] = 3

    # Check TESTS_OUTSOURCE.md
    outsource = project / "TESTS_OUTSOURCE.md"
    result["outsource_exists"] = outsource.exists()

    # Strict validation of outsource if it exists
    if result["outsource_exists"] and result["dag_nodes"]:
        dag_node_ids = [n["id"] for n in result["dag_nodes"]]
        validation = validate_outsource(project, dag_node_ids)
        result["outsource_validation"] = validation
        if not validation["valid"]:
            result["warnings"].append(
                f"TESTS_OUTSOURCE.md has validation errors: {validation['errors']}"
            )
        if validation["warnings"]:
            result["warnings"].extend(
                f"[outsource] {w}" for w in validation["warnings"]
            )

    # Check API key
    result["api_key_available"] = _load_api_key() is not None

    # Check existing test files
    if result["dag_nodes"]:
        result["existing_test_files"] = detect_existing_tests(
            project, result["dag_nodes"]
        )

    # Check Bridge.lean
    result["bridge_exists"] = (project / "Tests" / "Bridge.lean").exists()

    # Check results.json
    result["results_json_exists"] = (project / "Tests" / "results.json").exists()

    # Detect Mathlib availability
    for name in ("lakefile.toml", "lakefile.lean"):
        lf = project / name
        if lf.exists():
            content = lf.read_text(encoding="utf-8")
            if "mathlib" in content.lower():
                result["mathlib_available"] = True
                break
    # Check for test overlay
    overlay_lf = project / "Tests" / "lakefile.toml"
    if overlay_lf.exists():
        result["test_overlay_exists"] = True
        if not result["mathlib_available"]:
            result["mathlib_available"] = True  # available via overlay
            result["warnings"].append(
                "Mathlib available via Tests/ overlay (not in main project)"
            )

    # Determine exit code (if not already fatal)
    if result["exit_code"] == 3:
        pass  # already fatal
    elif result["outsource_exists"]:
        # Check if outsource is valid enough to use
        if (result["outsource_validation"]
                and not result["outsource_validation"]["valid"]):
            # Outsource exists but is invalid — exit 4 (new code: needs regeneration)
            result["exit_code"] = 4
            result["errors"].append(
                "TESTS_OUTSOURCE.md exists but has format errors — "
                "use --force-generate to regenerate"
            )
        else:
            all_have_tests = all(
                v["properties"] or v["integration"]
                for v in result["existing_test_files"].values()
            ) if result["existing_test_files"] else False
            result["exit_code"] = 0 if all_have_tests else 1
    elif result["api_key_available"]:
        result["exit_code"] = 2
    else:
        result["errors"].append(
            "TESTS_OUTSOURCE.md not found and GOOGLE_API_KEY not available"
        )
        result["exit_code"] = 3

    return result


# ─── Node JSON Builder ───────────────────────────────────────────────────────

def build_nodes_json(
    nodes: list[dict], node_filter: list[str] | None = None,
) -> dict:
    """Build {"N1.1": ["File.lean", ...]} for launch_test_agent.py."""
    result = {}
    for node in nodes:
        nid = node["id"]
        if node_filter and nid not in node_filter:
            continue
        result[nid] = node.get("files", [])
    return result


# ─── Report Aggregation ──────────────────────────────────────────────────────

def aggregate_results(project: Path) -> str:
    """Read Tests/results.json + dag.json, generate report markdown.

    Returns the report as a string and writes it to report_{name}_{version}.md.
    """
    version = detect_version(project)
    project_name = project.name

    # Load results
    results_path = project / "Tests" / "results.json"
    if not results_path.exists():
        return f"ERROR: Tests/results.json not found in {project}"
    results = json.loads(results_path.read_text(encoding="utf-8"))

    # Load dag for phase grouping
    dag_path = project / "dag.json"
    phases = []
    if dag_path.exists():
        try:
            dag = json.loads(dag_path.read_text(encoding="utf-8"))
            phases = dag.get("phases", [])
            if not phases and "declarations" in dag:
                # Declaration format — generate virtual phases
                phases = _build_virtual_phases(dag)
        except (json.JSONDecodeError, OSError):
            pass

    # Extract meta
    meta = results.pop("_meta", {})
    bridge_status = meta.get("bridge_status", "MISSING")

    # Build name↔id mapping from DAG phases for deduplication.
    # results.json may have entries keyed by name ("UnionFind") or by
    # DAG id ("N26") — we normalize everything to the DAG id.
    name_to_id: dict[str, str] = {}
    id_to_name: dict[str, str] = {}
    for phase in phases:
        for node in phase.get("nodes", []):
            nid = node["id"]
            nname = node.get("name", "")
            if nname:
                name_to_id[nname] = nid
                id_to_name[nid] = nname

    # Aggregate totals
    total_nodes = 0
    total_props = 0
    total_props_pass = 0
    total_props_fail = 0
    total_props_nr = 0
    total_integ = 0
    total_integ_pass = 0
    total_integ_fail = 0
    blocking = []

    node_rows = []

    # Deduplicate: normalize keys to DAG node IDs, prefer entries with
    # actual test data over bare node IDs.
    # Handles: "N2.1", "N2.1 ArithExpr", "UnionFind" → all map to "N26".
    deduped: dict[str, tuple[str, dict]] = {}
    for node_id, node_result in sorted(results.items()):
        if not isinstance(node_result, dict) or "node" not in node_result:
            continue
        # Extract short ID (e.g., "N2.1" from "N2.1 ArithExpr Frontend")
        short_id = node_id.split()[0] if " " in node_id else node_id
        # Normalize: if short_id is a name, map to DAG id
        if short_id in name_to_id:
            short_id = name_to_id[short_id]
        has_data = (
            node_result.get("properties") is not None
            or node_result.get("integration") is not None
        )
        # Prefer entries with integration/properties data over bare ones
        existing = deduped.get(short_id)
        if existing is None:
            deduped[short_id] = (node_id, node_result)
        elif has_data:
            # Merge: keep bridge from existing if new doesn't have it
            old_id, old_result = existing
            merged = dict(node_result)
            if merged.get("bridge") is None and old_result.get("bridge"):
                merged["bridge"] = old_result["bridge"]
            if merged.get("properties") is None and old_result.get("properties"):
                merged["properties"] = old_result["properties"]
            if merged.get("integration") is None and old_result.get("integration"):
                merged["integration"] = old_result["integration"]
            deduped[short_id] = (node_id, merged)

    for short_id, (node_id, node_result) in sorted(deduped.items()):
        total_nodes += 1

        props = node_result.get("properties")
        integ = node_result.get("integration")

        p_total = props["total"] if props else 0
        p_pass = props["passing"] if props else 0
        p_fail = props["failing"] if props else 0
        p_nr = props.get("not_runnable", 0) if props else 0

        i_total = integ["total"] if integ else 0
        i_pass = integ["passing"] if integ else 0
        i_fail = integ["failing"] if integ else 0

        total_props += p_total
        total_props_pass += p_pass
        total_props_fail += p_fail
        total_props_nr += p_nr
        total_integ += i_total
        total_integ_pass += i_pass
        total_integ_fail += i_fail

        p0_pass = node_result.get("p0_pass", True)
        all_pass = node_result.get("all_pass", False)

        node_rows.append({
            "id": node_id,
            "short_id": short_id,
            "props": f"{p_pass}/{p_total}" if props else "N/A",
            "integ": f"{i_pass}/{i_total}" if integ else "N/A",
            "p0": "PASS" if p0_pass else "FAIL",
            "status": "PASS" if all_pass else "FAIL",
        })

        for bf in node_result.get("blocking_failures", []):
            blocking.append(f"{node_id}: {bf}")

    # Bridge info from first node
    bridge_info = None
    for node_result in results.values():
        if isinstance(node_result, dict) and "bridge" in node_result:
            bridge_info = node_result["bridge"]
            break

    overall = "ALL PASS" if not blocking else f"{len(blocking)} FAILURES"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build report
    lines = []
    lines.append(f"# {project_name}: Test Report")
    lines.append("")
    lines.append(f"**Version**: {version}")
    lines.append(f"**Date**: {now}")
    lines.append(f"**Method**: Adversarial subagent testing via TESTS_OUTSOURCE.md specs")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Nodes tested | {total_nodes} |")
    lines.append(f"| Properties total | {total_props} |")
    lines.append(f"| Properties PASS | {total_props_pass} |")
    lines.append(f"| Properties FAIL | {total_props_fail} |")
    lines.append(f"| Properties NOT_RUNNABLE | {total_props_nr} |")
    lines.append(f"| Integration total | {total_integ} |")
    lines.append(f"| Integration PASS | {total_integ_pass} |")
    lines.append(f"| Integration FAIL | {total_integ_fail} |")
    lines.append(f"| **Overall** | **{overall}** |")
    lines.append("")

    # Bridge results
    lines.append("## Formal Bridge")
    lines.append("")
    if bridge_info:
        lines.append(f"- **Status**: {bridge_info.get('status', 'MISSING')}")
        lines.append(f"- **#check statements**: {bridge_info.get('checks', 0)}")
        lines.append(f"- **Hypothesis witnesses**: {bridge_info.get('witnesses', 0)}")
        for name in bridge_info.get("check_names", []):
            lines.append(f"  - `#check {name}`")
        for name in bridge_info.get("witness_names", []):
            lines.append(f"  - `theorem {name}`")
        if bridge_info.get("errors"):
            lines.append(f"- **Errors**: {bridge_info['errors'][:200]}")
    else:
        lines.append("Tests/Bridge.lean: NOT FOUND")
    lines.append("")

    # Results by phase
    if phases:
        lines.append("## Results by Phase")
        lines.append("")
        for phase in phases:
            phase_id = phase.get("id", "?")
            phase_name = phase.get("name", "?")
            phase_nodes = [n["id"] for n in phase.get("nodes", [])]

            lines.append(f"### {phase_id}: {phase_name}")
            lines.append("")
            lines.append("| Node | Properties | Integration | P0 | Status |")
            lines.append("|------|-----------|-------------|-----|--------|")
            for row in node_rows:
                if row["short_id"] in phase_nodes:
                    lines.append(
                        f"| {row['short_id']} | {row['props']} | {row['integ']} "
                        f"| {row['p0']} | {row['status']} |"
                    )
            lines.append("")
    else:
        # No phases — flat table
        lines.append("## Results by Node")
        lines.append("")
        lines.append("| Node | Properties | Integration | P0 | Status |")
        lines.append("|------|-----------|-------------|-----|--------|")
        for row in node_rows:
            lines.append(
                f"| {row['short_id']} | {row['props']} | {row['integ']} "
                f"| {row['p0']} | {row['status']} |"
            )
        lines.append("")

    # Blocking failures
    if blocking:
        lines.append("## Blocking Failures")
        lines.append("")
        for bf in blocking:
            lines.append(f"- {bf}")
        lines.append("")

    # Coverage summary
    lines.append("## Coverage Summary")
    lines.append("")
    if bridge_info:
        b = f"{bridge_info.get('status', '?')} ({bridge_info.get('checks', 0)} #check, {bridge_info.get('witnesses', 0)} witnesses)"
    else:
        b = "MISSING (no Tests/Bridge.lean)"
    lines.append(f"- **Layer 1 (Formal Bridge)**: {b}")
    if total_props > 0:
        lines.append(f"- **Layer 2 (Properties)**: {total_props_pass}/{total_props} pass")
    else:
        lines.append("- **Layer 2 (Properties)**: N/A (no property tests)")
    if total_integ > 0:
        lines.append(f"- **Layer 3 (Integration)**: {total_integ_pass}/{total_integ} pass")
    else:
        lines.append("- **Layer 3 (Integration)**: N/A (no integration tests)")
    lines.append("")

    # Methodology
    lines.append("## Methodology")
    lines.append("")
    lines.append("```")
    lines.append("dag.json + ARCHITECTURE.md")
    lines.append("    |")
    lines.append("    v")
    lines.append("generate_tests.py (Gemini 2.5 Pro)")
    lines.append("    |")
    lines.append("    v")
    lines.append("TESTS_OUTSOURCE.md")
    lines.append("    |")
    lines.append("    v")
    lines.append("launch_test_agent.py -> Task subagent")
    lines.append("    |")
    lines.append("    v")
    lines.append("Tests/Bridge.lean + Tests/Properties/*.lean + Tests/Integration/*.lean")
    lines.append("    |")
    lines.append("    v")
    lines.append("run_tests.py -> Tests/results.json")
    lines.append("    |")
    lines.append("    v")
    lines.append("test_project.py --aggregate -> this report")
    lines.append("```")
    lines.append("")

    # Raw results
    lines.append("## Raw Results")
    lines.append("")
    lines.append(f"- Machine-readable: `Tests/results.json`")
    lines.append(f"- Test specifications: `TESTS_OUTSOURCE.md`")
    lines.append("")

    report = "\n".join(lines)

    # Write report file
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", project_name)
    safe_version = version.replace(".", "_")
    report_filename = f"report_{safe_name}_{safe_version}.md"
    report_path = project / report_filename
    report_path.write_text(report, encoding="utf-8")

    return json.dumps({
        "report_file": str(report_path),
        "report_filename": report_filename,
        "overall": overall,
        "total_nodes": total_nodes,
        "total_props": total_props,
        "total_props_pass": total_props_pass,
        "total_integ": total_integ,
        "total_integ_pass": total_integ_pass,
        "bridge_status": bridge_status,
        "blocking_count": len(blocking),
    })


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Helper for /test-project skill",
    )
    parser.add_argument("--project", required=True, help="Path to project")
    parser.add_argument("--check", action="store_true",
                        help="Validate prerequisites")
    parser.add_argument("--aggregate", action="store_true",
                        help="Aggregate results into report")
    parser.add_argument("--detect-version", action="store_true",
                        help="Print detected version")
    args = parser.parse_args()

    project = Path(args.project).resolve()

    if not project.is_dir():
        print(
            json.dumps({"error": f"{project} is not a directory", "exit_code": 3}),
        )
        sys.exit(3)

    if args.detect_version:
        print(detect_version(project))
        sys.exit(0)

    if args.check:
        result = check_prerequisites(project)
        print(json.dumps(result, indent=2))
        sys.exit(result["exit_code"])

    if args.aggregate:
        output = aggregate_results(project)
        print(output)
        sys.exit(0)

    print("ERROR: Specify --check, --aggregate, or --detect-version",
          file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
