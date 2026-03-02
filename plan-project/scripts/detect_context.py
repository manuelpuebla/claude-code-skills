#!/usr/bin/env python3
"""
Detect Context - Detecta el contexto actual del proyecto

Métodos de detección:
1. Argumento explícito (--context)
2. Git branch name
3. Plan file activo en ~/.claude/plans/
4. TODO state (si disponible)

Output: JSON con información de contexto
"""

import argparse
import json
import re
import subprocess
from pathlib import Path


def detect_from_git_branch() -> dict:
    """Detecta contexto desde el nombre del branch de git."""
    try:
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            stderr=subprocess.DEVNULL
        ).decode().strip()

        if not branch:
            return {}

        result = {"source": "git_branch", "branch": branch}

        # Patterns to match:
        # feature/fase2-something → Fase 2
        # fase-1-setup → Fase 1
        # phase3/subfase2 → Fase 3 Subfase 2
        patterns = [
            (r'fase[_-]?(\d+)[_-]subfase[_-]?(\d+)', lambda m: f"Fase {m.group(1)} Subfase {m.group(2)}"),
            (r'fase[_-]?(\d+)[_-]correccion[_-]?(\d+)', lambda m: f"Fase {m.group(1)} Corrección {m.group(2)}"),
            (r'fase[_-]?(\d+)', lambda m: f"Fase {m.group(1)}"),
            (r'phase[_-]?(\d+)', lambda m: f"Fase {m.group(1)}"),
        ]

        branch_lower = branch.lower()
        for pattern, formatter in patterns:
            match = re.search(pattern, branch_lower)
            if match:
                result["current_phase"] = formatter(match)
                return result

        return result

    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}


def detect_from_plan_files() -> dict:
    """Detecta contexto desde archivos de plan activos."""
    plan_dir = Path.home() / ".claude" / "plans"

    if not plan_dir.exists():
        return {}

    # Look for active plans (with EN PROGRESO or in_progress)
    for plan_file in sorted(plan_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            content = plan_file.read_text()

            # Check if plan is active
            if "EN PROGRESO" not in content and "in_progress" not in content.lower():
                continue

            result = {"source": "plan_file", "file": str(plan_file)}

            # Extract current phase
            # Pattern: "Fase N: Title [EN PROGRESO"
            patterns = [
                r'(Fase \d+ Subfase \d+ Capa \d+)[^\[]*\[EN PROGRESO',
                r'(Fase \d+ Subfase \d+)[^\[]*\[EN PROGRESO',
                r'(Fase \d+ Corrección \d+)[^\[]*\[EN PROGRESO',
                r'(Fase \d+)[^\[]*\[EN PROGRESO',
            ]

            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    result["current_phase"] = match.group(1)
                    return result

            # Also check for "← ACTUAL" marker
            actual_match = re.search(r'(Fase \d+[^←\n]*?)←\s*ACTUAL', content)
            if actual_match:
                result["current_phase"] = actual_match.group(1).strip()
                return result

            return result

        except Exception:
            continue

    return {}


def detect_from_project_roadmap(cwd: str = None) -> dict:
    """Detecta contexto desde roadmap del proyecto actual."""
    search_dirs = [Path(cwd) if cwd else Path.cwd()]

    # Also search parent directories
    current = search_dirs[0]
    for _ in range(5):
        current = current.parent
        search_dirs.append(current)

    for search_dir in search_dirs:
        for roadmap_pattern in ["roadmap*.md", "*/roadmap*.md", "docs/roadmap*.md"]:
            for roadmap_file in search_dir.glob(roadmap_pattern):
                try:
                    content = roadmap_file.read_text()

                    # Same detection as plan files
                    if "EN PROGRESO" not in content:
                        continue

                    result = {"source": "project_roadmap", "file": str(roadmap_file)}

                    patterns = [
                        r'(Fase \d+ Subfase \d+)[^\[]*\[EN PROGRESO',
                        r'(Fase \d+)[^\[]*\[EN PROGRESO',
                    ]

                    for pattern in patterns:
                        match = re.search(pattern, content)
                        if match:
                            result["current_phase"] = match.group(1)
                            return result

                except Exception:
                    continue

    return {}


def parse_explicit_context(context_str: str) -> dict:
    """Parsea contexto explícito del usuario."""
    if not context_str:
        return {}

    result = {"source": "explicit", "raw": context_str}

    # Normalize common formats
    context_lower = context_str.lower().strip()

    # fase2 → Fase 2
    match = re.match(r'fase(\d+)$', context_lower)
    if match:
        result["current_phase"] = f"Fase {match.group(1)}"
        return result

    # fase2-subfase1 → Fase 2 Subfase 1
    match = re.match(r'fase(\d+)[_-]subfase(\d+)', context_lower)
    if match:
        result["current_phase"] = f"Fase {match.group(1)} Subfase {match.group(2)}"
        return result

    # Already properly formatted
    if context_str.startswith("Fase "):
        result["current_phase"] = context_str
        return result

    return result


def count_sorries_in_project(project_path: str = None) -> int:
    """Cuenta el número de sorry en archivos .lean del proyecto actual."""
    import subprocess as sp
    search_path = project_path or "."
    try:
        result = sp.run(
            ["grep", "-r", "--include=*.lean", "-l", r"\bsorry\b", search_path],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            files_with_sorry = [f for f in result.stdout.strip().split('\n') if f and '.lake' not in f]
            return len(files_with_sorry)
    except Exception:
        pass
    return 0


def classify_complexity(task_description: str, context: dict = None) -> str:
    """Classify task complexity for adaptive thinking (Opus 4.6).

    Returns effort level: "low", "medium", "high", or "max".
    This determines QA rounds, detail level, and obstacle resolution depth.

    Signals:
    - Phase count estimation from keywords
    - Domain complexity (lean4 > rust > general)
    - Nested planning (corrections are simpler)
    - Keyword indicators (crypto, NTT, verification = complex)
    - Sorry elimination tasks (high by default)
    """
    if context is None:
        context = {}

    score = 0
    desc_lower = task_description.lower()

    # Domain complexity
    domain_scores = {
        "lean4": 3, "lean": 3, "coq": 3,
        "rust": 2, "crypto": 3, "ntt": 3,
        "python": 1, "javascript": 1,
    }
    for domain, domain_score in domain_scores.items():
        if domain in desc_lower or domain in str(context.get("domain", "")):
            score += domain_score
            break

    # Complexity keywords (use stems for Spanish gender/conjugation variants)
    complex_keywords = [
        "verifica", "verification", "formal", "proof", "demostrac",
        "criptograf", "cryptograph", "post-quantum", "post-cuántic",
        "ntt", "fft", "transform", "optimizac", "optimization",
        "refactor", "arquitectur", "architecture", "migrac", "migration",
        "axiom", "sorry", "mathlib", "theorem", "teorema",
    ]
    score += sum(2 for kw in complex_keywords if kw in desc_lower)

    # Phase estimation from structural keywords
    phase_keywords = ["fase", "phase", "módulo", "module", "componente", "component"]
    phase_count = sum(1 for kw in phase_keywords if kw in desc_lower)
    score += phase_count * 2

    # DAG / dependency depth indicators (deep dependencies = more complex)
    dag_keywords = [
        "dependenc", "depende de", "depends on", "prerequisit",
        "fundacional", "foundational", "precondic", "precondition",
        "sorry", "axiom", "eliminar sorry", "eliminate sorry",
        "de-risk", "derisking", "orden de prueba", "proof order",
        "transitiv", "downstream", "cascad",
    ]
    score += sum(2 for kw in dag_keywords if kw in desc_lower)

    # Multi-step indicators
    multi_keywords = ["y luego", "después", "además", "también", "then", "also", "and then"]
    score += sum(1 for kw in multi_keywords if kw in desc_lower)

    # Sorry elimination detection (always high complexity)
    sorry_keywords = [
        "eliminar sorry", "eliminate sorry", "remove sorry", "quitar sorry",
        "probar sorry", "prove sorry", "resolver sorry", "sorry elimination",
        "deuda teórica", "deuda técnica de sorry", "formal proof",
    ]
    sorry_task = any(kw in desc_lower for kw in sorry_keywords)
    if sorry_task:
        score += 4  # Sorry elimination is inherently complex

    # Count sorries in project if it's a Lean task
    if sorry_task or "lean" in desc_lower or context.get("domain", "") in ("lean4", "lean"):
        sorry_file_count = count_sorries_in_project()
        if sorry_file_count > 5:
            score += 2  # Many files with sorry = higher complexity

    # Simplicity indicators (reduce score)
    simple_keywords = [
        "fix", "corregir", "bug", "typo", "rename", "renombrar",
        "simple", "pequeño", "minor", "quick", "rápido",
    ]
    score -= sum(2 for kw in simple_keywords if kw in desc_lower)

    # Nested planning is typically simpler
    if context.get("nested", False):
        score -= 2

    # Classify
    if score <= 2:
        return "low"
    elif score <= 5:
        return "medium"
    elif score <= 10:
        return "high"
    else:
        return "max"


def detect_context(explicit_context: str = None) -> dict:
    """Detecta el contexto actual usando todos los métodos disponibles.

    Priority:
    1. Explicit context (--context argument)
    2. Git branch
    3. Plan file
    4. Project roadmap
    """
    context = {
        "current_phase": None,
        "source": None,
        "nested": False,
        "details": {},
    }

    # Method 1: Explicit context
    if explicit_context:
        result = parse_explicit_context(explicit_context)
        if "current_phase" in result:
            context.update(result)
            context["nested"] = True
            return context

    # Method 2: Git branch
    result = detect_from_git_branch()
    if "current_phase" in result:
        context.update(result)
        context["nested"] = True
        return context

    # Method 3: Plan files
    result = detect_from_plan_files()
    if "current_phase" in result:
        context.update(result)
        context["nested"] = True
        return context

    # Method 4: Project roadmap
    result = detect_from_project_roadmap()
    if "current_phase" in result:
        context.update(result)
        context["nested"] = True
        return context

    # No context found - this is a new project
    context["source"] = "none"
    context["nested"] = False

    return context


def main():
    parser = argparse.ArgumentParser(
        description="Detect current project context for planning"
    )
    parser.add_argument("--context", "-c", type=str, default="",
                        help="Explicit context (e.g., 'fase2', 'Fase 2 Subfase 1')")
    parser.add_argument("--format", "-f", type=str, default="json",
                        choices=["json", "text"],
                        help="Output format")
    parser.add_argument("--task", "-t", type=str, default="",
                        help="Task description for complexity classification")
    parser.add_argument("--domain", type=str, default="",
                        help="Domain hint for complexity (e.g., lean4, rust)")

    args = parser.parse_args()

    context = detect_context(args.context)

    # Add complexity classification if task description provided
    if args.task:
        complexity_context = dict(context)
        if args.domain:
            complexity_context["domain"] = args.domain
        context["complexity"] = classify_complexity(args.task, complexity_context)
    else:
        context["complexity"] = "high"  # Default: assume non-trivial

    if args.format == "json":
        print(json.dumps(context, indent=2, ensure_ascii=False))
    else:
        if context["current_phase"]:
            print(f"Contexto detectado: {context['current_phase']}")
            print(f"Fuente: {context['source']}")
            print(f"Planificación anidada: {'Sí' if context['nested'] else 'No'}")
        else:
            print("No se detectó contexto - proyecto nuevo")
        print(f"Complejidad: {context.get('complexity', 'high')}")


if __name__ == "__main__":
    main()
