#!/usr/bin/env python3
"""run_tests.py — Ejecuta tests Lean y parsea resultados. 0 tokens LLM (excepto dispute).

Ejecuta archivos de test en Tests/Properties/ y Tests/Integration/,
parsea resultados de slim_check y #eval, retorna JSON estructurado.

Uso:
  python3 run_tests.py --project /path --node N2.1 --json
  python3 run_tests.py --project /path --node N2.1 --type properties
  python3 run_tests.py --project /path --node N2.1 --type integration

  # Disputa (usa Gemini API):
  python3 run_tests.py --project /path --node N2.1 \
    --dispute "T5_overflow_bounds" \
    --reason "Fin n guarantees bounds by construction" \
    --evidence "LambdaSat/UnionFind.lean:45-60"
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# ─── Constants ───────────────────────────────────────────────────────────────

TESTS_DIR = "Tests"
PROPERTIES_DIR = "Properties"
INTEGRATION_DIR = "Integration"

NOT_RUNNABLE_MARKER = "-- NOT_YET_RUNNABLE"

# Priority regex: extract from comments like "-- P0, INVARIANT: description"
PRIORITY_PATTERN = re.compile(
    r"--\s*(P[012])\s*(?:[,(]\s*(\w+)\s*[):]?)?\s*:?\s*(.*)"
)

# Test name pattern for integration: def T1_name or "T1_name"
TEST_NAME_PATTERN = re.compile(r'\("?(\w+)"?\s*,')


# ─── Mathlib Detection ──────────────────────────────────────────────────────

def detect_mathlib(project: Path) -> bool:
    """Check if the project already has Mathlib as a dependency."""
    for name in ("lakefile.toml", "lakefile.lean"):
        lf = project / name
        if lf.exists():
            content = lf.read_text(encoding="utf-8")
            if "mathlib" in content.lower():
                return True
    return False


def setup_test_overlay(project: Path) -> bool:
    """Create a Tests/ sub-project with its own lakefile that imports Mathlib.

    Returns True if overlay was created/exists, False if unnecessary or failed.
    The overlay allows Tests/Properties/*.lean to import Mathlib.Testing.SlimCheck
    without adding Mathlib to the main project.
    """
    if detect_mathlib(project):
        return False  # already has Mathlib, no overlay needed

    tests_dir = project / TESTS_DIR
    tests_dir.mkdir(exist_ok=True)
    overlay_lakefile = tests_dir / "lakefile.toml"

    if overlay_lakefile.exists():
        return True  # already set up

    # Read project name and lean-toolchain
    project_name = project.name
    for name in ("lakefile.toml", "lakefile.lean"):
        lf = project / name
        if lf.exists():
            content = lf.read_text(encoding="utf-8")
            import re as _re
            m = _re.search(r'name\s*=\s*"([^"]+)"', content)
            if m:
                project_name = m.group(1)
            break

    toolchain = "leanprover/lean4:v4.16.0"
    tc_file = project / "lean-toolchain"
    if tc_file.exists():
        toolchain = tc_file.read_text(encoding="utf-8").strip()

    # Write overlay lakefile
    overlay_content = f"""# Auto-generated test overlay — imports Mathlib for SlimCheck property tests.
# This does NOT modify the main project's dependencies.
[package]
name = "{project_name}-tests"

[[require]]
name = "{project_name}"
path = ".."

[[require]]
name = "mathlib"
scope = "leanprover-community"

[[lean_lib]]
name = "Properties"
globs = ["Properties"]
"""
    overlay_lakefile.write_text(overlay_content, encoding="utf-8")

    # Write matching lean-toolchain
    (tests_dir / "lean-toolchain").write_text(toolchain + "\n", encoding="utf-8")

    return True


def resolve_node_name(project: Path, node_id: str) -> str:
    """Resolve a bare node ID (e.g., 'N1') to its DAG name (e.g., 'NatOpt').

    For virtual-phase DAGs (declaration format), the node name is the file stem.
    For planning-format DAGs, node names come from the phase definitions.
    Returns the original node_id if resolution fails.
    """
    dag_path = project / "dag.json"
    if not dag_path.exists():
        return node_id
    try:
        dag = json.loads(dag_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return node_id

    # Check planning-format phases first
    phases = dag.get("phases", [])
    if phases:
        for phase in phases:
            for node in phase.get("nodes", []):
                if node.get("id") == node_id and node.get("name"):
                    return node["name"]
        return node_id

    # Declaration format — build virtual phase mapping
    if "declarations" not in dag:
        return node_id

    file_groups: dict[str, list] = {}
    decl_by_name: dict[str, dict] = {}
    for d in dag["declarations"]:
        decl_by_name[d["name"]] = d
        fname = Path(d.get("file", "")).stem if d.get("file") else "unknown"
        file_groups.setdefault(fname, []).append(d)

    graph_edges = dag.get("graph_edges", {})
    file_deps: dict[str, set] = {f: set() for f in file_groups}
    for d in dag["declarations"]:
        src = Path(d.get("file", "")).stem if d.get("file") else "unknown"
        for dep_name in graph_edges.get(d["name"], []):
            dep = decl_by_name.get(dep_name)
            if dep:
                dst = Path(dep.get("file", "")).stem if dep.get("file") else "unknown"
                if dst != src:
                    file_deps[src].add(dst)

    # Topological sort (same as _build_virtual_phases in test_project.py)
    in_degree = {f: 0 for f in file_groups}
    reverse_deps: dict[str, set] = {f: set() for f in file_groups}
    for f, deps in file_deps.items():
        for dep in deps:
            if dep in reverse_deps:
                reverse_deps[dep].add(f)
                in_degree[f] += 1
    queue = sorted([f for f, deg in in_degree.items() if deg == 0])
    sorted_files: list[str] = []
    while queue:
        f = queue.pop(0)
        sorted_files.append(f)
        for dependent in sorted(reverse_deps.get(f, [])):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
    for f in file_groups:
        if f not in sorted_files:
            sorted_files.append(f)

    # Match node ID to file stem
    # node_id format: "N{idx}" where idx is 1-based
    m = re.match(r"^N(\d+)$", node_id)
    if m:
        idx = int(m.group(1))
        if 1 <= idx <= len(sorted_files):
            return sorted_files[idx - 1]

    return node_id


# ─── File Discovery ──────────────────────────────────────────────────────────

PROPERTY_TESTS_DIR = "PropertyTests"

def find_test_files(project: Path, node_name: str) -> dict:
    """Find test files for a node.

    Convention: Tests/Properties/{NodeClean}.lean, Tests/Integration/{NodeClean}.lean
    where NodeClean is the node name without the ID prefix (e.g., N2.1 → UnionFind).

    Also searches PropertyTests/Properties/ for Plausible-based property tests
    (overlay project that imports Mathlib without contaminating the main project).
    """
    tests_dir = project / TESTS_DIR
    result = {"properties": None, "integration": None}

    # Try exact match first, then fuzzy
    node_clean = _clean_node_name(node_name)

    # Search for properties in both Tests/Properties/ and PropertyTests/Properties/
    prop_dirs = []
    if tests_dir.exists():
        prop_dirs.append(tests_dir / PROPERTIES_DIR)
    overlay_props = project / PROPERTY_TESTS_DIR / PROPERTIES_DIR
    if overlay_props.exists():
        prop_dirs.append(overlay_props)

    for props_dir in prop_dirs:
        if props_dir.exists():
            for f in props_dir.glob("*.lean"):
                if _matches_node(f.stem, node_clean, node_name):
                    result["properties"] = f
                    break
            if result["properties"]:
                break

    # Integration: only in Tests/Integration/
    if tests_dir.exists():
        integ_dir = tests_dir / INTEGRATION_DIR
        if integ_dir.exists():
            for f in integ_dir.glob("*.lean"):
                if _matches_node(f.stem, node_clean, node_name):
                    result["integration"] = f
                    break

    return result


def _clean_node_name(node_name: str) -> str:
    """Extract clean name from node ID like 'N2.1' or 'N2.1 Union-Find'."""
    # Remove ID prefix (N2.1, F1.2, etc.)
    cleaned = re.sub(r"^[A-Z]\d+\.\d+\s*", "", node_name).strip()
    # If nothing left, use the original
    if not cleaned:
        cleaned = node_name
    # Convert to PascalCase for file matching
    cleaned = cleaned.replace("-", " ").replace("_", " ")
    parts = cleaned.split()
    return "".join(p.capitalize() for p in parts)


def _matches_node(filename: str, node_clean: str, node_id: str) -> bool:
    """Check if a filename matches a node name."""
    f_lower = filename.lower()
    c_lower = node_clean.lower()
    # Remove ID dots for matching
    id_clean = node_id.replace(".", "").replace(" ", "").lower()
    return (
        f_lower == c_lower
        or f_lower.startswith(c_lower)
        or c_lower.startswith(f_lower)
        or id_clean in f_lower
    )


# ─── Test Execution ─────────────────────────────────────────────────────────

def run_lean_file(project: Path, filepath: Path, timeout: int = 300,
                  run_main: bool = False, cwd: Path | None = None) -> dict:
    """Run a Lean file via lake env lean and capture output.

    If run_main=True, uses --run to execute the main function (for integration tests).
    cwd overrides the working directory (default: project root).
    """
    cmd = ["lake", "env", "lean"]
    if run_main:
        cmd.append("--run")
    cmd.append(str(filepath))
    work_dir = str(cwd) if cwd else str(project)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "time_seconds": 0.0,  # subprocess doesn't track this directly
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Timeout after {timeout}s",
            "time_seconds": float(timeout),
        }
    except FileNotFoundError:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": "lake not found in PATH",
            "time_seconds": 0.0,
        }


def _detect_eval_mode(source: str) -> bool:
    """Detect if a Properties file uses #eval-based tests (no-Mathlib mode)
    instead of slim_check theorems."""
    return "def main" in source and ("[PASS]" in source or "[FAIL]" in source)


def parse_properties_result(
    filepath: Path, run_result: dict
) -> dict:
    """Parse results from a Properties test file.

    Two modes:
    1. SlimCheck mode (Mathlib): example/theorem with slim_check tactic
       - No output = PASS (slim_check passes silently)
       - "Found a counter-example" = FAIL
    2. Eval mode (no Mathlib): #eval with [PASS]/[FAIL] output
       - Same format as Integration tests

    Common: "error:" in stderr = ERROR, NOT_YET_RUNNABLE marker = skip
    """
    source = filepath.read_text(encoding="utf-8") if filepath.exists() else ""
    source_lines = source.splitlines()
    stderr = run_result.get("stderr", "")
    stdout = run_result.get("stdout", "")
    output = stderr + "\n" + stdout

    # Detect eval-based property tests (no-Mathlib mode)
    if _detect_eval_mode(source):
        return _parse_eval_properties(filepath, run_result, source_lines)

    # ── SlimCheck mode ──
    # Extract properties from source
    properties = []
    current_priority = "P1"
    current_type = "UNKNOWN"
    current_name = ""
    not_runnable_next = False

    for i, line in enumerate(source_lines, 1):
        stripped = line.strip()

        # Check for NOT_YET_RUNNABLE
        if NOT_RUNNABLE_MARKER in stripped:
            not_runnable_next = True
            continue

        # Parse priority/type comments
        m = PRIORITY_PATTERN.match(stripped)
        if m:
            current_priority = m.group(1)
            if m.group(2):
                current_type = m.group(2)
            current_name = m.group(3).strip() if m.group(3) else ""
            continue

        # Detect example/theorem declarations (property definitions)
        if re.match(r"^(example|theorem|lemma)\s+", stripped) or stripped.startswith("example "):
            # Extract name
            name_match = re.match(r"^(?:example|theorem|lemma)\s+(\w+)", stripped)
            prop_name = name_match.group(1) if name_match else current_name or f"prop_L{i}"

            if not_runnable_next:
                status = "NOT_RUNNABLE"
                not_runnable_next = False
            else:
                status = "PENDING"  # Will be resolved below

            properties.append({
                "name": prop_name,
                "priority": current_priority,
                "type": current_type,
                "status": status,
                "line": i,
            })

    # If compilation error, mark all non-skipped as ERROR
    has_error = "error:" in output.lower() and run_result.get("exit_code", 0) != 0
    # Plausible/SlimCheck outputs:
    #   PASS: "Unable to find a counter-example"
    #   FAIL: "Found a counter-example!" (without "Unable to find")
    found_counter = "found a counter-example" in output.lower()
    only_unable = "unable to find a counter-example" in output.lower()
    has_real_counter = found_counter and not only_unable

    if has_error:
        for p in properties:
            if p["status"] == "PENDING":
                p["status"] = "ERROR"
    elif has_real_counter:
        # Per-property granularity: map counter-example lines to property lines
        # For now, mark all as FAIL (conservative — most files test one concept)
        for p in properties:
            if p["status"] == "PENDING":
                p["status"] = "FAIL"
    else:
        for p in properties:
            if p["status"] == "PENDING":
                p["status"] = "PASS"

    # Count stats
    total = len(properties)
    passing = sum(1 for p in properties if p["status"] == "PASS")
    failing = sum(1 for p in properties if p["status"] == "FAIL")
    not_runnable = sum(1 for p in properties if p["status"] == "NOT_RUNNABLE")
    errors = sum(1 for p in properties if p["status"] == "ERROR")

    return {
        "file": str(filepath.relative_to(filepath.parent.parent.parent)),
        "total": total,
        "passing": passing,
        "failing": failing,
        "not_runnable": not_runnable,
        "errors": errors,
        "details": properties,
    }


def _parse_eval_properties(
    filepath: Path, run_result: dict, source_lines: list[str]
) -> dict:
    """Parse #eval-based property tests (no-Mathlib mode).

    Same [PASS]/[FAIL] format as integration tests, but we also extract
    priority/type comments from source for richer reporting.
    """
    stdout = run_result.get("stdout", "")
    stderr = run_result.get("stderr", "")
    output = stdout + "\n" + stderr
    exit_code = run_result.get("exit_code", -1)

    # Build priority map from source comments
    priority_map: dict[str, tuple[str, str]] = {}  # name -> (priority, type)
    current_priority = "P1"
    current_type = "UNKNOWN"
    for line in source_lines:
        stripped = line.strip()
        m = PRIORITY_PATTERN.match(stripped)
        if m:
            current_priority = m.group(1)
            if m.group(2):
                current_type = m.group(2)
            continue
        # Match def test_xxx lines to associate priority
        dm = re.match(r"^def\s+(test_\w+)", stripped)
        if dm:
            priority_map[dm.group(1)] = (current_priority, current_type)

    details = []
    for line in output.splitlines():
        stripped = line.strip()
        if "[PASS]" in stripped:
            name_match = re.search(r"\[PASS\]\s+(.*)", stripped)
            name = name_match.group(1).strip() if name_match else "unknown"
            p, t = priority_map.get(name, ("P1", "UNKNOWN"))
            details.append({"name": name, "status": "PASS", "priority": p, "type": t})
        elif "[FAIL]" in stripped:
            name_match = re.search(r"\[FAIL\]\s+(.*)", stripped)
            name = name_match.group(1).strip() if name_match else "unknown"
            p, t = priority_map.get(name, ("P1", "UNKNOWN"))
            details.append({"name": name, "status": "FAIL", "priority": p, "type": t})

    if not details and ("error:" in stderr.lower() or exit_code != 0):
        details.append({"name": filepath.stem, "status": "ERROR", "priority": "P0", "type": "ERROR"})

    total = len(details)
    passing = sum(1 for d in details if d["status"] == "PASS")
    failing = sum(1 for d in details if d["status"] == "FAIL")
    errors = sum(1 for d in details if d["status"] == "ERROR")

    return {
        "file": str(filepath.relative_to(filepath.parent.parent.parent)),
        "total": total,
        "passing": passing,
        "failing": failing,
        "not_runnable": 0,
        "errors": errors,
        "details": details,
    }


def parse_integration_result(
    filepath: Path, run_result: dict
) -> dict:
    """Parse results from an Integration test file.

    Integration tests use #eval with [PASS]/[FAIL] pattern.
    """
    stdout = run_result.get("stdout", "")
    stderr = run_result.get("stderr", "")
    output = stdout + "\n" + stderr
    exit_code = run_result.get("exit_code", -1)

    details = []

    # Parse [PASS] and [FAIL] lines
    for line in output.splitlines():
        stripped = line.strip()
        if "[PASS]" in stripped:
            name_match = re.search(r"\[PASS\]\s+(.*)", stripped)
            name = name_match.group(1).strip() if name_match else "unknown"
            details.append({"name": name, "status": "PASS"})
        elif "[FAIL]" in stripped:
            name_match = re.search(r"\[FAIL\]\s+(.*)", stripped)
            name = name_match.group(1).strip() if name_match else "unknown"
            details.append({"name": name, "status": "FAIL"})

    # If no [PASS]/[FAIL] found but has errors, report as ERROR
    if not details and ("error:" in stderr.lower() or exit_code != 0):
        details.append({
            "name": filepath.stem,
            "status": "ERROR",
        })

    total = len(details)
    passing = sum(1 for d in details if d["status"] == "PASS")
    failing = sum(1 for d in details if d["status"] == "FAIL")
    errors = sum(1 for d in details if d["status"] == "ERROR")

    return {
        "file": str(filepath.relative_to(filepath.parent.parent.parent)),
        "total": total,
        "passing": passing,
        "failing": failing,
        "errors": errors,
        "details": details,
    }


# ─── Bridge Parsing ──────────────────────────────────────────────────────────

def parse_bridge_result(project: Path, run_result: dict) -> dict:
    """Parse results from Tests/Bridge.lean.

    Counts #check statements, bridge_* theorem witnesses, and joint witnesses
    (example : <type> := theorem_name ...).
    """
    bridge_file = project / TESTS_DIR / "Bridge.lean"
    checks = []
    witnesses = []
    joint_witnesses = []

    if bridge_file.exists():
        try:
            content = bridge_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            content = ""
        for m in re.finditer(r"^#check\s+@?(\S+)", content, re.MULTILINE):
            checks.append(m.group(1))
        for m in re.finditer(
            r"^(theorem|lemma)\s+(bridge_\w+)", content, re.MULTILINE
        ):
            witnesses.append(m.group(2))
        # Joint witnesses: example : <type> := <theorem_name> <args>
        for m in re.finditer(
            r"^example\s+:", content, re.MULTILINE
        ):
            joint_witnesses.append(f"joint_witness@{m.start()}")

    exit_code = run_result.get("exit_code", -1)
    stderr = run_result.get("stderr", "")
    has_errors = exit_code != 0 or "error:" in stderr.lower()

    return {
        "file": str(TESTS_DIR + "/Bridge.lean"),
        "status": "FAIL" if has_errors else "PASS",
        "checks": len(checks),
        "witnesses": len(witnesses),
        "joint_witnesses": len(joint_witnesses),
        "check_names": checks,
        "witness_names": witnesses,
        "errors": stderr.strip() if has_errors else "",
    }


# ─── Dispute Mechanism ───────────────────────────────────────────────────────

def dispute_test(project: Path, node: str, test_name: str,
                 reason: str, evidence_files: list[str]) -> dict:
    """Dispute a test by requesting Gemini re-evaluation.

    Returns dispute result dict with verdict and rationale.
    """
    try:
        from google import genai
    except ImportError:
        return {
            "error": "google-genai not installed. Run: pip install google-genai",
            "verdict": "ERROR",
        }

    # 1. Find and load the test source
    test_files = find_test_files(project, node)
    test_code = ""
    for key in ("properties", "integration"):
        fpath = test_files.get(key)
        if fpath and fpath.exists():
            content = fpath.read_text(encoding="utf-8")
            if test_name in content:
                test_code = content
                break

    if not test_code:
        return {
            "error": f"Test '{test_name}' not found in test files for node {node}",
            "verdict": "ERROR",
        }

    # 2. Load evidence code
    evidence_code = ""
    for ref in evidence_files:
        # Parse "file.lean:45-60" format
        parts = ref.split(":")
        fpath = project / parts[0]
        if fpath.exists():
            lines = fpath.read_text(encoding="utf-8").splitlines()
            if len(parts) > 1:
                line_range = parts[1]
                if "-" in line_range:
                    start, end = line_range.split("-")
                    start, end = int(start) - 1, int(end)
                    evidence_code += f"-- {ref}\n"
                    evidence_code += "\n".join(lines[start:end]) + "\n\n"
                else:
                    ln = int(line_range) - 1
                    evidence_code += f"-- {ref}\n{lines[ln]}\n\n"
            else:
                evidence_code += f"-- {ref}\n{fpath.read_text(encoding='utf-8')}\n\n"

    # 3. Load project scope from ARCHITECTURE.md
    arch_path = project / "ARCHITECTURE.md"
    scope = ""
    if arch_path.exists():
        arch_content = arch_path.read_text(encoding="utf-8")
        # Extract first 50 lines as scope summary
        scope = "\n".join(arch_content.splitlines()[:50])

    # 4. Build dispute prompt
    prompt = f"""You are a Senior Test Engineer reviewing a test dispute.

The Lead Developer (Claude) disputes one of your generated tests.

## Disputed Test
```lean
{test_code}
```

Test in question: `{test_name}`

## Developer's Justification
{reason}

## Relevant Code Evidence
```lean
{evidence_code}
```

## Project Scope (from ARCHITECTURE.md)
{scope}

## Your Options
1. ACCEPT_DISPUTE: The test is indeed out of scope or redundant due to type-level guarantees
2. INSIST: The test covers a genuine risk that the developer hasn't addressed
3. MODIFY_TEST: The concern is valid but the test needs adjustment

Respond with EXACTLY this format:
VERDICT: [ACCEPT_DISPUTE | INSIST | MODIFY_TEST]
RATIONALE: [Brief explanation]
MODIFIED_TEST: [Only if MODIFY_TEST - the corrected Lean 4 test code in a lean code block]"""

    # 5. Call Gemini API
    client = _create_gemini_client()
    if not client:
        return {"error": "Cannot create Gemini client", "verdict": "ERROR"}

    try:
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt,
            config={"temperature": 0.3, "max_output_tokens": 4096},
        )
        if response is None or response.text is None:
            return {"error": "Gemini returned no response", "verdict": "ERROR"}
        text = response.text
    except Exception as e:
        return {"error": f"Gemini API error: {e}", "verdict": "ERROR"}

    # 6. Parse verdict
    verdict = "ERROR"
    rationale = ""
    modified_test = ""

    for line in text.splitlines():
        if line.startswith("VERDICT:"):
            v = line.split(":", 1)[1].strip()
            if v in ("ACCEPT_DISPUTE", "INSIST", "MODIFY_TEST"):
                verdict = v
        elif line.startswith("RATIONALE:"):
            rationale = line.split(":", 1)[1].strip()

    # Extract modified test if MODIFY_TEST
    if verdict == "MODIFY_TEST":
        lean_match = re.search(r"```lean\n(.*?)```", text, re.DOTALL)
        if lean_match:
            modified_test = lean_match.group(1).strip()

    # 7. Build result
    result = {
        "test": test_name,
        "node": node,
        "reason": reason,
        "evidence": evidence_files,
        "gemini_verdict": verdict,
        "gemini_rationale": rationale,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }

    if modified_test:
        result["modified_test"] = modified_test

    # 8. Update tests.json
    _update_disputes(project, node, result)

    return result


def _create_gemini_client():
    """Create Gemini client (reuses pattern from collab.py)."""
    try:
        from google import genai
    except ImportError:
        print("ERROR: google-genai not installed", file=sys.stderr)
        return None

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        env_paths = [
            Path.home() / ".env",
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
        return None

    return genai.Client(api_key=api_key)


def _update_disputes(project: Path, node: str, dispute: dict):
    """Update tests.json with dispute result."""
    tests_json = project / TESTS_DIR / "tests.json"
    data = {}
    if tests_json.exists():
        data = json.loads(tests_json.read_text(encoding="utf-8"))

    if node not in data:
        data[node] = {"disputes": []}
    if "disputes" not in data[node]:
        data[node]["disputes"] = []

    # Remove existing dispute for same test
    data[node]["disputes"] = [
        d for d in data[node]["disputes"] if d.get("test") != dispute["test"]
    ]
    data[node]["disputes"].append(dispute)

    tests_json.parent.mkdir(parents=True, exist_ok=True)
    tests_json.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_disputes(project: Path, node: str) -> list[dict]:
    """Load existing disputes for a node."""
    tests_json = project / TESTS_DIR / "tests.json"
    if not tests_json.exists():
        return []
    data = json.loads(tests_json.read_text(encoding="utf-8"))
    return data.get(node, {}).get("disputes", [])


# ─── Main Logic ──────────────────────────────────────────────────────────────

def run_node_tests(
    project: Path, node_name: str,
    test_type: str = "all", timeout: int = 300,
) -> dict:
    """Run all tests for a node and return structured results."""
    files = find_test_files(project, node_name)
    disputes = load_disputes(project, node_name)
    disputed_tests = {
        d["test"] for d in disputes
        if d.get("gemini_verdict") == "ACCEPT_DISPUTE"
    }

    result = {
        "node": node_name,
        "bridge": None,
        "properties": None,
        "integration": None,
        "all_pass": True,
        "p0_pass": True,
        "blocking_failures": [],
    }

    # Bridge (run once — checks formal theorem coupling)
    bridge_file = project / TESTS_DIR / "Bridge.lean"
    if bridge_file.exists():
        start = time.time()
        bridge_run = run_lean_file(project, bridge_file, timeout)
        bridge_run["time_seconds"] = round(time.time() - start, 1)
        bridge = parse_bridge_result(project, bridge_run)
        result["bridge"] = bridge
        if bridge["status"] != "PASS":
            result["all_pass"] = False
            result["blocking_failures"].append(
                f"Bridge FAIL: {bridge['errors'][:120]}"
            )

    # Properties — use overlay cwd if property file is in PropertyTests/ or Tests/
    if test_type in ("all", "properties") and files["properties"]:
        prop_file = files["properties"]
        # Determine which overlay to use based on where the file lives
        prop_cwd = None
        if PROPERTY_TESTS_DIR in str(prop_file):
            # PropertyTests/ overlay (Plausible/Mathlib)
            overlay_lf = project / PROPERTY_TESTS_DIR / "lakefile.toml"
            if overlay_lf.exists():
                prop_cwd = project / PROPERTY_TESTS_DIR
        else:
            # Tests/ overlay (legacy)
            overlay_lf = project / TESTS_DIR / "lakefile.toml"
            if overlay_lf.exists():
                prop_cwd = project / TESTS_DIR
        # Detect eval-mode properties (no-Mathlib) — need --run for main
        prop_source = prop_file.read_text(encoding="utf-8")
        prop_run_main = _detect_eval_mode(prop_source)
        start = time.time()
        run_result = run_lean_file(
            project, prop_file, timeout,
            run_main=prop_run_main, cwd=prop_cwd,
        )
        run_result["time_seconds"] = round(time.time() - start, 1)
        props = parse_properties_result(files["properties"], run_result)
        result["properties"] = props

        # Apply dispute exclusions
        for p in props.get("details", []):
            if p["name"] in disputed_tests:
                p["status"] = "DISPUTED"

        # Recount after disputes
        active = [p for p in props["details"] if p["status"] != "DISPUTED"]
        props["passing"] = sum(1 for p in active if p["status"] == "PASS")
        props["failing"] = sum(1 for p in active if p["status"] == "FAIL")
        props["not_runnable"] = sum(1 for p in active if p["status"] == "NOT_RUNNABLE")
        props["errors"] = sum(1 for p in active if p["status"] == "ERROR")

        # P0 check: only P0 properties that are ACTIVE matter
        p0_props = [p for p in active if p.get("priority") == "P0"]
        p0_failing = [p for p in p0_props if p["status"] in ("FAIL", "ERROR")]
        if p0_failing:
            result["p0_pass"] = False
            result["all_pass"] = False
            result["blocking_failures"].extend(
                f"P0 {p['name']}: {p['status']}" for p in p0_failing
            )

        # Errors are always blocking
        if props["errors"] > 0:
            result["all_pass"] = False

    # Integration (use --run to execute main)
    if test_type in ("all", "integration") and files["integration"]:
        start = time.time()
        run_result = run_lean_file(project, files["integration"], timeout, run_main=True)
        run_result["time_seconds"] = round(time.time() - start, 1)
        integ = parse_integration_result(files["integration"], run_result)
        result["integration"] = integ

        # Apply dispute exclusions
        for t in integ.get("details", []):
            if t["name"] in disputed_tests:
                t["status"] = "DISPUTED"

        # Recount
        active = [t for t in integ["details"] if t["status"] != "DISPUTED"]
        integ["passing"] = sum(1 for t in active if t["status"] == "PASS")
        integ["failing"] = sum(1 for t in active if t["status"] == "FAIL")
        integ["errors"] = sum(1 for t in active if t["status"] == "ERROR")

        if integ["failing"] > 0 or integ["errors"] > 0:
            result["all_pass"] = False
            result["blocking_failures"].extend(
                f"Integration {t['name']}: {t['status']}"
                for t in active if t["status"] in ("FAIL", "ERROR")
            )

    # If no test files exist at all, pass vacuously with warning
    if files["properties"] is None and files["integration"] is None:
        result["warning"] = f"No test files found for node {node_name}"

    return result


def format_text_report(result: dict) -> str:
    """Format human-readable test results."""
    lines = []
    node = result.get("node", "?")
    lines.append(f"{'=' * 56}")
    lines.append(f"  TEST RESULTS: {node}")
    lines.append(f"{'=' * 56}")
    lines.append("")

    bridge = result.get("bridge")
    if bridge:
        lines.append(f"FORMAL BRIDGE ({bridge['file']}):")
        lines.append(f"  Status: {bridge['status']}")
        lines.append(f"  #check statements: {bridge['checks']}")
        lines.append(f"  Hypothesis witnesses: {bridge['witnesses']}")
        lines.append(f"  Joint witnesses: {bridge.get('joint_witnesses', 0)}")
        for name in bridge.get("check_names", []):
            lines.append(f"    CHK  {name}")
        for name in bridge.get("witness_names", []):
            lines.append(f"    WIT  {name}")
        if bridge["errors"]:
            lines.append(f"  Errors: {bridge['errors'][:200]}")
        lines.append("")

    props = result.get("properties")
    if props:
        lines.append(f"PROPERTIES ({props['file']}):")
        lines.append(f"  Total: {props['total']}  Pass: {props['passing']}  "
                     f"Fail: {props['failing']}  NR: {props['not_runnable']}  "
                     f"Err: {props['errors']}")
        for p in props.get("details", []):
            status_icon = {
                "PASS": "PASS", "FAIL": "FAIL", "ERROR": "ERR!",
                "NOT_RUNNABLE": "SKIP", "DISPUTED": "DISP",
            }.get(p["status"], "????")
            lines.append(f"    {status_icon}  [{p.get('priority', '??')}] {p['name']}")
        lines.append("")

    integ = result.get("integration")
    if integ:
        lines.append(f"INTEGRATION ({integ['file']}):")
        lines.append(f"  Total: {integ['total']}  Pass: {integ['passing']}  "
                     f"Fail: {integ['failing']}  Err: {integ['errors']}")
        for t in integ.get("details", []):
            status_icon = "PASS" if t["status"] == "PASS" else (
                "DISP" if t["status"] == "DISPUTED" else "FAIL"
            )
            lines.append(f"    {status_icon}  {t['name']}")
        lines.append("")

    if result.get("warning"):
        lines.append(f"WARNING: {result['warning']}")
        lines.append("")

    lines.append(f"{'─' * 56}")
    all_pass = result.get("all_pass", False)
    p0_pass = result.get("p0_pass", True)
    lines.append(f"P0 PROPERTIES: {'PASS' if p0_pass else 'FAIL'}")
    lines.append(f"ALL TESTS:     {'PASS' if all_pass else 'FAIL'}")

    if result.get("blocking_failures"):
        lines.append("")
        lines.append("BLOCKING FAILURES:")
        for f in result["blocking_failures"]:
            lines.append(f"  - {f}")

    # Coverage summary (3 layers)
    lines.append("")
    lines.append("COVERAGE SUMMARY:")
    if bridge:
        jw = bridge.get('joint_witnesses', 0)
        b_str = f"{bridge['status']} ({bridge['checks']} #check, {bridge['witnesses']} witnesses, {jw} joint)"
    else:
        b_str = "MISSING (no Tests/Bridge.lean)"
    lines.append(f"  Layer 1 (Formal Bridge):  {b_str}")
    if props:
        p_str = f"{props['passing']}/{props['total']} pass"
    else:
        p_str = "N/A (no property tests)"
    lines.append(f"  Layer 2 (Properties):     {p_str}")
    if integ:
        i_str = f"{integ['passing']}/{integ['total']} pass"
    else:
        i_str = "N/A (no integration tests)"
    lines.append(f"  Layer 3 (Integration):    {i_str}")

    lines.append(f"{'─' * 56}")
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Run Lean tests and parse results"
    )
    parser.add_argument("--project", required=True, help="Path to project")
    parser.add_argument("--node", required=True, help="Node name (e.g., N2.1)")
    parser.add_argument(
        "--type", choices=["all", "properties", "integration"],
        default="all", help="Type of tests to run"
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout per file (s)")
    parser.add_argument("--save-results", default=None,
                        help="Save results to JSON file (appends per node)")

    # Dispute flags
    parser.add_argument("--dispute", default=None, help="Test name to dispute")
    parser.add_argument("--reason", default=None, help="Reason for dispute")
    parser.add_argument(
        "--evidence", nargs="*", default=[],
        help="Evidence files (e.g., 'File.lean:45-60')"
    )

    args = parser.parse_args()
    project = Path(args.project).resolve()

    # Handle dispute mode
    if args.dispute:
        if not args.reason:
            print("ERROR: --reason required with --dispute", file=sys.stderr)
            sys.exit(2)
        result = dispute_test(
            project, args.node, args.dispute,
            args.reason, args.evidence or []
        )
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            verdict = result.get("gemini_verdict", "ERROR")
            rationale = result.get("gemini_rationale", "")
            print(f"DISPUTE: {args.dispute}")
            print(f"VERDICT: {verdict}")
            print(f"RATIONALE: {rationale}")
            if result.get("error"):
                print(f"ERROR: {result['error']}")
        sys.exit(0 if result.get("gemini_verdict") != "ERROR" else 1)

    # Resolve bare virtual-phase IDs (e.g., "N1" → "NatOpt") so that
    # find_test_files can locate Tests/Integration/NatOpt.lean.
    resolved_name = resolve_node_name(project, args.node)
    if resolved_name != args.node:
        # Use the resolved name for test discovery
        result = run_node_tests(project, resolved_name, args.type, args.timeout)
    else:
        result = run_node_tests(project, args.node, args.type, args.timeout)

    # Save results to file if requested
    if args.save_results:
        save_path = Path(args.save_results)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        existing = {}
        if save_path.exists():
            try:
                existing = json.loads(save_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}
        existing[args.node] = result
        bridge_info = result.get("bridge")
        existing["_meta"] = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "project": str(project),
            "bridge_status": bridge_info["status"] if bridge_info else "MISSING",
        }
        save_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_text_report(result))

    sys.exit(0 if result.get("all_pass", False) else 1)


if __name__ == "__main__":
    main()
