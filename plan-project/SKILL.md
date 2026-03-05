---
name: plan-project
description: Orquestador de planificación que usa subagentes para revisar bibliografía, lecciones, y consultar QA antes de presentar un plan estructurado. Optimizado para Opus 4.6 (Agent Teams, Adaptive Thinking, 1M Context, Compaction).
allowed-tools: Task, Bash(python3 *), Read, Glob, Grep
argument-hint: "\"descripción de la tarea\" [--context fase2] [--domain lean4] [--effort auto] [--study-context]"
---

# Plan Project: Orquestador de Planificación (Opus 4.6)

## Help

Si el usuario invoca con `?` o `--help`, mostrar:
```
/plan-project "tarea" [--context fase2] [--domain lean4] [--effort auto|low|medium|high|max] [--study-context]
Workflow: Bibliografía + Lecciones + Contexto + Expertos + DAG → Plan Topológico → QA → Presentar
Ejecución: Scout Phase (code map) → Agent Teams (paralelo) o Secuencial → Checkpoints
  --study-context   Genera contexto de estudio por nodo (papers, lessons, libraries) en dag.json
```

## Activation

Se activa explícitamente (`/plan-project`) o automáticamente cuando la tarea requiere múltiples fases, arquitectura, o decisiones técnicas no triviales.

## Guardia Anti-Replanificación

**ANTES de planificar**, verificar si ya existe un plan activo:
1. Buscar: `ARCHITECTURE.md`, `roadmap_*.md`, `fase*_roadmap.md`, `*_plan.md`, `plan_actual.md` en el proyecto
2. Si existe plan activo con tareas pendientes:
   - **NO re-planificar**. Informar al usuario: "Ya existe un plan activo en {archivo}. ¿Quieres continuar ejecutándolo o planificar algo nuevo?"
   - Si el usuario quiere continuar: leer el plan, identificar siguiente tarea, ejecutar directamente (no necesita esta skill)
   - Si el usuario quiere planificar algo NUEVO o ANIDADO: usar nomenclatura anidada (Corrección/Mejora/Investigación) dentro de la fase actual
3. Si NO existe plan: proceder con planificación normal

## Paso 0: Clasificar Complejidad

```bash
python3 ~/.claude/skills/plan-project/scripts/detect_context.py \
  --context "{CONTEXT}" --task "{TASK_DESCRIPTION}" --domain "{DOMAIN}"
```

| Complejidad | QA | Detail | Paso 5b | Paso 7 |
|-------------|-----|--------|---------|--------|
| low | skip | compact | SKIP | SKIP |
| medium | 1 ronda | compact | BATCH | 1 ciclo |
| high | 2 rondas | compact | BATCH | 2 ciclos |
| max | 3 rondas | full | BATCH | 3 ciclos |

**Low = short-circuit**: Solo Agents 1-3 + 5, saltar 5b/6/7, ir directo a 5c → 8.

### Paso 0b: Cargar Insights (si existen)

Buscar `insights_*.md` o `*_insights.md` en el proyecto.
Si existe: leerlo y extraer hallazgos relevantes a la tarea.
Pasar como contexto adicional a Agents 1-2 (bibliografía/lecciones) para búsqueda dirigida, y a Agent 4 (expertos) para evitar consultas redundantes.
Si no existe: continuar normalmente.

## Pasos 1-5: Recolección Paralela

**Lanzar TODOS en una sola llamada (Agent Teams):**

**Agent 1: Bibliografía** — Task(Explore, haiku)
```
"Lee ~/Documents/claudio/biblioteca/indices/_global_topic_index.md
Para carpetas relevantes a '{TASK}': lee indices/<folder>/_folder_index.md
NO usar query_graph.py. Retorna: documentos relevantes (nombre + 1 línea) + 3-5 conceptos clave."
```

**Agent 2: Lecciones** — Task(Explore, haiku)
```
"Ejecuta: python3 ~/Documents/claudio/lecciones/scripts/query_lessons.py --hybrid '{TASK}'
Si el resultado es insuficiente, ejecuta una segunda búsqueda con keywords más específicos.
Para las top 3-5 lecciones relevantes, ejecuta --lesson <ID> para leer el contenido completo.
Retorna: IDs + título (1 línea c/u), CRÍTICAS con contenido (máx 3 líneas c/u), anti-patrones."
```

**Agent 3: Contexto** — Bash directo (no subagente)
```bash
python3 ~/.claude/skills/plan-project/scripts/detect_context.py \
  --context "{CONTEXT}" --task "{TASK}" --domain "{DOMAIN}"
```

**Agent 4: Expertos** — Task(general-purpose), solo si domain=lean4 y complexity >= medium
```
"Ejecuta:
1. python3 ~/.claude/skills/ask-dojo/scripts/lean_search.py --name '{KEYWORDS}' --max 5
2. python3 ~/.claude/skills/ask-lean/scripts/ask_lean.py --rounds 1 --detail compact --context '{TASK}' '{QUESTION}'
Retorna síntesis compacta: teoremas + estrategia clave."
```

**Agent 5: DAG Formal** — Bash directo, solo si domain=lean4
```bash
python3 ~/.claude/skills/plan-project/scripts/extract_lean_dag.py \
  "{PROJECT_PATH}" --format summary --sorry-only
```

## Paso 5: Plan Topológico

**PRINCIPIO: El plan de trabajo ES el orden topológico.**

**5a. Ingerir DAG** (si lean4):
- `topological_order` → esqueleto del plan
- `hojas_sorry` → atacar primero | `fundacionales_sorry` → de-risk obligatorio
- `criticos` → firewall _aux | `cycles` → resolver PRIMERO

Si domain != lean4: construir DAG manualmente (entregables → dependencias → clasificar → ordenar).

**5b. Consultar Expertos BATCH** (solo si complexity >= medium):
UNA sola llamada con TODOS los sorry, NO una por teorema.
```
Task(general-purpose):
"1. python3 lean_search.py --name '{TODOS_SEPARADOS_POR_COMA}' --max 5
2. python3 ask_lean.py --rounds 1 --detail compact --context 'Evaluar dificultad BAJA/MEDIA/ALTA/MUY_ALTA para: {lista: nombre|clasificación|signatura}'
Retorna tabla: Teorema | Dificultad | Estrategia (1 línea) | Lemas clave"
```
Si FUNDACIONAL evaluado MUY_ALTA → incluir fase previa de investigación.

**5c. Ensamblar** como secuencia de bloques:

**5c-study. Contexto de estudio por nodo** (solo si `--study-context`):
Para CADA nodo del DAG, generar un campo `study` usando la información recolectada por Agents 1-4:
```json
"study": {
  "papers": ["carpeta/summary.md"],
  "lessons": ["L-337", "L-203"],
  "libraries": ["LeanHash:SboxProperties"],
  "notes": "Hint breve del planificador para el worker"
}
```
- `papers`: summaries de `biblioteca/indices/` relevantes al nodo (de Agent 1)
- `lessons`: IDs de lecciones aplicables al nodo (de Agent 2)
- `libraries`: `librería:módulo` con teoremas reutilizables (de Agent 1/3, cruzar con librerías internas)
- `notes`: 1-2 líneas de contexto estratégico del planificador
Si `--study-context` NO está activo: NO generar campo `study`. Los nodos quedan sin él y el workflow es idéntico al actual.

**Terminología obligatoria:**
- **Nodo** = unidad individual del DAG (FUNDACIONAL / CRÍTICO / PARALELO / HOJA). Unidad de verificación.
- **Bloque** = agrupación de nodos para ejecución. Un bloque puede tener 1 nodo (secuencial) o N nodos independientes (paralelo).

**Reglas de agrupación:**
- FUNDACIONAL o CRÍTICO → bloque de 1 nodo, ejecución SECUENCIAL, precedido por GATE de-risk
- ≥2 nodos PARALELO/HOJA independientes + complexity >= medium → bloque multi-nodo, ejecución AGENT_TEAM
- 1 solo nodo PARALELO/HOJA, o complexity = low → bloque de 1 nodo, SECUENCIAL
- NUNCA mezclar nodos FUNDACIONAL/CRÍTICO con otros en el mismo bloque

## Paso 6: QA (adaptativo a complejidad)

```
Task(general-purpose):
"python3 ~/.claude/skills/collab-qa/scripts/collab.py \
  --rounds {N} --detail {compact|full} --context '{CONTEXT}' '{PLAN_DRAFT}'
Retorna síntesis: recomendación + issues + propuestas."
```

### Paso 6b: Criterios de Verificación (via /benchmark-qa)

```
Task(general-purpose):
"python3 ~/.claude/skills/collab-qa/scripts/collab.py \
  --rounds 1 --detail full \
  --context 'Generar criterios de verificación exhaustivos para cada tipo de nodo del plan' \
  '{PLAN_CON_NODOS_Y_CLASIFICACIONES}'

Para cada tipo de nodo (HOJA, INTERMEDIO, FUNDACIONAL, GATE):
- Checks mecánicos obligatorios
- Stress testing: qué inputs adversarios probar
- Casos borde: qué condiciones límite verificar
- Robustez: qué propiedades deben resistir cambios
- Calidad de pruebas: qué patrones evitar (native_decide, simp[*], etc.)
- Coherencia arquitectónica: qué invariantes verificar

Retorna rúbrica estructurada por tipo de nodo."
```

Guardar criterios en **BENCHMARKS.md** del proyecto (sección header). Costo: 1 llamada a Gemini (~5K tokens), amortizada sobre todos los nodos.

### Paso 6c: Formal Properties (SlimCheck stubs)

Para cada nodo del DAG, generar:

1. **En ARCHITECTURE.md § Formal Properties**: tabla con propiedades en lenguaje natural (intención de diseño).
   - Columnas: Nodo | Propiedad | Tipo (SOUNDNESS/EQUIVALENCE/INVARIANT/PRESERVATION/OPTIMIZATION) | Prioridad (P0/P1/P2)
   - P0 = la propiedad es central al nodo; P1 = deseable; P2 = nice-to-have.

2. **En BENCHMARKS.md § Formal Properties**: stubs ejecutables de SlimCheck correspondientes.
   - Cada stub incluye `import Mathlib.Testing.SlimCheck` y usa `slim_check` como tactic.
   - Tipos custom necesitan instancias `SampleableExt` + `Shrinkable` (anotar como "Not Yet Runnable" si no existen).

**Heurísticas para generar propiedades por tipo de nodo:**
- FUNDACIONAL → invariantes, commutativity, idempotency
- CRÍTICO → soundness, preservation (transformaciones preservan semántica)
- PARALELO → equivalencia entre representaciones
- HOJA → propiedades de output (acotación, no-negatividad, formato)

Las propiedades se generan UNA VEZ durante planificación. Son advisory: no bloquean cierre de nodo, pero se reportan en la sección 5 de resultados por bloque.

### Paso 6d: Generate Test Specifications

Después de `init_project_docs.py` (Paso 8), generar especificaciones de test via Gemini:

```bash
python3 ~/.claude/skills/plan-project/scripts/generate_tests.py \
  --project {PROJECT_PATH} --all
```

Esto invoca Gemini 2.5 Pro como "Senior QA Architect" para diseñar:
- Qué propiedades verificar por nodo (con prioridad P0/P1/P2)
- Qué integration tests escribir (con escenarios y valores concretos)
- Output: **`TESTS_OUTSOURCE.md`** (especificaciones, NO código Lean)

**Gemini NO escribe código Lean** — no tiene acceso al compilador ni puede iterar.

### Flujo de testing (subagente)

```
PLANIFICACIÓN (Session A):
  generate_tests.py → TESTS_OUTSOURCE.md

TESTING (Subagente via Task — lanzado por Session A):
  1. Recibe prompt de launch_test_agent.py
  2. Lee código fuente con Read (API signatures)
  3. Escribe Tests/Properties/{Node}.lean + Tests/Integration/{Node}.lean
  4. Compila con lake env lean hasta que pasen
  5. Ejecuta run_tests.py --save-results Tests/results.json por nodo
  6. Retorna resumen estructurado

IMPROVEMENT LOOP (Session A):
  Si FAIL:
    - Test incorrecto → dispute via run_tests.py --dispute
    - Implementación incorrecta → fix code
    - Relanzar subagente fresco (mismas specs, max 3 iter)

CIERRE (Session A):
  close_block.py --tests-prerun Tests/results.json
```

**El subagente escribe los tests de forma independiente**, sin conocer el contexto de implementación. Solo ve las firmas públicas y las specs de Gemini. Esto garantiza separación de concerns.

**Lanzamiento del subagente**:
```bash
# Generar prompt
PROMPT=$(python3 ~/.claude/skills/plan-project/scripts/launch_test_agent.py \
  --project {path} --nodes '{"N2.1": ["File.lean"]}')
# Pasar a Task(general-purpose) con el prompt generado
```

**Disputas**: Si la sesión A identifica tests irrelevantes al ejecutarlos:
```bash
python3 run_tests.py --project PATH --node N2.1 \
  --dispute "test_name" --reason "justificación" --evidence "File.lean:45-60"
```
Gemini re-evalúa: ACCEPT_DISPUTE | INSIST | MODIFY_TEST.

## Paso 7: Resolver Obstáculos

Ciclo según complejidad. Clasificar: MENOR (resolver inline) | TÁCTICO (ask-dojo/ask-lean) | ARQUITECTURAL (collab-qa). Salida: QA aprueba, max ciclos, o usuario avanza.

## Paso 8: Presentar y Guardar

**Project-aware**: antes de crear documentación, verificar si ya existe.

```bash
# Check si las fases del plan ya están documentadas
echo '{PLAN_JSON}' | python3 ~/.claude/skills/plan-project/scripts/init_project_docs.py \
  --project {PROJECT_PATH} --name "{NAME}" --version {VERSION} --check
```

Interpretar el exit code:
- **Exit 0** → fases nuevas, crear docs:
  ```bash
  echo '{PLAN_JSON}' | python3 ~/.claude/skills/plan-project/scripts/init_project_docs.py \
    --project {PROJECT_PATH} --name "{NAME}" --version {VERSION}
  ```
- **Exit 2** → fases ya documentadas. NO crear ni modificar docs.
  Esto ocurre cuando se re-planifica una fase dentro de una versión activa
  (ej: `/plan-project` para fase 6 de un proyecto de 9 fases ya planificado).

El JSON del plan debe tener formato:
```json
{
  "phases": [{"id": "faseN", "name": "...", "description": "...",
    "nodes": [{"id": "N1.1", "name": "...", "type": "CRITICO", "files": [...], "deps": [...], "blocks": [...],
               "study": {"papers": [...], "lessons": [...], "libraries": [...], "notes": "..."}}],
    "blocks": [{"id": "B1", "name": "...", "nodes": ["N1.1"]}]
  }],
  "rubric": {"correctness": [...], "performance": [...], "quality": [...]},
  "properties": [
    {"node": "N1.1", "description": "...", "type": "SOUNDNESS", "priority": "P0",
     "stub": "example (x : T) : P x := by slim_check"}
  ]
}
```

La rúbrica viene del Paso 6b (`/benchmark-qa`). Incluirla en el JSON del plan.

**README.md**: Crear o actualizar si es proyecto nuevo o cambió el alcance.

## Protocolo de Ejecución

### Scout Phase (OBLIGATORIO antes de cada bloque)
```bash
python3 ~/.claude/skills/plan-project/scripts/scout.py \
  --targets "{nodos}" --context-lines 5 {archivos}
```
Code Map (~2-3K tok, 0 LLM, ~100ms). Workers y orquestador usan el Code Map, NO leen archivos completos.

### Agent Teams (bloques multi-nodo paralelos)
1. Scout → Code Map
2. Un Task por nodo, TODOS en un mensaje (run_in_background=true)
3. Workers retornan PATCH en formato: STATUS | TARGET | CAMBIOS | AUXILIARES
4. Aplicar patches en orden de línea DESCENDENTE (bottom-up)
5. Compilar → si falla, revertir patch problemático, resolver secuencialmente
6. Máximo 5 agentes simultáneos por bloque
7. **→ Ejecutar close_block.py (ver Cierre de Bloque abajo)**

### Secuencial (bloques de 1 nodo: fundacionales/críticos)
Orquestador trabaja con Code Map, Read con offset+limit si necesita más contexto.
**→ Al terminar, ejecutar close_block.py (ver Cierre de Bloque abajo)**

### Protocolo fundacional (firewall _aux)
1. Crear `theorem {nombre}_aux` con signatura flexible
2. Probar `_aux` sin tocar original
3. Migrar solo cuando `_aux` compile sin sorry
4. `lake build` completo después

### Escalación
Intentos 1-2: directo | 3: /ask-dojo | 4: /ask-lean | persiste: reformular nodo.
Hooks E/F lo enforzan automáticamente.

### Cierre de Bloque (OBLIGATORIO — enforced por hook)

Al completar CADA bloque, ANTES de avanzar al siguiente bloque:

**Granularidad de verificación:**
- **Rúbrica** (pre-generada por el analista QA en Paso 6b, guardada en BENCHMARKS.md § Criterios con anotaciones `<!-- CHECK:... -->`): por **tipo de nodo**.
- **Verificación mecánica** (`verify_node.py`): por **cada nodo** del bloque.
- **Tests** (`run_tests.py`): por **cada nodo** — properties (SlimCheck) + integration (#eval).
- **Gate de rúbrica** (`evaluate_rubric.py`): evalúa criterios CHECK contra resultados.
- **QA riguroso** (`collab.py`): por **bloque completo**, aplicando la rúbrica.
- **Resultados** en BENCHMARKS.md § Resultados: por **nodo**.

**Paso 1. Verificación automatizada de 4 pasos** (close_block.py):
```bash
python3 ~/.claude/skills/plan-project/scripts/close_block.py \
  --project {path} --block "Bloque N" \
  --nodes '{"NODO_A": ["archivo1.lean"], "NODO_B": ["archivo2.lean", "archivo3.lean"]}' \
  --tests-prerun Tests/results.json
```

`close_block.py` ejecuta automáticamente:
1. **Mecánico**: verify_node.py por nodo (sorry/axiom/build/warnings/regresiones)
2. **Tests**: lee resultados pre-guardados de Tests/results.json (si `--tests-prerun`)
3. **Rúbrica**: evaluate_rubric.py (criterios CHECK de BENCHMARKS.md)
4. **Agregación**: all_pass = mecánico AND tests AND rúbrica

Flags de backward compat: `--skip-tests`, `--skip-rubric`, `--tests-prerun` (para subagente pre-ejecutado).

**Paso 2. QA riguroso + extracción de lecciones** (subagente, ~3-5K tokens):
Solo si close_block.py retorna PASS. Lanzar QA via subagente:
```
Task(general-purpose):
"python3 ~/.claude/skills/collab-qa/scripts/collab.py \
  --rounds 1 --detail full \
  --context 'Cierre de bloque: {nombre}. Proyecto: {proyecto}. Rúbrica pre-generada en BENCHMARKS.md § Criterios de Verificación.' \
  '{código_relevante_de_todos_los_nodos_del_bloque}'

Evaluar EXHAUSTIVAMENTE cada nodo contra la rúbrica pre-generada por el analista QA (Paso 6b),
aplicando los criterios correspondientes al TIPO de cada nodo (HOJA/INTERMEDIO/FUNDACIONAL/GATE):
- Stress testing: inputs adversarios, overflow, empty collections, zero fuel
- Casos borde: condiciones límite de cada theorem/def
- Robustez: ¿las pruebas sobreviven cambios en Mathlib? ¿dependen de orden de hipótesis?
- Hipótesis redundantes: ¿algún theorem tiene precondiciones innecesarias?
- Calidad de pruebas: ¿hay native_decide/decide donde debería haber prueba constructiva?
- Coherencia arquitectónica: ¿el código sigue el plan en ARCHITECTURE.md?

ADEMÁS: extraer 1-5 lecciones aprendidas durante este bloque. Formato JSON:
[{\"title\": \"Título conciso\", \"body\": \"Contenido con ```lean si aplica\", \"keywords\": [\"kw1\", \"kw2\"]}]

Retorna: PASS/FAIL por nodo + hallazgos + recomendaciones + JSON de lecciones."
```

**Paso 3. Si PASS**: Cerrar bloque con lecciones:
```bash
python3 ~/.claude/skills/plan-project/scripts/update_docs.py \
  --project {path} --close-block {BLOCK_ID} \
  --result '{result_json}' \
  --lessons '[{lessons_json_from_qa}]'
```
Esto registra resultados en BENCHMARKS.md, clasifica y guarda lecciones en `~/Documents/claudio/lecciones/lean4/`, y marca ✓ en ARCHITECTURE.md.

**Paso 4. Si FAIL**: Resolver problema → re-ejecutar close_block.py → re-QA. Lecciones del fallo se guardan en la siguiente iteración exitosa.

**IMPORTANTE**: El hook `guard-block-close.sh` BLOQUEA la edición de ARCHITECTURE.md para agregar ✓ si close_block.py no se ejecutó. No intentar saltarse este paso.

## Reglas Críticas

- Plan = Fases (visión) + Orden topológico (ejecución). Fases PRIMERO, luego DAG.
- Output del plan va a ARCHITECTURE.md + BENCHMARKS.md (no plan_actual.md).
- NUNCA diferir nodos fundacionales. SIEMPRE de-risk con sketch primero.
- SIEMPRE scout.py antes de cada bloque. Sin Code Map, NO empezar.
- SIEMPRE verificación post-bloque (`close_block.py` + QA riguroso) ANTES de avanzar al siguiente bloque.
- Nomenclatura anidada dentro de fases: Corrección/Mejora/Investigación.
- Ver `REFERENCE.md` para: worker template detallado, manejo de fallos, integración LSP, hooks.
