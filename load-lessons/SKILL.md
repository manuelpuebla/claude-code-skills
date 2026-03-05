# Load Lessons: Carga Selectiva de Lecciones Aprendidas

Carga lecciones relevantes desde `~/Documents/claudio/lecciones/` usando búsqueda híbrida (keyword + semántica).

Wrapper sobre `query_lessons.py` — toda la lógica vive en el repo de lecciones.

## Help Request Detection

Si el usuario invoca con `?`, `--help`, `help`, mostrar esta referencia:

```
/load-lessons - Carga selectiva de lecciones aprendidas (471+ lecciones)

USAGE:
  /load-lessons <dominio> [opciones]

DOMINIOS:
  lean4          Verificación formal en Lean 4

MODOS DE BÚSQUEDA:
  -q, --hybrid "text"     Keyword + semántico combinado (RECOMENDADO)
  --semantic "text"        Solo semántico (lenguaje natural)
  -s, --search "text"     Solo keyword
  -p, --problem "text"    Lookup en tabla de problemas rápidos
  -l, --lesson ID         Lección exacta por ID (e.g., L-153)
  --section SEC            Sección completa (e.g., §47)
  -r, --related ID        Lecciones relacionadas (grafo)
  --list                   Listar todas las secciones

EXAMPLES:
  /load-lessons lean4 --list                             # Secciones disponibles
  /load-lessons lean4 -q "omega multiplicación"          # Híbrido (recomendado)
  /load-lessons lean4 --semantic "nonlinear arithmetic"  # Semántico
  /load-lessons lean4 -s "simp"                          # Keyword
  /load-lessons lean4 -p "omega no funciona"             # Por problema
  /load-lessons lean4 -l L-445                           # Lección exacta
  /load-lessons lean4 -r L-445                           # Relacionadas
```

## How to Use

Cuando el usuario invoca esta skill:

1. **Identificar dominio** (lean4)
2. **Si tiene query**: Usar `--hybrid` por defecto (mejor recall que keyword solo)
3. **Si pide lección específica**: Usar `--lesson`
4. **Si pide sección**: Usar `--section`
5. **Si pide listar**: Usar `--list`

## Execution

```bash
# Búsqueda híbrida (recomendado)
python3 $SKILL_DIR/scripts/load_lessons.py lean4 -q "omega multiplication"

# Búsqueda semántica
python3 $SKILL_DIR/scripts/load_lessons.py lean4 --semantic "how to handle dependent types"

# Keyword
python3 $SKILL_DIR/scripts/load_lessons.py lean4 -s "simp omega"

# Problema
python3 $SKILL_DIR/scripts/load_lessons.py lean4 -p "ZMod timeout"

# Lección exacta
python3 $SKILL_DIR/scripts/load_lessons.py lean4 -l L-445

# Listar secciones
python3 $SKILL_DIR/scripts/load_lessons.py lean4 --list
```

## Cuándo Usar Automáticamente

Claude DEBE consultar lecciones cuando:
1. Trabaja en archivos `.lean`
2. Encuentra error de tipo conocido (ZMod, omega, simp, dependent types)
3. Planifica eliminación de sorries/axiomas
4. El QA sugiere un patrón que podría estar documentado

**Preferir `--hybrid`** sobre `--search` para mejor recall semántico.

## Integración con Otras Skills

```
/ask-dojo          → Buscar teoremas en Mathlib
/load-lessons      → Lecciones de cómo resolver problemas
/ask-lean          → Consulta experta a DeepSeek
/collab-qa         → Validar estrategia con Gemini
```
