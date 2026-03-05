---
name: insights
description: Investigación pre-planificación con hasta 8 agentes paralelos. Estudia bibliografía, lecciones, proyectos y recursos online para producir insights estructurados. Con --depth deep, extrae teoremas y los formaliza en Lean 4.
allowed-tools: Task, Bash(python3 *), Read, Glob, Grep, WebSearch, WebFetch, Write
argument-hint: '"objeto de estudio" [--domain lean4] [--project path/] [--max-downloads 5] [--skip-online] [--depth standard|deep] [--library NAME] [--target-library PATH] [--mathlib]'
---

# Insights: Investigación Pre-Planificación con Agent Team

## Help

Si el usuario invoca con `?` o `--help`, mostrar:
```
/insights "objeto de estudio" [--domain lean4] [--project path/] [--max-downloads 5] [--skip-online]
                               [--depth standard|deep] [--library NAME] [--target-library PATH] [--mathlib]

Investigación pre-planificación con hasta 8 agentes paralelos:
  Agent 1: Analiza el objeto de estudio / proyecto de entrada
  Agent 2: Estudia lecciones aprendidas globales (lecciones/)
  Agent 3: Busca bibliografía relevante en el grafo conceptual
  Agent 4: Extrae estrategias de proyectos previos (decisiones_*, benchmarks_*)
  Agent 5: Busca y descarga bibliografía online faltante
  Agent 6: Indexa nueva bibliografía y extrae insights
  Agent 7: [deep] Extrae teoremas formalizables de papers
  Agent 8: [deep] Formaliza teoremas en Lean 4 y gestiona librería

Workflow: Wave 1 (1-4 paralelo) → Wave 2 (5 online) → Wave 3 (6 indexación)
          → [Wave 4 (7 extracción) → Wave 5 (8 formalización)] → Síntesis
Output:   {slug}_insights.md en directorio actual

Opciones:
  --domain DOMAIN        Dominio de lecciones (lean4, etc.)
  --project PATH         Ruta al proyecto existente a investigar
  --max-downloads N      Máximo de PDFs a descargar online (default: 5)
  --skip-online          Saltar búsqueda online (solo recursos locales)
  --depth standard|deep  Profundidad (default: standard). "deep" añade extracción de
                         teoremas y formalización Lean 4 (Waves 4-5)
  --library NAME         Crear nueva librería privada con este nombre (requiere --depth deep)
  --target-library PATH  Agregar teoremas a librería existente (requiere --depth deep)
  --mathlib              La nueva librería depende de Mathlib (solo con --library)
```

## Paso 0: Parse y Preparación

1. Extraer argumentos del prompt del usuario:
   - `STUDY_OBJECT`: el texto entre comillas (obligatorio)
   - `--domain DOMAIN`: dominio de lecciones (default: auto-detectar)
   - `--project PROJECT_PATH`: ruta al proyecto existente (default: directorio actual si tiene roadmap)
   - `--max-downloads N`: máximo descargas online (default: 5)
   - `--skip-online`: flag booleano
   - `--depth DEPTH`: "standard" (default) o "deep"
   - `--library LIBRARY_NAME`: nombre para nueva librería (solo con --depth deep)
   - `--target-library TARGET_LIB_PATH`: path a librería existente (solo con --depth deep)
   - `--mathlib`: flag booleano (solo con --library)

2. **Detección contextual de profundidad** (si `--depth` NO fue dado explícitamente):
   Buscar en el prompt del usuario (case-insensitive) indicadores de modo deep:
   - Palabras clave: `profundo`, `profunda`, `deep`, `formalizar`, `formalización`,
     `teoremas`, `lean4`, `librería`, `library`, `exhaustivo`, `exhaustiva`
   - Si se detectan **2 o más** de estas palabras → inferir `--depth deep`
   - Si se detecta `--library` o `--target-library` como argumento → inferir `--depth deep` automáticamente
   - Si se infirió deep: informar al usuario "Detectado modo profundo. Usando --depth deep."
   - Si se infirió deep pero falta `--library`/`--target-library`: **preguntar al usuario**
     el nombre de la librería destino antes de continuar.

3. Generar slug para el archivo de salida:
```bash
SLUG=$(python3 $SKILL_DIR/scripts/slugify_topic.py "{STUDY_OBJECT}")
```
   El archivo final será: `{SLUG}_insights.md`

4. Auto-detectar dominio si no se proporcionó:
   - Si PROJECT_PATH contiene archivos `.lean` → domain=lean4
   - Si no se puede detectar → domain=general

5. Auto-detectar proyecto:
   - Buscar `roadmap_*.md`, `fase*_roadmap.md`, `ROADMAP.md` en directorio actual
   - Si existe, usar como PROJECT_PATH

6. Validar argumentos deep:
   - Si `--depth deep` Y ni `--library` ni `--target-library` → **ERROR**: "Se requiere --library NAME o --target-library PATH con --depth deep"
   - Si `--library` Y `--target-library` → **ERROR**: "Usar --library O --target-library, no ambos"
   - Si `--mathlib` sin `--library` → **WARNING**: "--mathlib ignorado sin --library"
   - Si `--depth deep` Y `--skip-online` → **WARNING**: "--depth deep funciona mejor con papers online. Continuando con bibliografía existente."
   - Si `--target-library PATH` → verificar que PATH existe y contiene `lakefile.lean`
   - Si `--library NAME` → verificar que `~/Documents/claudio/{nombre_lowercase}/` NO existe

## Paso 1: Wave 1 — Recolección Paralela

**Lanzar los 4 agentes en UNA sola llamada Task (Agent Teams):**

**Agent 1: Input Analyzer** — Task(Explore, haiku)
```
"Analiza el siguiente objeto de estudio para una investigación pre-planificación.

OBJETO DE ESTUDIO: {STUDY_OBJECT}

{SI PROJECT_PATH existe:}
PROYECTO EXISTENTE en: {PROJECT_PATH}
1. Lee los archivos roadmap: Glob('roadmap_*.md', 'ROADMAP.md', 'fase*_roadmap.md') en {PROJECT_PATH}
2. Lee el estado actual: busca archivos TODO, plan_actual.md, progreso
3. Analiza la estructura del proyecto: Glob('**/*.lean' o '**/*.rs' o '**/*.py') — solo contar, no leer
4. Identifica el estado actual: qué fases están completadas, qué está pendiente

{SI hay archivos de entrada adicionales:}
Lee y analiza los archivos proporcionados.

RETORNA en formato estructurado:
- RESUMEN: 3-5 oraciones describiendo el objeto de estudio
- KEYWORDS: 10-15 keywords técnicos relevantes (para búsqueda bibliográfica)
- ESTADO: nuevo | upgrade | investigación
- GAPS: áreas donde falta información o investigación
- DEPENDENCIAS: conceptos prerequisito identificados"
```

**Agent 2: Lecciones Globales** — Task(Explore, haiku)
```
"Busca lecciones aprendidas relevantes para: {STUDY_OBJECT}

Dominio: {DOMAIN}

1. Ejecuta: python3 ~/Documents/claudio/lecciones/scripts/query_lessons.py --hybrid '{STUDY_OBJECT}'
2. Si el resultado es insuficiente, ejecuta búsquedas adicionales con keywords más específicos
3. Para las top 5-8 lecciones, ejecuta --lesson <ID> para leer contenido completo
4. Clasifica cada lección encontrada como: aplicable / anti-patrón / técnica reutilizable

RETORNA en formato estructurado:
- LECCIONES_APLICABLES: lista de (ID, título, resumen 2 líneas, categoría)
- ANTI_PATRONES: lista de anti-patrones relevantes
- TÉCNICAS: técnicas reutilizables con referencia a lección
- CRÍTICAS: las 3-5 lecciones más importantes para este objeto"
```

**Agent 3: Bibliografía Existente** — Task(Explore, haiku)
```
"Investiga la bibliografía existente relevante para: {STUDY_OBJECT}

1. Lee ~/Documents/claudio/biblioteca/indices/_global_topic_index.md
2. Identifica carpetas relevantes del índice global
3. Para cada carpeta relevante, lee su _folder_index.md en indices/{carpeta}/
4. Ejecuta búsquedas en el grafo conceptual:
   python3 ~/.claude/skills/study-biblio/scripts/query_graph.py --topic '{KEYWORD}'
   (para 3-5 keywords clave del objeto de estudio)
5. Para conceptos encontrados, busca dependencias:
   python3 ~/.claude/skills/study-biblio/scripts/query_graph.py --deps '{CONCEPTO}'

RETORNA en formato estructurado:
- DOCUMENTOS_RELEVANTES: lista de (nombre, carpeta, resumen 1 línea)
- CONCEPTOS_CONECTADOS: conceptos del grafo relacionados con el objeto
- PATHWAYS: research pathways relevantes del índice global
- GAPS_BIBLIOGRÁFICOS: temas del objeto NO cubiertos por la biblioteca actual"
```

**Agent 4: Estrategias de Proyecto** — Task(Explore, haiku)
```
"Busca estrategias y decisiones de proyectos previos relevantes para: {STUDY_OBJECT}

1. Busca archivos de decisiones y lecciones de proyecto:
   Glob('**/decisiones_*.md') en ~/Documents/claudio/
   Glob('**/lecciones_fase*.md') en ~/Documents/claudio/
   Glob('**/benchmarks_*.md') en ~/Documents/claudio/
2. Busca roadmaps para entender estrategias:
   Glob('**/roadmap_*.md') en ~/Documents/claudio/
   Glob('**/fase*_roadmap.md') en ~/Documents/claudio/
3. Lee los archivos encontrados y extrae:
   - Estrategias que funcionaron (ganadoras)
   - Decisiones arquitecturales clave
   - Benchmarks alcanzados como referencia
   - Errores evitados (decisiones descartadas y por qué)

RETORNA en formato estructurado:
- ESTRATEGIAS_GANADORAS: lista de (estrategia, proyecto fuente, resultado)
- DECISIONES_ARQUITECTURALES: decisiones relevantes con justificación
- BENCHMARKS_REFERENCIA: métricas alcanzadas en proyectos similares
- ERRORES_EVITADOS: decisiones descartadas y la razón"
```

## Paso 2: Recolectar Wave 1

Esperar a que los 4 agentes terminen. Leer sus outputs.

Extraer de Agent 1: `KEYWORDS` y `GAPS` para Wave 2.
Extraer de Agent 3: `GAPS_BIBLIOGRÁFICOS` para Wave 2.

## Paso 3: Wave 2 — Investigación Online

**SALTAR si `--skip-online` está activo.** Ir directo al Paso 7 (o Paso 5 si --depth deep).

**Agent 5: Online Researcher** — Task(general-purpose)
```
"Busca bibliografía online faltante para: {STUDY_OBJECT}

KEYWORDS del análisis: {KEYWORDS de Agent 1}
GAPS BIBLIOGRÁFICOS: {GAPS de Agent 3}

1. Para cada gap bibliográfico, busca con WebSearch:
   - '{gap} paper PDF'
   - '{gap} arxiv'
   - '{gap} tutorial'
   Fuentes prioritarias: arXiv, IACR ePrint, documentación oficial

2. Para cada paper relevante encontrado (máximo {MAX_DOWNLOADS}):
   a. Clasifica el paper:
      python3 ~/.claude/skills/insights/scripts/classify_paper.py \
        --title '{TÍTULO}' --abstract '{ABSTRACT}'
   b. Descarga el PDF:
      python3 ~/.claude/skills/insights/scripts/download_papers.py \
        --url '{URL}' --folder '{FOLDER}' --name '{SLUG}'

3. NO descargar si:
   - El paper ya existe en la biblioteca (verificar con Glob)
   - La URL no lleva a un PDF real
   - El paper no es relevante para el objeto de estudio

RETORNA en formato estructurado:
- PAPERS_DESCARGADOS: lista de (título, url, carpeta, path local, resumen 1 línea)
- PAPERS_EXISTENTES: papers encontrados que ya estaban en la biblioteca
- PAPERS_NO_DESCARGADOS: papers relevantes encontrados pero no descargados (y razón)
- RESUMEN_BÚSQUEDA: resumen de lo que se encontró online"
```

## Paso 4: Wave 3 — Indexar Nueva Bibliografía

**SALTAR si `--skip-online` o si Agent 5 no descargó nada.** Ir al Paso 5 (si --depth deep) o Paso 7 (síntesis).

**Agent 6: New Biblio Studier** — Task(general-purpose)
```
"Indexa los nuevos PDFs descargados y extrae insights.

PAPERS DESCARGADOS:
{lista de paths de Agent 5}

1. Para CADA PDF nuevo, indexar:
   python3 ~/.claude/skills/study-biblio/scripts/study_pdf.py '{PATH}'

2. Reconstruir el grafo conceptual:
   python3 ~/.claude/skills/study-biblio/scripts/build_graph.py --verbose

3. Leer los resúmenes generados (en biblioteca/indices/) y extraer insights relevantes para:
   {STUDY_OBJECT}

RETORNA en formato estructurado:
- INSIGHTS_NUEVOS: hallazgos relevantes de cada paper nuevo
- CONCEPTOS_AGREGADOS: conceptos nuevos incorporados al grafo
- CONEXIONES_DESCUBIERTAS: nuevas conexiones entre conceptos existentes y nuevos"
```

## Paso 5: Wave 4 — Extracción Profunda de Teoremas

**SALTAR si `--depth` != `deep`.** Ir directo al Paso 7 (Síntesis).

**Preparar inputs:**
1. Recolectar TODOS los resúmenes relevantes:
   - De Agent 3 (bibliografía existente): paths a summaries en `biblioteca/indices/`
   - De Agent 6 (nueva bibliografía indexada): paths a summaries nuevos
   - Buscar summaries adicionales con:
     ```bash
     python3 ~/.claude/skills/study-biblio/scripts/query_graph.py --topic '{STUDY_OBJECT}'
     ```
     Para cada concepto encontrado, obtener sus documentos:
     ```bash
     python3 ~/.claude/skills/study-biblio/scripts/query_graph.py --docs '{CONCEPTO}'
     ```
2. Filtrar: solo summaries que tengan Mathematical Objects relevantes o Key Concepts del estudio

**Agent 7: Deep Theorem Extractor** — Task(general-purpose)
```
"Extrae teoremas formalizables de los resúmenes de papers sobre: {STUDY_OBJECT}

RESÚMENES DISPONIBLES:
{lista de paths a summaries filtrados}

1. Lee cada resumen (son archivos .md cortos, ~100 líneas cada uno)
2. Para cada paper con contenido matemático relevante:
   - Identifica teoremas, proposiciones, lemas formalizables
   - Foco en: {STUDY_OBJECT} y keywords: {KEYWORDS}

3. Ejecuta el extractor (PRIMARIO — Gemini Flash):
   python3 $SKILL_DIR/scripts/extract_theorems.py \
     --summaries {PATHS...} \
     --study-object '{STUDY_OBJECT}' \
     --keywords {KEYWORDS...} \
     --max-theorems 30

4. **FALLBACK si extract_theorems.py falla** (Gemini no disponible, error de API, JSON inválido):
   Realizar la extracción INLINE sin script:
   a. Leer cada summary directamente (son .md cortos)
   b. Identificar secciones 'Mathematical Objects' y 'Key Concepts'
   c. Para cada concepto matemático relevante al STUDY_OBJECT:
      - Formular como theorem candidate con: name, informal_statement, dependencies, topic_group
      - Asignar suggested_lean_name (camelCase)
      - Estimar difficulty (trivial/easy/medium/hard)
   d. Construir dependency_order manualmente (fundaciones primero)
   e. Formatear el resultado en la misma estructura JSON que extract_theorems.py
   NOTA: La extracción inline es menos sofisticada pero funcional como fallback.

5. Valida el output JSON (sea de Gemini o inline):
   - Verificar que dependency_order es un orden topológico válido
   - Verificar que topic_groups agrupa lógicamente
   - Si la librería destino NO usa Mathlib: filtrar teoremas con mathlib_likely=true

RETORNA el JSON completo + análisis:
- TOTAL_TEOREMAS: número de teoremas extraídos
- POR_GRUPO: desglose por topic_group
- ORDEN_TRABAJO: dependency_order (orden sugerido de formalización)
- DIFICULTAD: distribución (trivial/easy/medium/hard)
- FUENTE_EXTRACCIÓN: 'gemini' | 'inline_fallback'"
```

Guardar el output JSON como variable `THEOREMS_JSON` para Wave 5.
Si la extracción retorna 0 teoremas, **SALTAR Wave 5** e indicar en síntesis.

## Paso 6: Wave 5 — Formalización Lean 4 y Gestión de Librería

**SALTAR si Wave 4 produjo 0 teoremas o `--depth` != `deep`.**

### Paso 6a: Crear/Preparar Librería

**Si `--library NAME`:**
```bash
python3 $SKILL_DIR/scripts/create_library.py \
  --name '{LIBRARY_NAME}' \
  --description 'Formal verification library for {STUDY_OBJECT}' \
  {--mathlib si flag activo}
```
Guardar el JSON de resultado. `LIB_PATH` = path retornado. `CAMEL_NAME` = camel_name retornado.

**Si `--target-library PATH`:**
`LIB_PATH` = TARGET_LIB_PATH. Leer `lakefile.lean` para determinar `CAMEL_NAME`.

### Paso 6b: Formalización por Grupos

**Agent 8: Lean 4 Formalizer** — Task(general-purpose)
```
"Formaliza teoremas en Lean 4 para la librería en: {LIB_PATH}

LIBRERÍA: {CAMEL_NAME}
MATHLIB: {sí/no}
TEOREMAS (en orden de dependencias):
{THEOREMS_JSON con dependency_order y detalles}

Para cada grupo de teoremas (topic_group), EN ORDEN de dependency_order:

1. **Consulta previa** (para teoremas con mathlib_likely=true o difficulty=hard):
   - Busca si Mathlib ya lo tiene:
     Usar lean_loogle con la signatura estimada del teorema
     Usar lean_leansearch con el statement informal
   - Si Mathlib lo tiene: importar directamente, no re-probar

2. **Crear archivo Lean 4**:
   - Path: {LIB_PATH}/{CAMEL_NAME}/{TopicGroup}.lean
   - Header: module docstring con fuente (paper) y descripción
   - Imports: solo de módulos ya creados dentro de la librería + Mathlib si aplica

3. **Para cada teorema en el grupo**:
   a. Escribir definiciones prerequisito (si no existen en módulo previo)
   b. Escribir statement del theorem
   c. Intentar cascada de solvers:
      - `by rfl`
      - `by simp`
      - `by ring` (si Mathlib)
      - `by omega`
      - `by exact?` (via lean_code_actions)
      - `by apply?` (via lean_code_actions)
      - `by aesop`
      - `by norm_num` (si Mathlib)
      - `by field_simp; ring` (si Mathlib)
      - `by decide` / `by native_decide`
   d. Verificar con lean_diagnostic_messages si compila
   e. Si NO compila tras cascada:
      - Intentar lean_multi_attempt con 5 variantes heurísticas
      - Si falla: **ESCALACIÓN a ask-lean** (DeepSeek expert):
        python3 ~/.claude/skills/ask-lean/scripts/ask_lean.py \
          --rounds 1 --model reasoner --subagent \
          "Prove this Lean 4 theorem: {theorem_statement}. Goal state: {goal_from_lean_goal}. Context: {local_context}"
        Aplicar la sugerencia de DeepSeek e intentar compilar.
      - Si aún falla: **FALLBACK a ask-qwen** (Qwen local, sin costo):
        python3 ~/.claude/skills/ask-qwen/scripts/ask_qwen.py \
          --rounds 1 --subagent \
          "Suggest a proof for: {theorem_statement}"
        Aplicar e intentar compilar.
      - Si todo falla: dejar sorry con comentario documentando:
        /- TODO: proof needed
           Informal: {informal_statement}
           Source: {source_paper}
           Attempted: solver cascade + lean_multi_attempt + ask-lean + ask-qwen -/
   f. Máximo 3 rondas de cascada + 1 ronda ask-lean + 1 ronda ask-qwen por teorema, luego sorry

4. **Actualizar root module** ({CAMEL_NAME}.lean):
   - Agregar `import {CAMEL_NAME}.{TopicGroup}` para cada archivo nuevo
   - Actualizar docstring con conteo de teoremas

5. **Verificar compilación**:
   - Ejecutar lean_diagnostic_messages en cada archivo nuevo
   - Si hay errores de compilación (no sorry): intentar reparar
   - Último recurso: comentar el teorema problemático con -- COMPILATION_ERROR

6. **Reportar**:

RETORNA en formato estructurado:
- ARCHIVOS_CREADOS: lista de paths
- POR_ARCHIVO: {path, teoremas, probados, sorry, errores}
- RESUMEN: {total_teoremas, total_probados, total_sorry, total_error}
- IMPORTS_AGREGADOS: lista de imports añadidos al root module"
```

### Paso 6c: Build Final

Ejecutar `lake build` en LIB_PATH:
```bash
cd {LIB_PATH} && lake build 2>&1 | tail -20
```

Si hay errores de build:
1. Leer los errores
2. Intentar fix rápido (imports faltantes, typos de tipo)
3. Si Mathlib aún descargando (primer build): reportar "build pendiente — Mathlib descargando"
4. Si no se puede resolver: reportar en la síntesis como "build parcial"

### Paso 6d: Actualizar MEMORY.md

Si se creó una librería nueva (`--library`), actualizar la tabla de inventario en:
`~/.claude/projects/-Users-manuelpuebla-Documents-claudio/memory/MEMORY.md`

Agregar nueva fila con: Nombre, Path, Toolchain (v4.26.0), conteo de teoremas, dominio.

## Paso 7: Síntesis Final

Combinar TODOS los outputs de los agentes (6 en standard, 8 en deep) en el documento final.

### Generar la sección 7 (Síntesis de Insights)

Analizar cruzadamente todos los resultados para producir:
1. **Hallazgos clave (Top 5-10)**: Los insights más relevantes, priorizados por impacto
2. **Riesgos identificados**: Riesgos que emergen de la investigación
3. **Recomendaciones para planificación**: Input directo para `/plan-project`
4. **Recursos prioritarios**: Top 5 documentos/lecciones a tener a mano

### Escribir el archivo

Guardar como `{SLUG}_insights.md` en el directorio actual con esta estructura:

```markdown
# Insights: {STUDY_OBJECT}

**Fecha**: {YYYY-MM-DD}
**Dominio**: {DOMAIN}
**Estado del objeto**: {nuevo | upgrade | investigación}

## 1. Análisis del Objeto de Estudio
{Output Agent 1}

## 2. Lecciones Aplicables
### Lecciones reutilizables
{Lecciones del Agent 2 con ID y contenido resumido}
### Anti-patrones a evitar
{Anti-patrones del Agent 2}

## 3. Bibliografía Existente Relevante
### Documentos clave
{Documentos del Agent 3 con resumen}
### Grafo de conceptos relacionados
{Conexiones del grafo conceptual}
### Gaps identificados
{Gaps bibliográficos}

## 4. Estrategias y Decisiones Previas
### Estrategias ganadoras
{Estrategias del Agent 4}
### Decisiones arquitecturales aplicables
{Decisiones del Agent 4}
### Benchmarks de referencia
{Benchmarks del Agent 4}

## 5. Nueva Bibliografía Encontrada
{Output Agent 5 — o "Sección omitida (--skip-online)" si se saltó}

## 6. Insights de Nueva Bibliografía
{Output Agent 6 — o "Sección omitida (sin descargas nuevas)" si se saltó}

## 7. Síntesis de Insights
### Hallazgos clave
{Top 5-10 insights priorizados}
### Riesgos identificados
{Riesgos}
### Recomendaciones para planificación
{Recomendaciones concretas para /plan-project}
### Recursos prioritarios
{Top 5 documentos/lecciones a consultar}
### Deep Analysis (si --depth deep)
{Integrar findings de Waves 4-5: teoremas formalizados como evidencia de viabilidad,
cobertura de conceptos del paper, recomendaciones de /fill-sorry para proofs pendientes}

## 8. Teoremas Extraídos
{Output Agent 7 — o "Sección omitida (--depth standard)" si no aplica}
### Por grupo temático
{Tabla: grupo | cantidad | dificultad promedio}
### Orden de dependencias
{DAG textual de dependencias entre teoremas}

## 9. Formalización Lean 4
{Output Agent 8 — o "Sección omitida (--depth standard)" si no aplica}
### Resumen
| Métrica | Valor |
|---------|-------|
| Teoremas totales | N |
| Probados | N |
| Sorry | N |
| Errores compilación | N |
### Archivos generados
{Lista de archivos con estadísticas por archivo}

## 10. Librería Generada
{Info de la librería — o "Sección omitida (--depth standard)" si no aplica}
- **Nombre**: {CAMEL_NAME}
- **Path**: {LIB_PATH}
- **Mathlib**: sí/no
- **Build**: OK / parcial / pendiente
- **Uso**: copiar/adaptar teoremas al proyecto destino (NUNCA importar como dependencia)
```

## Paso 8: Presentar al Usuario

1. Mostrar resumen compacto:
   - Número de insights encontrados
   - Papers descargados (si aplica)
   - Lecciones relevantes encontradas
   - Gaps identificados
   - (si --depth deep) Teoremas extraídos: N total, N por grupo
   - (si --depth deep) Formalización: N probados / N sorry / N errores
2. Indicar ruta del archivo: `{SLUG}_insights.md`
3. Sugerir: "Para planificar con estos insights: `/plan-project '{STUDY_OBJECT}'`"
4. (si --depth deep) Indicar: "Librería en `{LIB_PATH}`. Para verificar: `cd {LIB_PATH} && lake build`"
5. (si --depth deep con sorry) Sugerir: "Para completar proofs pendientes: `/fill-sorry {FILE}:{LINE}`"

## Edge Cases

- **Sin lecciones para el dominio**: Sección 2 muestra "No hay lecciones registradas para el dominio {DOMAIN}"
- **Sin resultados online**: Secciones 5-6 muestran "Biblioteca existente cubre el tema adecuadamente"
- **Proyecto inexistente**: Agent 1 trabaja solo con descripción textual
- **Grafo conceptual no existe**: Agent 3 usa solo _global_topic_index.md e índices de carpeta
- **--skip-online**: Waves 2-3 se saltan, secciones 5-6 indican "Omitido por --skip-online"
- **Todas las descargas fallan**: Sección 5 reporta errores, sección 6 se omite
- **--depth deep sin papers matemáticos**: Waves 4-5 se saltan, secciones 8-10 muestran "Sin papers con contenido matemático para extraer"
- **--depth deep, todos los teoremas sorry**: Sección 9 reporta todo como sorry, sugiere revisión manual con `/fill-sorry`
- **--target-library con conflicto de nombres**: Si un archivo .lean ya existe en la librería, agregar sufijo (`_v2`, `_ext`) al nombre del módulo
- **--library con nombre existente**: ERROR si el directorio ya existe en ~/Documents/claudio/
- **Mathlib download timeout**: Sección 10 reporta "build pendiente — Mathlib aún descargando" (primer build con Mathlib puede ser largo)
- **--depth deep + --skip-online**: Usa solo bibliografía existente para extracción; si no hay papers relevantes, saltar Waves 4-5

## Reglas

- NUNCA cargar archivos completos de lecciones en el contexto principal — delegar a agentes
- NUNCA leer PDFs directamente — usar scripts de study-biblio
- Wave 1 SIEMPRE paralela (4 agentes en UNA sola llamada)
- Máximo 5 descargas online por defecto (configurable con --max-downloads)
- El archivo de salida SIEMPRE se escribe, incluso si algunas secciones están vacías
- Wave 4 NUNCA lee PDFs directamente — solo resúmenes de biblioteca/indices/
- Wave 5 NUNCA importa librerías internas como dependencia lake — solo copia/adapta
- Solver cascade en Wave 5: máximo 3 rondas por teorema, luego sorry documentado
- `lake build` en la librería es OBLIGATORIO antes de reportar resultados
- MEMORY.md se actualiza SOLO si se creó librería nueva (--library)
- `--depth standard` (default) NO ejecuta Waves 4-5 ni genera secciones 8-10
