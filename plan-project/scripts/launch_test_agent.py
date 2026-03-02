#!/usr/bin/env python3
"""Build a prompt for the testing subagent (Task tool).

Usage:
    python3 launch_test_agent.py \
        --project /path/to/project \
        --nodes '{"N2.1": ["File.lean"]}' \
        [--outsource-md /path/to/TESTS_OUTSOURCE.md]

Prints the prompt to stdout. Session A captures it and passes it to Task().
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
RUN_TESTS_PY = SCRIPTS_DIR / "run_tests.py"

PROMPT_TEMPLATE = """\
You are a Testing Engineer for a Lean 4 project. Write and execute tests.

## Rules
- You have NO access to the implementation session's context
- You CAN read source files to understand public APIs (use Read tool)
- Write tests based ONLY on the specifications below
- Execute tests and save results

## Project: {project_path}
## Nodes: {node_list}
## Source files per node:
{node_files_section}

## Tools
- Read source: Read tool on project files
- Write tests: Write tool for Tests/Properties/{{Node}}.lean, Tests/Integration/{{Node}}.lean
- Compile: Bash: lake env lean Tests/Properties/{{Node}}.lean (from {project_path})
- Run tests: Bash: python3 {run_tests_py} --project {project_path} --node {{node_id}} --json --save-results {results_path}

## Test Conventions
- Properties: import Mathlib.Testing.SlimCheck, example/theorem with slim_check
- Priority comments: -- P0, INVARIANT: description
- NOT_YET_RUNNABLE: -- NOT_YET_RUNNABLE (if SampleableExt missing)
- Integration: #eval with IO.println "[PASS] name" or "[FAIL] name"
- main : IO UInt32 returning 0 if all pass

## Workflow
For each node:
1. Read source files to understand API
2. Write Tests/Properties/{{Node}}.lean
3. Write Tests/Integration/{{Node}}.lean
4. Compile each: lake env lean Tests/{{type}}/{{Node}}.lean (from {project_path})
5. Fix compilation errors until clean
6. Run: python3 {run_tests_py} --project {project_path} --node {{node_id}} --json --save-results {results_path}

## Output
Return exactly:
---TEST-RESULTS---
OVERALL: PASS | FAIL
RESULTS_FILE: {results_path}
{node_result_placeholders}
[BLOCKING: test_name: reason (if any failures)]
---END-TEST-RESULTS---

## Test Specifications
{outsource_md_content}
"""


def build_node_files_section(nodes: dict) -> str:
    lines = []
    for node_name, files in nodes.items():
        lines.append(f"- {node_name}: {', '.join(files)}")
    return "\n".join(lines)


def build_node_result_placeholders(nodes: dict) -> str:
    lines = []
    for node_name in nodes:
        lines.append(
            f"{node_name}: PASS|FAIL - {{pass}}/{{total}} properties, "
            f"{{int_pass}}/{{int_total}} integration"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Build prompt for the testing subagent"
    )
    parser.add_argument("--project", required=True, help="Path to project")
    parser.add_argument(
        "--nodes", required=True,
        help='JSON: {"node_name": ["file1.lean", ...], ...}',
    )
    parser.add_argument(
        "--outsource-md", default=None,
        help="Path to TESTS_OUTSOURCE.md (default: {project}/TESTS_OUTSOURCE.md)",
    )
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON with prompt field")
    args = parser.parse_args()

    project = Path(args.project).resolve()

    try:
        nodes = json.loads(args.nodes)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid --nodes JSON: {e}", file=sys.stderr)
        sys.exit(2)

    if not nodes:
        print("ERROR: --nodes is empty", file=sys.stderr)
        sys.exit(2)

    # Resolve outsource md
    outsource_path = Path(args.outsource_md) if args.outsource_md else project / "TESTS_OUTSOURCE.md"
    if not outsource_path.exists():
        print(f"ERROR: {outsource_path} not found", file=sys.stderr)
        sys.exit(1)

    outsource_content = outsource_path.read_text(encoding="utf-8")
    results_path = project / "Tests" / "results.json"

    prompt = PROMPT_TEMPLATE.format(
        project_path=project,
        node_list=", ".join(nodes.keys()),
        node_files_section=build_node_files_section(nodes),
        run_tests_py=RUN_TESTS_PY,
        results_path=results_path,
        node_result_placeholders=build_node_result_placeholders(nodes),
        outsource_md_content=outsource_content,
    )

    if args.json:
        output = {
            "prompt": prompt,
            "project": str(project),
            "nodes": list(nodes.keys()),
            "results_path": str(results_path),
            "outsource_md": str(outsource_path),
        }
        print(json.dumps(output, indent=2))
    else:
        print(prompt)


if __name__ == "__main__":
    main()
