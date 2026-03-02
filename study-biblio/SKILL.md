---
name: study-biblio
description: Indexa PDFs de la biblioteca usando Gemini Flash. Genera resúmenes, índices por carpeta, índice global y grafo conceptual. Opera incrementalmente.
allowed-tools: Bash(python3 *)
argument-hint: "study-all | study-folder <folder> | study-pdf <path> | status | query \"topic\" | ?"
---

# study-biblio: Indexador de Biblioteca PDF

Estudia PDFs en `~/Documents/claudio/biblioteca/`, genera índices estructurados y un grafo conceptual de dependencias. Usa Gemini Flash para extracción semántica. Opera incrementalmente (no repite trabajo).

## Help Request Detection

If the user invokes with `?`, `--help`, `help`, or asks how to use it, show this quick reference instead of running the script:

```
/study-biblio - PDF Library Indexer with Concept Graph

USAGE:
  /study-biblio <command> [options]

COMMANDS:
  study-all                    Index all unindexed PDFs + build graph
  study-folder <folder>        Index one folder (e.g., "ntt", "criptografia")
  study-pdf <path>             Index a single PDF
  status                       Show indexing progress (indexed vs pending)
  query "topic"                Search topic in concept graph
  query --deps "concept"       Show upstream dependencies
  query --path "A" "B"         Find path between two concepts

OPTIONS:
  --force, -f                  Re-index even if already indexed
  --verbose, -v                Show detailed progress

EXAMPLES:
  /study-biblio status                          # See progress
  /study-biblio study-folder ntt                # Index ntt/ folder
  /study-biblio study-all                       # Index everything
  /study-biblio query "NTT"                     # Search NTT in graph
  /study-biblio query --deps "poseidon"         # What does Poseidon depend on?
  /study-biblio query --path "NTT" "zero-knowledge"  # Path between concepts

OUTPUT:
  ~/Documents/claudio/biblioteca/indices/
  ├── manifest.json                 # Indexing state
  ├── _global_topic_index.md        # General topic index
  ├── _concept_graph.json           # Conceptual DAG
  ├── ntt/
  │   ├── _folder_index.md          # Folder index
  │   └── <slug>.md                 # Per-PDF summary
  └── ...
```

## How to Use

When the user invokes this skill, parse the command and run the appropriate script.

## Execution

### study-all
```bash
python3 $SKILL_DIR/scripts/study_all.py {--force} {--verbose}
```
Indexes all unindexed PDFs, generates folder indices, global index, and concept graph.

### study-folder
```bash
python3 $SKILL_DIR/scripts/study_folder.py "{FOLDER_NAME}" {--force} {--verbose}
```
Indexes all unindexed PDFs in the specified folder and generates its `_folder_index.md`.

### study-pdf
```bash
python3 $SKILL_DIR/scripts/study_pdf.py "{PDF_PATH}" {--force}
```
Indexes a single PDF. Path can be absolute or relative to biblioteca/.

### status
```bash
python3 $SKILL_DIR/scripts/show_status.py
```
Shows indexing progress per folder.

### query
```bash
python3 $SKILL_DIR/scripts/query_graph.py --topic "{QUERY}"
python3 $SKILL_DIR/scripts/query_graph.py --deps "{CONCEPT}"
python3 $SKILL_DIR/scripts/query_graph.py --path "{CONCEPT_A}" "{CONCEPT_B}"
```

## Architecture

Raw PDF content NEVER enters Claude's context. All processing happens in separate Python processes:
1. PyMuPDF extracts text in its own memory
2. Gemini Flash generates summaries (500-2000 tokens each)
3. Summaries are written to disk
4. Only minimal JSON status goes to stdout
5. Process memory is freed on exit

## Cost

~$0.15 to index all 94 PDFs (Gemini Flash pricing).
