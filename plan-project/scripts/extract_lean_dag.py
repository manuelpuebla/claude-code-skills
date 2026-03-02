#!/usr/bin/env python3
"""
extract_lean_dag.py - Extrae el grafo de dependencias formales de un proyecto Lean 4

Analiza archivos .lean para:
1. Encontrar todas las declaraciones (theorem, lemma, def, instance, abbrev)
2. Identificar cuáles contienen sorry
3. Construir grafo dirigido de dependencias entre declaraciones
4. Computar orden topológico seguro para eliminación de sorry
5. Clasificar nodos: FUNDACIONAL / CRÍTICO / HOJA / INTERMEDIO
6. Generar recomendaciones de firewall (_aux) por propagación de riesgo

Dos modos:
- static (default): Análisis regex, rápido, sin compilación
- compiler: Genera #print axioms, requiere lake (más preciso)

Uso:
  python3 extract_lean_dag.py /path/to/lean/project
  python3 extract_lean_dag.py /path/to/lean/project --format dag --sorry-only
  python3 extract_lean_dag.py /path/to/lean/project --format json
"""

import argparse
import json
import re
import sys
from collections import defaultdict, deque
from pathlib import Path


# ─── Paso 1: Encontrar archivos ─────────────────────────────────────────────

def find_lean_files(project_path: str, max_files: int = 200) -> list:
    """Encuentra archivos .lean del proyecto, excluyendo .lake y build."""
    project = Path(project_path)
    excluded = {".lake", "lake-packages", "build", ".git", "node_modules"}

    files = []
    for f in sorted(project.rglob("*.lean")):
        if any(part in excluded for part in f.parts):
            continue
        files.append(f)
        if len(files) >= max_files:
            break

    return files


# ─── Paso 2: Extraer declaraciones ──────────────────────────────────────────

DECL_PATTERN = re.compile(
    r'^(?:(?:private|protected|noncomputable|nonrec|unsafe|partial)\s+)*'
    r'(theorem|lemma|def|abbrev|instance)\s+'
    r'([^\s\(:{\[]+)',
    re.MULTILINE
)

# Patrón para detectar sección-level markers que NO son declaraciones
SECTION_PATTERN = re.compile(
    r'^(section|namespace|end|open|variable|import|#)',
    re.MULTILINE
)


def extract_declarations(file_path: Path) -> list:
    """Extrae declaraciones de un archivo .lean con su cuerpo aproximado."""
    try:
        content = file_path.read_text(encoding='utf-8')
    except (UnicodeDecodeError, OSError):
        return []

    declarations = []
    matches = list(DECL_PATTERN.finditer(content))

    for idx, match in enumerate(matches):
        kind = match.group(1)
        name = match.group(2).rstrip(':')

        # Ignorar nombres que son claramente keywords o artefactos
        if name in ('where', 'with', 'if', 'then', 'else', 'do', 'let', 'have', 'match'):
            continue

        start_pos = match.start()
        line_num = content[:start_pos].count('\n') + 1

        # Extraer cuerpo: desde el final del match hasta la siguiente declaración
        body_start = match.end()
        if idx + 1 < len(matches):
            body_end = matches[idx + 1].start()
        else:
            body_end = len(content)

        body = content[body_start:body_end]

        # Detectar sorry en el cuerpo
        has_sorry = bool(re.search(r'\bsorry\b', body))

        # Detectar si usa axiom
        uses_axiom = bool(re.search(r'\baxiom\b', body)) or bool(re.search(r'\bsorryAx\b', body))

        declarations.append({
            "name": name,
            "kind": kind,
            "file": str(file_path),
            "line": line_num,
            "has_sorry": has_sorry,
            "uses_axiom": uses_axiom,
            "_body": body,  # Interno, se elimina del output
        })

    return declarations


# ─── Paso 3: Construir grafo de dependencias ────────────────────────────────

def build_dependency_graph(declarations: list) -> tuple:
    """
    Construye grafo dirigido: A → B significa "A depende de B" (A usa B en su cuerpo).
    Retorna (graph, reverse_graph).
    - graph[A] = {B, C} → A depende de B y C
    - reverse_graph[B] = {A, D} → B es usado por A y D
    """
    all_names = {d["name"] for d in declarations}

    # Pre-compilar patrones para cada nombre (solo nombres razonablemente largos)
    name_patterns = {}
    for name in all_names:
        if len(name) >= 3:  # Ignorar nombres muy cortos que generan falsos positivos
            name_patterns[name] = re.compile(r'\b' + re.escape(name) + r'\b')

    graph = defaultdict(set)      # A depende de B
    reverse_graph = defaultdict(set)  # B es usado por A

    for decl in declarations:
        body = decl["_body"]
        my_name = decl["name"]

        for other_name, pattern in name_patterns.items():
            if other_name == my_name:
                continue
            if pattern.search(body):
                graph[my_name].add(other_name)
                reverse_graph[other_name].add(my_name)

    return dict(graph), dict(reverse_graph)


# ─── Paso 4: Propagación de sorry ───────────────────────────────────────────

def compute_sorry_propagation(declarations: list, reverse_graph: dict) -> tuple:
    """
    Computa qué declaraciones están transitivamente infectadas por sorry.
    Si A tiene sorry y B depende de A, B está infectado.

    Retorna (sorry_sources, all_infected).
    """
    sorry_sources = {d["name"] for d in declarations if d["has_sorry"]}

    # BFS desde cada sorry a través del reverse_graph
    infected = set(sorry_sources)
    queue = deque(sorry_sources)

    while queue:
        current = queue.popleft()
        for dependent in reverse_graph.get(current, set()):
            if dependent not in infected:
                infected.add(dependent)
                queue.append(dependent)

    return sorry_sources, infected


# ─── Paso 5: Fan-out y clasificación ────────────────────────────────────────

def compute_fan_out(reverse_graph: dict) -> dict:
    """Fan-out = cuántas declaraciones dependen directamente de esta."""
    return {name: len(deps) for name, deps in reverse_graph.items()}


def classify_nodes(declarations: list, graph: dict, reverse_graph: dict,
                   sorry_sources: set, fan_out: dict) -> dict:
    """
    Clasifica cada nodo del grafo:

    - FUNDACIONAL_SORRY:  Alto fan-out + tiene sorry → MÁXIMO RIESGO
    - FUNDACIONAL_PROBADO: Alto fan-out + sin sorry → Estable, no tocar
    - CRÍTICO:            Fan-out medio + sorry → Riesgo alto
    - HOJA_SORRY:         Fan-out 0 + sorry → Seguro de atacar primero
    - HOJA_PROBADO:       Fan-out 0 + sin sorry → Estable
    - INTERMEDIO_SORRY:   Fan-out bajo + sorry → Riesgo medio
    - INTERMEDIO_PROBADO: Fan-out bajo + sin sorry → Estable
    """
    classifications = {}

    for decl in declarations:
        name = decl["name"]
        fo = fan_out.get(name, 0)
        has_sorry = decl["has_sorry"]

        if fo >= 3:
            if has_sorry:
                classifications[name] = "FUNDACIONAL_SORRY"
            else:
                classifications[name] = "FUNDACIONAL_PROBADO"
        elif fo >= 1:
            if has_sorry:
                if fo >= 2:
                    classifications[name] = "CRÍTICO"
                else:
                    classifications[name] = "INTERMEDIO_SORRY"
            else:
                classifications[name] = "INTERMEDIO_PROBADO"
        else:
            if has_sorry:
                classifications[name] = "HOJA_SORRY"
            else:
                classifications[name] = "HOJA_PROBADO"

    return classifications


# ─── Paso 6: Orden topológico ────────────────────────────────────────────────

def compute_topological_order(graph: dict, declarations: list) -> tuple:
    """
    Computa orden topológico SOLO para declaraciones con sorry.
    Este es el orden seguro de eliminación: hojas primero, raíces al final.

    Retorna (order, cycles).
    - order: lista de nombres en orden de eliminación
    - cycles: lista de nombres involucrados en ciclos (si hay)
    """
    sorry_names = {d["name"] for d in declarations if d["has_sorry"]}

    if not sorry_names:
        return [], []

    # Subgrafo solo de sorry declarations
    in_degree = {name: 0 for name in sorry_names}
    sub_graph = defaultdict(set)

    for name in sorry_names:
        deps = graph.get(name, set())
        sorry_deps = deps & sorry_names
        for dep in sorry_deps:
            sub_graph[dep].add(name)
            in_degree[name] += 1

    # Kahn's algorithm
    queue = deque(sorted([n for n in sorry_names if in_degree[n] == 0]))
    order = []

    while queue:
        current = queue.popleft()
        order.append(current)
        for dependent in sorted(sub_graph.get(current, set())):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    # Detectar ciclos
    cycles = sorted(sorry_names - set(order)) if len(order) != len(sorry_names) else []

    return order, cycles


# ─── Paso 7: Análisis de firewall ───────────────────────────────────────────

def compute_firewall_analysis(declarations: list, reverse_graph: dict,
                              fan_out: dict) -> dict:
    """
    Para cada sorry, determina la estrategia de modificación segura:

    - MODIFICACIÓN_DIRECTA: fan-out 0, nadie depende → modificar libremente
    - MODIFICACIÓN_CAUTELOSA: fan-out 1-2 → verificar dependientes después
    - FIREWALL_OBLIGATORIO: fan-out ≥ 3 → usar técnica _aux antes de tocar
    """
    results = {}

    for decl in declarations:
        if not decl["has_sorry"]:
            continue

        name = decl["name"]
        fo = fan_out.get(name, 0)
        dependents = sorted(reverse_graph.get(name, set()))

        if fo == 0:
            results[name] = {
                "strategy": "MODIFICACIÓN_DIRECTA",
                "risk": "bajo",
                "reason": "Ningún otro teorema depende de este — modificar libremente",
                "dependents": [],
                "checkpoint": "Compilar solo este archivo después de cambio",
            }
        elif fo <= 2:
            results[name] = {
                "strategy": "MODIFICACIÓN_CAUTELOSA",
                "risk": "medio",
                "reason": f"{fo} teorema(s) dependen de este — verificar compatibilidad tras cambio",
                "dependents": dependents,
                "checkpoint": "Compilar este archivo + archivos de dependientes",
            }
        else:
            results[name] = {
                "strategy": "FIREWALL_OBLIGATORIO",
                "risk": "alto",
                "reason": f"{fo} teoremas dependen — crear _aux con signatura flexible, probar allí, luego migrar",
                "dependents": dependents,
                "checkpoint": "NO modificar signatura original hasta que _aux compile sin sorry",
            }

    return results


# ─── Paso 8: Compilación de resultados ──────────────────────────────────────

def build_result(project_path: str, files: list, declarations: list,
                 graph: dict, reverse_graph: dict, sorry_sources: set,
                 infected: set, fan_out: dict, classifications: dict,
                 topo_order: list, cycles: list, firewall: dict) -> dict:
    """Compila todos los análisis en un resultado estructurado."""

    # Limpiar declaraciones (remover _body)
    clean = []
    for d in declarations:
        entry = {k: v for k, v in d.items() if not k.startswith('_')}
        entry["classification"] = classifications.get(d["name"], "UNKNOWN")
        entry["fan_out"] = fan_out.get(d["name"], 0)
        entry["sorry_infected"] = d["name"] in infected
        if d["name"] in firewall:
            entry["firewall"] = firewall[d["name"]]
        clean.append(entry)

    return {
        "project_path": str(project_path),
        "files_scanned": len(files),
        "total_declarations": len(declarations),
        "sorry_count": len(sorry_sources),
        "sorry_infected_count": len(infected),
        "topological_order": topo_order,
        "cycles": cycles,
        "declarations": clean,
        "graph_edges": {k: sorted(v) for k, v in graph.items()},
        "firewall_analysis": firewall,
        "summary": {
            "hojas_sorry": sorted([
                d["name"] for d in clean
                if d.get("classification") == "HOJA_SORRY"
            ]),
            "fundacionales_sorry": sorted([
                d["name"] for d in clean
                if d.get("classification") == "FUNDACIONAL_SORRY"
            ]),
            "criticos": sorted([
                d["name"] for d in clean
                if d.get("classification") == "CRÍTICO"
            ]),
            "firewall_obligatorio": sorted([
                name for name, f in firewall.items()
                if f["strategy"] == "FIREWALL_OBLIGATORIO"
            ]),
            "modificacion_directa": sorted([
                name for name, f in firewall.items()
                if f["strategy"] == "MODIFICACIÓN_DIRECTA"
            ]),
            "modificacion_cautelosa": sorted([
                name for name, f in firewall.items()
                if f["strategy"] == "MODIFICACIÓN_CAUTELOSA"
            ]),
        },
    }


# ─── Output formateado ──────────────────────────────────────────────────────

def print_dag_format(result: dict):
    """Imprime el DAG en formato legible para humanos y para el plan."""
    r = result
    s = r["summary"]

    print("=" * 60)
    print("  DAG DE DEPENDENCIAS FORMALES (Lean 4)")
    print("=" * 60)
    print()
    print(f"  Archivos escaneados:      {r['files_scanned']}")
    print(f"  Declaraciones totales:    {r['total_declarations']}")
    print(f"  Sorries directos:         {r['sorry_count']}")
    print(f"  Infectados por sorry:     {r['sorry_infected_count']}")
    print()

    if r["cycles"]:
        print("  *** CICLOS DETECTADOS (problema de diseño) ***")
        for name in r["cycles"]:
            print(f"    - {name}")
        print()

    # Resumen por categoría
    print("-" * 60)
    print("  CLASIFICACIÓN DE NODOS CON SORRY")
    print("-" * 60)
    print()

    if s["fundacionales_sorry"]:
        print("  FUNDACIONAL_SORRY (máximo riesgo — firewall obligatorio):")
        for name in s["fundacionales_sorry"]:
            fo = r["firewall_analysis"].get(name, {}).get("dependents", [])
            print(f"    * {name}  (fan-out: {len(fo)}, dependientes: {', '.join(fo[:5])})")
        print()

    if s["criticos"]:
        print("  CRÍTICO (riesgo alto — evaluar firewall):")
        for name in s["criticos"]:
            print(f"    * {name}")
        print()

    if s["modificacion_directa"]:
        print("  HOJA_SORRY (riesgo bajo — atacar primero):")
        for name in s["modificacion_directa"]:
            print(f"    * {name}")
        print()

    if s["modificacion_cautelosa"]:
        print("  INTERMEDIO_SORRY (riesgo medio — precaución):")
        for name in s["modificacion_cautelosa"]:
            deps = r["firewall_analysis"].get(name, {}).get("dependents", [])
            print(f"    * {name}  → dependen: {', '.join(deps)}")
        print()

    # Orden topológico
    print("-" * 60)
    print("  ORDEN TOPOLÓGICO DE ELIMINACIÓN (plan de trabajo)")
    print("-" * 60)
    print()

    decl_map = {d["name"]: d for d in r["declarations"]}

    for i, name in enumerate(r["topological_order"], 1):
        decl = decl_map.get(name, {})
        fw = r["firewall_analysis"].get(name, {})
        cls = decl.get("classification", "?")
        risk = fw.get("risk", "?")
        strategy = fw.get("strategy", "?")
        checkpoint = fw.get("checkpoint", "")
        file_loc = f"{decl.get('file', '?')}:{decl.get('line', '?')}"

        print(f"  {i}. {name}")
        print(f"     Ubicación:     {file_loc}")
        print(f"     Clasificación: {cls}")
        print(f"     Riesgo:        {risk}")
        print(f"     Estrategia:    {strategy}")
        if fw.get("dependents"):
            print(f"     Dependientes:  {', '.join(fw['dependents'])}")
        if checkpoint:
            print(f"     Checkpoint:    {checkpoint}")
        print()

    # Recomendaciones
    print("-" * 60)
    print("  RECOMENDACIONES DE SEGURIDAD")
    print("-" * 60)
    print()
    print("  1. Atacar HOJAS primero (riesgo bajo, sin efecto cascada)")
    print("  2. Para FUNDACIONAL/CRÍTICO: crear theorem _aux con signatura flexible")
    print("  3. Compilar después de CADA eliminación (no acumular cambios)")
    print("  4. Si un sorry requiere cambio de signatura en nodo con fan-out ≥ 3:")
    print("     → NO modificar el original hasta que _aux compile sin sorry")
    print("  5. Consultar expertos (/ask-lean, /ask-dojo) para nodos FUNDACIONALES")
    print()


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Extrae grafo de dependencias formales de proyecto Lean 4"
    )
    parser.add_argument(
        "project_path",
        help="Ruta al proyecto Lean 4"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "dag", "summary"],
        default="dag",
        help="Formato de salida: json (máquina), dag (humano), summary (compacto)"
    )
    parser.add_argument(
        "--sorry-only", "-s",
        action="store_true",
        help="Solo mostrar declaraciones con sorry o infectadas"
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=200,
        help="Máximo de archivos a escanear"
    )

    args = parser.parse_args()
    project_path = Path(args.project_path)

    if not project_path.exists():
        print(json.dumps({"error": f"Ruta no encontrada: {project_path}"}))
        sys.exit(1)

    # ── Ejecutar pipeline ──

    files = find_lean_files(str(project_path), args.max_files)

    if not files:
        print(json.dumps({"error": "No se encontraron archivos .lean", "path": str(project_path)}))
        sys.exit(1)

    # Extraer declaraciones
    all_declarations = []
    for f in files:
        decls = extract_declarations(f)
        all_declarations.extend(decls)

    if not all_declarations:
        print(json.dumps({
            "error": "No se encontraron declaraciones",
            "files_scanned": len(files)
        }))
        sys.exit(1)

    # Construir grafo
    graph, reverse_graph = build_dependency_graph(all_declarations)

    # Análisis
    sorry_sources, infected = compute_sorry_propagation(all_declarations, reverse_graph)
    fan_out = compute_fan_out(reverse_graph)
    classifications = classify_nodes(
        all_declarations, graph, reverse_graph, sorry_sources, fan_out
    )
    topo_order, cycles = compute_topological_order(graph, all_declarations)
    firewall = compute_firewall_analysis(all_declarations, reverse_graph, fan_out)

    # Compilar resultado
    result = build_result(
        str(project_path), files, all_declarations,
        graph, reverse_graph, sorry_sources, infected,
        fan_out, classifications, topo_order, cycles, firewall
    )

    # Filtrar si sorry-only
    if args.sorry_only:
        result["declarations"] = [
            d for d in result["declarations"]
            if d.get("has_sorry") or d.get("sorry_infected")
        ]

    # Output
    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.format == "dag":
        print_dag_format(result)
    elif args.format == "summary":
        s = result["summary"]
        print(json.dumps({
            "sorry_count": result["sorry_count"],
            "infected_count": result["sorry_infected_count"],
            "topological_order": result["topological_order"],
            "cycles": result["cycles"],
            "hojas_sorry": s["hojas_sorry"],
            "fundacionales_sorry": s["fundacionales_sorry"],
            "criticos": s["criticos"],
            "firewall_obligatorio": s["firewall_obligatorio"],
        }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
