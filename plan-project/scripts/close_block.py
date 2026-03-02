#!/usr/bin/env python3
"""close_block.py — Verificación obligatoria al cerrar un bloque del DAG.

Pipeline de 4 pasos:
  Paso 1: verify_node.py por nodo (mecánico, 0 LLM tokens)
  Paso 2: run_tests.py por nodo (ejecución de tests)
  Paso 3: evaluate_rubric.py (gate de rúbrica)
  Paso 4: Agregación → all_pass = mecánico AND tests AND rúbrica

Crea un marker file para el hook guard-block-close.sh.

Uso:
  python3 close_block.py --project /path --block "Bloque 3" \
    --nodes '{"PARALELO_C": ["Module/C.lean"], "HOJA_D": ["Module/D.lean"]}'

  python3 close_block.py --project /path --block "Bloque 1" \
    --nodes '{"FUNDACIONAL_A": ["Core/Base.lean", "Core/Types.lean"]}' --json

  # Backward compat: skip tests/rubric for projects without test files
  python3 close_block.py --project /path --block "Bloque 1" \
    --nodes '{"N1": ["File.lean"]}' --skip-tests --skip-rubric
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
VERIFY_SCRIPT = SCRIPTS_DIR / "verify_node.py"
RUN_TESTS_SCRIPT = SCRIPTS_DIR / "run_tests.py"
EVALUATE_RUBRIC_SCRIPT = SCRIPTS_DIR / "evaluate_rubric.py"
MARKER_DIR = Path("/tmp")

TELEGRAM_FLAG = Path("/tmp/claude-telegram-active")
TELEGRAM_NOTIFY_DIR = Path("/tmp/claude-telegram/notify")


def telegram_notify(event: str, project: str, **kwargs) -> None:
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


# ─── Step 1: Mechanical Verification ────────────────────────────────────────

def run_verify_node(project, node_name, files, timeout=600):
    """Run verify_node.py for a single node and return parsed JSON result."""
    cmd = [
        sys.executable, str(VERIFY_SCRIPT),
        "--project", project,
        "--files", *files,
        "--node", node_name,
        "--json",
        "--timeout", str(timeout),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout + 30,
        )
        output = result.stdout.strip()
        if output:
            return json.loads(output)
        return {
            "node": node_name,
            "all_pass": False,
            "error": f"No output. stderr: {result.stderr[:200]}",
        }
    except subprocess.TimeoutExpired:
        return {"node": node_name, "all_pass": False, "error": f"Timeout {timeout}s"}
    except json.JSONDecodeError as e:
        return {"node": node_name, "all_pass": False, "error": f"JSON parse: {e}"}
    except Exception as e:
        return {"node": node_name, "all_pass": False, "error": str(e)}


# ─── Step 2: Test Execution ─────────────────────────────────────────────────

def run_node_tests(project, node_name, timeout=300):
    """Run run_tests.py for a single node and return parsed JSON result."""
    cmd = [
        sys.executable, str(RUN_TESTS_SCRIPT),
        "--project", project,
        "--node", node_name,
        "--json",
        "--timeout", str(timeout),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout + 30,
        )
        output = result.stdout.strip()
        if output:
            return json.loads(output)
        return {
            "node": node_name,
            "all_pass": True,
            "warning": f"No test output. stderr: {result.stderr[:200]}",
        }
    except subprocess.TimeoutExpired:
        return {
            "node": node_name, "all_pass": True,
            "warning": f"Test timeout {timeout}s (non-blocking)",
        }
    except json.JSONDecodeError as e:
        return {
            "node": node_name, "all_pass": True,
            "warning": f"Test JSON parse: {e}",
        }
    except Exception as e:
        return {
            "node": node_name, "all_pass": True,
            "warning": f"Test error: {e}",
        }


# ─── Step 3: Rubric Evaluation ──────────────────────────────────────────────

def evaluate_rubric(project, node_results, test_results):
    """Run evaluate_rubric.py and return parsed JSON result."""
    # Write mechanical results to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="mech_"
    ) as f:
        json.dump(node_results, f)
        mech_path = f.name

    # Write test results to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="tests_"
    ) as f:
        json.dump(test_results, f)
        tests_path = f.name

    cmd = [
        sys.executable, str(EVALUATE_RUBRIC_SCRIPT),
        "--project", project,
        "--mechanical", mech_path,
        "--tests", tests_path,
        "--json",
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        if output:
            return json.loads(output)
        return {
            "blocking_pass": True,
            "advisory_pass": True,
            "all_pass": True,
            "warning": "No rubric output",
        }
    except Exception as e:
        return {
            "blocking_pass": True,
            "advisory_pass": True,
            "all_pass": True,
            "warning": f"Rubric error: {e}",
        }
    finally:
        try:
            os.unlink(mech_path)
            os.unlink(tests_path)
        except OSError:
            pass


# ─── Marker ──────────────────────────────────────────────────────────────────

def create_marker(project, block_name, all_pass):
    """Create marker file so the guard hook knows close_block ran."""
    project_slug = Path(project).name.replace(" ", "_")
    marker_path = MARKER_DIR / f"claude_block_verified_{project_slug}"

    entry = {
        "block": block_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pass": all_pass,
    }

    # Append to marker file (multiple blocks can be verified in a session)
    with open(marker_path, "a") as f:
        f.write(json.dumps(entry) + "\n")

    return str(marker_path)


# ─── Report Formatting ──────────────────────────────────────────────────────

def format_report(
    block_name, node_results, test_results, rubric_result, elapsed,
    skip_tests, skip_rubric,
):
    """Format a human-readable report for Claude's context."""
    lines = []
    lines.append(f"{'=' * 60}")
    lines.append(f"  CIERRE DE BLOQUE: {block_name}")
    lines.append(f"{'=' * 60}")
    lines.append("")

    # ── Step 1: Mechanical ──
    lines.append("PASO 1: VERIFICACIÓN MECÁNICA")
    total_nodes = len(node_results)
    passed_nodes = sum(1 for r in node_results if r.get("all_pass"))

    for r in node_results:
        node = r.get("node", "?")
        status = "PASS ✓" if r.get("all_pass") else "FAIL ✗"
        lines.append(f"  {status}  {node}")

        if r.get("error"):
            lines.append(f"         Error: {r['error']}")
        elif not r.get("all_pass"):
            totals = r.get("totals", {})
            if totals.get("sorry", 0) > 0:
                lines.append(f"         sorry: {totals['sorry']}")
            if totals.get("axiom", 0) > 0:
                lines.append(f"         axiom: {totals['axiom']}")
            build = r.get("build", {})
            if not build.get("pass", True):
                errors = build.get("errors", [])
                if errors:
                    lines.append(f"         build: {errors[0][:100]}")
            deps = r.get("dependents", {})
            if deps.get("issues"):
                lines.append(f"         regresiones: {len(deps['issues'])} dependientes")

        totals = r.get("totals", {})
        if totals:
            slim_n = totals.get("slim_check", 0)
            slim_tag = f" SC:{slim_n}" if slim_n > 0 else ""
            lines.append(
                f"         {totals.get('loc', 0)} LOC, "
                f"{totals.get('theorems', 0)}T {totals.get('lemmas', 0)}L "
                f"{totals.get('defs', 0)}D{slim_tag}"
            )

    mechanical_pass = all(r.get("all_pass") for r in node_results)
    lines.append(f"  → Mecánico: {'PASS' if mechanical_pass else 'FAIL'}")
    lines.append("")

    # ── Step 2: Tests ──
    lines.append("PASO 2: EJECUCIÓN DE TESTS")
    tests_pass = True

    if skip_tests:
        lines.append("  (omitido — --skip-tests)")
    elif not test_results:
        lines.append("  (sin tests disponibles)")
    else:
        for node_name, tr in test_results.items():
            if tr.get("warning"):
                lines.append(f"  WARN  {node_name}: {tr['warning']}")
                continue

            props = tr.get("properties")
            integ = tr.get("integration")

            if props:
                lines.append(
                    f"  Props {node_name}: "
                    f"{props.get('passing', 0)}/{props.get('total', 0)} pass"
                    f"  (NR:{props.get('not_runnable', 0)} err:{props.get('errors', 0)})"
                )
            if integ:
                lines.append(
                    f"  Integ {node_name}: "
                    f"{integ.get('passing', 0)}/{integ.get('total', 0)} pass"
                    f"  (err:{integ.get('errors', 0)})"
                )

            if not tr.get("all_pass", True):
                tests_pass = False
                for bf in tr.get("blocking_failures", []):
                    lines.append(f"    BLOCK: {bf}")

        lines.append(f"  → Tests: {'PASS' if tests_pass else 'FAIL'}")

    lines.append("")

    # ── Step 3: Rubric ──
    lines.append("PASO 3: EVALUACIÓN DE RÚBRICA")

    rubric_pass = True
    if skip_rubric:
        lines.append("  (omitido — --skip-rubric)")
    elif rubric_result.get("warning"):
        lines.append(f"  WARN: {rubric_result['warning']}")
    else:
        for c in rubric_result.get("criteria", []):
            tag = "BLOCK" if c.get("blocking") else "ADVSR"
            status = c.get("status", "?")
            lines.append(f"  {status:6s} [{tag}] {c.get('name', '?')}")

        rubric_pass = rubric_result.get("blocking_pass", True)
        advisory = rubric_result.get("advisory_pass", True)
        lines.append(f"  → Rúbrica blocking: {'PASS' if rubric_pass else 'FAIL'}")
        if not advisory:
            lines.append(f"  → Rúbrica advisory: FAIL (non-blocking)")

    lines.append("")

    # ── Step 4: Aggregation ──
    all_pass = mechanical_pass and tests_pass and rubric_pass

    # SlimCheck coverage summary (advisory)
    total_slim = sum(
        r.get("totals", {}).get("slim_check", 0) for r in node_results
    )
    lines.append(f"SLIMCHECK COVERAGE (advisory): {total_slim} propiedades encontradas")
    if total_slim == 0:
        lines.append("  Sin propiedades SlimCheck en este bloque.")
        lines.append("  Verificar BENCHMARKS.md § Formal Properties para stubs pendientes.")

    lines.append("")
    lines.append(f"{'─' * 60}")
    lines.append(f"NODOS:    {passed_nodes}/{total_nodes} PASS (mecánico)")
    lines.append(f"TESTS:    {'PASS' if tests_pass else 'FAIL'}")
    lines.append(f"RÚBRICA:  {'PASS' if rubric_pass else 'FAIL'}")
    lines.append(f"BLOQUE:   {'PASS ✓' if all_pass else 'FAIL ✗'}")
    lines.append(f"TIEMPO:   {elapsed:.1f}s")
    lines.append(f"{'─' * 60}")

    if all_pass:
        lines.append("")
        lines.append("SIGUIENTE PASO OBLIGATORIO:")
        lines.append("  1. Lanzar QA riguroso via subagente:")
        lines.append("     Task(general-purpose): collab.py --rounds 1 --detail full")
        lines.append("     Evaluar contra criterios en BENCHMARKS.md")
        lines.append("     INCLUIR extracción de lecciones como JSON array:")
        lines.append('     [{"title":"...","body":"...","keywords":["..."]}]')
        lines.append("  2. Si QA PASS → update_docs.py --close-block --result '...' --lessons '[...]'")
        lines.append("     Las lecciones se clasifican y guardan automáticamente.")
        lines.append("  3. Si QA FAIL → resolver → re-ejecutar close_block.py")
    else:
        lines.append("")
        lines.append("ACCIÓN REQUERIDA:")
        lines.append("  Resolver TODOS los problemas → re-ejecutar close_block.py")
        lines.append("  NO avanzar al siguiente bloque hasta PASS.")

    return "\n".join(lines)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Verificación obligatoria al cerrar un bloque del DAG"
    )
    parser.add_argument("--project", required=True, help="Path al proyecto")
    parser.add_argument("--block", required=True, help="Nombre del bloque (ej: 'Bloque 3')")
    parser.add_argument(
        "--nodes", required=True,
        help='JSON: {"node_name": ["file1.lean", "file2.lean"], ...}',
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--timeout", type=int, default=600, help="Build timeout per node (s)")
    parser.add_argument("--skip-tests", action="store_true",
                        help="Skip test execution (backward compat)")
    parser.add_argument("--skip-rubric", action="store_true",
                        help="Skip rubric evaluation")
    parser.add_argument("--test-timeout", type=int, default=300,
                        help="Test execution timeout per node (s)")
    parser.add_argument("--tests-prerun", default=None,
                        help="Path to pre-saved test results JSON (skip execution)")
    args = parser.parse_args()

    project = os.path.abspath(args.project)

    try:
        nodes = json.loads(args.nodes)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid --nodes JSON: {e}", file=sys.stderr)
        sys.exit(2)

    if not nodes:
        print("ERROR: --nodes is empty", file=sys.stderr)
        sys.exit(2)

    start = time.time()

    # ── Step 1: Mechanical verification ──────────────────────────────────
    node_results = []
    for node_name, files in nodes.items():
        print(f"[1/4] Verificando nodo: {node_name} ({len(files)} archivos)...", file=sys.stderr)
        result = run_verify_node(project, node_name, files, timeout=args.timeout)
        node_results.append(result)

    mechanical_pass = all(r.get("all_pass") for r in node_results)

    # ── Step 2: Test results ────────────────────────────────────────────
    test_results = {}
    tests_pass = True

    if args.tests_prerun:
        print(f"[2/4] Tests: cargando resultados de {args.tests_prerun}...", file=sys.stderr)
        prerun_path = Path(args.tests_prerun)
        if prerun_path.exists():
            loaded = json.loads(prerun_path.read_text(encoding="utf-8"))
            loaded.pop("_meta", None)
            test_results = loaded
            tests_pass = all(r.get("all_pass", True) for r in test_results.values())
        else:
            print(f"  WARN: {prerun_path} no encontrado, tests omitidos", file=sys.stderr)
    elif not args.skip_tests:
        for node_name in nodes:
            print(f"[2/4] Tests para: {node_name}...", file=sys.stderr)
            tr = run_node_tests(project, node_name, timeout=args.test_timeout)
            test_results[node_name] = tr
        tests_pass = all(r.get("all_pass", True) for r in test_results.values())
    else:
        print("[2/4] Tests: omitido (--skip-tests)", file=sys.stderr)

    # ── Step 3: Rubric evaluation ────────────────────────────────────────
    rubric_result = {
        "blocking_pass": True,
        "advisory_pass": True,
        "all_pass": True,
    }

    if not args.skip_rubric:
        print("[3/4] Evaluando rúbrica...", file=sys.stderr)
        rubric_result = evaluate_rubric(project, node_results, test_results)
    else:
        print("[3/4] Rúbrica: omitido (--skip-rubric)", file=sys.stderr)

    rubric_pass = rubric_result.get("blocking_pass", True)

    # ── Step 4: Aggregation ──────────────────────────────────────────────
    all_pass = mechanical_pass and tests_pass and rubric_pass
    elapsed = time.time() - start

    print(f"[4/4] Agregación: {'PASS' if all_pass else 'FAIL'}", file=sys.stderr)

    # Create marker for guard hook
    marker = create_marker(project, args.block, all_pass)
    print(f"Marker: {marker}", file=sys.stderr)

    if args.json:
        output = {
            "block": args.block,
            "nodes": node_results,
            "tests": test_results,
            "rubric": rubric_result,
            "mechanical_pass": mechanical_pass,
            "tests_pass": tests_pass,
            "rubric_pass": rubric_pass,
            "all_pass": all_pass,
            "elapsed_seconds": round(elapsed, 1),
            "marker": marker,
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_report(
            args.block, node_results, test_results, rubric_result, elapsed,
            args.skip_tests, args.skip_rubric,
        ))

    telegram_notify(
        "block_closed",
        project,
        block_name=args.block,
        node_names=list(nodes.keys()),
        all_pass=all_pass,
        mechanical_pass=mechanical_pass,
        tests_pass=tests_pass,
        rubric_pass=rubric_pass,
        elapsed_seconds=round(elapsed, 1),
    )

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
