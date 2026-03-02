---
name: ask-dojo
description: Consulta LeanDojo - Busca en 87,766 teoremas de Mathlib y sugiere tácticas usando IA local.
allowed-tools: Bash(python3 *)
argument-hint: "\"query\" [--name] [--state] [--suggest \"goal\"]"
---

# Ask Dojo: Consulta LeanDojo para Lean 4

Busca en 87,766 teoremas de Mathlib y sugiere tácticas usando un modelo de IA local.

## Help Request Detection

Si el usuario invoca con `?`, `--help`, `help`, mostrar esta referencia:

```
/ask-dojo - Consulta LeanDojo (87,766 teoremas de Mathlib)

MODOS DE BÚSQUEDA:
  /ask-dojo "query"              Búsqueda general por nombre
  /ask-dojo --name "theorem"     Buscar por nombre de teorema
  /ask-dojo --state "goal"       Buscar por estado/goal similar
  /ask-dojo --suggest "⊢ goal"   Sugerir tácticas para un goal
  /ask-dojo --file archivo.lean  Analizar archivo, encontrar sorries
  /ask-dojo --context spec.md    Agregar contexto desde archivo .md

OPCIONES:
  --name, -n "text"      Buscar teoremas por nombre
  --state, -s "text"     Buscar por estado de prueba similar
  --suggest, -t "goal"   Generar sugerencias de táctica (modelo IA)
  --file, -f FILE.lean   Analizar archivo Lean (encuentra sorries)
  --context, -ctx FILE   Archivo .md con contexto adicional
  --max, -m N            Máximo de resultados (default: 5)
  --compact, -c          Salida compacta sin estados

EJEMPLOS:
  /ask-dojo "sum range"
  /ask-dojo --name "primitive root" --max 10
  /ask-dojo --state "Finset.sum"
  /ask-dojo --suggest "⊢ n + m = m + n"
  /ask-dojo --file MiTeorema.lean
  /ask-dojo --file prueba.lean --context especificacion.md

DATOS:
  - Dataset: 87,766 teoremas de Mathlib (LeanDojo)
  - Modelo: tacgen-byt5-small (~1.1GB, corre en CPU)

DIFERENCIA CON /lean-search:
  /ask-dojo     → Dataset offline LeanDojo (87K teoremas históricos)
  /lean-search  → LSP tiempo real (proyecto actual, cameronfreer plugin)
```

## How to Use

Cuando el usuario invoca esta skill o cuando Claude necesita buscar teoremas:

1. **Identificar el tipo de búsqueda**:
   - Por nombre de teorema → `--name`
   - Por goal/estado similar → `--state`
   - Necesita sugerencia de táctica → `--suggest`

2. **Ejecutar el script**:
   ```bash
   python3 $SKILL_DIR/scripts/lean_search.py [opciones] "query"
   ```

3. **Presentar resultados** al usuario

## Execution

```bash
# Búsqueda por nombre
python3 $SKILL_DIR/scripts/lean_search.py --name "{QUERY}" --max {MAX_RESULTS}

# Búsqueda por estado
python3 $SKILL_DIR/scripts/lean_search.py --state "{GOAL_STATE}"

# Sugerencia de táctica
python3 $SKILL_DIR/scripts/lean_search.py --suggest "{GOAL_STATE}"

# Combinado
python3 $SKILL_DIR/scripts/lean_search.py --name "{QUERY}" --suggest "{GOAL_STATE}"
```

## Casos de Uso

### 1. Buscar teoremas existentes antes de implementar

```
Usuario: Necesito probar que la suma de un rango es n*(n-1)/2
Claude: Voy a buscar en Mathlib...

/ask-dojo "sum range formula"

Resultado: Finset.sum_range_id existe en Mathlib
```

### 2. Encontrar tácticas para un goal específico

```
Usuario: Estoy atascado en este goal: ⊢ a + b = b + a
Claude: Busco sugerencias...

/ask-dojo --suggest "⊢ a + b = b + a"

Sugerencias:
1. `ring`
2. `exact Nat.add_comm a b`
3. `rw [Nat.add_comm]`
```

### 3. Buscar teoremas con goals similares

```
/ask-dojo --state "IsPrimitiveRoot"

Encuentra teoremas que usan IsPrimitiveRoot en sus pruebas
```

### 4. Analizar archivo .lean con sorries

```
Usuario: Tengo este archivo con sorries que no puedo resolver
Claude: Analizo el archivo...

/ask-dojo --file Radix4NTT/NTT.lean

Resultado:
- Línea 45: `ntt_roundtrip` - sorry encontrado
  - Teoremas similares: DFT.inv_mul_eq_id
  - Tácticas sugeridas: `rw [inv_mul_cancel]`, `simp`
```

### 5. Buscar con contexto de documento

```
/ask-dojo --name "primitive root" --context fase2_roadmap.md

Incluye el contexto del roadmap en la búsqueda
para dar resultados más relevantes al proyecto actual
```

## Workflow Integrado con Otras Skills

```
┌─────────────────────────────────────────────────────────────┐
│ 1. /lean-search (LSP)                                       │
│    → Busca en proyecto actual (tiempo real)                 │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. /ask-dojo (LeanDojo)                                     │
│    → Busca en 87K teoremas de Mathlib (histórico)           │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. /ask-lean (DeepSeek)                                     │
│    → Consulta experto para estrategia de prueba             │
└─────────────────────────────────────────────────────────────┘
```

## Datos Técnicos

| Componente | Detalles |
|------------|----------|
| **Dataset** | LeanDojo (tasksource/leandojo) |
| **Teoremas** | 87,766 de Mathlib |
| **Modelo** | tacgen-byt5-small |
| **Tamaño modelo** | ~300MB |
| **Hardware** | CPU (no requiere GPU) |
| **Ubicación** | `~/.claude/skills/ask-dojo/data/` |

## Limitaciones

- Búsqueda basada en texto (no semántica)
- Modelo pequeño: sugerencias básicas
- Dataset de una versión específica de Mathlib
- No interactúa directamente con Lean (usar `/lean-search` para LSP)

## Mantenimiento

```bash
# Re-descargar dataset (si hay actualización)
python3 ~/.claude/skills/ask-dojo/scripts/setup.py

# Verificar instalación
python3 ~/.claude/skills/ask-dojo/scripts/lean_search.py --help
```

## Comparación de Skills de Búsqueda Lean

| Skill | Fuente | Tiempo | Uso Principal |
|-------|--------|--------|---------------|
| `/lean-search` | LSP (cameronfreer) | Tiempo real | Proyecto actual |
| `/ask-dojo` | LeanDojo dataset | Offline | Mathlib histórico |
| `/ask-lean` | DeepSeek | API call | Estrategia experta |
