---
name: ask-lean
description: Consulta a DeepSeek como experto en Lean 4 y Mathlib. Multi-ronda con contexto y archivos de referencia. Soporta modo subagente.
allowed-tools: Bash(python3 *)
argument-hint: "[--rounds N] [--context \"desc\"] [--reference file.lean] [--subagent]"
---

# Ask Lean Expert: Consulta DeepSeek para Lean 4

Esta skill consulta a DeepSeek (modelo entrenado con conocimiento de Lean 4) para obtener ayuda experta en programación Lean.

## Help Request Detection

Si el usuario invoca con `?`, `--help`, `help`, mostrar esta referencia:

```
/ask-lean - Consultar DeepSeek como experto Lean 4

USAGE:
  /ask-lean "pregunta o código"

OPTIONS:
  --rounds N, -r N       Rondas de consulta (1-5, default: 2)
  --context "text"       Descripción de contexto
  --reference FILE       Archivo de referencia (.lean, .md)
  --model MODEL          deepseek-chat (default) o deepseek-reasoner
  --subagent, -s         Modo subagente: retorna síntesis compacta

EXAMPLES:
  /ask-lean "How do I prove n + m = m + n?"
  /ask-lean --rounds 3 "Review this tactic strategy"
  /ask-lean --context "NTT verification" "Best tactics for sum manipulation?"
  /ask-lean --reference MiTeorema.lean "Help complete the sorry"
  /ask-lean -r 2 --reference spec.md "How to prove this theorem?"
  /ask-lean --subagent --rounds 2 "tactic for ZMod"

MODES:
  Direct:    Salida completa (default)
  Subagent:  Síntesis compacta (~500 tokens vs ~4K tokens)

DEEPSEEK RESPONDS WITH:
  - Analysis: Assessment of your question/code
  - Issues or Gaps: Problems identified
  - Suggested Solution: Specific tactics and code
  - Relevant Mathlib: Useful lemmas and theorems
  - Alternative Approaches: Other ways to solve it
```

## How to Use

Cuando el usuario invoca esta skill:

1. **Capturar la pregunta o código** del usuario (o última respuesta de Claude si es revisión)
2. **Ejecutar el script** con los parámetros apropiados
3. **Presentar la respuesta** de DeepSeek
4. **Sintetizar** si hay múltiples rondas

## Execution

```bash
python3 $SKILL_DIR/scripts/ask_lean.py --rounds {ROUNDS} --context "{CONTEXT}" --reference "{REFERENCE_FILE}" "{USER_INPUT}"
```

O con heredoc para inputs largos:

```bash
python3 $SKILL_DIR/scripts/ask_lean.py --rounds {ROUNDS} --context "{CONTEXT}" --reference "{REFERENCE_FILE}" "$(cat <<'INPUT'
{USER_INPUT}
INPUT
)"
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--rounds N` | Number of consultation rounds | 2 |
| `--context "text"` | Brief description of context | "" |
| `--reference file` | Reference file (.lean, .md) | none |
| `--model` | deepseek-chat or deepseek-reasoner | deepseek-chat |

## Workflow

```
┌─────────────────────────────────────────────────────────┐
│ 1. Usuario tiene pregunta/problema de Lean 4            │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│ 2. /ask-lean --reference mi_teorema.lean "ayuda"        │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│ 3. DeepSeek analiza y responde con:                     │
│    - Analysis                                           │
│    - Issues or Gaps                                     │
│    - Suggested Solution (con código Lean)               │
│    - Relevant Mathlib                                   │
│    - Alternative Approaches                             │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│ 4. Claude integra la respuesta y ayuda al usuario       │
└─────────────────────────────────────────────────────────┘
```

## Model Selection

| Model | Use Case |
|-------|----------|
| `deepseek-chat` | Respuestas rápidas, código directo |
| `deepseek-reasoner` | Problemas complejos, chain-of-thought |

## After DeepSeek Responds

Claude debe:
1. **Evaluar** la calidad de la respuesta
2. **Verificar** que el código Lean sugerido sea correcto
3. **Complementar** con información de `/lean-search` si es necesario
4. **Sintetizar** una respuesta integrada para el usuario

## Differences from /collab-qa

| Aspect | /collab-qa | /ask-lean |
|--------|------------|-----------|
| **Provider** | Gemini 2.5 Pro | DeepSeek |
| **Role** | Senior QA Engineer | Lean 4 Expert |
| **Focus** | Review & critique | Help & suggestions |
| **Output** | APPROVE/REJECT | Solutions & code |
| **Best for** | Validar planes/código | Resolver dudas Lean |

## Integration with Other Skills

```
/lean-search → Encontrar teoremas en Mathlib
/ask-lean → Pedir ayuda experta en Lean 4
/collab-qa → Revisar plan/código con QA
/benchmark-qa → Definir criterios de benchmark
```

## API Configuration

Requires `DEEPSEEK_API_KEY`. Get one at: https://platform.deepseek.com/

Set in environment or in `~/.env`:
```
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
```

## Subagent Mode

Cuando se invoca con `--subagent`, la skill retorna una síntesis compacta:

### Beneficios
- **Eficiencia de contexto**: ~500 tokens vs ~4K tokens por consulta
- **Integración automática**: Usado por `/plan-project` durante planificación
- **Disponibilidad directa**: Los usuarios pueden invocar directamente sin `--subagent`

### Formato de Síntesis
```
# Lean Expert Synthesis (DeepSeek)

**Rounds completed**: 2

## Analysis
[Resumen del análisis]

## Issues Identified
[Problemas encontrados]

## Suggested Solution
[Solución con código Lean]

## Relevant Mathlib
[Lemmas y estructuras útiles]
```

### Uso en Subagentes
```bash
python3 $SKILL_DIR/scripts/ask_lean.py --subagent --rounds 2 --context "..." "pregunta"
```
