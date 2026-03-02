#!/usr/bin/env python3
"""
Load Lessons - Carga selectiva de lecciones aprendidas

Uso:
    python3 load_lessons.py <dominio> [opciones]

Dominios:
    lean4   - Verificación formal en Lean 4

Opciones:
    --category, -c CAT    Cargar archivo de categoría
    --problem, -p "text"  Buscar por descripción del problema
    --list, -l            Listar categorías disponibles
    --critical            Mostrar lecciones críticas
"""

import argparse
import os
import re
import sys
from pathlib import Path

# Base path for lessons
LESSONS_BASE = Path.home() / "Documents" / "claudio" / "lecciones"

# Domain configurations
DOMAINS = {
    "lean4": {
        "path": LESSONS_BASE / "lean4",
        "index": "INDEX.md",
        "categories": {
            "tacticas": "tacticas.md",
            "campos-finitos": "campos-finitos.md",
            "induccion": "induccion.md",
            "arquitectura": "arquitectura.md",
            "anti-patrones": "anti-patrones.md",
            "qa-workflow": "qa-workflow.md",
        },
        "critical": [
            ("L-015", "ZMod.val_injective - NUNCA trabajar directo con ZMod grande"),
            ("L-023", "omega necesita bounds explícitos - construir cadena manual"),
            ("L-049", "termination_by + decreasing_by para eliminar partial"),
            ("L-035", "Intentar probar axioma es la mejor auditoría"),
            ("L-078", "Statement más fuerte = IH más fuerte"),
        ],
    }
}


def load_index(domain: str) -> str:
    """Load and return the INDEX.md content for a domain."""
    config = DOMAINS.get(domain)
    if not config:
        return f"Error: Dominio '{domain}' no encontrado. Disponibles: {list(DOMAINS.keys())}"

    index_path = config["path"] / config["index"]
    if not index_path.exists():
        return f"Error: INDEX.md no encontrado en {index_path}"

    return index_path.read_text()


def load_category(domain: str, category: str) -> str:
    """Load and return a specific category file."""
    config = DOMAINS.get(domain)
    if not config:
        return f"Error: Dominio '{domain}' no encontrado."

    if category not in config["categories"]:
        available = ", ".join(config["categories"].keys())
        return f"Error: Categoría '{category}' no encontrada. Disponibles: {available}"

    cat_path = config["path"] / config["categories"][category]
    if not cat_path.exists():
        return f"Error: Archivo {cat_path} no encontrado."

    return cat_path.read_text()


def search_problem(domain: str, problem: str) -> str:
    """Search INDEX.md for relevant lessons based on problem description."""
    config = DOMAINS.get(domain)
    if not config:
        return f"Error: Dominio '{domain}' no encontrado."

    index_path = config["path"] / config["index"]
    if not index_path.exists():
        return f"Error: INDEX.md no encontrado."

    index_content = index_path.read_text().lower()
    problem_lower = problem.lower()

    # Search for matching rows in the problem table
    results = []

    # Find the "Búsqueda Rápida por Problema" section
    lines = index_path.read_text().split('\n')
    in_table = False

    for line in lines:
        if "Búsqueda Rápida por Problema" in line:
            in_table = True
            continue
        if in_table and line.startswith('|') and '---' not in line:
            # Check if any word from problem matches this line
            words = problem_lower.split()
            if any(word in line.lower() for word in words):
                results.append(line)
        if in_table and line.startswith('##') and "Búsqueda" not in line:
            break

    if not results:
        return f"No se encontraron lecciones para '{problem}'.\n\nConsulta el índice completo:\n{load_index(domain)}"

    output = f"Lecciones encontradas para '{problem}':\n\n"
    output += "| Problema | Archivo | Secciones |\n"
    output += "|----------|---------|----------|\n"
    for r in results:
        output += r + "\n"

    # Extract category from first result and suggest loading it
    if results:
        match = re.search(r'`([^`]+\.md)`', results[0])
        if match:
            cat_file = match.group(1).replace('.md', '')
            output += f"\n**Sugerencia**: Cargar categoría con:\n"
            output += f"  /load-lessons {domain} -c {cat_file}\n"

    return output


def list_categories(domain: str) -> str:
    """List available categories for a domain."""
    config = DOMAINS.get(domain)
    if not config:
        return f"Error: Dominio '{domain}' no encontrado."

    output = f"Categorías disponibles para {domain}:\n\n"
    output += "| Categoría | Archivo | Descripción |\n"
    output += "|-----------|---------|-------------|\n"

    descriptions = {
        "tacticas": "simp, omega, rfl, congr, split_ifs",
        "campos-finitos": "ZMod, GoldilocksField, homomorfismos",
        "induccion": "terminación, WF-recursion, partial",
        "arquitectura": "bridge lemmas, axiomatización, Memory",
        "anti-patrones": "errores comunes, tipos inadecuados",
        "qa-workflow": "integración QA, consulta expertos",
    }

    for cat, filename in config["categories"].items():
        desc = descriptions.get(cat, "")
        output += f"| {cat} | {filename} | {desc} |\n"

    return output


def show_critical(domain: str) -> str:
    """Show critical lessons that should be memorized."""
    config = DOMAINS.get(domain)
    if not config:
        return f"Error: Dominio '{domain}' no encontrado."

    output = f"Lecciones Críticas - {domain.upper()} (MEMORIZAR)\n"
    output += "=" * 50 + "\n\n"

    for lesson_id, description in config["critical"]:
        output += f"**{lesson_id}**: {description}\n\n"

    output += "\nEstas lecciones resuelven los problemas más frecuentes.\n"
    output += "Aplicarlas ANTES de buscar otras soluciones.\n"

    return output


def main():
    parser = argparse.ArgumentParser(
        description="Carga selectiva de lecciones aprendidas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  %(prog)s lean4                      # Muestra índice
  %(prog)s lean4 --list               # Lista categorías
  %(prog)s lean4 -c campos-finitos    # Carga categoría
  %(prog)s lean4 -p "ZMod timeout"    # Busca por problema
  %(prog)s lean4 --critical           # Lecciones críticas
        """
    )

    parser.add_argument("domain", nargs="?", default=None,
                        help="Dominio de lecciones (lean4, rust, etc.)")
    parser.add_argument("-c", "--category", type=str,
                        help="Cargar archivo de categoría específica")
    parser.add_argument("-p", "--problem", type=str,
                        help="Buscar lección por descripción del problema")
    parser.add_argument("-l", "--list", action="store_true",
                        help="Listar categorías disponibles")
    parser.add_argument("--critical", action="store_true",
                        help="Mostrar lecciones críticas")

    args = parser.parse_args()

    # No domain specified
    if not args.domain:
        print("Dominios disponibles:")
        for d in DOMAINS:
            print(f"  {d}")
        print("\nUso: load_lessons.py <dominio> [opciones]")
        print("Ayuda: load_lessons.py --help")
        return

    domain = args.domain.lower()

    if domain not in DOMAINS:
        print(f"Error: Dominio '{domain}' no encontrado.")
        print(f"Disponibles: {', '.join(DOMAINS.keys())}")
        sys.exit(1)

    # Handle options
    if args.critical:
        print(show_critical(domain))
    elif args.list:
        print(list_categories(domain))
    elif args.category:
        print(load_category(domain, args.category))
    elif args.problem:
        print(search_problem(domain, args.problem))
    else:
        # Default: show index
        print(load_index(domain))


if __name__ == "__main__":
    main()
