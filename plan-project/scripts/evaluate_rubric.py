#!/usr/bin/env python3
"""evaluate_rubric.py — Gate de rúbrica para cierre de bloque.

Evalúa criterios de BENCHMARKS.md con anotaciones <!-- CHECK:... --> contra
resultados mecánicos (verify_node) y de tests (run_tests). 0 tokens LLM.

Formato de anotación (HTML comments en BENCHMARKS.md § Criteria):
  - Zero sorry, zero axiom <!-- CHECK:mechanical:blocking -->
  - All P0 properties pass  <!-- CHECK:tests:p0:blocking -->
  - Integration tests pass   <!-- CHECK:tests:integration:blocking -->
  - Compile time < 45s       <!-- CHECK:build_time:45:advisory -->
  - Custom criterion          <!-- CHECK:custom:blocking -->

Uso:
  python3 evaluate_rubric.py --project /path \
    --mechanical mech.json --tests tests.json --json

  python3 evaluate_rubric.py --project /path \
    --mechanical mech.json --json
"""

import argparse
import json
import re
import sys
from pathlib import Path


# ─── Parsing ─────────────────────────────────────────────────────────────────

CHECK_PATTERN = re.compile(
    r"<!--\s*CHECK:(\w+)(?::([^:]+))?:(\w+)\s*-->"
)


def parse_rubric_criteria(benchmarks_path: Path) -> list[dict]:
    """Parse BENCHMARKS.md for CHECK-annotated criteria.

    Returns list of dicts:
      {"name": str, "category": str, "source": str, "param": str|None,
       "blocking": bool, "line": int}
    """
    if not benchmarks_path.exists():
        return []

    content = benchmarks_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Find Criteria section
    in_criteria = False
    current_category = "general"
    criteria = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        if stripped.startswith("## Criteria"):
            in_criteria = True
            continue

        # End of Criteria section
        if in_criteria and stripped.startswith("---"):
            break

        if not in_criteria:
            continue

        # Track category headers (### Correctness, ### Performance, etc.)
        if stripped.startswith("### "):
            current_category = stripped[4:].strip().lower()
            continue

        # Look for CHECK annotations
        match = CHECK_PATTERN.search(line)
        if match:
            source = match.group(1)     # mechanical, tests, build_time, custom
            param = match.group(2)      # p0, integration, 45, etc.
            level = match.group(3)      # blocking or advisory

            # Extract criterion name from the markdown list item
            name = stripped
            # Remove the CHECK annotation from the display name
            name = CHECK_PATTERN.sub("", name).strip()
            # Remove leading "- " or "* "
            name = re.sub(r"^[-*]\s*", "", name).strip()
            # Remove backticks for comparison
            name = name.strip("`")

            criteria.append({
                "name": name,
                "category": current_category,
                "source": source,
                "param": param,
                "blocking": level == "blocking",
                "line": i,
            })

    return criteria


# ─── Evaluation ──────────────────────────────────────────────────────────────

def evaluate_mechanical(criterion: dict, mechanical: list[dict]) -> str:
    """Evaluate a mechanical criterion against verify_node results.

    Returns: PASS, FAIL, or SKIP
    """
    if not mechanical:
        return "SKIP"

    name_lower = criterion["name"].lower()

    # Check for zero sorry
    if "sorry" in name_lower and "zero" in name_lower:
        total = sum(r.get("totals", {}).get("sorry", 0) for r in mechanical)
        return "PASS" if total == 0 else "FAIL"

    # Check for zero axiom
    if "axiom" in name_lower and "zero" in name_lower:
        total = sum(r.get("totals", {}).get("axiom", 0) for r in mechanical)
        return "PASS" if total == 0 else "FAIL"

    # Check for zero admit
    if "admit" in name_lower and "zero" in name_lower:
        total = sum(r.get("totals", {}).get("admit", 0) for r in mechanical)
        return "PASS" if total == 0 else "FAIL"

    # Check for lake build passes
    if "lake build" in name_lower:
        all_build = all(r.get("build", {}).get("pass", False) for r in mechanical)
        return "PASS" if all_build else "FAIL"

    # Check for zero warnings
    if "warning" in name_lower and "zero" in name_lower:
        total = sum(len(r.get("build", {}).get("warnings", [])) for r in mechanical)
        return "PASS" if total == 0 else "FAIL"

    # Check for dependent modules
    if "dependent" in name_lower:
        issues = sum(len(r.get("dependents", {}).get("issues", [])) for r in mechanical)
        return "PASS" if issues == 0 else "FAIL"

    # Check for anti-patterns
    if "native_decide" in name_lower:
        total = sum(
            len(f.get("native_decide", []))
            for r in mechanical for f in r.get("files", [])
        )
        return "PASS" if total == 0 else "FAIL"

    if "simp" in name_lower and "*" in name_lower:
        total = sum(
            len(f.get("simp_star", []))
            for r in mechanical for f in r.get("files", [])
        )
        return "PASS" if total == 0 else "FAIL"

    # Generic all_pass check
    all_pass = all(r.get("all_pass", False) for r in mechanical)
    return "PASS" if all_pass else "FAIL"


def evaluate_tests(criterion: dict, tests: dict) -> str:
    """Evaluate a test criterion against run_tests results.

    Returns: PASS, FAIL, or SKIP
    """
    if not tests:
        return "SKIP"

    param = criterion.get("param", "")

    if param == "p0":
        # All P0 properties must pass across all nodes
        for node_result in tests.values():
            if not node_result.get("p0_pass", True):
                return "FAIL"
        return "PASS"

    elif param == "integration":
        # All integration tests must pass
        for node_result in tests.values():
            integration = node_result.get("integration", {})
            if integration.get("errors", 0) > 0:
                return "FAIL"
            if integration.get("failing", 0) > 0:
                return "FAIL"
        return "PASS"

    else:
        # Generic: all tests pass
        for node_result in tests.values():
            if not node_result.get("all_pass", True):
                return "FAIL"
        return "PASS"


def evaluate_build_time(criterion: dict, mechanical: list[dict]) -> str:
    """Evaluate build time criterion.

    Returns: PASS, FAIL, or SKIP
    """
    if not mechanical:
        return "SKIP"

    param = criterion.get("param")
    if not param:
        return "SKIP"

    try:
        threshold = float(param)
    except ValueError:
        return "SKIP"

    # Sum build times across nodes
    total_time = sum(
        r.get("build", {}).get("time_seconds", 0.0) for r in mechanical
    )
    return "PASS" if total_time < threshold else "FAIL"


def evaluate_criteria(
    criteria: list[dict],
    mechanical: list[dict],
    tests: dict,
) -> list[dict]:
    """Evaluate all parsed criteria against results.

    Returns list of evaluated criteria with 'status' field added.
    """
    results = []

    for c in criteria:
        source = c["source"]
        result = dict(c)

        if source == "mechanical":
            result["status"] = evaluate_mechanical(c, mechanical)
        elif source == "tests":
            result["status"] = evaluate_tests(c, tests)
        elif source == "build_time":
            result["status"] = evaluate_build_time(c, mechanical)
        elif source == "custom":
            result["status"] = "MANUAL"
        else:
            result["status"] = "SKIP"

        results.append(result)

    return results


# ─── Output ──────────────────────────────────────────────────────────────────

def format_text_report(results: list[dict]) -> str:
    """Format human-readable rubric evaluation report."""
    lines = []
    lines.append(f"{'=' * 56}")
    lines.append("  RUBRIC EVALUATION")
    lines.append(f"{'=' * 56}")
    lines.append("")

    # Group by category
    categories = {}
    for r in results:
        cat = r.get("category", "general")
        categories.setdefault(cat, []).append(r)

    blocking_pass = True
    advisory_pass = True

    for cat, items in categories.items():
        lines.append(f"  {cat.upper()}:")
        for item in items:
            status = item["status"]
            blocking = item["blocking"]
            tag = "BLOCK" if blocking else "ADVSR"
            icon = "PASS" if status == "PASS" else (
                "SKIP" if status in ("SKIP", "MANUAL") else "FAIL"
            )
            lines.append(f"    {icon}  [{tag}] {item['name']}")

            if status == "FAIL" and blocking:
                blocking_pass = False
            if status == "FAIL" and not blocking:
                advisory_pass = False

        lines.append("")

    all_pass = blocking_pass and advisory_pass
    lines.append(f"{'─' * 56}")
    lines.append(f"BLOCKING: {'PASS' if blocking_pass else 'FAIL'}")
    lines.append(f"ADVISORY: {'PASS' if advisory_pass else 'FAIL'}")
    lines.append(f"OVERALL:  {'PASS' if all_pass else 'FAIL'}")
    lines.append(f"{'─' * 56}")

    return "\n".join(lines)


def build_json_output(results: list[dict]) -> dict:
    """Build structured JSON output."""
    blocking_pass = all(
        r["status"] != "FAIL"
        for r in results if r["blocking"]
    )
    advisory_pass = all(
        r["status"] != "FAIL"
        for r in results if not r["blocking"]
    )
    # Remove internal 'line' field from output
    clean = []
    for r in results:
        entry = {k: v for k, v in r.items() if k != "line"}
        clean.append(entry)

    return {
        "criteria": clean,
        "blocking_pass": blocking_pass,
        "advisory_pass": advisory_pass,
        "all_pass": blocking_pass and advisory_pass,
    }


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate rubric criteria from BENCHMARKS.md (0 LLM tokens)"
    )
    parser.add_argument("--project", required=True, help="Path to project")
    parser.add_argument(
        "--mechanical", default=None,
        help="JSON file with verify_node results (array of node results)"
    )
    parser.add_argument(
        "--tests", default=None,
        help="JSON file with run_tests results (dict node→result)"
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    benchmarks_path = project / "BENCHMARKS.md"

    # Parse criteria from BENCHMARKS.md
    criteria = parse_rubric_criteria(benchmarks_path)

    if not criteria:
        # No CHECK annotations found — pass vacuously
        output = {
            "criteria": [],
            "blocking_pass": True,
            "advisory_pass": True,
            "all_pass": True,
            "warning": "No CHECK annotations found in BENCHMARKS.md",
        }
        if args.json:
            print(json.dumps(output, indent=2))
        else:
            print("RUBRIC: No CHECK annotations in BENCHMARKS.md — PASS (vacuous)")
        sys.exit(0)

    # Load mechanical results
    mechanical = []
    if args.mechanical:
        mech_path = Path(args.mechanical)
        if mech_path.exists():
            data = json.loads(mech_path.read_text(encoding="utf-8"))
            # Accept both single dict and array
            if isinstance(data, list):
                mechanical = data
            else:
                mechanical = [data]

    # Load test results
    tests = {}
    if args.tests:
        test_path = Path(args.tests)
        if test_path.exists():
            tests = json.loads(test_path.read_text(encoding="utf-8"))

    # Evaluate
    results = evaluate_criteria(criteria, mechanical, tests)

    # Output
    if args.json:
        output = build_json_output(results)
        print(json.dumps(output, indent=2))
    else:
        print(format_text_report(results))

    # Exit code based on blocking criteria
    blocking_pass = all(
        r["status"] != "FAIL"
        for r in results if r["blocking"]
    )
    sys.exit(0 if blocking_pass else 1)


if __name__ == "__main__":
    main()
