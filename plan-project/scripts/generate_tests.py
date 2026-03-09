#!/usr/bin/env python3
"""generate_tests.py — Genera TESTS_OUTSOURCE.md (especificaciones de test).

Invoca Gemini 2.5 Pro como "Senior QA Architect for Lean 4" para diseñar
qué tests escribir, con qué prioridad, y qué propiedades verificar.

NO genera código Lean. El código lo escribe otra sesión de Claude Code
que lee TESTS_OUTSOURCE.md y usa el tooling de Lean (compilador, ask-lean,
ask-dojo) para producir archivos .lean compilables.

Uso:
  python3 generate_tests.py --project PATH --all
  python3 generate_tests.py --project PATH --node N2.1
  python3 generate_tests.py --project PATH --all --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCOUT_SCRIPT = Path(__file__).parent / "scout.py"
DEFAULT_MODEL = "gemini-2.5-pro"


# ─── Gemini Client (reuses pattern from collab.py) ──────────────────────────

def create_client():
    """Create Google GenAI client with API key."""
    try:
        from google import genai
    except ImportError:
        print("ERROR: google-genai not installed. Run: pip install google-genai",
              file=sys.stderr)
        sys.exit(1)

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
        print("Set GOOGLE_API_KEY env var or add to ~/.env", file=sys.stderr)
        sys.exit(1)

    return genai.Client(api_key=api_key)


def query_gemini(client, prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Query Gemini and return text response."""
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "temperature": 0.3,
                "max_output_tokens": 8192,
            },
        )
        if response is None or response.text is None:
            return "ERROR: Gemini returned no response"
        return response.text
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


# ─── Project Analysis ────────────────────────────────────────────────────────

def load_dag(project: Path) -> dict:
    """Load dag.json from project."""
    dag_path = project / "dag.json"
    if not dag_path.exists():
        print(f"ERROR: dag.json not found at {dag_path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(dag_path.read_text(encoding="utf-8"))


def get_node_info(dag: dict, node_id: str) -> dict | None:
    """Get node info from dag by ID."""
    for phase in dag.get("phases", []):
        for node in phase.get("nodes", []):
            if node["id"] == node_id:
                return node
    return None


def get_all_nodes(dag: dict) -> list[dict]:
    """Get all nodes from dag."""
    nodes = []
    for phase in dag.get("phases", []):
        for node in phase.get("nodes", []):
            nodes.append(node)
    return nodes


def load_benchmarks_properties(project: Path) -> dict:
    """Load Formal Properties section from BENCHMARKS.md.

    Returns dict: node_id -> stub text.
    """
    bench_path = project / "BENCHMARKS.md"
    if not bench_path.exists():
        return {}

    content = bench_path.read_text(encoding="utf-8")
    properties = {}

    in_props = False
    current_node = None
    current_code = []
    in_code_block = False

    for line in content.splitlines():
        stripped = line.strip()

        if stripped.startswith("## Formal Properties"):
            in_props = True
            continue
        if in_props and stripped.startswith("## ") and "Formal Properties" not in stripped:
            break
        if in_props and stripped == "---":
            break
        if not in_props:
            continue

        if stripped.startswith("### "):
            if current_node and current_code:
                properties[current_node] = "\n".join(current_code)
            header = stripped[4:]
            node_match = re.match(r"([A-Z]\d+\.\d+)", header)
            current_node = node_match.group(1) if node_match else header
            current_code = []
            continue

        if stripped.startswith("```lean"):
            in_code_block = True
            continue
        if stripped == "```":
            in_code_block = False
            continue
        if in_code_block and current_node:
            current_code.append(line)

    if current_node and current_code:
        properties[current_node] = "\n".join(current_code)

    return properties


def load_rubric_criteria(project: Path) -> str:
    """Load rubric criteria text from BENCHMARKS.md."""
    bench_path = project / "BENCHMARKS.md"
    if not bench_path.exists():
        return ""

    content = bench_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    in_criteria = False
    criteria_lines = []

    for line in lines:
        if line.strip().startswith("## Criteria"):
            in_criteria = True
            continue
        if in_criteria and line.strip() == "---":
            break
        if in_criteria:
            criteria_lines.append(line)

    return "\n".join(criteria_lines)


def run_scout(project: Path, files: list[str]) -> str:
    """Run scout.py to get code signatures."""
    resolved = []
    for f in files:
        fpath = project / f
        if fpath.exists():
            resolved.append(str(fpath))

    if not resolved:
        return "(archivos aún no existen — se crearán durante implementación)"

    cmd = [sys.executable, str(SCOUT_SCRIPT)] + resolved
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        return result.stdout[:4000]
    except Exception as e:
        return f"(scout error: {e})"


def detect_mathlib(project: Path) -> bool:
    """Check if project uses Mathlib."""
    for lakefile in ("lakefile.toml", "lakefile.lean"):
        path = project / lakefile
        if path.exists():
            content = path.read_text(encoding="utf-8").lower()
            if "mathlib" in content:
                return True
    return False


def read_toolchain(project: Path) -> str:
    """Read lean-toolchain file."""
    tc_path = project / "lean-toolchain"
    if tc_path.exists():
        return tc_path.read_text(encoding="utf-8").strip()
    return "unknown"


def scan_spec_theorems(project: Path) -> list[dict]:
    """Scan *Spec.lean files for formal theorems and their hypotheses.

    Returns list of dicts: {name, file, hypotheses: [str]}.
    """
    specs = []
    for lean_file in sorted(project.rglob("*.lean")):
        if ".lake" in str(lean_file):
            continue
        if not lean_file.stem.endswith("Spec"):
            continue
        rel = str(lean_file.relative_to(project))
        try:
            content = lean_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in re.finditer(
            r"^(theorem|lemma)\s+(\w+)", content, re.MULTILINE,
        ):
            name = m.group(2)
            # Extract hypothesis types: (hXxx : TypeName) patterns
            sig_start = m.start()
            sig_end = content.find(":=", sig_start)
            if sig_end == -1:
                sig_end = content.find("by", sig_start)
            if sig_end == -1:
                sig_end = min(sig_start + 500, len(content))
            sig = content[sig_start:sig_end]
            hyps = re.findall(r"\(h\w*\s*:\s*(\w+)", sig)
            specs.append({"name": name, "file": rel, "hypotheses": hyps})
    return specs


# ─── Spec Generation ────────────────────────────────────────────────────────

SPEC_PROMPT = """You are a Senior QA Architect designing a test plan for a Lean 4 project.

You do NOT write Lean code. You design test SPECIFICATIONS that another engineer
(with full compiler access) will implement as compilable .lean files.

## Node Information
- ID: {node_id}
- Name: {node_name}
- Type: {node_type} (FUNDACIONAL = core dependency / CRITICO = many dependents / PARALELO = independent / HOJA = leaf)
- Files: {files}

## Code Signatures (current state)
{signatures}

## Existing Property Stubs (from planning, may be outdated)
{stubs}

## Rubric Criteria
{rubric}

## Project uses Mathlib: {has_mathlib}

## Formal Theorems in *Spec.lean files
{spec_theorems_text}

## COUPLING REQUIREMENT (MANDATORY for Lean 4 formal projects)
If formal theorems exist above, you MUST add a BRIDGE section at the end of your output:
1. For each formal theorem relevant to this node, specify a #check statement
2. For each hypothesis Prop, indicate if it can be IO-checked (Decidable) or needs a proof witness
3. For integration tests exercising formally-verified functions, specify semantic equivalence checks

Use this format:
```
BRIDGE:
- [B1] CHECK: #check @theorem_name ConcreteType1 ConcreteType2
- [B2] WITNESS: hypothesis_type — egraph_empty_wf or similar witness theorem
- [B3] SEMANTIC: evalExpr extracted_expr env == expected_value
```
If no formal theorems exist for this node, write: `BRIDGE: (none — no formal specs for this node)`

## Your Task

Design two categories of tests for this node:

### A. Property Tests (SlimCheck)
For each property, specify:
1. **ID**: P1, P2, P3...
2. **Priority**: P0 (blocking — must pass) / P1 (important) / P2 (nice-to-have)
3. **Type**: INVARIANT / SOUNDNESS / EQUIVALENCE / PRESERVATION / IDEMPOTENCY / COMMUTATIVITY
4. **Description**: What the property checks, in plain language
5. **Signature sketch**: Approximate Lean statement (the implementer will fix types/imports)
6. **SampleableExt needed?**: Does the type need a custom sampling instance?
7. **Risk if missing**: What bug class this property catches

Heuristics by node type:
- FUNDACIONAL → invariants, commutativity, idempotency, representation correctness
- CRITICO → soundness, preservation (transformations preserve semantics)
- PARALELO → equivalence between representations, consistency
- HOJA → output properties (bounds, non-negativity, format)

### B. Integration Tests (#eval)
For each test, specify:
1. **ID**: T1, T2, T3...
2. **Category**: BASIC / EDGE_CASE / STRESS / REGRESSION
3. **Description**: What scenario is tested
4. **Setup**: What data/state to construct
5. **Expected behavior**: What the test checks (exact value, property, non-crash)
6. **Boundary conditions**: Specific values to use (empty, zero, max, single-element)

Cover at minimum:
- Happy path (basic functionality works)
- Empty/zero/nil inputs
- Single-element cases
- Maximum-size or boundary cases
- Known tricky scenarios for this algorithm/structure

### Output Format

Use EXACTLY this format (the implementer's tooling parses it):

```
PROPERTIES:
- [P1] P0 INVARIANT: description
  Sketch: example (x : Type) : property x := by slim_check
  SampleableExt: yes/no
  Risk: what bug class

- [P2] P1 EQUIVALENCE: description
  Sketch: example (a b : Type) : f a b = g a b := by slim_check
  SampleableExt: no
  Risk: what bug class

INTEGRATION:
- [T1] BASIC: description
  Setup: construct X with values ...
  Check: result should equal / satisfy ...

- [T2] EDGE_CASE: description
  Setup: empty input / zero / boundary
  Check: should not crash, should return ...

- [T3] STRESS: description
  Setup: large input (N=1000)
  Check: completes without timeout, result satisfies ...
```"""


def _format_spec_theorems(spec_theorems: list[dict], node_files: list[str]) -> str:
    """Format spec theorems relevant to a node for prompt injection."""
    if not spec_theorems:
        return "(no *Spec.lean files found in project)"
    # Filter to theorems whose file shares a prefix with node files
    node_stems = set()
    for f in node_files:
        stem = Path(f).stem.replace("Spec", "").replace("spec", "")
        node_stems.add(stem.lower())
    relevant = [
        t for t in spec_theorems
        if any(s in Path(t["file"]).stem.lower() for s in node_stems)
    ]
    if not relevant:
        relevant = spec_theorems  # fallback: show all
    lines = []
    for t in relevant[:20]:
        hyps = ", ".join(t["hypotheses"]) if t["hypotheses"] else "(none)"
        lines.append(f"- {t['name']} ({t['file']}) — hypotheses: {hyps}")
    return "\n".join(lines) if lines else "(none found)"


def generate_node_spec(
    client, node: dict, signatures: str,
    stubs: str, rubric: str, has_mathlib: bool,
    spec_theorems: list[dict] | None = None,
) -> dict:
    """Generate test specifications for a single node via Gemini."""
    node_id = node["id"]
    node_name = node.get("name", node_id)
    node_type = node.get("type", "HOJA")
    files = node.get("files", [])

    spec_theorems_text = _format_spec_theorems(
        spec_theorems or [], files,
    )

    prompt = SPEC_PROMPT.format(
        node_id=node_id, node_name=node_name, node_type=node_type,
        files=", ".join(files), signatures=signatures,
        stubs=stubs or "(none defined yet)",
        rubric=rubric or "(none defined yet)",
        has_mathlib="Yes" if has_mathlib else "No",
        spec_theorems_text=spec_theorems_text,
    )

    print(f"  Designing specs for {node_id}...", file=sys.stderr)
    response = query_gemini(client, prompt)

    if response.startswith("ERROR:"):
        return {"node": node_id, "error": response, "spec": ""}

    # Parse counts from response
    prop_count = len(re.findall(r"\[P\d+\]", response))
    test_count = len(re.findall(r"\[T\d+\]", response))
    p0_count = len(re.findall(r"\]\s*P0\s", response))

    return {
        "node": node_id,
        "spec": response,
        "counts": {
            "properties": prop_count,
            "p0_properties": p0_count,
            "integration_tests": test_count,
        },
    }


# ─── TESTS_OUTSOURCE.md ─────────────────────────────────────────────────────

def write_outsource_md(
    project: Path, dag: dict,
    specs: list[dict], rubric_text: str,
    has_mathlib: bool,
    spec_theorems: list[dict] | None = None,
):
    """Write TESTS_OUTSOURCE.md — self-contained spec for the testing session."""
    outsource_path = project / "TESTS_OUTSOURCE.md"
    toolchain = read_toolchain(project)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    project_name = dag.get("project", project.name)
    version = dag.get("version", "?")

    lines = []

    # ── Header ──
    lines.append(f"# Test Specifications: {project_name} {version}")
    lines.append("")
    lines.append(f"Generated: {now}")
    lines.append(f"Project: {project}")
    lines.append(f"Toolchain: {toolchain}")
    lines.append(f"Mathlib: {'yes' if has_mathlib else 'no'}")
    lines.append("")
    lines.append("> **Este archivo es leído por otra sesión de Claude Code que escribe")
    lines.append("> los archivos .lean de test. NO contiene código compilable.**")
    lines.append("")

    # ── Instructions for the testing session ──
    lines.append("## Instrucciones para la sesión de testing")
    lines.append("")
    lines.append("1. Leer este archivo completo")
    lines.append("2. Para cada nodo, leer el código fuente real (`scout.py` + `Read`)")
    lines.append("3. Escribir `Tests/Properties/{NodeName}.lean` con las propiedades especificadas")
    lines.append("4. Escribir `Tests/Integration/{NodeName}.lean` con los integration tests")
    lines.append("5. Compilar cada archivo con `lake env lean Tests/.../*.lean` hasta que pase")
    lines.append("6. Usar `/ask-lean` o `/ask-dojo` si faltan tácticas o instancias")
    lines.append("")
    lines.append("### Convenciones obligatorias")
    lines.append("")
    lines.append("**Properties** (`Tests/Properties/{Name}.lean`):")
    lines.append("- `import Mathlib.Testing.SlimCheck` (si Mathlib disponible)")
    lines.append("- Cada propiedad como `example` o `theorem` con `slim_check` tactic")
    lines.append("- Comentario con prioridad: `-- P0, INVARIANT: descripción`")
    lines.append("- Si un tipo necesita `SampleableExt` y no existe: `-- NOT_YET_RUNNABLE`")
    lines.append("")
    lines.append("**Integration** (`Tests/Integration/{Name}.lean`):")
    lines.append("- Cada test imprime `[PASS] nombre` o `[FAIL] nombre`")
    lines.append("- Función `main : IO UInt32` que retorna 0 si todo pasa, 1 si hay fallos")
    lines.append("- Pattern: `def T1_name : IO Bool := do ...`")
    lines.append("")
    lines.append("### Ejecución (la hace la sesión implementadora)")
    lines.append("")
    lines.append("```bash")
    lines.append("# La sesión implementadora ejecuta:")
    lines.append("python3 ~/.claude/skills/plan-project/scripts/close_block.py \\")
    lines.append("  --project PATH --block \"Bloque N\" --nodes '{...}'")
    lines.append("# Que internamente corre: lake env lean Tests/Properties/*.lean")
    lines.append("#                         lake env lean Tests/Integration/*.lean")
    lines.append("```")
    lines.append("")

    # ── Rubric ──
    if rubric_text:
        lines.append("## Criterios de rúbrica (de BENCHMARKS.md)")
        lines.append("")
        lines.append(rubric_text)
        lines.append("")

    # ── Per-node specs ──
    lines.append("---")
    lines.append("")
    lines.append("## Especificaciones por nodo")
    lines.append("")

    total_props = 0
    total_tests = 0
    total_p0 = 0

    for spec in specs:
        node_id = spec["node"]
        node_info = get_node_info(dag, node_id)
        node_name = node_info.get("name", node_id) if node_info else node_id
        node_type = node_info.get("type", "?") if node_info else "?"
        node_files = node_info.get("files", []) if node_info else []

        counts = spec.get("counts", {})
        total_props += counts.get("properties", 0)
        total_tests += counts.get("integration_tests", 0)
        total_p0 += counts.get("p0_properties", 0)

        # Clean name for target filenames
        name_part = re.sub(r"^[A-Z]\d+\.\d+\s*", "", node_name).strip()
        if not name_part:
            name_part = node_id.replace(".", "")
        node_clean = name_part.replace("-", "").replace(" ", "")

        lines.append(f"### {node_id} — {node_name}")
        lines.append("")
        lines.append(f"- **Tipo**: {node_type}")
        lines.append(f"- **Archivos fuente**: {', '.join(f'`{f}`' for f in node_files)}")
        lines.append(f"- **Target properties**: `Tests/Properties/{node_clean}.lean`")
        lines.append(f"- **Target integration**: `Tests/Integration/{node_clean}.lean`")
        lines.append(f"- **Properties**: {counts.get('properties', '?')} "
                     f"({counts.get('p0_properties', '?')} P0)")
        lines.append(f"- **Integration tests**: {counts.get('integration_tests', '?')}")
        lines.append("")

        if spec.get("error"):
            lines.append(f"> ERROR generando spec: {spec['error']}")
            lines.append("")
        elif spec.get("spec"):
            lines.append(spec["spec"])
            lines.append("")

        lines.append("---")
        lines.append("")

    # ── Summary ──
    lines.append("## Resumen")
    lines.append("")
    lines.append(f"| Métrica | Total |")
    lines.append(f"|---------|-------|")
    lines.append(f"| Nodos | {len(specs)} |")
    lines.append(f"| Properties | {total_props} ({total_p0} P0) |")
    lines.append(f"| Integration tests | {total_tests} |")
    lines.append(f"| Archivos .lean a crear | {len(specs) * 2} |")
    lines.append("")

    # ── Formal Bridge Requirements ──
    if spec_theorems:
        lines.append("---")
        lines.append("")
        lines.append("## Formal Bridge Requirements")
        lines.append("")
        lines.append("The testing session **MUST** create `Tests/Bridge.lean` that verifies")
        lines.append("formal theorems apply to the concrete test domain.")
        lines.append("")
        lines.append("### Theorems to instantiate (#check)")
        lines.append("")
        lines.append("| Theorem | Source | #check statement |")
        lines.append("|---------|--------|-----------------|")
        for t in spec_theorems:
            lines.append(
                f"| `{t['name']}` | `{t['file']}` "
                f"| `#check @{t['name']}` |"
            )
        lines.append("")
        # Collect unique hypothesis types
        all_hyps = set()
        for t in spec_theorems:
            all_hyps.update(t["hypotheses"])
        if all_hyps:
            lines.append("### Hypothesis types found")
            lines.append("")
            for h in sorted(all_hyps):
                lines.append(
                    f"- `{h}` — verify this holds for the concrete test domain"
                )
            lines.append("")
        lines.append("### Bridge.lean template")
        lines.append("")
        lines.append("```lean")
        lines.append("-- Tests/Bridge.lean — Formal coupling verification")
        lines.append("import <ProjectLib>  -- replace with actual import")
        lines.append("")
        lines.append("-- Layer 1a: Verify theorems apply to concrete domain")
        for t in spec_theorems[:15]:
            lines.append(f"#check @{t['name']}")
        lines.append("")
        lines.append("-- Layer 1b: Joint witnesses (CRITICAL for pipeline theorems)")
        lines.append("-- For each pipeline theorem with >=2 Prop hypotheses,")
        lines.append("-- apply it with ALL hypotheses discharged on concrete values:")
        lines.append("-- example : <conclusion> := theorem_name concrete_val (proof_h1) (proof_h2)")
        lines.append("")
        lines.append("-- Layer 1c: Individual witnesses (for complex single hypotheses)")
        lines.append("-- theorem bridge_xxx : HypType := ...")
        lines.append("```")
        lines.append("")

        # Canonical examples section for pipeline theorems
        pipeline_thms = [t for t in spec_theorems if any(
            kw in t["name"].lower() for kw in
            ("sound", "correct", "pipeline", "e2e", "bridge", "preserv")
        )]
        if pipeline_thms:
            lines.append("### Canonical Examples")
            lines.append("")
            lines.append("For each pipeline theorem below, the testing session should write")
            lines.append("at least one `#eval` in `Tests/Integration/` demonstrating the")
            lines.append("theorem's conclusion with concrete values.")
            lines.append("")
            for t in pipeline_thms[:10]:
                lines.append(f"- **`{t['name']}`**: Construct concrete inputs satisfying "
                             f"hypotheses and show the conclusion holds via `#eval`")
            lines.append("")

    outsource_path.write_text("\n".join(lines), encoding="utf-8")
    return str(outsource_path)


# ─── DAG Update ──────────────────────────────────────────────────────────────

def update_dag_properties(project: Path, dag: dict, node_id: str, counts: dict):
    """Update dag.json node properties counters from spec counts."""
    for phase in dag.get("phases", []):
        for node in phase.get("nodes", []):
            if node["id"] == node_id:
                if "properties" not in node:
                    node["properties"] = {
                        "total": 0, "passing": 0,
                        "failing": 0, "not_runnable": 0,
                    }
                node["properties"]["total"] = counts.get("properties", 0)
                break

    dag_path = project / "dag.json"
    dag_path.write_text(json.dumps(dag, indent=2), encoding="utf-8")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate test specifications (TESTS_OUTSOURCE.md) via Gemini"
    )
    parser.add_argument("--project", required=True, help="Path to project")
    parser.add_argument("--node", default=None, help="Specific node ID (e.g., N2.1)")
    parser.add_argument("--all", action="store_true", help="Generate for all nodes")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be generated")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    if not args.node and not args.all:
        print("ERROR: Specify --node NODE_ID or --all", file=sys.stderr)
        sys.exit(2)

    project = Path(args.project).resolve()
    dag = load_dag(project)
    has_mathlib = detect_mathlib(project)
    rubric_text = load_rubric_criteria(project)
    properties = load_benchmarks_properties(project)
    spec_theorems = scan_spec_theorems(project)

    # Determine nodes to process
    if args.all:
        nodes = get_all_nodes(dag)
    else:
        node_info = get_node_info(dag, args.node)
        if not node_info:
            print(f"ERROR: Node {args.node} not found in dag.json", file=sys.stderr)
            sys.exit(1)
        nodes = [node_info]

    if args.dry_run:
        print(f"Would generate specs for {len(nodes)} nodes:")
        for n in nodes:
            print(f"  {n['id']} {n.get('name', '')} ({n.get('type', '?')})")
        print(f"Output: TESTS_OUTSOURCE.md")
        sys.exit(0)

    # Create Gemini client
    client = create_client()

    # Generate specs per node
    all_specs = []
    for node in nodes:
        node_id = node["id"]
        stubs = properties.get(node_id, "")
        signatures = run_scout(project, node.get("files", []))

        spec = generate_node_spec(
            client, node, signatures, stubs, rubric_text, has_mathlib,
            spec_theorems=spec_theorems,
        )
        all_specs.append(spec)

        # Update dag.json property counts
        if spec.get("counts"):
            update_dag_properties(project, dag, node_id, spec["counts"])

    # Write TESTS_OUTSOURCE.md
    outsource_file = write_outsource_md(
        project, dag, all_specs, rubric_text, has_mathlib,
        spec_theorems=spec_theorems,
    )
    print(f"Generated: {outsource_file}", file=sys.stderr)

    # Output
    output = {
        "outsource_file": outsource_file,
        "nodes": len(all_specs),
        "total_properties": sum(
            s.get("counts", {}).get("properties", 0) for s in all_specs
        ),
        "total_p0": sum(
            s.get("counts", {}).get("p0_properties", 0) for s in all_specs
        ),
        "total_integration": sum(
            s.get("counts", {}).get("integration_tests", 0) for s in all_specs
        ),
        "errors": [s["error"] for s in all_specs if s.get("error")],
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"\nTESTS_OUTSOURCE.md: {outsource_file}")
        print(f"Nodos: {output['nodes']}")
        print(f"Properties: {output['total_properties']} ({output['total_p0']} P0)")
        print(f"Integration: {output['total_integration']}")
        if output["errors"]:
            print(f"Errors: {len(output['errors'])}")
            for e in output["errors"]:
                print(f"  {e}")

    sys.exit(1 if output["errors"] else 0)


if __name__ == "__main__":
    main()
