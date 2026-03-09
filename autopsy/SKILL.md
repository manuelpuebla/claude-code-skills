---
name: autopsy
description: "Autopsia de proyecto: README claims x DAG x cobertura Lean -> propiedades SlimCheck sugeridas"
allowed-tools: [Bash(python3 *), Read, Glob, Grep, Task]
argument-hint: "<project-dir> [--suggest-properties] [--json]"
---

# Autopsy: Project Post-Mortem Audit

Audits a completed or in-progress Lean 4 project by cross-referencing README claims, ARCHITECTURE.md DAG, and source code to produce a verification gap analysis and SlimCheck property suggestions.

## Help Request Detection

If the user invokes with `?`, `--help`, `help`, show this quick reference instead of running:

```
/autopsy - Project post-mortem audit + SlimCheck property suggestions

USAGE:
  /autopsy <project-dir> [options]

OPTIONS:
  --suggest-properties   Generate SlimCheck property stubs for uncovered claims
  --json                 Output raw data as JSON (for programmatic use)

EXAMPLES:
  /autopsy ~/Documents/claudio/vr1cs-lean
  /autopsy ~/Documents/claudio/SuperTensor-lean --suggest-properties
  /autopsy . --json

OUTPUT:
  1. Project overview (LOC, theorems, sorry, axioms)
  2. Specification hygiene (T1 vacuity, T1.5 identity passes, T2-T4)
  3. README claims cross-referenced with code evidence
  4. DAG structure + completion status
  5. Coverage gaps (defs without theorems)
  6. SlimCheck property suggestions (if --suggest-properties)
  7. Risk assessment per node
  8. THEOREMS.md registry (generated)
```

## Workflow

### Paso 1: Gather mechanical data

Run the autopsy script to collect structural data:

```bash
python3 ~/.claude/skills/autopsy/scripts/autopsy.py "{PROJECT_DIR}"
```

This produces a structured report with:
- Lean code inventory (defs, theorems, sorry, axioms, #eval, @[simp], slim_check)
- DAG nodes from ARCHITECTURE.md (type, deps, status)
- README sections and claim indicators
- BENCHMARKS.md presence
- Component breakdown
- Version history

### Paso 1.5: Specification Hygiene

The autopsy script automatically runs `spec_audit.py` and produces a `── SPECIFICATION HYGIENE ──` section with:

- **T1 (vacuity, blocking)**: Theorems that prove nothing (`True`, `⊤`, tautology `a=a`)
- **T1.5 (identity passes, blocking)**: Definitions with `:= id` or `fun x => x` in pass fields, and trivial proofs (`by trivial`, `by exact True.intro`) in proof fields. These compile clean but have zero probative value.
- **T2 (weak specs, advisory)**: Existential-only conclusions, pipeline sorry, unused params
- **T3 (structural, advisory)**: Name/conclusion mismatch, >8 hypotheses
- **T4 (no-witness, advisory)**: Theorems with Prop hypotheses lacking non-vacuity witnesses. Pipeline threshold=2, default=3.
- **T5 (weak conclusion, --deep only)**: Pipeline theorems with trivially-weak conclusions (strength<=1)

If T1 or T1.5 > 0, STATUS = FAIL. The section lists all identity passes with file:line and all T4 entries.

With `--deep` mode (when available), the audit also checks:
- Semantic identity passes via Lean `rfl` (catches obfuscated identity functions)
- Dead hypotheses (Prop hypotheses not used in proof body)
- Conclusion strength scoring (T5)

The script also generates `THEOREMS.md` — a full registry of all theorems for human audit.

This data comes automatically from the script; no additional flags needed.

### Paso 2: Semantic claim analysis

Read the full README.md of the project (use Read with offset+limit if >200 lines) and identify **explicit promises**. For each claim, classify it:

| Claim Type | Example | Verifiable via |
|------------|---------|----------------|
| SOUNDNESS | "every transformation is sound" | theorem with `sound` in name |
| ZERO_SORRY | "zero sorry" | sorry count = 0 |
| PRESERVATION | "preserves semantics" | theorem with `preserv` in name |
| EQUIVALENCE | "equivalent representation" | theorem with `equiv`/`iff` |
| OPTIMIZATION | "reduces multiplications" | benchmark results or theorem |
| COMPLETENESS | "handles all cases" | pattern match exhaustiveness |
| TCB | "only Lean + Mathlib in TCB" | no external axioms |

### Paso 3: Cross-reference claims with evidence

For each README claim, check if the codebase provides supporting evidence:

1. **Direct proof**: A theorem/lemma whose name or statement matches the claim
2. **Indirect proof**: The claim follows from composition of verified components
3. **Tested only**: Covered by #eval or slim_check but no formal proof
4. **UNCOVERED**: No evidence found -- this is a **gap**

Produce a cross-reference table:

```
CLAIM CROSS-REFERENCE:
  [COVERED]   "zero sorry"                    -> sorry count = 0 confirmed
  [COVERED]   "101 verified rewrite rules"    -> 101 SoundRewriteRule instances found
  [PARTIAL]   "preserves CCS satisfaction"    -> theorem exists but has sorry
  [GAP]       "supports Plonky2/3"            -> cost model exists, no soundness theorem
```

### Paso 3.5: Hypothesis coupling analysis

The autopsy script automatically analyzes coupling between formal theorems (`*Spec.lean` files) and tests. The report includes:

- Count of `*Spec.lean` files and formal theorems found
- Whether `Tests/Bridge.lean` exists
- How many theorems have `#check` coverage in Bridge.lean
- Coupling ratio: % of spec theorems referenced in any test file
- List of uncoupled theorems (formal proofs with no test connection)

This section appears automatically in the report as `── HYPOTHESIS COUPLING ──` when `*Spec.lean` files exist. No flags needed.

### Paso 4: Suggest SlimCheck properties (if --suggest-properties)

Based on the gaps found in Paso 3, generate concrete SlimCheck property stubs. Use these heuristic rules:

**From claim type to property pattern:**

| Claim Type | SlimCheck Pattern |
|------------|-------------------|
| PRESERVATION | `example : forall (x : InputType), f (g x) = x := by slim_check` |
| EQUIVALENCE | `example : forall (x : T), repr_a x = repr_b x := by slim_check` |
| SOUNDNESS | `example : forall (e : Expr), eval env (transform e) = eval env e := by slim_check` |
| OPTIMIZATION | `example : forall (e : Expr), cost (optimize e) <= cost e := by slim_check` |
| INVARIANT | `example : forall (s : State), invariant s -> invariant (step s) := by slim_check` |

**From uncovered defs:**

For each definition without an associated theorem, suggest a basic property:
- If it returns a numeric type: boundedness, non-negativity
- If it transforms a structure: preservation of some field
- If it's a predicate: at least one positive and one negative witness

**From existing #eval:**

Each `#eval` is a manual sanity check. Convert to a SlimCheck property by generalizing the concrete values to universally quantified variables.

**Important**: Generated stubs require `import Mathlib.Testing.SlimCheck`. The types used must have `SampleableExt` and `Shrinkable` instances. For custom AST types, note that the user must implement these instances.

### Paso 5: Risk assessment

Assign a risk level to each DAG node (or component if no DAG exists):

| Risk | Criteria |
|------|----------|
| LOW | Node has theorems, zero sorry, and README claims are covered |
| MEDIUM | Node has theorems but some claims lack direct evidence, or has uncovered defs |
| HIGH | Node has sorry, or is FUND/CRIT type with uncovered claims |
| CRITICAL | FUND/CRIT node with sorry AND multiple dependents |

### Paso 6: Present final report

Output the complete autopsy in this format:

```
============================================================
 AUTOPSIA: {Project Name}
============================================================

-- OVERVIEW --
  [metrics from script output]

-- VERIFICATION STATUS --
  ZERO SORRY / N sorry pending

-- SPECIFICATION HYGIENE --
  Theorems scanned: {N}
  T1 (vacuity): {n}  T1.5 (identity passes): {n}
  T2 (weak): {n}  T3 (structural): {n}  T4 (no-witness): {n}
  STATUS: {PASS|FAIL}
  [identity passes list, T4 entries if any]
  THEOREMS.md: {path}

-- CLAIM CROSS-REFERENCE --
  [from Paso 3]

-- DAG HEALTH --
  [completion bar + node status]

-- COVERAGE GAPS --
  [uncovered defs, missing theorems]

-- HYPOTHESIS COUPLING --
  [spec files, theorems, Bridge.lean status, coupling ratio, uncoupled list]

-- RISK ASSESSMENT --
  [per node/component risk level]

-- SLIMCHECK SUGGESTIONS -- (if --suggest-properties)
  [property stubs from Paso 4]

-- RECOMMENDATIONS --
  [prioritized list of actions]
```

## Workflow Diagram

```
README.md              ARCHITECTURE.md           *.lean files
    |                       |                         |
    v                       v                         v
 CLAIMS                DAG + PHASES              INVENTORY
 (what it promises)    (structure)              (what exists)
    |                       |                         |
    +----------+------------+                         |
               |                                      |
               v                                      |
    CROSS-REFERENCE  <--------------------------------+
    (claim x evidence)
               |
               v
    +----------+----------+
    |                     |
    v                     v
 GAPS                 RISK MAP
    |                     |
    v                     v
 SLIMCHECK           RECOMMENDATIONS
 SUGGESTIONS
```

## Notes

- This skill is **read-only** -- it never modifies project files (except generating THEOREMS.md)
- For projects without ARCHITECTURE.md, it falls back to source-only analysis
- For projects without README.md, it skips claim analysis and focuses on code inventory
- The `--json` flag passes through to the script for programmatic consumption
- SlimCheck properties are **suggestions** -- they require human review for semantic correctness
- Custom AST types need `SampleableExt`/`Shrinkable` instances for SlimCheck to work
