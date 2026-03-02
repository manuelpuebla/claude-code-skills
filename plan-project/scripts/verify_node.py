#!/usr/bin/env python3
"""verify_node.py — Verificación mecánica post-nodo para proyectos Lean 4.

Costo: 0 tokens LLM. Parsing puro + lake build + grep.

Uso:
  python3 verify_node.py --project /path/to/project --files Module.lean --node "nombre"
  python3 verify_node.py --project /path/to/project --files A.lean B.lean --json
  python3 verify_node.py --project /path/to/project --files A.lean --skip-build --skip-deps
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


# ─── Lake Build ───────────────────────────────────────────────────────────────

def run_lake_build(project_path, timeout=600):
    """Run lake build and capture results."""
    start = time.time()
    try:
        result = subprocess.run(
            ["lake", "build"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "time_seconds": timeout,
            "errors": [f"TIMEOUT after {timeout}s"],
            "warnings": [],
            "pass": False,
        }
    except FileNotFoundError:
        return {
            "exit_code": -1,
            "time_seconds": 0,
            "errors": ["lake not found in PATH"],
            "warnings": [],
            "pass": False,
        }

    elapsed = round(time.time() - start, 1)
    combined = result.stderr + "\n" + result.stdout

    errors = []
    warnings = []
    for line in combined.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"\berror\b", stripped, re.IGNORECASE) and not stripped.startswith("--"):
            errors.append(stripped[:200])
        elif re.search(r"\bwarning\b", stripped, re.IGNORECASE) and not stripped.startswith("--"):
            warnings.append(stripped[:200])

    return {
        "exit_code": result.returncode,
        "time_seconds": elapsed,
        "errors": errors[:20],
        "warnings": warnings[:20],
        "pass": result.returncode == 0,
    }


# ─── File Scanner ─────────────────────────────────────────────────────────────

def scan_lean_file(filepath):
    """Scan a Lean file for sorry, axiom, declarations, anti-patterns, etc."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.splitlines()
    except (FileNotFoundError, IOError) as e:
        return {"error": str(e), "file": os.path.basename(filepath)}

    loc = len(lines)

    # Declarations
    theorems = 0
    lemmas = 0
    defs = 0
    instances = 0
    structures = 0
    classes = 0

    # Problems
    sorry_locs = []
    axiom_locs = []
    admit_locs = []

    # Anti-patterns
    native_decide_locs = []
    simp_star_locs = []
    decide_heavy_locs = []
    todo_locs = []

    # SlimCheck usage
    slim_check_locs = []

    # Track block comments
    in_block_comment = False

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Block comment tracking (simplified)
        if "/-" in stripped and "-/" not in stripped:
            in_block_comment = True
            continue
        if "-/" in stripped:
            in_block_comment = False
            continue
        if in_block_comment:
            continue
        # Skip line comments
        if stripped.startswith("--"):
            continue

        # Declarations
        decl_line = stripped
        if re.match(r"^(private\s+|protected\s+)?(noncomputable\s+)?theorem\s+", decl_line):
            theorems += 1
        elif re.match(r"^(private\s+|protected\s+)?(noncomputable\s+)?lemma\s+", decl_line):
            lemmas += 1
        elif re.match(r"^(private\s+|protected\s+)?(noncomputable\s+)?def\s+", decl_line):
            defs += 1
        elif re.match(r"^(private\s+|scoped\s+)?instance\s+", decl_line):
            instances += 1
        elif re.match(r"^(private\s+)?structure\s+", decl_line):
            structures += 1
        elif re.match(r"^(private\s+)?class\s+", decl_line):
            classes += 1

        # Problems (context-aware: not in strings or comments)
        if re.search(r"\bsorry\b", stripped):
            sorry_locs.append({"line": i, "text": stripped[:120]})
        if re.match(r"^axiom\s+", stripped):
            axiom_locs.append({"line": i, "text": stripped[:120]})
        if re.search(r"\badmit\b", stripped):
            admit_locs.append({"line": i, "text": stripped[:120]})

        # Anti-patterns
        if re.search(r"\bnative_decide\b", stripped):
            native_decide_locs.append({"line": i, "text": stripped[:120]})
        if re.search(r"simp\s*\[\s*\*", stripped):
            simp_star_locs.append({"line": i, "text": stripped[:120]})
        if re.search(r"\bdecide\b", stripped) and (theorems + lemmas > 5):
            decide_heavy_locs.append({"line": i, "text": stripped[:120]})
        if re.search(r"\bTODO\b|\bFIXME\b|\bHACK\b", stripped):
            todo_locs.append({"line": i, "text": stripped[:120]})

        # SlimCheck usage
        if re.search(r"\bslim_check\b", stripped):
            slim_check_locs.append({"line": i, "text": stripped[:120]})

    # Imports
    imports = [l.strip() for l in lines if re.match(r"^import\s+", l.strip())]

    return {
        "file": os.path.basename(filepath),
        "path": filepath,
        "loc": loc,
        "theorems": theorems,
        "lemmas": lemmas,
        "defs": defs,
        "instances": instances,
        "structures": structures,
        "classes": classes,
        "sorry": sorry_locs,
        "axiom": axiom_locs,
        "admit": admit_locs,
        "native_decide": native_decide_locs,
        "simp_star": simp_star_locs,
        "decide_heavy": decide_heavy_locs,
        "todo": todo_locs,
        "slim_check": slim_check_locs,
        "imports": len(imports),
    }


# ─── Dependent Regression Check ──────────────────────────────────────────────

def check_dependents(project_path, file_paths):
    """Find modules that import the given files and check they still compile."""
    issues = []
    checked = set()

    for fpath in file_paths:
        rel = os.path.relpath(fpath, project_path)
        # Extract module name from path: VR1CS/EGraph/Core.lean → Core
        basename = Path(rel).stem

        try:
            result = subprocess.run(
                ["grep", "-rl", f"import.*{basename}", "--include=*.lean",
                 "--exclude-dir=.lake", "--exclude-dir=lake-packages", "."],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, Exception):
            continue

        for dep_line in result.stdout.splitlines():
            dep = dep_line.strip().lstrip("./")
            if not dep or dep == rel or dep in checked:
                continue
            checked.add(dep)

            try:
                check = subprocess.run(
                    ["lake", "env", "lean", dep],
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if check.returncode != 0:
                    # Extract first error line
                    err = ""
                    for eline in (check.stderr + check.stdout).splitlines():
                        if "error" in eline.lower():
                            err = eline.strip()[:120]
                            break
                    issues.append({"file": dep, "status": "FAIL", "error": err})
            except subprocess.TimeoutExpired:
                issues.append({"file": dep, "status": "TIMEOUT", "error": ""})
            except Exception:
                pass

    return {"checked": len(checked), "issues": issues}


# ─── Report Formatting ───────────────────────────────────────────────────────

def format_text_report(build, scans, deps, node_name):
    """Format structured text report for LLM consumption (~500 tokens)."""

    # Totals
    t_loc = sum(s.get("loc", 0) for s in scans)
    t_thm = sum(s.get("theorems", 0) for s in scans)
    t_lem = sum(s.get("lemmas", 0) for s in scans)
    t_def = sum(s.get("defs", 0) for s in scans)
    t_inst = sum(s.get("instances", 0) for s in scans)
    t_sorry = sum(len(s.get("sorry", [])) for s in scans)
    t_axiom = sum(len(s.get("axiom", [])) for s in scans)
    t_admit = sum(len(s.get("admit", [])) for s in scans)
    t_native = sum(len(s.get("native_decide", [])) for s in scans)
    t_simp_s = sum(len(s.get("simp_star", [])) for s in scans)
    t_decide = sum(len(s.get("decide_heavy", [])) for s in scans)
    t_todo = sum(len(s.get("todo", [])) for s in scans)
    t_warn = len(build.get("warnings", []))
    dep_fails = len(deps.get("issues", []))

    # Check results
    checks = []

    def chk(ok, label):
        status = "PASS" if ok else "FAIL"
        checks.append((ok, status, label))
        return f"  {status}  {label}"

    lines = []
    lines.append(f"{'=' * 56}")
    lines.append(f"  VERIFICACIÓN POST-NODO: {node_name or '(sin nombre)'}")
    lines.append(f"{'=' * 56}")
    lines.append("")
    lines.append("CHECKS MECÁNICOS:")
    lines.append(chk(build["pass"], f"lake build ({build['time_seconds']}s)"))
    lines.append(chk(t_sorry == 0, f"Zero sorry ({t_sorry})"))
    lines.append(chk(t_axiom == 0, f"Zero axiom ({t_axiom})"))
    lines.append(chk(t_admit == 0, f"Zero admit ({t_admit})"))
    lines.append(chk(t_warn == 0, f"Zero warnings ({t_warn})"))
    lines.append(chk(t_native == 0, f"Zero native_decide ({t_native})"))
    lines.append(chk(t_simp_s == 0, f"Zero simp[*] ({t_simp_s})"))
    lines.append(chk(t_todo == 0, f"Zero TODO/FIXME ({t_todo})"))
    lines.append(chk(dep_fails == 0, f"Dependientes OK ({deps.get('checked', 0)} checked, {dep_fails} fail)"))

    n_pass = sum(1 for ok, _, _ in checks if ok)
    n_total = len(checks)

    lines.append("")
    lines.append("MÉTRICAS:")
    lines.append(f"  LOC:        {t_loc}")
    lines.append(f"  Theorems:   {t_thm}")
    lines.append(f"  Lemmas:     {t_lem}")
    lines.append(f"  Defs:       {t_def}")
    lines.append(f"  Instances:  {t_inst}")
    lines.append(f"  Archivos:   {len(scans)}")
    lines.append(f"  SlimCheck:  {sum(len(s.get('slim_check', [])) for s in scans)}")
    lines.append(f"  Compile:    {build['time_seconds']}s")

    # Per-file breakdown
    if len(scans) > 1:
        lines.append("")
        lines.append("POR ARCHIVO:")
        for s in scans:
            sorry_mark = f" ⚠ {len(s['sorry'])} sorry" if s.get("sorry") else ""
            lines.append(f"  {s['file']}: {s['loc']} LOC, {s['theorems']}T {s['lemmas']}L {s['defs']}D{sorry_mark}")

    # Problems detail
    all_problems = []
    for s in scans:
        for item in s.get("sorry", []):
            all_problems.append(f"  sorry   {s['file']}:L{item['line']}: {item['text']}")
        for item in s.get("axiom", []):
            all_problems.append(f"  axiom   {s['file']}:L{item['line']}: {item['text']}")
        for item in s.get("admit", []):
            all_problems.append(f"  admit   {s['file']}:L{item['line']}: {item['text']}")

    if all_problems:
        lines.append("")
        lines.append("PROBLEMAS ENCONTRADOS:")
        lines.extend(all_problems[:15])

    # Anti-patterns
    anti = []
    for s in scans:
        for item in s.get("native_decide", []):
            anti.append(f"  native_decide  {s['file']}:L{item['line']}")
        for item in s.get("simp_star", []):
            anti.append(f"  simp[*]        {s['file']}:L{item['line']}")
        for item in s.get("decide_heavy", []):
            anti.append(f"  decide (heavy) {s['file']}:L{item['line']}")

    if anti:
        lines.append("")
        lines.append("ANTI-PATRONES:")
        lines.extend(anti[:10])

    # SlimCheck coverage (advisory, does not affect PASS/FAIL)
    t_slim = sum(len(s.get("slim_check", [])) for s in scans)
    lines.append("")
    lines.append(f"SLIMCHECK (advisory): {t_slim} slim_check invocaciones encontradas")
    if t_slim > 0:
        for s in scans:
            for item in s.get("slim_check", []):
                lines.append(f"  {s['file']}:L{item['line']}: {item['text']}")
    else:
        lines.append("  Ninguna propiedad SlimCheck en este nodo.")
        lines.append("  Considerar agregar stubs de BENCHMARKS.md § Formal Properties.")

    # Warnings
    if build.get("warnings"):
        lines.append("")
        lines.append("WARNINGS COMPILADOR:")
        for w in build["warnings"][:8]:
            lines.append(f"  {w}")

    # Dependent regressions
    if deps.get("issues"):
        lines.append("")
        lines.append("REGRESIONES EN DEPENDIENTES:")
        for d in deps["issues"]:
            lines.append(f"  {d['status']}  {d['file']}: {d.get('error', '')}")

    lines.append("")
    lines.append(f"{'─' * 56}")
    lines.append(f"RESULTADO MECÁNICO: {n_pass}/{n_total} checks PASS")
    all_pass = n_pass == n_total
    lines.append(f"STATUS GLOBAL: {'PASS ✓' if all_pass else 'FAIL ✗'}")
    lines.append(f"{'─' * 56}")

    if all_pass:
        lines.append("")
        lines.append("SIGUIENTE: QA riguroso via subagente (stress, borde, robustez)")
        lines.append("  Task(general-purpose): collab.py --rounds 1 --detail full")
        lines.append("  Evaluar: casos borde, stress, hipótesis redundantes, calidad pruebas")
    else:
        lines.append("")
        lines.append("ACCIÓN: Resolver problemas ANTES de QA y ANTES de continuar.")

    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Verificación mecánica post-nodo (0 tokens LLM)"
    )
    parser.add_argument("--project", required=True, help="Path al proyecto Lean")
    parser.add_argument("--files", nargs="+", required=True, help="Archivos del nodo")
    parser.add_argument("--node", default="", help="Nombre del nodo")
    parser.add_argument("--skip-build", action="store_true", help="Skip lake build")
    parser.add_argument("--skip-deps", action="store_true", help="Skip dependent check")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--timeout", type=int, default=600, help="Build timeout (s)")
    parser.add_argument("--test-results", default=None,
                        help="JSON file with run_tests.py results for this node")
    args = parser.parse_args()

    project = os.path.abspath(args.project)

    # Resolve file paths
    resolved = []
    for f in args.files:
        if os.path.isabs(f):
            resolved.append(f)
        else:
            candidate = os.path.join(project, f)
            if os.path.exists(candidate):
                resolved.append(candidate)
            elif os.path.exists(f):
                resolved.append(os.path.abspath(f))
            else:
                print(f"WARNING: File not found: {f}", file=sys.stderr)

    if not resolved:
        print("ERROR: No valid files to verify.", file=sys.stderr)
        sys.exit(1)

    # Run lake build
    if not args.skip_build:
        build = run_lake_build(project, timeout=args.timeout)
    else:
        build = {
            "exit_code": 0, "time_seconds": 0.0,
            "errors": [], "warnings": [], "pass": True,
        }

    # Scan files
    scans = [scan_lean_file(f) for f in resolved]
    scans = [s for s in scans if "error" not in s]

    # Check dependents
    if not args.skip_deps and build["pass"]:
        deps = check_dependents(project, resolved)
    else:
        deps = {"checked": 0, "issues": []}

    # Load test results if provided
    test_results = None
    if args.test_results:
        try:
            with open(args.test_results, "r", encoding="utf-8") as f:
                test_results = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"WARNING: Could not load test results: {e}", file=sys.stderr)

    # Compute mechanical pass
    mechanical_pass = (
        build["pass"]
        and sum(len(s.get("sorry", [])) for s in scans) == 0
        and sum(len(s.get("axiom", [])) for s in scans) == 0
        and sum(len(s.get("admit", [])) for s in scans) == 0
        and len(build.get("warnings", [])) == 0
        and len(deps.get("issues", [])) == 0
    )

    # Combined pass: mechanical AND tests (if provided)
    tests_pass = test_results.get("all_pass", True) if test_results else True
    all_pass = mechanical_pass and tests_pass

    # Output
    if args.json:
        output = {
            "node": args.node,
            "build": build,
            "files": scans,
            "dependents": deps,
            "totals": {
                "loc": sum(s.get("loc", 0) for s in scans),
                "theorems": sum(s.get("theorems", 0) for s in scans),
                "lemmas": sum(s.get("lemmas", 0) for s in scans),
                "defs": sum(s.get("defs", 0) for s in scans),
                "sorry": sum(len(s.get("sorry", [])) for s in scans),
                "axiom": sum(len(s.get("axiom", [])) for s in scans),
                "admit": sum(len(s.get("admit", [])) for s in scans),
                "slim_check": sum(len(s.get("slim_check", [])) for s in scans),
            },
            "all_pass": all_pass,
        }
        if test_results:
            output["tests"] = test_results
        print(json.dumps(output, indent=2))
    else:
        report = format_text_report(build, scans, deps, args.node)
        # Append test results section if available
        if test_results:
            report += "\n\nTEST RESULTS:\n"
            props = test_results.get("properties")
            if props:
                report += (f"  Properties: {props.get('passing', 0)}/{props.get('total', 0)} pass"
                          f"  ({props.get('not_runnable', 0)} NR, {props.get('errors', 0)} err)\n")
            integ = test_results.get("integration")
            if integ:
                report += (f"  Integration: {integ.get('passing', 0)}/{integ.get('total', 0)} pass"
                          f"  ({integ.get('errors', 0)} err)\n")
            if test_results.get("blocking_failures"):
                report += "  BLOCKING:\n"
                for bf in test_results["blocking_failures"]:
                    report += f"    - {bf}\n"
            report += f"  Tests: {'PASS' if tests_pass else 'FAIL'}\n"
        print(report)

    sys.exit(1 if not all_pass else 0)


if __name__ == "__main__":
    main()
