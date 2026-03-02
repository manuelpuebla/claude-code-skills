# Plan Project: Referencia Detallada

Este archivo complementa SKILL.md con detalles extendidos. Cargar solo cuando se necesite.

## Worker Template Completo

```
Task(subagent_type="general-purpose", run_in_background=true):
"Tu tarea: resolver UN problema específico en {ruta_archivo}.

TARGET: {nombre}
ARCHIVO: {ruta_archivo}
LÍNEA:   {número_línea}
CLASIFICACIÓN: {del DAG}
ESTRATEGIA SUGERIDA: {del plan — 1 línea}

CODE MAP (generado por scout.py):
{code_map_output}

INSTRUCCIONES:
1. Usa el Code Map para entender la estructura
2. Si necesitas más contexto: Read con offset+limit (sección, nunca archivo entero)
3. Resuelve con la estrategia sugerida. Si falla, alternativas (máx 3)
4. Helpers auxiliares: defínelos ARRIBA del target

RETORNA:
---RESULTADO---
STATUS: {SUCCESS | FAILURE}
TARGET: {nombre}
ARCHIVO: {ruta_archivo}

CAMBIOS (solo si SUCCESS):
-- REEMPLAZAR líneas {inicio}-{fin} con:
{código}

AUXILIARES (solo si agregaste helpers):
-- INSERTAR ANTES de línea {línea} en {archivo}:
{definiciones}

SI FAILURE:
ESTADO_PENDIENTE: {problema}
INTENTOS: {qué probó, 3 líneas máx}
---FIN---

IMPORTANTE: Solo retornar patch. NO modificar archivo. NO tocar otros targets."
```

## Manejo de Fallos Post-Compilación

```
SI lake build falla después de aplicar patches:
  1. IDENTIFICAR cuál patch causó el error
  2. REVERTIR selectivamente:
     a) 1 patch: revertir solo ese, re-compilar
     b) Múltiples: revertir todos, aplicar uno por uno con compilación intermedia
  3. NODOS FALLIDOS: Marcar para resolución secuencial
  4. NO re-lanzar agent team para nodos fallidos (resolver secuencialmente)
```

## Cuándo NO Usar Agent Teams (Override a Secuencial)

- Todos los sorry del bloque en el MISMO rango de 50 líneas
- Un nodo evaluado como MUY_ALTA dificultad
- Bloque con solo 2 nodos (overhead > beneficio)
- Máximo 5 agentes simultáneos; si >5 nodos: sub-bloques de 5
- Timeout por agente: 10 minutos

## Integración LSP para Lean 4

```
Si DOMAIN == "lean4" y hay proyecto Lean activo:
  1. /lean-check → Estado de compilación
  2. /lean-diagnostics → Errores/warnings
  3. /lean-goal → Goals pendientes (sorries)
```

Subagentes cameronfreer (durante ejecución, no planificación):
- proof-search-agent, tactic-agent, error-diagnosis-agent

## Recursos Combinados Lean 4

| Paso | Skill | Ejecución | Tokens |
|------|-------|-----------|--------|
| 0 | detect_context.py | Inline | ~500 |
| 1 | Bibliografía (haiku) | PARALELO | ~5K |
| 2 | Lecciones (haiku) | PARALELO | ~3K |
| 3 | /lean-check (cameronfreer) | PARALELO | ~1K |
| 4 | ask-dojo + ask-lean (compact) | PARALELO | ~5K |
| 5 | extract_lean_dag.py (summary) | PARALELO | ~2K |
| 5b | ask-lean + ask-dojo (BATCH) | Secuencial | ~5K |
| 5c | Ensamblar plan topológico | Secuencial | ~3K |
| 6 | collab-qa (compact) | Secuencial | ~3K |
| 7 | Obstáculos | Iterativo | ~5K |
| 8 | Síntesis | Secuencial | ~5K |

## Output Extendido Lean 4

```markdown
## Estado LSP Actual
- Compilación: {OK / ERRORES}
- Errores: {lista}
- Sorries: {cantidad y ubicaciones}

## Teoremas Relevantes (Mathlib)
- {teorema}: {signature + uso}

## Estrategia (DeepSeek)
{Estrategia con razonamiento}
```

## Formato Completo de Nodo en Plan

```
PASO {N}: {nombre_teorema}
  Clasificación: {del DAG formal}
  Dificultad:    {de la consulta experta}
  Estrategia:    {DIRECTA | CAUTELOSA | FIREWALL_OBLIGATORIO}

  ¿Por qué aquí?: {por qué este orden es seguro}
  Dependencias resueltas: {nodos previos}
  Dependientes bloqueados: {nodos que se desbloquean}

  Plan de prueba:
  - {estrategia del experto}
  - Lemas Mathlib: {de /ask-dojo}
  - Alternativa: {si falla}

  Seguridad:
  - Firewall: {sí/no}
  - Checkpoint: {qué compilar}
  - Si falla tras 3-4 intentos: escalar
```

## Formato Completo de Bloque

```
BLOQUE {N}:
  SCOUT:
    python3 ~/.claude/skills/plan-project/scripts/scout.py \
      --targets "{nodos}" --context-lines 5 {archivos}
  Ejecución: {AGENT_TEAM | SECUENCIAL}
  Nodos: {cantidad}
  ├── PASO {a}: {nodo} — {archivo}:{línea} — {resumen}
  └── PASO {b}: {nodo} — {archivo}:{línea} — {resumen}
  Sync: lake build después del bloque

GATE: De-risk {nodo_fundacional}
  SCOUT: scout.py --targets "{nodo}" --context-lines 10 {archivo}
  Acción: Sketch antes de avanzar
  Si viable → continuar | Si imposible → STOP, rediseñar
```

## Flujo del Orquestador con Scout

```
PARA CADA bloque:
  0. SCOUT PHASE (python3 scout.py — 0 tokens LLM, ~100ms)

  SI AGENT_TEAM:
    1. Hook I crea branch al primer edit
    2. Un Task por nodo, TODOS en un mensaje (paralelo)
    3. Recolectar resultados
    4. Aplicar patches bottom-up (líneas descendentes)
    5. Compilar → si falla, ver Manejo de Fallos
    6. Reportar resumen

  SI SECUENCIAL:
    1. Orquestador trabaja nodo por nodo con Code Map
    2. Read offset+limit si necesita más detalle
    3. Checkpoint después de cada nodo
```

## Hooks Activos (referencia — ya están en settings.json)

| Hook | Evento | Qué hace |
|------|--------|----------|
| C | PreToolUse Read | Advierte archivo >200 líneas sin offset → sugiere scout.py |
| D | PreToolUse Grep | Sugiere scout.py como alternativa |
| E | PostToolUse Bash | Compilación falla ≥3 veces → inyecta /ask-dojo + /ask-lean |
| F | PostToolUse Bash | Compilación exitosa → resetea contadores |
| G | PreToolUse Edit | Archivo con ≥3 importadores → advierte usar `_aux` |
| H | PostToolUse Edit | 3 edits sin compilar → inyecta "COMPILA AHORA" |
| I | PreToolUse Edit | 1er edit de sesión → sugiere branch |

Coordinación: F resetea H | G + I son independientes en PreToolUse Edit | I solo 1 vez por sesión.

## Historial de Optimización (v1 → v2)

| Aspecto | v1 | v2 |
|---------|----|----|
| Planificación | Paralela | Paralela + short-circuit |
| Lectura de código | Lee archivos completos | scout.py Code Map (~3K tok) |
| Detail level | full siempre | compact por defecto |
| Step 5b | N llamadas | 1 BATCH |
| DAG format | json (10-30K tok) | summary (~2K tok) |
| Agents 1,2 | Opus | Haiku |
| QA | 3 rondas full | Adaptativo 0-3, compact |
| Tokens planificación | 100-280K | 35-80K |
| Compliance | ~10% | ~95% (hooks) |
