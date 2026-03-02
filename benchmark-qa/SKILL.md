---
name: benchmark-qa
description: Request strict benchmark criteria from Gemini QA based on phase roadmap and emphasis areas.
allowed-tools: Bash(python3 *)
argument-hint: "--phase faseX_roadmap.md [--emphasis \"texto\"]"
---

# Benchmark QA: Criterios Estrictos de Gemini

Esta skill envía el roadmap de una fase a Gemini 2.5 Pro para que defina criterios de benchmark estrictos y métricas de éxito.

## Help Request Detection

Si el usuario invoca con `?`, `--help`, `help`, mostrar esta referencia:

```
/benchmark-qa - Solicitar criterios de benchmark estrictos a Gemini QA

USAGE:
  /benchmark-qa --phase <roadmap_file> [options]

OPTIONS:
  --phase, -p FILE       Archivo roadmap de la fase (requerido)
  --emphasis, -e "text"  Áreas de énfasis para los benchmarks
  --strict               Modo estricto (criterios más exigentes)

EXAMPLES:
  /benchmark-qa --phase fase2_roadmap.md
  /benchmark-qa -p fase3_roadmap.md --emphasis "latencia y throughput"
  /benchmark-qa --phase fase1_roadmap.md -e "memory footprint" --strict

OUTPUT:
  Gemini QA responderá con:
  - Métricas específicas a medir
  - Valores objetivo (baseline vs óptimo)
  - Metodología de medición
  - Criterios de aceptación/rechazo
  - Herramientas recomendadas
```

## How to Use

Cuando el usuario invoca esta skill:

1. **Leer el archivo roadmap** especificado en `--phase`
2. **Ejecutar el script** con el contenido del roadmap y el énfasis
3. **Presentar los criterios** de Gemini al usuario
4. **Discutir** y refinar si es necesario

## Execution

```bash
python3 $SKILL_DIR/scripts/benchmark.py --phase "{PHASE_FILE}" --emphasis "{EMPHASIS_TEXT}" [--strict]
```

## Arguments

| Argument | Description | Required |
|----------|-------------|----------|
| `--phase FILE` | Archivo roadmap de la fase | Sí |
| `--emphasis "text"` | Áreas de énfasis | No |
| `--strict` | Criterios más exigentes | No |

## Workflow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Usuario: /benchmark-qa --phase fase2_roadmap.md          │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Claude lee el roadmap de la fase                         │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Envía a Gemini QA con rol de Benchmark Engineer          │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Gemini responde con:                                     │
│    - Métricas a medir                                       │
│    - Valores objetivo                                       │
│    - Metodología                                            │
│    - Criterios de aceptación                                │
│    - Herramientas recomendadas                              │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. Claude presenta y discute los criterios con el usuario   │
└─────────────────────────────────────────────────────────────┘
```

## Gemini Role

En esta skill, Gemini actúa como **Senior Performance/Benchmark Engineer** con expertise en:
- Diseño de benchmarks reproducibles
- Análisis de rendimiento y profiling
- Metodología científica de medición
- Criterios estadísticos de validación

## After Gemini Responds

Claude debe:
1. Presentar los criterios propuestos
2. Identificar criterios que pueden ser demasiado estrictos o laxos
3. Sugerir ajustes basados en el contexto del proyecto
4. Preparar template para `benchmarks_fase{n}.md`
