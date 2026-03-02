#!/usr/bin/env python3
"""
query_graph.py - Query the concept graph.

Supports: topic search, dependency tree, path finding, document lookup.
Uses adjacency_out / adjacency_in indices for O(degree) lookups instead
of scanning the full edge list.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from utils import CONCEPT_GRAPH_PATH


def load_graph() -> dict:
    """Load the concept graph from disk."""
    if not CONCEPT_GRAPH_PATH.exists():
        print("ERROR: Concept graph not found. Run build_graph.py first.", file=sys.stderr)
        sys.exit(1)
    return json.loads(CONCEPT_GRAPH_PATH.read_text())


def _get_adj_out(graph: dict) -> dict[str, list]:
    """Get outgoing adjacency index, building on the fly if absent."""
    if "adjacency_out" in graph:
        return graph["adjacency_out"]
    # Fallback for graphs saved before adjacency indices were added
    adj: dict[str, list] = {}
    for e in graph.get("edges", []):
        adj.setdefault(e["from"], []).append(
            {"to": e["to"], "type": e["type"], "weight": e.get("weight", 0.5)})
    return adj


def _get_adj_in(graph: dict) -> dict[str, list]:
    """Get incoming adjacency index, building on the fly if absent."""
    if "adjacency_in" in graph:
        return graph["adjacency_in"]
    adj: dict[str, list] = {}
    for e in graph.get("edges", []):
        adj.setdefault(e["to"], []).append(
            {"from": e["from"], "type": e["type"], "weight": e.get("weight", 0.5)})
    return adj


def _find_concept(nodes: dict, query: str) -> Optional[str]:
    """Fuzzy-match a concept ID by query string."""
    q = query.lower()
    for cid in nodes:
        if q in cid or q in nodes[cid].get("label", "").lower():
            return cid
    return None


def search_topic(graph: dict, query: str) -> str:
    """Search for concepts matching a query string."""
    query_lower = query.lower()
    nodes = graph.get("nodes", {})
    adj_out = _get_adj_out(graph)
    adj_in = _get_adj_in(graph)

    matches = []
    for cid, info in nodes.items():
        label = info.get("label", cid)
        if query_lower in cid or query_lower in label.lower():
            matches.append((cid, info))

    if not matches:
        return f"No concepts found matching '{query}'.\n\nAvailable concepts ({len(nodes)}):\n" + \
               "\n".join(f"  - {info.get('label', cid)} [{info.get('category', '?')}]"
                         for cid, info in sorted(nodes.items())[:30])

    lines = [f"# Concepts matching '{query}' ({len(matches)} found)\n"]

    for cid, info in matches:
        label = info.get("label", cid)
        category = info.get("category", "unknown")
        docs = info.get("documents", [])

        lines.append(f"## {label}")
        lines.append(f"**ID**: `{cid}` | **Category**: {category}")

        if docs:
            lines.append(f"**Documents**: {', '.join(docs)}")

        outgoing = adj_out.get(cid, [])
        incoming = adj_in.get(cid, [])

        if outgoing:
            lines.append("**Connects to**:")
            for e in outgoing:
                target_label = nodes.get(e["to"], {}).get("label", e["to"])
                lines.append(f"  - {target_label} [{e['type']}, w={e['weight']}]")

        if incoming:
            lines.append("**Connected from**:")
            for e in incoming:
                source_label = nodes.get(e["from"], {}).get("label", e["from"])
                lines.append(f"  - {source_label} [{e['type']}, w={e['weight']}]")

        lines.append("")

    return "\n".join(lines)


def find_deps(graph: dict, concept: str) -> str:
    """Find all upstream dependencies of a concept (BFS on depends_on edges)."""
    nodes = graph.get("nodes", {})
    adj_in = _get_adj_in(graph)

    target = _find_concept(nodes, concept)
    if not target:
        return f"Concept '{concept}' not found in graph."

    # BFS: follow depends_on edges backward
    # adjacency_in[cid] has entries like {"from": dep, "type": "depends_on", ...}
    # meaning dep --depends_on--> cid, so dep is a prerequisite of cid
    visited = set()
    queue = deque([target])
    deps = []
    levels = {target: 0}

    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)

        for e in adj_in.get(current, []):
            if e["type"] == "depends_on":
                dep = e["from"]
                if dep not in visited:
                    queue.append(dep)
                    levels[dep] = levels[current] + 1
                    deps.append((dep, levels[dep], e["weight"]))

    if not deps:
        return f"No upstream dependencies found for '{nodes[target].get('label', target)}'."

    target_label = nodes[target].get("label", target)
    lines = [f"# Dependencies of '{target_label}'\n"]

    max_level = max(d[1] for d in deps)
    for level in range(1, max_level + 1):
        level_deps = [(d[0], d[2]) for d in deps if d[1] == level]
        indent = "  " * (level - 1)
        for cid, weight in level_deps:
            label = nodes.get(cid, {}).get("label", cid)
            lines.append(f"{indent}{'└── ' if level > 1 else '- '}{label} (w={weight})")

    return "\n".join(lines)


def find_path(graph: dict, concept_a: str, concept_b: str) -> str:
    """Find shortest path between two concepts (BFS, any edge type)."""
    nodes = graph.get("nodes", {})
    adj_out = _get_adj_out(graph)
    adj_in = _get_adj_in(graph)

    start = _find_concept(nodes, concept_a)
    end = _find_concept(nodes, concept_b)

    if not start:
        return f"Concept '{concept_a}' not found."
    if not end:
        return f"Concept '{concept_b}' not found."

    # Build undirected adjacency from the directed indices
    adj_undirected: dict[str, list[tuple[str, str]]] = {}
    for cid, edges_out in adj_out.items():
        for e in edges_out:
            adj_undirected.setdefault(cid, []).append((e["to"], e["type"]))
    for cid, edges_in in adj_in.items():
        for e in edges_in:
            adj_undirected.setdefault(cid, []).append((e["from"], e["type"]))

    # BFS
    visited = {start}
    queue = deque([(start, [(start, None)])])

    while queue:
        current, path = queue.popleft()
        if current == end:
            start_label = nodes[start].get("label", start)
            end_label = nodes[end].get("label", end)
            lines = [f"# Path: {start_label} → {end_label} ({len(path)-1} hops)\n"]
            for i, (cid, edge_type) in enumerate(path):
                label = nodes.get(cid, {}).get("label", cid)
                if i == 0:
                    lines.append(f"  {label}")
                else:
                    lines.append(f"  --[{edge_type}]--> {label}")
            return "\n".join(lines)

        for neighbor, etype in adj_undirected.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [(neighbor, etype)]))

    start_label = nodes[start].get("label", start)
    end_label = nodes[end].get("label", end)
    return f"No path found between '{start_label}' and '{end_label}'."


def show_docs(graph: dict, concept: str) -> str:
    """Show documents covering a concept."""
    nodes = graph.get("nodes", {})
    doc_concepts = graph.get("document_concepts", {})

    target = _find_concept(nodes, concept)
    if not target:
        return f"Concept '{concept}' not found in graph."

    label = nodes[target].get("label", target)
    docs = [doc for doc, concepts in doc_concepts.items() if target in concepts]

    if not docs:
        docs = nodes[target].get("documents", [])

    if not docs:
        return f"No documents found for concept '{label}'."

    lines = [f"# Documents covering '{label}'\n"]
    for doc in sorted(docs):
        lines.append(f"- `{doc}`")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Query the concept graph")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--topic", "-t", type=str, help="Search for a topic")
    group.add_argument("--deps", "-d", type=str, help="Show dependencies of a concept")
    group.add_argument("--path", "-p", nargs=2, metavar=("FROM", "TO"),
                       help="Find path between two concepts")
    group.add_argument("--docs", type=str, help="Show documents covering a concept")

    args = parser.parse_args()
    graph = load_graph()

    if args.topic:
        print(search_topic(graph, args.topic))
    elif args.deps:
        print(find_deps(graph, args.deps))
    elif args.path:
        print(find_path(graph, args.path[0], args.path[1]))
    elif args.docs:
        print(show_docs(graph, args.docs))


if __name__ == "__main__":
    main()
