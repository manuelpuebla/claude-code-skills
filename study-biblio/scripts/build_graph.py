#!/usr/bin/env python3
"""
build_graph.py - Build a conceptual dependency graph from per-PDF summaries.

Incremental by default: detects new/modified/removed summaries via content
hashes stored in _meta.summary_hashes. Only new/modified docs are sent to
Gemini. Use --full to force a complete rebuild.

Graph structure:
{
    "nodes": {
        "concept_id": {
            "label": "Human-readable name",
            "category": "algorithm|structure|field|technique|application",
            "documents": ["folder/slug.md", ...]
        }
    },
    "edges": [
        {
            "from": "concept_id",
            "to": "concept_id",
            "type": "depends_on|extends|applies|related",
            "weight": 0.0-1.0
        }
    ],
    "document_concepts": {
        "folder/slug.md": ["concept_id1", "concept_id2", ...]
    },
    "_meta": {
        "summary_hashes": {
            "folder/slug.md": "<sha256_prefix_16>"
        }
    }
}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from utils import INDICES_DIR, CONCEPT_GRAPH_PATH, create_gemini_client

GEMINI_MODEL = "gemini-2.0-flash"

GRAPH_EXTRACTION_PROMPT = """You are building a concept dependency graph for a research library.

Given concept lists from academic papers, extract:
1. Key CONCEPTS (nodes) - specific technical concepts, algorithms, structures
2. RELATIONSHIPS (edges) between concepts

Output ONLY valid JSON with this EXACT structure (NO document_concepts, NO markdown fences):
{"nodes":{"concept-id":{"label":"Name","category":"algorithm"}},"edges":[{"from":"a","to":"b","type":"depends_on","weight":0.8}]}

Rules:
- concept_id: lowercase, hyphens, no spaces (e.g., "ntt", "montgomery-reduction")
- categories: algorithm, structure, field, technique, application
- edge types: depends_on, extends, applies, related
- weight: 0.0 (weak) to 1.0 (strong)
- Include 15-40 concepts per batch
- Focus on SPECIFIC concepts, not generic ones like "mathematics"
- Keep concept IDs SHORT (max 4 words)
- Output ONLY raw JSON, NO markdown fences, NO explanation, NO document_concepts
"""


def collect_summaries() -> dict[str, str]:
    """Collect all per-PDF summaries from indices/."""
    summaries = {}
    for md_file in sorted(INDICES_DIR.rglob("*.md")):
        # Skip folder indices and global index
        if md_file.name.startswith("_"):
            continue
        rel = str(md_file.relative_to(INDICES_DIR))
        summaries[rel] = md_file.read_text()
    return summaries


def _hash_content(content: str) -> str:
    """SHA256 prefix (16 hex chars) of summary content for change detection."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _compute_delta(
    summaries: dict[str, str], existing_graph: dict
) -> tuple[dict[str, str], list[str]]:
    """Determine which docs are new/modified/removed vs the existing graph.

    Returns:
        new_or_modified: {filename: content} needing Gemini processing
        removed: filenames present in graph but no longer on disk
    """
    old_hashes = existing_graph.get("_meta", {}).get("summary_hashes", {})

    new_or_modified = {}
    for filename, content in summaries.items():
        current_hash = _hash_content(content)
        if filename not in old_hashes or old_hashes[filename] != current_hash:
            new_or_modified[filename] = content

    removed = [f for f in old_hashes if f not in summaries]

    return new_or_modified, removed


def _remove_docs_from_graph(graph: dict, docs_to_remove: list[str]) -> None:
    """Remove document associations from graph (in-place).

    Cleans document_concepts, node.documents, and _meta.summary_hashes.
    """
    if not docs_to_remove:
        return
    remove_set = set(docs_to_remove)

    # Clean document_concepts
    doc_concepts = graph.get("document_concepts", {})
    for doc in docs_to_remove:
        doc_concepts.pop(doc, None)

    # Clean node.documents lists
    for cid, info in graph.get("nodes", {}).items():
        docs = info.get("documents", [])
        if docs:
            info["documents"] = [d for d in docs if d not in remove_set]

    # Clean _meta hashes
    meta_hashes = graph.get("_meta", {}).get("summary_hashes", {})
    for doc in docs_to_remove:
        meta_hashes.pop(doc, None)


def extract_concepts_compact(filename: str, content: str) -> str:
    """Extract only Key Concepts and Dependencies from a summary for graph building.

    This reduces input size ~5x vs sending the full summary.
    """
    lines = content.split("\n")
    title = ""
    sections = {}
    current_section = None

    for line in lines:
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            current_section = line[3:].strip()
            sections[current_section] = []
        elif current_section and line.strip():
            sections[current_section].append(line.strip())

    parts = [f"**{filename}**: {title}"]
    for key in ["Key Concepts", "Mathematical Objects", "Dependencies (Prerequisite Knowledge)",
                "Applications", "Related Topics"]:
        if key in sections and sections[key]:
            items = [l.lstrip("*- ") for l in sections[key] if l.lstrip("*- ")]
            if items:
                parts.append(f"  {key}: {', '.join(items)}")

    return "\n".join(parts)


def _call_gemini_for_graph(client, combined: str, num_docs: int, verbose: bool = False) -> dict:
    """Send a batch of compact summaries to Gemini and parse the graph JSON."""
    prompt = f"""{GRAPH_EXTRACTION_PROMPT}

## Documents ({num_docs} total):

{combined}
"""
    if verbose:
        print(f"  Sending {len(combined)} chars to Gemini...", file=sys.stderr)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={
            "temperature": 0.1,
            "max_output_tokens": 16384,
        }
    )
    if not response or not response.text:
        raise ValueError("Gemini returned no response")

    raw = response.text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines)

    return json.loads(raw)


def _merge_graphs(graphs: list[dict]) -> dict:
    """Merge multiple sub-graphs into one unified graph."""
    merged = {"nodes": {}, "edges": [], "document_concepts": {}}

    seen_edges = set()
    for g in graphs:
        # Merge nodes
        for cid, info in g.get("nodes", {}).items():
            if cid not in merged["nodes"]:
                merged["nodes"][cid] = info
            else:
                # Merge document lists
                existing_docs = merged["nodes"][cid].get("documents", [])
                new_docs = info.get("documents", [])
                merged["nodes"][cid]["documents"] = list(set(existing_docs + new_docs))

        # Merge edges (deduplicate)
        for e in g.get("edges", []):
            key = (e["from"], e["to"], e["type"])
            if key not in seen_edges:
                seen_edges.add(key)
                merged["edges"].append(e)

        # Merge document_concepts
        for doc, concepts in g.get("document_concepts", {}).items():
            if doc not in merged["document_concepts"]:
                merged["document_concepts"][doc] = concepts
            else:
                merged["document_concepts"][doc] = list(
                    set(merged["document_concepts"][doc] + concepts))

    return merged


def _merge_into_existing(existing: dict, new_graph: dict) -> None:
    """Merge a new sub-graph into the existing graph (in-place)."""
    existing_nodes = existing.setdefault("nodes", {})
    existing_edges = existing.setdefault("edges", [])

    for cid, info in new_graph.get("nodes", {}).items():
        if cid not in existing_nodes:
            existing_nodes[cid] = info
        else:
            old_docs = existing_nodes[cid].get("documents", [])
            new_docs = info.get("documents", [])
            existing_nodes[cid]["documents"] = list(set(old_docs + new_docs))

    seen = {(e["from"], e["to"], e["type"]) for e in existing_edges}
    for e in new_graph.get("edges", []):
        key = (e["from"], e["to"], e["type"])
        if key not in seen:
            seen.add(key)
            existing_edges.append(e)


def _assign_doc_concepts(
    graph: dict, summaries: dict[str, str], doc_subset: Optional[list[str]] = None
) -> None:
    """Assign concepts to documents by matching concept labels in summary text.

    Uses an inverted label→cid index instead of the previous O(docs×nodes)
    nested loop. Only processes docs in doc_subset (all docs if None).

    Note: in incremental mode, new concepts from new docs won't be matched
    against existing docs. Use --full for complete re-association.
    """
    nodes = graph.get("nodes", {})
    doc_concepts = graph.setdefault("document_concepts", {})

    # Build inverted index: {lowercase_term: concept_id}
    label_to_cid: dict[str, str] = {}
    for cid, info in nodes.items():
        label = info.get("label", cid).lower()
        label_to_cid[label] = cid
        id_as_words = cid.replace("-", " ")
        if id_as_words != label:
            label_to_cid[id_as_words] = cid

    targets = doc_subset if doc_subset is not None else list(summaries.keys())

    for filename in targets:
        content = summaries.get(filename)
        if not content:
            continue
        content_lower = content.lower()
        matched = set()
        for term, cid in label_to_cid.items():
            if term in content_lower:
                matched.add(cid)

        if matched:
            doc_concepts[filename] = sorted(matched)

        # Update node.documents
        for cid in matched:
            if cid in nodes:
                docs_list = nodes[cid].setdefault("documents", [])
                if filename not in docs_list:
                    docs_list.append(filename)


def _build_adjacency(graph: dict) -> None:
    """Build adjacency_out and adjacency_in indices from the edge list (in-place).

    adjacency_out[cid] = [{"to": ..., "type": ..., "weight": ...}, ...]
    adjacency_in[cid]  = [{"from": ..., "type": ..., "weight": ...}, ...]

    Converts O(E) edge scans per query to O(degree) lookups.
    """
    adj_out: dict[str, list] = {}
    adj_in: dict[str, list] = {}

    for e in graph.get("edges", []):
        src, dst = e["from"], e["to"]
        adj_out.setdefault(src, []).append(
            {"to": dst, "type": e["type"], "weight": e.get("weight", 0.5)})
        adj_in.setdefault(dst, []).append(
            {"from": src, "type": e["type"], "weight": e.get("weight", 0.5)})

    graph["adjacency_out"] = adj_out
    graph["adjacency_in"] = adj_in


def _load_existing_graph() -> dict:
    """Load existing graph from disk, or return empty structure."""
    if CONCEPT_GRAPH_PATH.exists():
        try:
            return json.loads(CONCEPT_GRAPH_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"nodes": {}, "edges": [], "document_concepts": {}, "_meta": {"summary_hashes": {}}}


def build_graph(verbose: bool = False, full: bool = False) -> dict:
    """Build the concept graph from all summaries.

    Incremental by default: only processes new/modified summaries and merges
    into the existing graph. Use full=True to force a complete rebuild.
    """
    summaries = collect_summaries()

    if not summaries:
        return {"status": "error", "error": "No summaries found. Run study-folder first."}

    if verbose:
        print(f"Found {len(summaries)} summaries", file=sys.stderr)

    # --- Delta detection ---
    if full:
        graph = {"nodes": {}, "edges": [], "document_concepts": {}, "_meta": {"summary_hashes": {}}}
        to_process = summaries
        removed = []
        if verbose:
            print("Full rebuild requested", file=sys.stderr)
    else:
        graph = _load_existing_graph()
        to_process, removed = _compute_delta(summaries, graph)

        # Clean associations for modified docs that already existed in graph
        modified_in_graph = [f for f in to_process if f in graph.get("document_concepts", {})]
        if modified_in_graph:
            _remove_docs_from_graph(graph, modified_in_graph)
            if verbose:
                print(f"Cleaned {len(modified_in_graph)} modified docs from graph", file=sys.stderr)

        if removed:
            _remove_docs_from_graph(graph, removed)
            if verbose:
                print(f"Removed {len(removed)} deleted docs from graph", file=sys.stderr)

        if not to_process:
            if verbose:
                print("No new or modified summaries — graph is up to date", file=sys.stderr)
            # Rebuild adjacency + save if we removed docs or indices are missing
            needs_save = removed or "adjacency_out" not in graph
            if needs_save:
                _build_adjacency(graph)
                CONCEPT_GRAPH_PATH.write_text(
                    json.dumps(graph, indent=2, ensure_ascii=False))
            nodes = graph.get("nodes", {})
            return {
                "status": "up_to_date",
                "nodes": len(nodes),
                "edges": len(graph.get("edges", [])),
                "documents": len(graph.get("document_concepts", {})),
                "new": 0,
                "removed": len(removed),
                "path": str(CONCEPT_GRAPH_PATH),
            }

        if verbose:
            print(f"Incremental: {len(to_process)} new/modified, "
                  f"{len(removed)} removed", file=sys.stderr)

    # --- Batch processing (only delta docs) ---
    client = create_gemini_client()

    compact = {fn: extract_concepts_compact(fn, c) for fn, c in to_process.items()}

    BATCH_SIZE = 12
    filenames = sorted(compact.keys())
    batches = [filenames[i:i + BATCH_SIZE] for i in range(0, len(filenames), BATCH_SIZE)]

    sub_graphs = []
    DELAY_BETWEEN_BATCHES = 3
    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 30

    for batch_idx, batch_files in enumerate(batches, 1):
        if verbose:
            print(f"\nBatch {batch_idx}/{len(batches)} ({len(batch_files)} docs)",
                  file=sys.stderr)

        parts = [compact[fn] for fn in batch_files]
        combined = "\n\n".join(parts)

        success = False
        for retry in range(MAX_RETRIES):
            try:
                sub_graph = _call_gemini_for_graph(
                    client, combined, len(batch_files), verbose=verbose)
                sub_graphs.append(sub_graph)
                if verbose:
                    print(f"  Got {len(sub_graph.get('nodes', {}))} nodes, "
                          f"{len(sub_graph.get('edges', []))} edges", file=sys.stderr)
                success = True
                break
            except (json.JSONDecodeError, ValueError) as e:
                print(f"  WARNING: Batch {batch_idx} failed: {e}", file=sys.stderr)
                break  # don't retry parse errors
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    wait = RETRY_BASE_DELAY * (2 ** retry)
                    print(f"  Rate limited. Waiting {wait}s "
                          f"(retry {retry + 1}/{MAX_RETRIES})...", file=sys.stderr)
                    time.sleep(wait)
                else:
                    print(f"  WARNING: Batch {batch_idx} failed: {e}", file=sys.stderr)
                    break  # don't retry unknown errors

        if not success and verbose:
            print(f"  Skipping batch {batch_idx} after retries", file=sys.stderr)

        # Delay between batches to avoid rate limits
        if batch_idx < len(batches):
            time.sleep(DELAY_BETWEEN_BATCHES)

    if not sub_graphs:
        if full:
            return {"status": "error", "error": "All graph extractions failed"}
        # Incremental: keep existing graph even if new batches failed
        if verbose:
            print("WARNING: New batch extractions failed, keeping existing graph",
                  file=sys.stderr)
    else:
        # Merge new sub-graphs
        new_graph = _merge_graphs(sub_graphs) if len(sub_graphs) > 1 else sub_graphs[0]

        if full:
            graph["nodes"] = new_graph.get("nodes", {})
            graph["edges"] = new_graph.get("edges", [])
        else:
            _merge_into_existing(graph, new_graph)

    # --- Assign document_concepts (only for delta docs in incremental mode) ---
    delta_docs = list(to_process.keys()) if not full else None
    _assign_doc_concepts(graph, summaries, doc_subset=delta_docs)

    # --- Update summary hashes for all current docs ---
    meta = graph.setdefault("_meta", {})
    hashes = meta.setdefault("summary_hashes", {})
    for filename, content in summaries.items():
        hashes[filename] = _hash_content(content)

    # --- Build adjacency indices ---
    _build_adjacency(graph)

    # --- Save ---
    CONCEPT_GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONCEPT_GRAPH_PATH.write_text(json.dumps(graph, indent=2, ensure_ascii=False))

    nodes = graph.get("nodes", {})
    if verbose:
        print(f"\nGraph saved: {len(nodes)} nodes, {len(graph.get('edges', []))} edges",
              file=sys.stderr)
        print(f"Written to: {CONCEPT_GRAPH_PATH}", file=sys.stderr)

    return {
        "status": "completed",
        "nodes": len(nodes),
        "edges": len(graph.get("edges", [])),
        "documents": len(graph.get("document_concepts", {})),
        "new": len(to_process),
        "removed": len(removed),
        "path": str(CONCEPT_GRAPH_PATH),
    }


def main():
    parser = argparse.ArgumentParser(description="Build concept graph from PDF summaries")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed progress")
    parser.add_argument("--full", action="store_true",
                        help="Force full rebuild (ignore incremental cache)")
    args = parser.parse_args()

    result = build_graph(verbose=args.verbose, full=args.full)
    print(json.dumps(result, indent=2))

    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
