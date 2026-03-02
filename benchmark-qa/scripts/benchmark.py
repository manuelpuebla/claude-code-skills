#!/usr/bin/env python3
"""
Benchmark QA Script - Request strict benchmark criteria from Gemini

Uses google-genai SDK with gemini-2.5-pro to define rigorous
benchmark criteria based on phase roadmaps.

Role: Senior Performance/Benchmark Engineer
"""

import os
import sys
from pathlib import Path
from typing import Optional

from google import genai

# Configuration
DEFAULT_MODEL = "gemini-2.5-pro"


GEMINI_BENCHMARK_PROMPT = """You are a Senior Performance/Benchmark Engineer with 15+ years of experience in:
- Designing reproducible and statistically valid benchmarks
- Performance profiling and optimization analysis
- Scientific measurement methodology
- Hardware-aware performance testing (CPU, memory, cache, SIMD)
- Cryptographic and mathematical algorithm benchmarking

Your task: Define STRICT benchmark criteria for the given phase roadmap.

## Response Format

### 1. Métricas a Medir
For each component in the roadmap, specify:
- **Metric name**: Clear, measurable metric
- **Unit**: Precise unit of measurement
- **Measurement method**: How to measure it

### 2. Valores Objetivo
| Componente | Métrica | Baseline | Target | Stretch Goal |
|------------|---------|----------|--------|--------------|
| ... | ... | ... | ... | ... |

- **Baseline**: Minimum acceptable (naive implementation)
- **Target**: Expected performance (optimized)
- **Stretch Goal**: Excellent performance (highly optimized)

### 3. Metodología de Medición
- **Warm-up runs**: Number of iterations to discard
- **Measurement runs**: Number of iterations to measure
- **Statistical analysis**: Mean, std dev, percentiles to report
- **Environment control**: What to control (CPU frequency, background processes, etc.)

### 4. Criterios de Aceptación/Rechazo
- **PASS criteria**: What must be achieved to pass
- **FAIL criteria**: What triggers immediate failure
- **WARNING criteria**: What needs investigation

### 5. Herramientas Recomendadas
| Herramienta | Propósito | Configuración |
|-------------|-----------|---------------|
| ... | ... | ... |

### 6. Anti-Patterns a Evitar
List common benchmarking mistakes to avoid for this specific domain.

### 7. Template de Reporte
Provide a template for documenting benchmark results.

BE STRICT. These benchmarks must be:
- Reproducible across runs
- Statistically valid
- Hardware-aware
- Domain-appropriate
"""


def create_client() -> genai.Client:
    """Create Google GenAI client with API key."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        env_paths = [
            Path.home() / ".env",
            Path.home() / "lean4-agent-orchestra" / ".env",
            Path.home() / "Documents" / "claudio" / ".env",
        ]
        for env_path in env_paths:
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if line.startswith("GOOGLE_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break
            if api_key:
                break

    if not api_key:
        print("ERROR: GOOGLE_API_KEY not found", file=sys.stderr)
        print("Set GOOGLE_API_KEY env var or add to ~/.env", file=sys.stderr)
        sys.exit(1)

    return genai.Client(api_key=api_key)


def read_file_if_exists(path: str) -> Optional[str]:
    """Read a file if it exists, return None otherwise."""
    try:
        p = Path(path)
        if p.exists():
            return p.read_text()
        if not p.is_absolute():
            for base in [Path.cwd(), Path.home() / "Documents" / "claudio"]:
                full = base / path
                if full.exists():
                    return full.read_text()
        return None
    except Exception as e:
        print(f"Warning: Could not read {path}: {e}", file=sys.stderr)
        return None


def query_gemini_benchmark(
    client: genai.Client,
    roadmap_content: str,
    emphasis: str = "",
    strict: bool = False,
    model: str = DEFAULT_MODEL,
) -> str:
    """Query Gemini for benchmark criteria."""

    strict_modifier = """
STRICT MODE ENABLED: Apply the most rigorous criteria possible.
- No tolerance for measurement noise
- Require statistical significance (p < 0.01)
- Demand reproducibility across multiple hardware configurations
- Set aggressive targets based on theoretical limits
""" if strict else ""

    emphasis_section = f"""
## Áreas de Énfasis
El usuario quiere especial atención en: {emphasis}
Asegúrate de incluir métricas específicas y criterios estrictos para estas áreas.
""" if emphasis else ""

    full_prompt = f"""{GEMINI_BENCHMARK_PROMPT}

{strict_modifier}

{emphasis_section}

## Phase Roadmap to Analyze

{roadmap_content}

---

Provide comprehensive benchmark criteria following the format above.
Respond in Spanish.
"""

    try:
        response = client.models.generate_content(
            model=model,
            contents=full_prompt,
            config={
                "temperature": 0.3,  # Lower for more precise/consistent output
                "max_output_tokens": 8192,
            }
        )
        return response.text
    except Exception as e:
        return f"ERROR querying Gemini: {type(e).__name__}: {e}"


def main():
    """Main entry point for the skill."""
    import argparse

    parser = argparse.ArgumentParser(description="Benchmark QA - Get strict criteria from Gemini")
    parser.add_argument("--phase", "-p", type=str, required=True,
                        help="Phase roadmap file to analyze")
    parser.add_argument("--emphasis", "-e", type=str, default="",
                        help="Areas to emphasize in benchmarks")
    parser.add_argument("--strict", action="store_true",
                        help="Enable strict mode (more rigorous criteria)")
    parser.add_argument("--model", "-m", type=str, default=DEFAULT_MODEL,
                        help="Gemini model to use")

    args = parser.parse_args()

    # Read roadmap file
    roadmap_content = read_file_if_exists(args.phase)
    if not roadmap_content:
        print(f"ERROR: Could not read roadmap file: {args.phase}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded roadmap: {args.phase} ({len(roadmap_content)} chars)", file=sys.stderr)
    if args.emphasis:
        print(f"Emphasis: {args.emphasis}", file=sys.stderr)
    if args.strict:
        print("STRICT MODE ENABLED", file=sys.stderr)

    # Query Gemini
    print(f"\n{'='*60}", file=sys.stderr)
    print("Consulting Gemini Benchmark Engineer...", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    client = create_client()
    response = query_gemini_benchmark(
        client=client,
        roadmap_content=roadmap_content,
        emphasis=args.emphasis,
        strict=args.strict,
        model=args.model,
    )

    print("\n## Gemini Benchmark QA Response\n")
    print(response)


if __name__ == "__main__":
    main()
