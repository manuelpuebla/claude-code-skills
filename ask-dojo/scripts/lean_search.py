#!/usr/bin/env python3
"""
LeanDojo Search - Bibliotecario para teoremas y tácticas de Lean 4

Modos de búsqueda:
1. Por nombre de teorema: busca en full_name
2. Por estado/goal: busca en state_before de las tácticas
3. Sugerencia de táctica: dado un goal, sugiere táctica con el modelo
4. Análisis de archivo .lean: encuentra sorry y sugiere soluciones
5. Contexto desde archivo .md: información adicional para búsqueda

Dataset: LeanDojo (87,766 teoremas de Mathlib)
Modelo: tacgen-byt5-small (sugerencias de tácticas)
"""

import os
import sys
import re
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass

# Paths
SKILL_DIR = Path(__file__).parent.parent
DATA_DIR = SKILL_DIR / "data"
DATASET_PATH = DATA_DIR / "leandojo_dataset"
MODEL_PATH = DATA_DIR / "tacgen-model"

# Lazy loading for heavy imports
_dataset = None
_tokenizer = None
_model = None


@dataclass
class SearchResult:
    """Resultado de búsqueda."""
    theorem_name: str
    file_path: str
    relevance: float
    state_before: Optional[str] = None
    tactic_used: Optional[str] = None
    state_after: Optional[str] = None


def load_dataset():
    """Load dataset lazily."""
    global _dataset
    if _dataset is None:
        from datasets import load_from_disk
        _dataset = load_from_disk(str(DATASET_PATH))
    return _dataset


def load_model():
    """Load tactic suggestion model lazily."""
    global _tokenizer, _model
    if _tokenizer is None:
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        _tokenizer = AutoTokenizer.from_pretrained(str(MODEL_PATH))
        _model = AutoModelForSeq2SeqLM.from_pretrained(str(MODEL_PATH))
    return _tokenizer, _model


def normalize_query(query: str) -> List[str]:
    """Normalize query into search terms."""
    # Convert to lowercase and split
    query = query.lower()
    # Remove special characters except underscores
    query = re.sub(r'[^\w\s_]', ' ', query)
    # Split into terms
    terms = query.split()
    # Filter short terms
    terms = [t for t in terms if len(t) > 2]
    return terms


def search_by_name(query: str, max_results: int = 10) -> List[SearchResult]:
    """Search theorems by name."""
    dataset = load_dataset()
    terms = normalize_query(query)

    if not terms:
        return []

    results = []

    for entry in dataset:
        name = entry['full_name'].lower()

        # Calculate relevance based on term matches
        matches = sum(1 for term in terms if term in name)
        if matches > 0:
            relevance = matches / len(terms)

            # Boost exact matches
            if all(term in name for term in terms):
                relevance *= 1.5

            # Get first tactic if available
            state_before = None
            tactic = None
            state_after = None
            if entry['traced_tactics']:
                first_tactic = entry['traced_tactics'][0]
                state_before = first_tactic.get('state_before', '')
                tactic = first_tactic.get('tactic', '')
                state_after = first_tactic.get('state_after', '')

            results.append(SearchResult(
                theorem_name=entry['full_name'],
                file_path=entry['file_path'],
                relevance=relevance,
                state_before=state_before,
                tactic_used=tactic,
                state_after=state_after,
            ))

    # Sort by relevance
    results.sort(key=lambda x: x.relevance, reverse=True)
    return results[:max_results]


def search_by_state(query: str, max_results: int = 10) -> List[SearchResult]:
    """Search by proof state/goal."""
    dataset = load_dataset()
    terms = normalize_query(query)

    if not terms:
        return []

    results = []

    for entry in dataset:
        if not entry['traced_tactics']:
            continue

        for tactic_info in entry['traced_tactics']:
            state = tactic_info.get('state_before', '').lower()

            # Calculate relevance
            matches = sum(1 for term in terms if term in state)
            if matches > 0:
                relevance = matches / len(terms)

                results.append(SearchResult(
                    theorem_name=entry['full_name'],
                    file_path=entry['file_path'],
                    relevance=relevance,
                    state_before=tactic_info.get('state_before', ''),
                    tactic_used=tactic_info.get('tactic', ''),
                    state_after=tactic_info.get('state_after', ''),
                ))
                break  # Only one result per theorem

    results.sort(key=lambda x: x.relevance, reverse=True)
    return results[:max_results]


def suggest_tactic(goal_state: str, num_suggestions: int = 3) -> List[str]:
    """Suggest tactics for a given goal state using the model."""
    tokenizer, model = load_model()

    # Prepare input
    inputs = tokenizer(goal_state, return_tensors="pt", max_length=512, truncation=True)

    # Generate suggestions
    outputs = model.generate(
        **inputs,
        max_length=256,
        num_return_sequences=num_suggestions,
        num_beams=num_suggestions,
        do_sample=False,
    )

    # Decode
    suggestions = []
    for output in outputs:
        tactic = tokenizer.decode(output, skip_special_tokens=True)
        if tactic and tactic not in suggestions:
            suggestions.append(tactic)

    return suggestions


def format_results(results: List[SearchResult], show_states: bool = True) -> str:
    """Format search results for display."""
    if not results:
        return "No se encontraron resultados."

    output = []
    output.append(f"## Resultados ({len(results)} encontrados)\n")

    for i, r in enumerate(results, 1):
        output.append(f"### {i}. `{r.theorem_name}`")
        output.append(f"**Archivo**: `{r.file_path}`")
        output.append(f"**Relevancia**: {r.relevance:.0%}")

        if show_states and r.state_before:
            output.append(f"\n**Estado inicial**:")
            output.append(f"```lean")
            output.append(r.state_before[:500])
            output.append(f"```")

        if r.tactic_used:
            output.append(f"\n**Táctica usada**: `{r.tactic_used}`")

        if show_states and r.state_after:
            output.append(f"\n**Estado después**:")
            output.append(f"```lean")
            output.append(r.state_after[:300])
            output.append(f"```")

        output.append("")

    return "\n".join(output)


def format_suggestions(suggestions: List[str]) -> str:
    """Format tactic suggestions."""
    if not suggestions:
        return "No se pudieron generar sugerencias."

    output = []
    output.append("## Tácticas Sugeridas\n")

    for i, tactic in enumerate(suggestions, 1):
        output.append(f"{i}. `{tactic}`")

    output.append("\n*Sugerencias generadas por tacgen-byt5-small*")
    return "\n".join(output)


@dataclass
class SorryLocation:
    """Location of a sorry in a Lean file."""
    line_num: int
    theorem_name: str
    context: str  # Lines around the sorry
    goal_hint: str  # Extracted from comments or theorem signature


def read_file_if_exists(path: str) -> Optional[str]:
    """Read a file if it exists."""
    try:
        p = Path(path)
        if p.exists():
            return p.read_text()
        if not p.is_absolute():
            for base in [Path.cwd(), Path.home() / "Documents" / "claudio"]:
                full = base / path
                if full.exists():
                    return full.read_text()
        return None
    except Exception as e:
        print(f"Warning: Could not read {path}: {e}", file=sys.stderr)
        return None


def parse_lean_file(content: str) -> List[SorryLocation]:
    """Parse a Lean file and find all sorry locations."""
    sorries = []
    lines = content.split('\n')

    current_theorem = None
    theorem_start = 0

    for i, line in enumerate(lines):
        # Track theorem/lemma/def declarations
        theorem_match = re.match(r'^(theorem|lemma|def|example)\s+(\w+)', line)
        if theorem_match:
            current_theorem = theorem_match.group(2)
            theorem_start = i

        # Find sorry
        if 'sorry' in line:
            # Get context (5 lines before and after)
            start = max(0, i - 5)
            end = min(len(lines), i + 6)
            context = '\n'.join(lines[start:end])

            # Try to extract goal hint from theorem signature or comments
            goal_hint = ""
            if current_theorem:
                # Get theorem signature
                sig_lines = lines[theorem_start:i+1]
                sig = '\n'.join(sig_lines)
                # Extract type after ':'
                type_match = re.search(r':\s*(.+?)\s*:=', sig, re.DOTALL)
                if type_match:
                    goal_hint = type_match.group(1).strip()

            sorries.append(SorryLocation(
                line_num=i + 1,
                theorem_name=current_theorem or "unknown",
                context=context,
                goal_hint=goal_hint,
            ))

    return sorries


def analyze_lean_file(file_path: str, max_results: int = 3) -> str:
    """Analyze a Lean file, find sorries, and suggest solutions."""
    content = read_file_if_exists(file_path)
    if not content:
        return f"Error: No se pudo leer el archivo '{file_path}'"

    sorries = parse_lean_file(content)

    if not sorries:
        return f"No se encontraron `sorry` en '{file_path}'"

    output = []
    output.append(f"## Análisis de `{file_path}`")
    output.append(f"**Sorries encontrados**: {len(sorries)}\n")

    for sorry in sorries:
        output.append(f"### Línea {sorry.line_num}: `{sorry.theorem_name}`")
        output.append(f"\n**Contexto**:")
        output.append("```lean")
        output.append(sorry.context)
        output.append("```")

        # Search for similar theorems
        if sorry.theorem_name and sorry.theorem_name != "unknown":
            output.append(f"\n**Teoremas similares en Mathlib**:")
            results = search_by_name(sorry.theorem_name, max_results)
            if results:
                for r in results:
                    output.append(f"- `{r.theorem_name}` ({r.file_path})")
                    if r.tactic_used:
                        output.append(f"  - Primera táctica: `{r.tactic_used}`")
            else:
                output.append("- No se encontraron teoremas similares")

        # Suggest tactics if we have a goal hint
        if sorry.goal_hint:
            output.append(f"\n**Goal extraído**: `{sorry.goal_hint[:100]}...`" if len(sorry.goal_hint) > 100 else f"\n**Goal extraído**: `{sorry.goal_hint}`")
            output.append(f"\n**Tácticas sugeridas**:")
            suggestions = suggest_tactic(sorry.goal_hint)
            for s in suggestions:
                output.append(f"- `{s}`")

        output.append("")

    return "\n".join(output)


def format_with_context(results: List[SearchResult], context: str, show_states: bool = True) -> str:
    """Format results with additional context from .md file."""
    output = []

    if context:
        output.append("## Contexto Proporcionado\n")
        # Show first 500 chars of context
        if len(context) > 500:
            output.append(context[:500] + "...\n")
        else:
            output.append(context + "\n")
        output.append("---\n")

    output.append(format_results(results, show_states))
    return "\n".join(output)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="LeanDojo Search - Bibliotecario Lean 4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Buscar por nombre de teorema
  lean_search.py --name "sum range"

  # Buscar por estado/goal
  lean_search.py --state "Finset.sum"

  # Sugerir táctica para un goal
  lean_search.py --suggest "⊢ n + m = m + n"

  # Analizar archivo .lean con sorries
  lean_search.py --file mi_teorema.lean

  # Buscar con contexto de archivo .md
  lean_search.py --name "NTT" --context proyecto.md

  # Combinado
  lean_search.py --file prueba.lean --context especificacion.md
"""
    )

    parser.add_argument("query", nargs="?", default="",
                        help="Búsqueda general (nombre o estado)")
    parser.add_argument("--name", "-n", type=str, default="",
                        help="Buscar por nombre de teorema")
    parser.add_argument("--state", "-s", type=str, default="",
                        help="Buscar por estado/goal")
    parser.add_argument("--suggest", "-t", type=str, default="",
                        help="Sugerir táctica para un goal")
    parser.add_argument("--file", "-f", type=str, default="",
                        help="Archivo .lean a analizar (busca sorries)")
    parser.add_argument("--context", "-ctx", type=str, default="",
                        help="Archivo .md con contexto adicional")
    parser.add_argument("--max", "-m", type=int, default=5,
                        help="Máximo de resultados (default: 5)")
    parser.add_argument("--compact", "-c", action="store_true",
                        help="Salida compacta (sin estados)")

    args = parser.parse_args()

    # Load context if provided
    context_content = ""
    if args.context:
        context_content = read_file_if_exists(args.context) or ""
        if context_content:
            print(f"Contexto cargado: {args.context} ({len(context_content)} chars)", file=sys.stderr)
        else:
            print(f"Warning: No se pudo cargar contexto: {args.context}", file=sys.stderr)

    # Determine search mode
    has_query = bool(args.query or args.name or args.state)
    has_suggest = bool(args.suggest)
    has_file = bool(args.file)

    if not has_query and not has_suggest and not has_file:
        parser.print_help()
        sys.exit(0)

    output_parts = []

    # Analyze Lean file
    if args.file:
        print(f"Analizando archivo: '{args.file}'...", file=sys.stderr)
        analysis = analyze_lean_file(args.file, args.max)
        if context_content:
            output_parts.append(f"## Contexto: {args.context}\n\n{context_content[:800]}{'...' if len(context_content) > 800 else ''}\n\n---\n")
        output_parts.append(analysis)

    # Search by name
    if args.name or (args.query and not args.state and not has_file):
        query = args.name or args.query
        print(f"Buscando teoremas: '{query}'...", file=sys.stderr)
        results = search_by_name(query, args.max)
        if context_content:
            output_parts.append(format_with_context(results, context_content, not args.compact))
        else:
            output_parts.append(format_results(results, not args.compact))

    # Search by state
    if args.state:
        print(f"Buscando por estado: '{args.state}'...", file=sys.stderr)
        results = search_by_state(args.state, args.max)
        output_parts.append(format_results(results, not args.compact))

    # Suggest tactics
    if args.suggest:
        print(f"Generando sugerencias de táctica...", file=sys.stderr)
        suggestions = suggest_tactic(args.suggest)
        output_parts.append(format_suggestions(suggestions))

    # Output
    print("\n---\n".join(output_parts))


if __name__ == "__main__":
    main()
