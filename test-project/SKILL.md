---
name: test-project
description: "Testing end-to-end de proyecto Lean 4: genera specs, escribe tests, ejecuta y produce reporte de 3 capas."
allowed-tools: [Task, Bash(python3 *), Read, Glob, Grep, Write]
argument-hint: "<project-dir> [--nodes N1.1,N2.1] [--force-generate] [--force-rewrite]"
---

# Test Project: End-to-End Testing for Lean 4 Projects

Orchestrates full project testing using existing scripts. Reuses all existing material (TESTS_OUTSOURCE.md, test .lean files) unless explicitly told to regenerate.

## Help Request Detection

If the user invokes with `?`, `--help`, `help`, show this quick reference instead of running:

```
/test-project - End-to-end testing for Lean 4 projects

USAGE:
  /test-project <project-dir> [options]

OPTIONS:
  --nodes N1.1,N2.1   Test only specific nodes (default: all)
  --force-generate     Regenerate TESTS_OUTSOURCE.md even if it exists
  --force-rewrite      Rewrite test .lean files even if they exist

EXAMPLES:
  /test-project ~/Documents/claudio/Trust-Lean
  /test-project ~/Documents/claudio/optisat --nodes N1.1,N1.2
  /test-project . --force-generate

OUTPUT:
  report_{project}_{version}.md in project root
  Tests/results.json (machine-readable)

PREREQUISITES:
  - dag.json with "phases" key (from /plan-project or /tidy-project)
  - GOOGLE_API_KEY in env (only if TESTS_OUTSOURCE.md needs to be generated)
```

## Workflow

### Paso 0: Validate prerequisites

Run the check script:

```bash
python3 ~/.claude/skills/test-project/scripts/test_project.py \
  --check --project {PROJECT_DIR}
```

Read the JSON output. Exit codes:
- **0**: Ready — outsource + all test .lean files exist. Go to Paso 4.
- **1**: Outsource exists but some test .lean files are missing. Go to Paso 2.
- **2**: Outsource missing, GOOGLE_API_KEY available. Go to Paso 1.
- **3**: Fatal — missing dag.json entirely or dag.json has neither `phases` nor `declarations`. Report error and STOP.
- **4**: Outsource exists but has format errors (strict validation). Go to Paso 1 with --force-generate.

The script supports TWO dag.json formats:
- **Planning format** (has `phases` key): Used directly with explicit nodes and phases.
- **Declaration format** (has `declarations` + `graph_edges`): Automatically converted to virtual phases by grouping declarations by file and topological-sorting. A warning is emitted suggesting `/tidy-project` for proper planning phases.

If `outsource_validation` in the JSON output has `"valid": false`, report the specific errors from `outsource_validation.errors` and suggest `--force-generate`.

If exit code 3, inform the user:
- "dag.json not found" → suggest running `/plan-project` or `/tidy-project` first
- "dag.json has neither phases nor declarations" → suggest `/tidy-project`
- "No outsource + no API key" → suggest setting `GOOGLE_API_KEY` or creating TESTS_OUTSOURCE.md manually

### Paso 1: Generate TESTS_OUTSOURCE.md (ONLY if missing or --force-generate)

SKIP this step if TESTS_OUTSOURCE.md already exists and --force-generate was NOT passed.

```bash
python3 ~/.claude/skills/plan-project/scripts/generate_tests.py \
  --project {PROJECT_DIR} --all
```

This calls Gemini 2.5 Pro and produces TESTS_OUTSOURCE.md with:
- Per-node property specs (SlimCheck)
- Per-node integration test specs
- Formal Bridge Requirements (if *Spec.lean files exist)

If this fails (API error, timeout), report the error and STOP.

### Paso 2: Detect which tests already exist

From the Paso 0 output, read `existing_test_files` to identify which nodes already have test .lean files.

Decision tree:
- **All nodes have tests** AND NOT --force-rewrite → Go to Paso 4
- **Some nodes have tests** AND NOT --force-rewrite → Go to Paso 3 with ONLY the missing nodes
- **No nodes have tests** OR --force-rewrite → Go to Paso 3 with ALL nodes

### Paso 3: Write missing tests (via subagent)

Build the nodes JSON for only the nodes that need tests:

```bash
python3 ~/.claude/skills/plan-project/scripts/launch_test_agent.py \
  --project {PROJECT_DIR} \
  --nodes '{nodes_json}' --json
```

Capture the `prompt` field from the JSON output. Then launch ONE subagent:

```
Task(subagent_type="general-purpose"):
"{captured_prompt}"
```

The subagent will:
1. Read TESTS_OUTSOURCE.md specs and source files
2. Write Tests/Bridge.lean (if Bridge Requirements section exists)
3. Write Tests/Properties/{Node}.lean and Tests/Integration/{Node}.lean per node
4. Compile each file until it works (up to 5 attempts per file)
5. Execute run_tests.py per node with --save-results

Wait for the subagent to complete. If it times out, note which nodes were completed (check Tests/results.json) and report partial results.

### Paso 4: Execute tests

For each node that needs execution (not already in Tests/results.json from Paso 3):

```bash
python3 ~/.claude/skills/plan-project/scripts/run_tests.py \
  --project {PROJECT_DIR} --node {NODE_ID} \
  --save-results {PROJECT_DIR}/Tests/results.json
```

If the subagent already ran run_tests.py and Tests/results.json has fresh data for a node, SKIP re-execution for that node.

Run nodes sequentially. Each call appends to Tests/results.json.

### Paso 5: Generate report

```bash
python3 ~/.claude/skills/test-project/scripts/test_project.py \
  --aggregate --project {PROJECT_DIR}
```

This reads Tests/results.json + dag.json + ARCHITECTURE.md and produces `report_{project}_{version}.md` in the project root. Read the output to know the report path.

### Paso 6: Present results

Read the generated report file and present a concise summary to the user:

```
/test-project: {Project Name} v{version}

BRIDGE:       {PASS|FAIL|MISSING} ({N} #check, {M} witnesses)
PROPERTIES:   {pass}/{total} PASS ({nr} not runnable)
INTEGRATION:  {pass}/{total} PASS
OVERALL:      {ALL PASS | N FAILURES}

{If failures: list blocking failures}

Report: {path_to_report}
Results: Tests/results.json
```

## Notes

- This skill is **read-heavy**: it reuses existing material wherever possible
- The only LLM-intensive step is Paso 3 (test writing subagent). All other steps are mechanical Python scripts
- For projects that already have TESTS_OUTSOURCE.md and test files (e.g., Trust-Lean), the skill essentially just runs `run_tests.py` per node and aggregates results — fast and cheap
- The `--force-generate` and `--force-rewrite` flags exist for intentional re-generation only
- Bridge.lean is executed ONCE per project (not per node), automatically by run_tests.py
- Tests/results.json is cumulative — each run_tests.py call adds/updates the node entry
