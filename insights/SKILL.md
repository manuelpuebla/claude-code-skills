---
name: insights
description: Investigación pre-planificación con 6 agentes paralelos. Estudia bibliografía, lecciones, proyectos y recursos online para producir insights estructurados.
allowed-tools: Task, Bash(python3 *), Read, Glob, Grep, WebSearch, WebFetch, Write
argument-hint: '"objeto de estudio" [--domain lean4] [--project path/] [--max-downloads 5] [--skip-online]'
---

# Insights: Investigación Pre-Planificación con Agent Team

## Help

Si el usuario invoca con `?` o `--help`, mostrar:
```
/insights "objeto de estudio" [--domain lean4] [--project path/] [--max-downloads 5] [--skip-online]

Investigación pre-planificación con 6 agentes paralelos:
  Agent 1: Analiza el objeto de estudio / proyecto de entrada
  Agent 2: Estudia lecciones aprendidas globales (lecciones/)
  Agent 3: Busca bibliografía relevante en el grafo conceptual
  Agent 4: Extrae estrategias de proyectos previos (decisiones_*, benchmarks_*)
  Agent 5: Busca y descarga bibliografía online faltante
  Agent 6: Indexa nueva bibliografía y extrae insights

Workflow: Wave 1 (1-4 paralelo) → Wave 2 (5 online) → Wave 3 (6 indexación) → Síntesis
Output:   {slug}_insights.md en directorio actual

Opciones:
  --domain DOMAIN      Dominio de lecciones (lean4, etc.)
  --project PATH       Ruta al proyecto existente a investigar
  --max-downloads N    Máximo de PDFs a descargar online (default: 5)
  --skip-online        Saltar búsqueda online (solo recursos locales)
```

## Paso 0: Parse y Preparación

1. Extraer argumentos del prompt del usuario:
   - `STUDY_OBJECT`: el texto entre comillas (obligatorio)
   - `--domain DOMAIN`: dominio de lecciones (default: auto-detectar)
   - `--project PROJECT_PATH`: ruta al proyecto existente (default: directorio actual si tiene roadmap)
   - `--max-downloads N`: máximo descargas online (default: 5)
   - `--skip-online`: flag booleano

2. Generar slug para el archivo de salida:
```bash
SLUG=$(python3 $SKILL_DIR/scripts/slugify_topic.py "{STUDY_OBJECT}")
```
   El archivo final será: `{SLUG}_insights.md`

3. Auto-detectar dominio si no se proporcionó:
   - Si PROJECT_PATH contiene archivos `.lean` → domain=lean4
   - Si no se puede detectar → domain=general

4. Auto-detectar proyecto:
   - Buscar `roadmap_*.md`, `fase*_roadmap.md`, `ROADMAP.md` en directorio actual
   - Si existe, usar como PROJECT_PATH

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

1. Lee ~/Documents/claudio/lecciones/{DOMAIN}/INDEX.md
2. Identifica categorías relevantes al objeto de estudio
3. Para cada categoría relevante, lee el archivo completo y extrae:
   - Lecciones directamente aplicables (ID + contenido)
   - Anti-patrones a evitar
   - Técnicas reutilizables
4. Si no existe el dominio, lista los dominios disponibles en ~/Documents/claudio/lecciones/

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

**SALTAR si `--skip-online` está activo.** Ir directo al Paso 5.

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

**SALTAR si `--skip-online` o si Agent 5 no descargó nada.** Ir al Paso 5.

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

## Paso 5: Síntesis Final

Combinar TODOS los outputs de los 6 agentes en el documento final.

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
```

## Paso 6: Presentar al Usuario

1. Mostrar resumen compacto:
   - Número de insights encontrados
   - Papers descargados (si aplica)
   - Lecciones relevantes encontradas
   - Gaps identificados
2. Indicar ruta del archivo: `{SLUG}_insights.md`
3. Sugerir: "Para planificar con estos insights: `/plan-project '{STUDY_OBJECT}'`"

## Edge Cases

- **Sin lecciones para el dominio**: Sección 2 muestra "No hay lecciones registradas para el dominio {DOMAIN}"
- **Sin resultados online**: Secciones 5-6 muestran "Biblioteca existente cubre el tema adecuadamente"
- **Proyecto inexistente**: Agent 1 trabaja solo con descripción textual
- **Grafo conceptual no existe**: Agent 3 usa solo _global_topic_index.md e índices de carpeta
- **--skip-online**: Waves 2-3 se saltan, secciones 5-6 indican "Omitido por --skip-online"
- **Todas las descargas fallan**: Sección 5 reporta errores, sección 6 se omite

## Reglas

- NUNCA cargar archivos completos de lecciones en el contexto principal — delegar a agentes
- NUNCA leer PDFs directamente — usar scripts de study-biblio
- Wave 1 SIEMPRE paralela (4 agentes en UNA sola llamada)
- Máximo 5 descargas online por defecto (configurable con --max-downloads)
- El archivo de salida SIEMPRE se escribe, incluso si algunas secciones están vacías
