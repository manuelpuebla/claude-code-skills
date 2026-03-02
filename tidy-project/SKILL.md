---
name: tidy-project
description: Reformatea ARCHITECTURE.md y BENCHMARKS.md al formato estándar. Extrae lecciones y genera dag.json.
allowed-tools: Bash(python3 *), Read, Glob
argument-hint: "--project /path [--version v1.0.0] [--dry-run] [--legacy-phase]"
---

# /tidy-project

Reformatea documentación de proyecto al estándar definido en `DOCUMENTATION_TEMPLATE.md`.

## Uso

```
/tidy-project --project /path/to/project [--version v1.0.0] [--dry-run] [--legacy-phase]
```

## Qué hace

1. **Parsea** ARCHITECTURE.md (detecta fases, nodos, bloques, lecciones en formatos heterogéneos)
2. **Parsea** BENCHMARKS.md (criterios, resultados por fase/bloque)
3. **Extrae** lecciones → `save_lessons.py` → `~/Documents/claudio/lecciones/lean4/`
4. **Genera** `dag.json` si no existe (desde nodos/bloques parseados)
5. **Reescribe** ARCHITECTURE.md y BENCHMARKS.md en formato template
6. **Backup** originales a `.{timestamp}.bak`

## Instrucciones

1. Ejecutar con `--dry-run` primero para verificar el parsing:

```bash
python3 ~/.claude/skills/tidy-project/scripts/tidy_project.py --project /path --dry-run
```

2. Revisar el resumen: fases, nodos, bloques, lecciones detectadas
3. Si el parsing es correcto, ejecutar sin `--dry-run`
4. Verificar los archivos generados
5. Si algo salió mal, restaurar desde `.bak`

## Formatos soportados

- **Phase-based** (LeanScribe): `## Fases del Proyecto` + `### Node classification` + `## Progress tree`
- **Fase-per-section** (SuperTensor): `## Fase N — Name` con contenido inline
- **Standard template** (init_project_docs.py output): `## Current Version` + `### Fase N`
- **Component-based** (VR1CS): sin fases explícitas — produce output mínimo

## Flag `--legacy-phase`

Para proyectos con documentación desordenada (secciones sin fase, benchmarks sueltos, contenido histórico no estructurado):

- Crea una **Fase 0: Foundation (pre-structured)** sintética con un nodo FUNDACIONAL
- Preserva secciones no mapeadas en **Legacy Content (pre-structured)** en ARCHITECTURE.md
- Separa benchmarks huérfanos (sin fase identificable) en **Legacy Results (pre-structured)** en BENCHMARKS.md
- Ideal para VR1CS (component-based, sin fases) y proyectos con historial desestructurado

Sin `--legacy-phase`, las secciones no mapeadas se preservan igualmente en Legacy Content, pero no se crea Fase 0.

## Notas

- `--version` auto-detecta si no se especifica (busca `Current Version:`, `tag vN.N.N`, etc.)
- No sobrescribe `dag.json` existente
- Las lecciones se guardan via `save_lessons.py` al repositorio centralizado
- Los `.bak` se nombran con timestamp para no sobrescribir backups previos
