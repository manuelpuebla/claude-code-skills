# claude-code-skills

Coleccion de 14 custom skills y 11 hooks para [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (la CLI oficial de Anthropic). Cada skill es un directorio independiente que puedes copiar a tu `~/.claude/skills/`, y los hooks se copian a `~/.claude/hooks/`.

## Que es esto

Custom skills son extensiones de Claude Code que le ensenan nuevos flujos de trabajo: desde verificacion formal en Lean 4 hasta QA colaborativo con Gemini, indexacion de bibliografia PDF y planificacion de proyectos con DAGs topologicos.

Estas skills fueron desarrolladas para un workflow de matematica pura + verificacion formal, pero muchas son de proposito general (planificacion, QA, documentacion, notificaciones).

## Instalacion

### Opcion 1: Copiar todo

```bash
git clone https://github.com/manuelpuebla/claude-code-skills.git
cp -R claude-code-skills/*/ ~/.claude/skills/
```

### Opcion 2: Copiar skills individuales

```bash
git clone https://github.com/manuelpuebla/claude-code-skills.git
cp -R claude-code-skills/collab-qa ~/.claude/skills/
cp -R claude-code-skills/plan-project ~/.claude/skills/
# ... solo las que necesites
```

Despues de copiar, reinicia Claude Code para que detecte las nuevas skills.

### Instalar hooks

```bash
cp -R claude-code-skills/hooks/*.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/*.sh
```

Luego registra los hooks en tu `~/.claude/settings.json`. Hay un ejemplo completo en `hooks/hooks-config.example.json` — copia la seccion `"hooks"` a tu settings. Si ya tienes hooks definidos, mergea las entradas manualmente.

### Setup especial: ask-dojo

`ask-dojo` requiere descargar un modelo de IA local y un dataset de teoremas (~1.3 GB en total). Despues de copiar el skill:

```bash
cd ~/.claude/skills/ask-dojo
python3 scripts/setup.py
```

Esto descarga el dataset LeanDojo (~150 MB) y el modelo `tacgen-byt5-small` (~1.1 GB) desde HuggingFace. Requiere las dependencias `transformers`, `datasets` y `torch`.

## Catalogo de Skills

### Lean 4 (Verificacion Formal)

| Skill | Comando | Descripcion |
|-------|---------|-------------|
| **lean4-theorem-proving** | *(automatico)* | Toolkit completo para Lean 4: 11 comandos interactivos, 19 scripts de automatizacion, 20 guias de referencia, repair loop, compiler-guided fixing, LSP integration |
| **lean4-subagents** | *(via Task tool)* | 5 agentes batch: proof-repair, sorry-filler (fast + deep), axiom-eliminator, proof-golfer |
| **ask-dojo** | `/ask-dojo` | Busca en 87,766 teoremas de Mathlib y sugiere tacticas usando modelo IA local (LeanDojo) |
| **ask-lean** | `/ask-lean` | Consulta a DeepSeek como experto en Lean 4. Multi-ronda con contexto y archivos de referencia. Modo subagente |
| **load-lessons** | `/load-lessons` | Carga selectiva de lecciones aprendidas por dominio, categoria o busqueda por problema |

### Planificacion y QA

| Skill | Comando | Descripcion |
|-------|---------|-------------|
| **plan-project** | `/plan-project` | Orquestador de planificacion: subagentes paralelos para bibliografia, lecciones, expertos, DAG topologico, QA y benchmarks. Optimizado para Opus 4.6 |
| **benchmark-qa** | `/benchmark-qa` | Genera criterios de benchmark estrictos via Gemini 2.5 Pro actuando como Senior Performance Engineer |
| **collab-qa** | `/collab-qa` | QA colaborativo multi-ronda: Claude (dev) + Gemini 2.5 Pro (QA Senior). Modo subagente disponible |
| **insights** | `/insights` | Investigacion pre-planificacion con 6 agentes paralelos: analisis, lecciones, bibliografia, estrategias, busqueda online, indexacion |

### Documentacion y Utilidades

| Skill | Comando | Descripcion |
|-------|---------|-------------|
| **study-biblio** | `/study-biblio` | Indexa PDFs usando Gemini Flash. Genera resumenes, indices por carpeta, indice global y grafo conceptual. Incremental |
| **test-project** | `/test-project` | Testing end-to-end de proyecto Lean 4: genera specs (Gemini), escribe tests (subagente), ejecuta y produce reporte de 3 capas |
| **autopsy** | `/autopsy` | Post-mortem de proyecto Lean 4: cruza README claims x DAG x cobertura de codigo. Sugiere propiedades SlimCheck |
| **tidy-project** | `/tidy-project` | Reformatea ARCHITECTURE.md y BENCHMARKS.md al formato estandar. Extrae lecciones y genera dag.json |
| **telegram** | `/telegram` | Modo away: activa/desactiva notificaciones Telegram para trabajo autonomo sin supervision |

## Hooks

Los hooks son shell scripts que Claude Code ejecuta automaticamente en respuesta a eventos (antes/despues de usar una herramienta, al detenerse, al pedir permisos). Se copian a `~/.claude/hooks/` y se registran en `~/.claude/settings.json`.

### PreToolUse (se ejecutan ANTES de que Claude use una herramienta)

| Hook | Trigger | Que hace |
|------|---------|----------|
| **warn-large-read.sh** | `Read` | Advierte si se intenta leer un archivo source >200 lineas sin offset. Sugiere usar scout.py primero |
| **suggest-scout-on-grep.sh** | `Grep` | Sugiere usar scout.py para busquedas estructurales en directorios source |
| **edit-guards.sh** | `Edit` | Verifica branch correcto, fan-out de archivos Lean, dirty tree, y que no se edite sin close_block |

### PostToolUse (se ejecutan DESPUES de que Claude usa una herramienta)

| Hook | Trigger | Que hace |
|------|---------|----------|
| **track-compilation.sh** | `Bash` | Rastrea fallos de compilacion Lean. Si falla >=3 veces, sugiere usar ask-dojo y ask-lean |
| **compile-after-edits.sh** | `Edit` | Dispara compilacion automatica despues de editar archivos .lean |

### Eventos globales

| Hook | Trigger | Que hace |
|------|---------|----------|
| **telegram-away.sh** | `Stop`, `PermissionRequest` | Si el modo away esta activo, notifica via Telegram cuando Claude se detiene o necesita permisos |
| **telegram-notify.sh** | *(invocado por otros hooks)* | Envia notificaciones a Telegram. Lee bot_token de `~/.config/claude-telegram/config.json` |
| **telegram-permission.sh** | *(invocado por telegram-away)* | Reenvia solicitudes de permisos a Telegram para aprobacion remota |

### Workflow de proyecto

| Hook | Uso | Que hace |
|------|-----|----------|
| **branch-per-block.sh** | Manual / CI | Crea una branch git por cada bloque de trabajo del DAG |
| **checkpoint-critical-edit.sh** | Manual | Hace commit checkpoint antes de ediciones criticas en archivos fundamentales |
| **guard-block-close.sh** | Manual | Verifica que se cumplan las precondiciones antes de cerrar un bloque (QA, benchmarks, lessons) |

### Configuracion

Los hooks se registran en `~/.claude/settings.json` bajo la clave `"hooks"`. Hay un ejemplo completo en [`hooks/hooks-config.example.json`](hooks/hooks-config.example.json).

Los hooks de Telegram requieren configuracion adicional en `~/.config/claude-telegram/config.json`:

```json
{
  "bot_token": "tu-bot-token-de-telegram",
  "chat_id": "tu-chat-id"
}
```

Para obtener estos valores: crea un bot con [@BotFather](https://t.me/BotFather) y obtiene tu chat_id enviando un mensaje al bot y consultando `https://api.telegram.org/bot<TOKEN>/getUpdates`.

## Variables de Entorno

Los scripts **nunca almacenan credenciales en codigo**. Leen API keys del entorno del sistema o de un archivo `~/.env`.

| Variable | Obligatoria | Donde obtenerla | Skills que la usan |
|----------|-------------|-----------------|---------------------|
| `GOOGLE_API_KEY` | Si, para skills con Gemini | [Google AI Studio](https://aistudio.google.com/apikey) | benchmark-qa, collab-qa, study-biblio, plan-project, insights |
| `DEEPSEEK_API_KEY` | Si, para ask-lean | [DeepSeek Platform](https://platform.deepseek.com/) | ask-lean |
| `OPENROUTER_API_KEY` | Opcional (fallback) | [OpenRouter](https://openrouter.ai/) | ask-lean (si DeepSeek no responde) |
| `CLAUDE_SESSION_ID` | Automatica | Claude Code la setea internamente | plan-project (tracking interno) |

Para configurar las variables, puedes:

```bash
# Opcion A: exportar en tu shell profile (~/.zshrc o ~/.bashrc)
export GOOGLE_API_KEY="tu-clave-aqui"
export DEEPSEEK_API_KEY="tu-clave-aqui"

# Opcion B: crear archivo ~/.env (una variable por linea)
GOOGLE_API_KEY=tu-clave-aqui
DEEPSEEK_API_KEY=tu-clave-aqui
```

## Dependencias

### Python

Requiere **Python >= 3.10**. Las dependencias varian segun la skill:

| Package | Skills que lo usan | Instalacion |
|---------|--------------------|-------------|
| `google-genai` | benchmark-qa, collab-qa, study-biblio, plan-project, insights | `pip install google-genai` |
| `openai` | ask-lean | `pip install openai` |
| `PyMuPDF` | study-biblio | `pip install PyMuPDF` |
| `datasets` | ask-dojo (setup) | `pip install datasets` |
| `transformers` | ask-dojo (inferencia) | `pip install transformers` |
| `torch` | ask-dojo (inferencia) | `pip install torch` |

Instalacion rapida de todo:

```bash
pip install google-genai openai PyMuPDF datasets transformers torch
```

### Herramientas externas

| Herramienta | Skills | Nota |
|-------------|--------|------|
| [Lean 4](https://leanprover.github.io/) + lake | lean4-theorem-proving, lean4-subagents, ask-dojo, autopsy | Necesario para compilar y verificar proofs |
| [lean-lsp MCP server](https://github.com/leanprover/lean4-mcp) | lean4-theorem-proving | Opcional. Feedback 30x mas rapido |
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | Todas | Estas skills son extensiones de Claude Code |

## Grafo de Dependencias

```
plan-project (orquestador central)
    |---> collab-qa -------> (GOOGLE_API_KEY)
    |---> benchmark-qa ----> (GOOGLE_API_KEY)
    |---> ask-dojo --------> (datos locales)
    |---> ask-lean --------> (DEEPSEEK_API_KEY)
    +---> study-biblio ----> (GOOGLE_API_KEY)

insights (pre-planificacion)
    |---> study-biblio
    +---> WebSearch/WebFetch

lean4-subagents -----------> lean4-theorem-proving (obligatorio)

test-project
    |---> plan-project/scripts/generate_tests.py (Gemini)
    +---> plan-project/scripts/run_tests.py

tidy-project                 (independiente)
autopsy                      (independiente)
load-lessons                 (independiente)
telegram                     (independiente)
```

`plan-project` es el orquestador central. La mayoria de skills son independientes y se pueden usar por separado.

## Como Funcionan las Skills

Cada skill es un directorio con un archivo `SKILL.md` en la raiz. Claude Code lo detecta automaticamente al iniciar.

El `SKILL.md` contiene:
- **Frontmatter YAML**: nombre, descripcion, herramientas permitidas, hint de argumentos
- **Instrucciones**: workflow que Claude sigue al activarse la skill
- **Ejemplos**: casos de uso

```yaml
---
name: mi-skill
description: Que hace esta skill
allowed-tools: Bash(python3 *)
argument-hint: "--flag valor"
---

# Instrucciones para Claude
...
```

Los subdirectorios opcionales incluyen:
- `scripts/` — scripts Python/Bash que Claude ejecuta
- `commands/` — sub-comandos interactivos (markdown)
- `agents/` — definiciones de agentes batch (markdown)
- `references/` — documentacion de referencia que Claude consulta
- `config/` — archivos de configuracion (YAML, JSON)
- `hooks/` — hooks de Claude Code asociados a la skill

## Adaptaciones Necesarias

Algunas skills referencian paths especificos del autor que debes adaptar:

| Path original | Que es | Skills afectadas |
|---------------|--------|------------------|
| `~/Documents/claudio/lecciones/` | Repositorio de lecciones aprendidas | load-lessons, tidy-project, plan-project |
| `~/Documents/claudio/biblioteca/` | Biblioteca de PDFs | study-biblio, insights |

Para adaptar, busca estas rutas en los SKILL.md y scripts correspondientes y reemplazalas por tus propias rutas.

## Estructura del Repositorio

```
claude-code-skills/
├── README.md
├── LICENSE
├── .gitignore
├── hooks/
│   ├── hooks-config.example.json  # Ejemplo de configuracion para settings.json
│   ├── warn-large-read.sh
│   ├── suggest-scout-on-grep.sh
│   ├── edit-guards.sh
│   ├── track-compilation.sh
│   ├── compile-after-edits.sh
│   ├── telegram-away.sh
│   ├── telegram-notify.sh
│   ├── telegram-permission.sh
│   ├── branch-per-block.sh
│   ├── checkpoint-critical-edit.sh
│   └── guard-block-close.sh
├── ask-dojo/
│   ├── SKILL.md
│   └── scripts/
│       ├── lean_search.py
│       └── setup.py            # Ejecutar para descargar modelo y datos
├── ask-lean/
│   ├── SKILL.md
│   └── scripts/
│       └── ask_lean.py
├── autopsy/
│   ├── SKILL.md
│   └── scripts/
│       └── autopsy.py
├── benchmark-qa/
│   ├── SKILL.md
│   └── scripts/
│       └── benchmark.py
├── collab-qa/
│   ├── SKILL.md
│   └── scripts/
│       └── collab.py
├── insights/
│   ├── SKILL.md
│   └── scripts/
│       ├── classify_paper.py
│       ├── download_papers.py
│       └── slugify_topic.py
├── lean4-subagents/
│   ├── README.md
│   └── agents/                 # 5 agent specs (.md)
├── lean4-theorem-proving/
│   ├── SKILL.md
│   ├── README.md
│   ├── COMMANDS.md
│   ├── commands/               # 11 interactive commands
│   ├── config/
│   ├── hooks/
│   ├── scripts/                # 19 automation scripts
│   ├── skills/.../references/  # 20 reference guides
│   └── tests/
├── load-lessons/
│   ├── SKILL.md
│   └── scripts/
│       └── load_lessons.py
├── plan-project/
│   ├── SKILL.md
│   └── scripts/                # 11 orchestrator scripts
├── study-biblio/
│   ├── SKILL.md
│   └── scripts/                # 7 indexer scripts
├── telegram/
│   └── SKILL.md
├── test-project/
│   ├── SKILL.md
│   └── scripts/
│       └── test_project.py
└── tidy-project/
    ├── SKILL.md
    └── scripts/
        └── tidy_project.py
```

## Licencia

MIT License. Ver [LICENSE](LICENSE).
