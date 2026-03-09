#!/usr/bin/env python3
"""
spec_audit.py — Specification Audit for Lean 4 Projects

Extracts all theorem/lemma statements, detects specification anti-patterns,
and generates a THEOREMS.md registry for human review.

Integration points:
  - Standalone:    python3 spec_audit.py --project /path/to/lean-project
  - close_block:   imported as module, called between verify_node and run_tests
  - BENCHMARKS.md: results feed into <!-- CHECK:spec:blocking --> criteria

Three tiers of checks:
  Tier 1 — Vacuity:      conclusion is True, trivial, or tautological
  Tier 2 — Weak specs:   unused params (_prefix), overly strong hypotheses
  Tier 3 — Structural:   direction analysis, chain completeness, existential-only conclusions

Exit code: 0 = all checks pass, 1 = blocking issues found, 2 = advisory warnings only
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ════════════════════════════════════════════════════════════
# Data structures
# ════════════════════════════════════════════════════════════

@dataclass
class TheoremEntry:
    """A single theorem/lemma extracted from source."""
    name: str
    kind: str               # "theorem" or "lemma"
    module: str              # Lean module name (from file path)
    file: str                # relative file path
    line: int                # line number (1-indexed)
    signature: str           # full type signature (params + conclusion)
    conclusion: str          # just the conclusion (after the last `:`)
    hypotheses: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tier: int = 0            # highest warning tier (0 = clean)
    is_pipeline: bool = False
    has_sorry: bool = False
    conclusion_strength: int = -1      # T5: -1 = not evaluated, 0-5 = strength score
    conclusion_strength_label: str = ""
    dead_hypotheses: list[str] = field(default_factory=list)  # --deep: hyps unused in proof


@dataclass
class IdentityPassEntry:
    """A definition identified as an identity pass (no-op in a pipeline)."""
    name: str
    module: str
    file: str
    line: int
    field_name: str          # e.g., "passR1CS", "transform", "optimizeExpr"
    pattern: str             # e.g., ":= id", "fun _ w => w"


@dataclass
class AuditResult:
    """Aggregated audit result for a project."""
    project: str
    total_theorems: int = 0
    total_lemmas: int = 0
    pipeline_count: int = 0
    tier1_issues: int = 0    # vacuity
    tier15_issues: int = 0   # identity passes (no-op pipeline steps)
    tier2_issues: int = 0    # weak specs
    tier3_issues: int = 0    # structural
    tier4_issues: int = 0    # no-witness (non-vacuity)
    tier5_issues: int = 0    # weak conclusion (--deep only)
    clean_count: int = 0
    identity_passes: list[IdentityPassEntry] = field(default_factory=list)
    entries: list[TheoremEntry] = field(default_factory=list)
    all_pass: bool = True
    deep_mode: bool = False
    dead_hypothesis_count: int = 0
    text_report: str = ""


# ════════════════════════════════════════════════════════════
# Extraction
# ════════════════════════════════════════════════════════════

# Keywords that suggest a theorem is a pipeline/important theorem
PIPELINE_KEYWORDS = {
    "pipeline", "sound", "correct", "main", "final",
    "e2e", "end_to_end", "spec", "completeness",
    "bridge", "contract", "roundtrip", "preservation",
}

# T4 thresholds: pipeline theorems with 2+ Prop hyps are already risky
T4_PIPELINE_THRESHOLD = 2
T4_DEFAULT_THRESHOLD = 3

# T5 conclusion strength scores (--deep only)
CONCLUSION_STRENGTH = {
    "equality": 5,        # a = b
    "biconditional": 5,   # a <-> b
    "conjunction": 4,     # a /\ b
    "implication": 3,     # a -> b (in conclusion)
    "existential_eq": 3,  # exists x, f x = g x
    "existential": 2,     # exists x, P x
    "bound": 1,           # a >= 0, a <= b (trivially true for Nat)
    "trivial": 0,         # True, a = a
}


# ════════════════════════════════════════════════════════════
# Deep analysis helpers (--deep flag, uses Lean subprocess)
# ════════════════════════════════════════════════════════════

def _detect_project_lib(project_root: Path) -> Optional[str]:
    """Detect the main library name from lakefile.toml or lakefile.lean."""
    toml_path = project_root / "lakefile.toml"
    if toml_path.exists():
        try:
            content = toml_path.read_text(encoding="utf-8")
            # [[lean_lib]] name = "Foo"
            m = re.search(r'\[\[lean_lib\]\].*?name\s*=\s*"(\w+)"', content, re.DOTALL)
            if m:
                return m.group(1)
        except OSError:
            pass

    lean_path = project_root / "lakefile.lean"
    if lean_path.exists():
        try:
            content = lean_path.read_text(encoding="utf-8")
            # lean_lib «Foo» OR lean_lib Foo
            m = re.search(r'lean_lib\s+[«]?(\w+)[»]?', content)
            if m:
                return m.group(1)
        except OSError:
            pass

    return None


def _check_identity_via_lean(
    project_root: Path,
    lib_name: str,
    def_full_name: str,
    field_name: str,
    cache: dict,
) -> bool:
    """Check if a definition field is definitionally equal to id using Lean rfl.

    Returns True if the field IS an identity (bad), False otherwise.
    """
    cache_key = f"{def_full_name}.{field_name}"
    if cache_key in cache:
        return cache[cache_key]

    # Build a snippet that checks if the field is definitionally id
    snippet = (
        f"import {lib_name}\n"
        f"#check (show {def_full_name}.{field_name} = id from rfl)\n"
    )

    try:
        result = subprocess.run(
            ["lake", "env", "lean", "--stdin"],
            input=snippet,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(project_root),
        )
        is_id = result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        is_id = False

    cache[cache_key] = is_id
    return is_id


def _classify_conclusion_strength(conclusion: str) -> tuple[int, str]:
    """Classify the strength of a theorem conclusion. Returns (score, label)."""
    c = conclusion.strip()

    # Trivial: True, a = a pattern
    if c in ("True", "true"):
        return (0, "trivial")
    # a = a tautology
    m = re.match(r'^(\S+)\s*=\s*(\S+)$', c)
    if m and m.group(1) == m.group(2):
        return (0, "trivial")

    # Biconditional
    if " ↔ " in c or " <-> " in c or " Iff " in c:
        return (5, "biconditional")

    # Equality (strong)
    if " = " in c and " ∃ " not in c:
        return (5, "equality")

    # Conjunction
    if " ∧ " in c or " /\\ " in c or " And " in c:
        return (4, "conjunction")

    # Existential with equality
    if (" ∃ " in c or "Exists " in c) and " = " in c:
        return (3, "existential_eq")

    # Implication in conclusion
    if " → " in c or " -> " in c:
        return (3, "implication")

    # Pure existential
    if " ∃ " in c or "Exists " in c:
        return (2, "existential")

    # Bounds that are trivially true for Nat (>= 0, <= max)
    if re.search(r'[≥>]\s*0\b', c) or re.search(r'\b0\s*[≤<]', c):
        return (1, "bound")

    # Default: moderate strength (unknown structure)
    return (3, "unknown")


def _check_dead_hypotheses(
    entry: TheoremEntry,
    project_root: Path,
    lib_name: str,
) -> list[str]:
    """Check if any Prop hypothesis is dead (can be replaced by sorry).

    Only for pipeline theorems (performance). Returns list of dead hypothesis names.
    """
    if not entry.is_pipeline:
        return []

    prop_hyps = [h for h in entry.hypotheses
                 if h.startswith("h") or h.startswith("_h")]
    if len(prop_hyps) < 1:
        return []

    dead = []
    for hyp_name in prop_hyps:
        # Build a snippet that tries to use the theorem with sorry for this hypothesis
        snippet = (
            f"import {lib_name}\n"
            f"#check @{entry.module}.{entry.name}\n"
        )
        # We can't easily construct the full application,
        # but we can check if the proof mentions the hypothesis.
        # Simpler approach: search the proof body in the source for the hypothesis name.
        thm_file = project_root / entry.file
        if not thm_file.exists():
            continue

        try:
            content = thm_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        # Find the theorem and extract its proof body
        lines = content.split("\n")
        in_proof = False
        proof_body = []
        depth = 0
        for i, line in enumerate(lines):
            if i + 1 == entry.line:
                in_proof = True
                continue
            if in_proof:
                # Track brace/where depth
                stripped = line.strip()
                depth += stripped.count("{") + stripped.count("where")
                depth -= stripped.count("}")
                proof_body.append(stripped)
                # End of proof: depth back to 0 and we see a new def/theorem/end
                if depth <= 0 and (
                    stripped.startswith("theorem ") or
                    stripped.startswith("lemma ") or
                    stripped.startswith("def ") or
                    stripped.startswith("instance ") or
                    stripped == ""
                ):
                    break

        proof_text = " ".join(proof_body)
        # If hypothesis name doesn't appear in proof body, it's likely dead
        if hyp_name not in proof_text:
            dead.append(hyp_name)

    return dead


def file_to_module(file_path: Path, project_root: Path) -> str:
    """Convert file path to Lean module name."""
    rel = file_path.relative_to(project_root)
    parts = list(rel.with_suffix("").parts)
    return ".".join(parts)


def extract_theorems(project_root: Path) -> list[TheoremEntry]:
    """Extract all theorem/lemma declarations from .lean files."""
    entries: list[TheoremEntry] = []
    lean_files = sorted(project_root.rglob("*.lean"))

    for fpath in lean_files:
        # Skip lake dependencies
        rel = str(fpath.relative_to(project_root))
        if ".lake/" in rel or "lake-packages/" in rel or ".elan/" in rel:
            continue

        try:
            content = fpath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        lines = content.split("\n")
        module = file_to_module(fpath, project_root)
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Match theorem/lemma declarations
            m = re.match(
                r'^((?:(?:private|protected|noncomputable|nonrec|unsafe)\s+)*)'
                r'(theorem|lemma)\s+(\S+)',
                stripped
            )
            if not m:
                i += 1
                continue

            kind = m.group(2)
            name = m.group(3)
            start_line = i + 1  # 1-indexed

            # Collect the full signature (until := or := by or where)
            sig_lines = [stripped]
            j = i + 1
            found_body = False
            while j < len(lines):
                sline = lines[j].strip()
                if re.match(r':=\s*by\b', sline) or sline == ":= by" or sline.startswith(":= by"):
                    found_body = True
                    break
                if re.match(r':=\s', sline) or sline == ":=":
                    found_body = True
                    break
                # Check if := is at end of a line
                if sline.endswith(":= by") or sline.endswith(":="):
                    sig_lines.append(sline)
                    found_body = True
                    break
                if ":= by" in sline or (":=" in sline and "where" not in sline):
                    # := is inline — split at :=
                    before_eq = sline.split(":=")[0].strip()
                    if before_eq:
                        sig_lines.append(before_eq)
                    found_body = True
                    break
                sig_lines.append(sline)
                j += 1
                if j - i > 50:  # safety limit
                    break

            signature = "\n".join(sig_lines)

            # Extract conclusion (text after last top-level `:`)
            conclusion = _extract_conclusion(signature)

            # Extract hypotheses (parenthesized params with `:`)
            hypotheses = re.findall(r'\((\w+)\s*:', signature)

            # Check if proof uses sorry
            has_sorry = False
            for k in range(j, min(j + 100, len(lines))):
                sline = lines[k].strip()
                if re.match(r'^(theorem|lemma|def|class|instance|structure)\b', sline):
                    break
                if re.search(r'\bsorry\b', sline):
                    has_sorry = True
                    break

            # Detect pipeline importance
            name_lower = name.lower()
            is_pipeline = any(kw in name_lower for kw in PIPELINE_KEYWORDS)

            entry = TheoremEntry(
                name=name,
                kind=kind,
                module=module,
                file=rel,
                line=start_line,
                signature=signature,
                conclusion=conclusion,
                hypotheses=hypotheses,
                is_pipeline=is_pipeline,
                has_sorry=has_sorry,
            )
            entries.append(entry)
            i = j + 1

    return entries


def _extract_conclusion(signature: str) -> str:
    """Extract the conclusion (return type) from a theorem signature."""
    # Find the last `:` that's not inside parentheses/brackets
    depth = 0
    last_colon = -1
    for i, ch in enumerate(signature):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == ":" and depth == 0:
            last_colon = i

    if last_colon == -1:
        return signature.strip()

    conclusion = signature[last_colon + 1:].strip()
    # Remove trailing := by or :=
    conclusion = re.sub(r'\s*:=\s*(by\s*)?$', '', conclusion)
    return conclusion


# ════════════════════════════════════════════════════════════
# Tier 1 — Vacuity checks
# ════════════════════════════════════════════════════════════

def check_tier1(entry: TheoremEntry) -> None:
    """Detect vacuous specifications."""
    c = entry.conclusion.strip()

    # Conclusion is True
    if c == "True" or c == "⊤":
        entry.warnings.append("T1-VACUOUS: conclusion is `True` — proves nothing")
        entry.tier = max(entry.tier, 1)
        return

    # Conclusion is a = a (reflexivity)
    m = re.match(r'^(\S+)\s*=\s*(\S+)$', c)
    if m and m.group(1) == m.group(2):
        entry.warnings.append(f"T1-TAUTOLOGY: conclusion `{c}` is trivially true by rfl")
        entry.tier = max(entry.tier, 1)

    # All params are underscore-prefixed (unused)
    if entry.hypotheses:
        unused = [h for h in entry.hypotheses if h.startswith("_")]
        if len(unused) == len(entry.hypotheses) and len(unused) > 0:
            entry.warnings.append(
                f"T1-UNUSED-ALL: all {len(unused)} parameters are _-prefixed — "
                "likely a stub or vacuous proof"
            )
            entry.tier = max(entry.tier, 1)


# ════════════════════════════════════════════════════════════
# Tier 1.5 — Identity pass detection
# ════════════════════════════════════════════════════════════

# Field names that commonly hold pipeline transformation functions
PASS_FIELD_NAMES = {
    "passR1CS", "passWitness", "transform", "optimizeExpr",
    "pass_forward", "pass_backward", "rewrite", "optimize",
    "forward_transform", "backward_transform",
}

# Proof field names in pipeline structures whose trivial proofs indicate
# a degenerate specification (the "proof side" of identity passes).
PROOF_FIELD_NAMES = {
    "sound", "correct", "preserves", "valid", "spec",
    "soundness", "correctness", "preservation",
    "proof_sound", "proof_correct", "proof_valid",
    "is_sound", "is_correct", "is_valid",
}

# Trivial proof patterns — proofs that indicate the spec degenerates
TRIVIAL_PROOF_PATTERNS = [
    (r'^trivial,?$', "trivial"),
    (r'^True\.intro,?$', "True.intro"),
    (r'^by\s+trivial$', "by trivial"),
    (r'^by\s+exact\s+trivial$', "by exact trivial"),
    (r'^by\s+exact\s+True\.intro$', "by exact True.intro"),
    (r'^by\s+simp$', "by simp"),           # on proof fields, simp closing = spec reduced to True
    (r'^by\s+tauto$', "by tauto"),
    (r'^fun\s+_\s*=>\s*(?:trivial|True\.intro),?$', "fun _ => trivial"),
    (r'^fun\s+\w+\s*=>\s*(?:trivial|True\.intro),?$', "fun x => trivial"),
]


def detect_identity_passes(
    project_root: Path,
    deep: bool = False,
    lib_name: Optional[str] = None,
) -> list[IdentityPassEntry]:
    """Scan project for identity/trivial patterns in pipeline structures.

    Detects two categories:
    1. **Identity functions** in pass fields: `:= id`, `fun x => x`, `fun _ w => w`
    2. **Trivial proofs** in proof fields: `:= trivial`, `by trivial`, `by exact True.intro`

    Category 2 indicates the soundness specification degenerates when the pass is
    identity — the theorem "works" but proves nothing because the spec collapsed.

    When deep=True, also checks pass fields via Lean `rfl` against `id` for
    patterns that regex cannot catch (e.g., `fun x => let y := x; y`).
    """
    results: list[IdentityPassEntry] = []
    lean_files = sorted(project_root.rglob("*.lean"))
    # Track which (def, field) pairs were already found by regex
    regex_found: set[tuple[str, str, int]] = set()  # (file, field_name, line)
    lean_cache: dict[str, bool] = {}  # cache for deep checks

    for fpath in lean_files:
        rel = str(fpath.relative_to(project_root))
        if ".lake/" in rel or "lake-packages/" in rel or ".elan/" in rel:
            continue
        # Skip test files — identity passes in tests are expected
        if "/Tests/" in rel or "/tests/" in rel or "Test.lean" in rel:
            continue

        try:
            content = fpath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        lines = content.split("\n")
        module = file_to_module(fpath, project_root)

        # Track current definition context
        current_def = None
        current_def_line = 0

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Track def/structure context
            m_def = re.match(
                r'^(?:(?:private|protected|noncomputable)\s+)*'
                r'(?:def|instance|abbrev)\s+(\S+)',
                stripped
            )
            if m_def:
                current_def = m_def.group(1)
                current_def_line = i + 1

            # Check for field assignments that are identity functions
            for field_name in PASS_FIELD_NAMES:
                # Match: passR1CS := id  OR  passR1CS := fun x => x
                pattern_assign = re.compile(
                    rf'\b{re.escape(field_name)}\s*:=\s*(.*)'
                )
                m_field = pattern_assign.match(stripped)
                if not m_field:
                    continue

                rhs = m_field.group(1).strip()

                # Check identity patterns
                is_identity = False
                matched_pattern = ""

                if rhs == "id" or rhs == "id,":
                    is_identity = True
                    matched_pattern = ":= id"
                elif re.match(r'fun\s+_\s+(\w+)\s*=>\s*\1,?$', rhs):
                    is_identity = True
                    matched_pattern = "fun _ w => w"
                elif re.match(r'fun\s+(\w+)\s*=>\s*\1,?$', rhs):
                    is_identity = True
                    matched_pattern = "fun x => x"
                elif rhs.startswith("fun") and "=>" in rhs:
                    # Check: fun _ _ x => x (multi-arg identity)
                    parts = rhs.split("=>", 1)
                    if len(parts) == 2:
                        body = parts[1].strip().rstrip(",")
                        args = parts[0].replace("fun", "").strip().split()
                        if body in args:
                            is_identity = True
                            matched_pattern = f"fun ... => {body}"

                if is_identity:
                    def_name = current_def or f"<anonymous@{i+1}>"
                    results.append(IdentityPassEntry(
                        name=def_name,
                        module=module,
                        file=rel,
                        line=i + 1,
                        field_name=field_name,
                        pattern=matched_pattern,
                    ))
                    regex_found.add((rel, field_name, i + 1))

            # Check for proof fields with trivial proofs
            for proof_field in PROOF_FIELD_NAMES:
                pattern_proof = re.compile(
                    rf'\b{re.escape(proof_field)}\s*:=\s*(.*)'
                )
                m_proof = pattern_proof.match(stripped)
                if not m_proof:
                    continue

                rhs = m_proof.group(1).strip()

                for pat_re, pat_label in TRIVIAL_PROOF_PATTERNS:
                    if re.match(pat_re, rhs):
                        def_name = current_def or f"<anonymous@{i+1}>"
                        results.append(IdentityPassEntry(
                            name=def_name,
                            module=module,
                            file=rel,
                            line=i + 1,
                            field_name=proof_field,
                            pattern=pat_label,
                        ))
                        break

    # Deep mode: semantic identity check via Lean rfl
    if deep and lib_name:
        print("  [deep] Running semantic identity checks via Lean...", file=sys.stderr)
        # Re-scan for pass field assignments that were NOT caught by regex
        for fpath in lean_files:
            rel = str(fpath.relative_to(project_root))
            if ".lake/" in rel or "lake-packages/" in rel or ".elan/" in rel:
                continue
            if "/Tests/" in rel or "/tests/" in rel or "Test.lean" in rel:
                continue

            try:
                content = fpath.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            lines_list = content.split("\n")
            module = file_to_module(fpath, project_root)
            current_def_name = None

            for idx, line in enumerate(lines_list):
                stripped = line.strip()
                m_def = re.match(
                    r'^(?:(?:private|protected|noncomputable)\s+)*'
                    r'(?:def|instance|abbrev)\s+(\S+)',
                    stripped
                )
                if m_def:
                    current_def_name = m_def.group(1)

                for field_name in PASS_FIELD_NAMES:
                    if (rel, field_name, idx + 1) in regex_found:
                        continue  # already caught
                    pat = re.compile(rf'\b{re.escape(field_name)}\s*:=\s*(.+)')
                    m_f = pat.match(stripped)
                    if not m_f:
                        continue
                    # This field assignment wasn't caught by regex — try Lean check
                    def_name = current_def_name or f"<anonymous@{idx+1}>"
                    full_name = f"{module}.{def_name}"
                    if _check_identity_via_lean(
                        project_root, lib_name, full_name, field_name, lean_cache
                    ):
                        results.append(IdentityPassEntry(
                            name=def_name,
                            module=module,
                            file=rel,
                            line=idx + 1,
                            field_name=field_name,
                            pattern="[deep] definitionally id",
                        ))

    return results


# ════════════════════════════════════════════════════════════
# Tier 2 — Weak specification checks
# ════════════════════════════════════════════════════════════

def check_tier2(entry: TheoremEntry) -> None:
    """Detect weak or suspicious specifications."""
    c = entry.conclusion.strip()

    # Some params are underscore-prefixed
    if entry.hypotheses:
        unused = [h for h in entry.hypotheses if h.startswith("_")]
        if 0 < len(unused) < len(entry.hypotheses):
            entry.warnings.append(
                f"T2-UNUSED-PARTIAL: {len(unused)}/{len(entry.hypotheses)} "
                f"params are _-prefixed: {unused}"
            )
            entry.tier = max(entry.tier, 2)

    # Conclusion is only an existential without equality
    if c.startswith("∃") or c.startswith("Exists"):
        if "=" not in c and "↔" not in c:
            entry.warnings.append(
                "T2-EXISTENTIAL-ONLY: conclusion is existential without "
                "equality/equivalence — may not reach concrete evaluation"
            )
            entry.tier = max(entry.tier, 2)

    # Pipeline theorem with sorry
    if entry.is_pipeline and entry.has_sorry:
        entry.warnings.append(
            "T2-PIPELINE-SORRY: pipeline theorem contains sorry — "
            "top-level result is unverified"
        )
        entry.tier = max(entry.tier, 2)


# ════════════════════════════════════════════════════════════
# Tier 3 — Structural / semantic checks
# ════════════════════════════════════════════════════════════

def check_tier3(entry: TheoremEntry) -> None:
    """Detect structural specification issues."""
    sig = entry.signature
    c = entry.conclusion.strip()

    # Name says "sound" but conclusion doesn't have equality or implication
    if "sound" in entry.name.lower():
        if "=" not in c and "↔" not in c and "→" not in c and "∧" not in c:
            entry.warnings.append(
                "T3-NAME-MISMATCH: name contains 'sound' but conclusion "
                "has no equality, biconditional, or implication"
            )
            entry.tier = max(entry.tier, 3)

    # Name says "correct" but conclusion is weak
    if "correct" in entry.name.lower():
        if c == "True" or (c.startswith("∃") and "=" not in c):
            entry.warnings.append(
                "T3-NAME-MISMATCH: name contains 'correct' but conclusion "
                "is trivial or existential-only"
            )
            entry.tier = max(entry.tier, 3)

    # Very many hypotheses (>8) on a pipeline theorem — might hide vacuity
    if entry.is_pipeline and len(entry.hypotheses) > 8:
        entry.warnings.append(
            f"T3-MANY-HYPOTHESES: {len(entry.hypotheses)} hypotheses on pipeline theorem — "
            "verify each is satisfiable and necessary"
        )
        entry.tier = max(entry.tier, 3)

    # Biconditional check: name says "bridge" or "sound" — is it ↔ or just →?
    if "bridge" in entry.name.lower() or "equiv" in entry.name.lower():
        if "↔" not in c and "Iff" not in c:
            entry.warnings.append(
                "T3-DIRECTION: name suggests equivalence but conclusion "
                "is unidirectional (→ not ↔)"
            )
            entry.tier = max(entry.tier, 3)


def check_tier4(entry: TheoremEntry, project_root: Path) -> None:
    """Detect theorems with many Prop hypotheses lacking non-vacuity examples.

    Uses T4_PIPELINE_THRESHOLD (2) for pipeline theorems and
    T4_DEFAULT_THRESHOLD (3) for others.
    """
    # Count Prop-like hypotheses (those starting with h, not data params)
    prop_hyps = [h for h in entry.hypotheses
                 if h.startswith("h") or h.startswith("_h")]
    threshold = T4_PIPELINE_THRESHOLD if entry.is_pipeline else T4_DEFAULT_THRESHOLD
    if len(prop_hyps) < threshold:
        return

    # Search for accompanying example that references this theorem
    thm_name = entry.name
    found_witness = False

    # Check Tests/NonVacuity.lean and Tests/NonVacuity/*.lean
    nonvac_paths = list(project_root.glob("Tests/NonVacuity.lean"))
    nonvac_paths += list(project_root.glob("Tests/NonVacuity/*.lean"))
    # Also check same file (inline examples)
    thm_file = project_root / entry.file
    nonvac_paths.append(thm_file)

    for nv_path in nonvac_paths:
        if not nv_path.exists():
            continue
        try:
            content = nv_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # Look for: example using the theorem name (direct or transitive)
        if re.search(rf'\b{re.escape(thm_name)}\b', content):
            # Check it's in an example context
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped.startswith("example") or stripped.startswith("/-- Non-vacuity"):
                    found_witness = True
                    break
                # Also count: the theorem is used inside another example's proof
                if thm_name in stripped and "example" in content[:content.index(thm_name)].split("theorem")[-1]:
                    found_witness = True
                    break
        if found_witness:
            break

    if not found_witness:
        pipeline_note = f" [pipeline, threshold={threshold}]" if entry.is_pipeline else ""
        entry.warnings.append(
            f"T4-NO-WITNESS: {len(prop_hyps)} Prop hypotheses{pipeline_note} but no "
            f"non-vacuity example found in Tests/NonVacuity*.lean or same file"
        )
        entry.tier = max(entry.tier, 4)


# ════════════════════════════════════════════════════════════
# Orchestration
# ════════════════════════════════════════════════════════════

def run_audit(
    project_root: Path,
    pipeline_only: bool = False,
    deep: bool = False,
) -> AuditResult:
    """Run full specification audit on a Lean project.

    Args:
        deep: Enable slow checks that use Lean subprocess (semantic identity,
              dead hypotheses, conclusion strength T5).
    """
    entries = extract_theorems(project_root)

    result = AuditResult(project=project_root.name)
    result.deep_mode = deep

    # Detect project library name (needed for --deep)
    lib_name = _detect_project_lib(project_root) if deep else None
    if deep and not lib_name:
        print("  [deep] Warning: could not detect project library name, "
              "some deep checks will be skipped", file=sys.stderr)

    for entry in entries:
        if entry.kind == "theorem":
            result.total_theorems += 1
        else:
            result.total_lemmas += 1

        if entry.is_pipeline:
            result.pipeline_count += 1

        # Run checks
        check_tier1(entry)
        check_tier2(entry)
        check_tier3(entry)
        check_tier4(entry, project_root)

        # Deep checks
        if deep:
            # T5: Conclusion strength
            score, label = _classify_conclusion_strength(entry.conclusion)
            entry.conclusion_strength = score
            entry.conclusion_strength_label = label
            if entry.is_pipeline and score <= 1:
                entry.warnings.append(
                    f"T5-WEAK-CONCLUSION: conclusion strength={score} ({label})"
                )
                result.tier5_issues += 1

            # Dead hypothesis detection
            if lib_name and entry.is_pipeline:
                dead = _check_dead_hypotheses(entry, project_root, lib_name)
                if dead:
                    entry.dead_hypotheses = dead
                    for h in dead:
                        entry.warnings.append(
                            f"T2-DEAD-HYPOTHESIS: hypothesis '{h}' appears unused in proof"
                        )
                    result.dead_hypothesis_count += len(dead)

        if entry.tier == 0:
            result.clean_count += 1
        elif entry.tier == 1:
            result.tier1_issues += 1
        elif entry.tier == 2:
            result.tier2_issues += 1
        elif entry.tier == 3:
            result.tier3_issues += 1
        elif entry.tier == 4:
            result.tier4_issues += 1

    # T1.5: Identity pass detection (definitions, not theorems)
    identity_passes = detect_identity_passes(
        project_root, deep=deep, lib_name=lib_name
    )
    result.identity_passes = identity_passes
    result.tier15_issues = len(identity_passes)

    if pipeline_only:
        entries = [e for e in entries if e.is_pipeline]

    result.entries = entries
    result.all_pass = result.tier1_issues == 0 and (
        result.tier2_issues == 0 or not any(
            e.is_pipeline and e.tier >= 2 for e in entries
        )
    )

    # Generate text report
    result.text_report = _generate_report(result)
    return result


def _generate_report(result: AuditResult) -> str:
    """Generate human-readable audit report."""
    lines = []
    lines.append(f"═══ Specification Audit: {result.project} ═══")
    lines.append(f"Theorems: {result.total_theorems}  Lemmas: {result.total_lemmas}  "
                 f"Pipeline: {result.pipeline_count}")
    t5_str = f"  T5(weak-conclusion): {result.tier5_issues}" if result.deep_mode else ""
    dead_str = f"  Dead-hyps: {result.dead_hypothesis_count}" if result.deep_mode else ""
    lines.append(f"Clean: {result.clean_count}  "
                 f"T1(vacuity): {result.tier1_issues}  "
                 f"T1.5(identity): {result.tier15_issues}  "
                 f"T2(weak): {result.tier2_issues}  "
                 f"T3(structural): {result.tier3_issues}  "
                 f"T4(no-witness): {result.tier4_issues}"
                 f"{t5_str}{dead_str}")
    if result.deep_mode:
        lines.append("  [deep mode enabled]")
    lines.append("")

    # Show identity passes (T1.5)
    if result.identity_passes:
        lines.append(f"── TIER 1.5 — IDENTITY PASSES ({len(result.identity_passes)} found) ──")
        lines.append("  Pipeline pass fields assigned to identity function (no-op).")
        lines.append("  These compile clean with zero sorry but prove nothing about optimization.")
        lines.append("")
        for ip in result.identity_passes:
            lines.append(f"  def {ip.name}")
            lines.append(f"    {ip.file}:{ip.line}  {ip.field_name} {ip.pattern}")
        lines.append("")

    # Show deep-mode sections
    if result.deep_mode:
        # Dead hypotheses
        dead_entries = [e for e in result.entries if e.dead_hypotheses]
        if dead_entries:
            lines.append(f"── DEAD HYPOTHESES ({result.dead_hypothesis_count} found) ──")
            lines.append("  Prop hypotheses that appear unused in the proof body.")
            lines.append("")
            for e in dead_entries:
                lines.append(f"  {e.kind} {e.name}")
                lines.append(f"    {e.file}:{e.line}")
                for h in e.dead_hypotheses:
                    lines.append(f"    hypothesis '{h}' appears unused")
                lines.append("")

        # T5 weak conclusions
        t5_entries = [e for e in result.entries
                      if e.conclusion_strength >= 0 and e.conclusion_strength <= 1
                      and e.is_pipeline]
        if t5_entries:
            lines.append(f"── TIER 5 — WEAK CONCLUSIONS ({len(t5_entries)} found) ──")
            lines.append("  Pipeline theorems with trivially-weak conclusions.")
            lines.append("")
            for e in t5_entries:
                lines.append(f"  {e.kind} {e.name}  strength={e.conclusion_strength} "
                             f"({e.conclusion_strength_label})")
                lines.append(f"    {e.file}:{e.line}")
                lines.append(f"    conclusion: {e.conclusion[:120]}")
                lines.append("")

    # Show issues grouped by tier
    for tier, label in [(1, "TIER 1 — VACUITY"), (2, "TIER 2 — WEAK SPECS"),
                        (3, "TIER 3 — STRUCTURAL"), (4, "TIER 4 — NO WITNESS")]:
        issues = [e for e in result.entries if e.tier == tier]
        if not issues:
            continue
        lines.append(f"── {label} ({len(issues)} issues) ──")
        for e in issues:
            pipeline_tag = " [PIPELINE]" if e.is_pipeline else ""
            sorry_tag = " [SORRY]" if e.has_sorry else ""
            lines.append(f"  {e.kind} {e.name}{pipeline_tag}{sorry_tag}")
            lines.append(f"    {e.file}:{e.line}")
            for w in e.warnings:
                lines.append(f"    ⚠ {w}")
            lines.append("")

    # Summary
    if result.all_pass:
        lines.append("✓ PASS — No blocking spec issues found")
    else:
        lines.append("✗ FAIL — Blocking spec issues detected (Tier 1 vacuity or pipeline sorry)")

    return "\n".join(lines)


# ════════════════════════════════════════════════════════════
# THEOREMS.md generation
# ════════════════════════════════════════════════════════════

def generate_theorems_md(result: AuditResult, output_path: Path) -> None:
    """Generate THEOREMS.md registry for human review."""
    lines = []
    lines.append("# Theorem Registry")
    lines.append("")
    lines.append(f"> Auto-generated by `spec_audit.py` for **{result.project}**")
    lines.append(f"> Theorems: {result.total_theorems} | Lemmas: {result.total_lemmas} | "
                 f"Pipeline: {result.pipeline_count}")
    lines.append("")

    # Pipeline theorems first
    pipeline = [e for e in result.entries if e.is_pipeline]
    if pipeline:
        lines.append("## Pipeline Theorems")
        lines.append("")
        lines.append("These are the main results of the project. **Audit these first.**")
        lines.append("")
        for e in pipeline:
            _append_entry_md(lines, e)

    # Theorems with warnings
    warned = [e for e in result.entries if e.tier > 0 and not e.is_pipeline]
    if warned:
        lines.append("## Theorems with Warnings")
        lines.append("")
        for e in warned:
            _append_entry_md(lines, e)

    # Foundational (non-pipeline theorems with many dependents — heuristic: name patterns)
    foundational_kw = {"preserv", "inv", "wf", "wellformed", "consistent", "sound", "correct"}
    foundational = [e for e in result.entries
                    if e.tier == 0 and not e.is_pipeline
                    and any(kw in e.name.lower() for kw in foundational_kw)]
    if foundational:
        lines.append("## Foundational Lemmas")
        lines.append("")
        lines.append("Lemmas likely depended upon by pipeline theorems.")
        lines.append("")
        for e in foundational[:30]:  # cap at 30
            _append_entry_md(lines, e, compact=True)

    # Stats footer
    lines.append("---")
    lines.append("")
    lines.append("### Audit Checklist")
    lines.append("")
    lines.append("For each pipeline theorem, verify:")
    lines.append("")
    lines.append("- [ ] Hypotheses are satisfiable (construct a concrete example)")
    lines.append("- [ ] Conclusion says what the name promises")
    lines.append("- [ ] Direction is correct (→ vs ↔)")
    lines.append("- [ ] Not vacuous (conclusion ≠ True, params used)")
    lines.append("- [ ] Chain is complete (every step has a theorem)")
    lines.append("- [ ] Reaches concrete equality (evalExpr a = evalExpr b)")
    lines.append("- [ ] No dangling hypotheses (each H has a lemma establishing it)")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


def _append_entry_md(lines: list[str], e: TheoremEntry, compact: bool = False) -> None:
    """Append a single theorem entry to THEOREMS.md."""
    sorry_badge = " `[SORRY]`" if e.has_sorry else ""
    tier_badge = f" `[T{e.tier}]`" if e.tier > 0 else ""

    lines.append(f"### `{e.name}`{sorry_badge}{tier_badge}")
    lines.append("")
    lines.append(f"- **Kind**: {e.kind}")
    lines.append(f"- **Module**: `{e.module}`")
    lines.append(f"- **Location**: `{e.file}:{e.line}`")

    if not compact:
        lines.append(f"- **Hypotheses**: {len(e.hypotheses)}")
        lines.append("")
        lines.append("```lean")
        lines.append(e.signature)
        lines.append("```")

    if e.warnings:
        lines.append("")
        for w in e.warnings:
            lines.append(f"> ⚠ {w}")

    lines.append("")


# ════════════════════════════════════════════════════════════
# JSON output (for close_block integration)
# ════════════════════════════════════════════════════════════

def to_json(result: AuditResult) -> dict:
    """Convert audit result to JSON-serializable dict."""
    data = {
        "project": result.project,
        "total_theorems": result.total_theorems,
        "total_lemmas": result.total_lemmas,
        "pipeline_count": result.pipeline_count,
        "tier1_issues": result.tier1_issues,
        "tier15_issues": result.tier15_issues,
        "tier2_issues": result.tier2_issues,
        "tier3_issues": result.tier3_issues,
        "tier4_issues": result.tier4_issues,
        "clean_count": result.clean_count,
        "all_pass": result.all_pass,
        "deep_mode": result.deep_mode,
        "identity_passes": [
            {
                "name": ip.name,
                "module": ip.module,
                "file": ip.file,
                "line": ip.line,
                "field": ip.field_name,
                "pattern": ip.pattern,
            }
            for ip in result.identity_passes
        ],
        "entries": [
            {
                "name": e.name,
                "kind": e.kind,
                "module": e.module,
                "file": e.file,
                "line": e.line,
                "is_pipeline": e.is_pipeline,
                "has_sorry": e.has_sorry,
                "tier": e.tier,
                "warnings": e.warnings,
                "conclusion": e.conclusion[:200],
                **({"conclusion_strength": e.conclusion_strength,
                    "conclusion_strength_label": e.conclusion_strength_label}
                   if result.deep_mode else {}),
                **({"dead_hypotheses": e.dead_hypotheses}
                   if e.dead_hypotheses else {}),
            }
            for e in result.entries
            if e.tier > 0 or e.is_pipeline  # only issues + pipeline in JSON
        ],
    }
    if result.deep_mode:
        data["tier5_issues"] = result.tier5_issues
        data["dead_hypothesis_count"] = result.dead_hypothesis_count
    return data


# ════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Lean 4 Specification Audit")
    parser.add_argument("--project", required=True, help="Path to Lean project root")
    parser.add_argument("--pipeline-only", action="store_true",
                        help="Only show pipeline theorems")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON instead of text")
    parser.add_argument("--generate-registry", action="store_true",
                        help="Generate THEOREMS.md in project root")
    parser.add_argument("--deep", action="store_true",
                        help="Enable slow checks: semantic identity via Lean, "
                             "dead hypothesis detection, conclusion strength (T5)")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    args = parser.parse_args()

    project_root = Path(args.project).resolve()
    if not project_root.is_dir():
        print(f"Error: {project_root} is not a directory", file=sys.stderr)
        sys.exit(1)

    result = run_audit(
        project_root,
        pipeline_only=args.pipeline_only,
        deep=args.deep,
    )

    # Generate THEOREMS.md if requested
    if args.generate_registry:
        registry_path = project_root / "THEOREMS.md"
        generate_theorems_md(result, registry_path)
        print(f"Generated {registry_path}", file=sys.stderr)

    # Output
    if args.json:
        output = json.dumps(to_json(result), indent=2)
    else:
        output = result.text_report

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)

    # Exit code
    if not result.all_pass:
        sys.exit(1)
    elif result.tier2_issues + result.tier3_issues > 0:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
