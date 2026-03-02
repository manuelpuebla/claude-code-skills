# Load Lessons: Carga Selectiva de Lecciones Aprendidas

Carga lecciones relevantes desde `~/Documents/claudio/lecciones/` basándose en el problema actual.

## Help Request Detection

Si el usuario invoca con `?`, `--help`, `help`, mostrar esta referencia:

```
/load-lessons - Carga selectiva de lecciones aprendidas

USAGE:
  /load-lessons <dominio> [opciones]

DOMINIOS DISPONIBLES:
  lean4          Verificación formal en Lean 4 (51 lecciones)

OPCIONES:
  --category, -c CAT     Cargar archivo de categoría específica
  --problem, -p "text"   Buscar lección por descripción del problema
  --list, -l             Listar categorías disponibles
  --critical             Mostrar solo lecciones críticas (memorizar)

CATEGORÍAS LEAN4:
  tacticas        simp, omega, rfl, congr, split_ifs
  campos-finitos  ZMod, GoldilocksField, homomorfismos
  induccion       terminación, WF-recursion, partial
  arquitectura    bridge lemmas, axiomatización, Memory
  anti-patrones   errores comunes, tipos inadecuados
  qa-workflow     integración QA, consulta expertos

EXAMPLES:
  /load-lessons lean4                          # Muestra índice
  /load-lessons lean4 --list                   # Lista categorías
  /load-lessons lean4 -c campos-finitos        # Carga campos-finitos.md
  /load-lessons lean4 -p "ZMod timeout"        # Busca en índice
  /load-lessons lean4 --critical               # Lecciones críticas

WORKFLOW TÍPICO:
  1. Encuentro problema → /load-lessons lean4 -p "mi problema"
  2. Índice indica categoría → Cargo solo esa categoría
  3. Leo lección específica → Aplico solución
```

## How to Use

Cuando el usuario invoca esta skill:

1. **Identificar dominio** (lean4, rust, python, etc.)
2. **Si no hay opciones**: Mostrar INDEX.md del dominio
3. **Si --category**: Cargar archivo de categoría completo
4. **Si --problem**: Buscar en INDEX.md y cargar sección relevante
5. **Si --critical**: Mostrar lecciones críticas inline

## Execution

```bash
# Mostrar índice
python3 $SKILL_DIR/scripts/load_lessons.py lean4

# Cargar categoría
python3 $SKILL_DIR/scripts/load_lessons.py lean4 --category campos-finitos

# Buscar por problema
python3 $SKILL_DIR/scripts/load_lessons.py lean4 --problem "ZMod timeout"

# Lecciones críticas
python3 $SKILL_DIR/scripts/load_lessons.py lean4 --critical
```

## Dominios Soportados

| Dominio | Lecciones | Archivos | Fuente |
|---------|-----------|----------|--------|
| `lean4` | 51 | 7 | AMO-Lean (18 sesiones) |

## Estructura de Archivos

```
~/Documents/claudio/lecciones/
└── lean4/
    ├── INDEX.md           # Índice por problema (~500 tokens)
    ├── tacticas.md        # §1,6,14,32-34,36,47-48
    ├── campos-finitos.md  # §8-9,15,18,20,39-44
    ├── induccion.md       # §2-3,21-22,30,46,49
    ├── arquitectura.md    # §4-5,10-13,17,27-29,31,37
    ├── anti-patrones.md   # §7,24,35,38,45,50-51
    └── qa-workflow.md     # §16,19,23,25-26
```

## Lecciones Críticas (Memorizar)

Estas lecciones se muestran con `--critical` y deben estar siempre presentes:

### Lean 4
```
L-015: ZMod.val_injective - NUNCA trabajar directo con ZMod grande
L-023: omega necesita bounds explícitos - construir cadena manual
L-049: termination_by + decreasing_by para eliminar partial
L-035: Intentar probar axioma es la mejor auditoría
L-078: Statement más fuerte = IH más fuerte
```

## Principio de Diseño

**NO cargar todo**: El objetivo es minimizar tokens de contexto.

```
ANTES (ineficiente):
- Cargar 2739 líneas = ~18K tokens = 9% del contexto

AHORA (eficiente):
- INDEX.md = ~500 tokens
- Una categoría = ~3-5K tokens
- Total = ~2-3% del contexto
```

## Integración con Otras Skills

```
/lean-search → Encontrar teoremas en Mathlib
/load-lessons lean4 -p "el problema" → Lección de cómo resolverlo
/ask-lean → Pedir ayuda experta
/collab-qa → Validar estrategia
```

## Cuándo Usar Automáticamente

Claude DEBE consultar lecciones cuando:
1. Trabaja en archivos `.lean`
2. Encuentra error de tipo conocido (ZMod, omega, simp)
3. Planifica eliminación de sorries/axiomas
4. El QA sugiere un patrón que podría estar documentado

## Agregar Nuevas Lecciones

Al completar una fase de un proyecto:
1. Documentar lecciones en `lecciones_fase{n}.md` del proyecto
2. Extraer lecciones reutilizables a `~/Documents/claudio/lecciones/{dominio}/`
3. Actualizar INDEX.md con nueva entrada
4. Categorizar en archivo apropiado
