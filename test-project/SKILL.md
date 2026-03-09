---
name: test-project
description: "Testing end-to-end de proyecto Lean 4: spec audit + genera specs, escribe tests, ejecuta y produce reporte de 4 capas."
allowed-tools: [Task, Bash(python3 *), Read, Glob, Grep, Write]
argument-hint: "<project-dir> [--nodes N1.1,N2.1] [--force-generate] [--force-rewrite] [--spec-only]"
---

# Test Project: End-to-End Testing for Lean 4 Projects

Orchestrates full project testing using existing scripts. Reuses all existing material (TESTS_OUTSOURCE.md, test .lean files) unless explicitly told to regenerate.

**4 Layers of Verification:**
- **Layer 0**: Specification Hygiene — theorem statements are non-vacuous, well-formed, properly directed
- **Layer 1**: Formal Bridge — theorems compile, hypotheses have witnesses
- **Layer 2**: Properties — invariants, soundness, equivalences (SlimCheck / #eval)
- **Layer 3**: Integration — concrete behaviors, edge cases, stress tests

## Help Request Detection

If the user invokes with `?`, `--help`, `help`, show this quick reference instead of running:

```
/test-project - End-to-end testing for Lean 4 projects (4 layers)

USAGE:
  /test-project <project-dir> [options]

OPTIONS:
  --nodes N1.1,N2.1   Test only specific nodes (default: all)
  --force-generate     Regenerate TESTS_OUTSOURCE.md even if it exists
  --force-rewrite      Rewrite test .lean files even if they exist
  --spec-only          Run only Layer 0 (spec audit) + generate THEOREMS.md

EXAMPLES:
  /test-project ~/Documents/claudio/Trust-Lean
  /test-project ~/Documents/claudio/optisat --nodes N1.1,N1.2
  /test-project . --force-generate
  /test-project ~/Documents/claudio/amo-lean --spec-only

OUTPUT:
  report_{project}_{version}.md in project root
  Tests/results.json (machine-readable)
  THEOREMS.md (theorem registry for human audit)

LAYERS:
  0: Spec Hygiene   — vacuity, identity passes, weak specs, structural, non-vacuity, T5 (--deep)
  1: Formal Bridge   — #check + hypothesis witnesses + joint witnesses + canonical examples
  2: Properties      — SlimCheck / #eval invariants
  3: Integration     — concrete behavior tests

PREREQUISITES:
  - dag.json with "phases" key (from /plan-project or /tidy-project)
    NOTE: dag.json is NOT required for --spec-only mode
  - GOOGLE_API_KEY in env (only if TESTS_OUTSOURCE.md needs to be generated)
```

## Workflow

### --spec-only shortcut

If the user passes `--spec-only`, run ONLY the spec audit (Layer 0) without requiring dag.json or any other prerequisites:

```bash
python3 ~/.claude/skills/test-project/scripts/test_project.py \
  --spec-audit --project {PROJECT_DIR}
```

Read the JSON output and present:
```
/test-project --spec-only: {Project Name}

SPEC AUDIT (Layer 0):
  Theorems scanned: {total}
  T1 (vacuity, blocking): {count}
  T1.5 (identity passes, blocking): {count}
  T2 (weak specs, advisory): {count}
  T3 (structural, advisory): {count}
  T4 (no-witness, advisory): {count}
  STATUS: {PASS|FAIL}

{If T1 > 0: list T1 issues}
{If T1.5 > 0: list identity passes — these are specs that compile clean but prove nothing}
{If T2+T3 > 0: list top 5 issues}

THEOREMS.md: {path} (generated for human review)
```

Then STOP — do not continue to Paso 0/1/2/3/4/5/6.

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

### Paso 0.5: Specification Audit (Layer 0)

The Paso 0 JSON output includes a `spec_audit` key with the results. Read it and note:

- **T1 issues (vacuity)**: Report prominently — these indicate theorems that prove nothing (e.g., `theorem X : True`)
- **T1.5 issues (identity passes)**: Report prominently — definitions with `:= id` or `fun x => x` in pipeline pass fields. These compile clean but perform no transformation, hiding technical debt as formal completeness.
- **T2 issues (weak specs)**: Report as advisory — existential-only conclusions, pipeline sorry, unused params
- **T3 issues (structural)**: Report as advisory — name/conclusion mismatch, >8 hypotheses
- **T4 issues (no-witness)**: Report as advisory — theorems with ≥3 Prop hypotheses lacking non-vacuity witnesses

T1 and T1.5 issues do NOT block test execution (unlike in close_block.py) but they are highlighted in the final report.

If `spec_audit.available` is `false`, note the warning and continue — the audit is best-effort.

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

SPEC HYGIENE: {PASS|FAIL|SKIPPED} (T1:{n} T1.5:{n} T2:{n} T3:{n} T4:{n} — {total} theorems)
BRIDGE:       {PASS|FAIL|MISSING} ({N} #check, {M} witnesses)
PROPERTIES:   {pass}/{total} PASS ({nr} not runnable)
INTEGRATION:  {pass}/{total} PASS
OVERALL:      {ALL PASS | N FAILURES}

{If T1 > 0: list T1 issues (these are spec bugs, not test failures)}
{If T1.5 > 0: list identity passes (specs that compile but prove nothing)}
{If failures: list blocking failures}

Report: {path_to_report}
Results: Tests/results.json
THEOREMS.md: {path} (theorem registry)
```

## Notes

- This skill is **read-heavy**: it reuses existing material wherever possible
- The only LLM-intensive step is Paso 3 (test writing subagent). All other steps are mechanical Python scripts
- For projects that already have TESTS_OUTSOURCE.md and test files (e.g., Trust-Lean), the skill essentially just runs `run_tests.py` per node and aggregates results — fast and cheap
- The `--force-generate` and `--force-rewrite` flags exist for intentional re-generation only
- Bridge.lean is executed ONCE per project (not per node), automatically by run_tests.py
- Tests/results.json is cumulative — each run_tests.py call adds/updates the node entry
