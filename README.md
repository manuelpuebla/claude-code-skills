# claude-code-skills

Coleccion de 13 custom skills para [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (la CLI oficial de Anthropic). Cada skill es un directorio independiente que puedes copiar a tu `~/.claude/skills/` para extender las capacidades de Claude.

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
| **autopsy** | `/autopsy` | Post-mortem de proyecto Lean 4: cruza README claims x DAG x cobertura de codigo. Sugiere propiedades SlimCheck |
| **tidy-project** | `/tidy-project` | Reformatea ARCHITECTURE.md y BENCHMARKS.md al formato estandar. Extrae lecciones y genera dag.json |
| **telegram** | `/telegram` | Modo away: activa/desactiva notificaciones Telegram para trabajo autonomo sin supervision |

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
└── tidy-project/
    ├── SKILL.md
    └── scripts/
        └── tidy_project.py
```

## Licencia

MIT License. Ver [LICENSE](LICENSE).
