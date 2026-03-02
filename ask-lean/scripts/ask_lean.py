#!/usr/bin/env python3
"""
Ask Lean Expert - Consulta a DeepSeek como experto en Lean 4

DeepSeek tiene modelos entrenados con conocimiento profundo de Lean 4,
incluyendo Mathlib y tácticas avanzadas.

Soporta dos proveedores:
1. DeepSeek directo (DEEPSEEK_API_KEY)
2. OpenRouter como fallback (OPENROUTER_API_KEY)

Sintaxis compatible con /collab-qa:
- --rounds N
- --context "text"
- --reference file.md
"""

import os
import sys
from pathlib import Path
from typing import Optional, Tuple

# DeepSeek/OpenRouter API is OpenAI-compatible
from openai import OpenAI

# Configuration
DEFAULT_ROUNDS = 2
MAX_ROUNDS = 5

# Provider configurations
PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "env_key": "DEEPSEEK_API_KEY",
        "models": {
            "chat": "deepseek-chat",
            "reasoner": "deepseek-reasoner",
        },
        "name": "DeepSeek Direct",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
        "models": {
            "chat": "deepseek/deepseek-chat",
            "reasoner": "deepseek/deepseek-reasoner",
        },
        "name": "OpenRouter",
    },
}


LEAN_EXPERT_SYSTEM_PROMPT = """You are a Senior Lean 4 Expert with deep knowledge of:
- Lean 4 syntax, tactics, and type system
- Mathlib library (structures, theorems, tactics)
- Formal verification and theorem proving strategies
- Mathematical proofs in constructive logic
- Performance optimization in Lean 4

Your role:
1. ANALYZE the code, proof, or question from the user
2. IDENTIFY issues, gaps, or potential improvements
3. SUGGEST specific tactics, lemmas, or approaches
4. PROVIDE working Lean 4 code when possible
5. EXPLAIN the reasoning behind your suggestions

Response format:
## Analysis
[Assessment of the current state/question]

## Issues or Gaps
[Problems identified, if any]

## Suggested Solution
[Specific recommendations with Lean 4 code]

## Relevant Mathlib
[Useful lemmas, theorems, or structures from Mathlib]

## Alternative Approaches
[Other ways to solve this, if applicable]

Be precise and provide working code. Reference specific Mathlib modules when relevant.
Respond in the same language as the user's input.
"""


def load_api_key(env_key: str) -> Optional[str]:
    """Load API key from environment or .env files."""
    api_key = os.getenv(env_key)
    if api_key:
        return api_key

    # Try loading from known .env locations
    env_paths = [
        Path.home() / ".env",
        Path.home() / "lean4-agent-orchestra" / ".env",
        Path.home() / "Documents" / "claudio" / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith(f"{env_key}="):
                    return line.split("=", 1)[1].strip()
    return None


def create_client(provider: str = "deepseek") -> Tuple[OpenAI, str, str]:
    """Create API client for the specified provider.

    Returns: (client, model_chat, model_reasoner)
    """
    config = PROVIDERS[provider]
    api_key = load_api_key(config["env_key"])

    if not api_key:
        raise ValueError(f"{config['env_key']} not found")

    client = OpenAI(api_key=api_key, base_url=config["base_url"])
    return client, config["models"]["chat"], config["models"]["reasoner"]


def get_working_client(preferred_model: str = "chat") -> Tuple[OpenAI, str, str]:
    """Get a working client. Uses OpenRouter directly."""

    try:
        client, model_chat, model_reasoner = create_client("openrouter")
        model = model_reasoner if preferred_model == "reasoner" else model_chat
        print(f"Using: OpenRouter ({model})", file=sys.stderr)
        return client, model, "openrouter"
    except ValueError:
        pass

    # No provider available
    print("ERROR: OPENROUTER_API_KEY not found", file=sys.stderr)
    print("\nConfigure: OPENROUTER_API_KEY - https://openrouter.ai/", file=sys.stderr)
    print("Add to ~/.env or ~/Documents/claudio/.env", file=sys.stderr)
    sys.exit(1)


def read_file_if_exists(path: str) -> Optional[str]:
    """Read a file if it exists."""
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


def query_expert(
    client: OpenAI,
    model: str,
    provider: str,
    user_input: str,
    context: str = "",
    conversation_history: list = None,
) -> str:
    """Query the Lean expert."""

    messages = [
        {"role": "system", "content": LEAN_EXPERT_SYSTEM_PROMPT}
    ]

    # Add conversation history for multi-round
    if conversation_history:
        messages.extend(conversation_history)

    # Build user message with context
    user_message = ""
    if context:
        user_message += f"## Context\n{context}\n\n"
    user_message += f"## Question/Code to Review\n{user_input}"

    messages.append({"role": "user", "content": user_message})

    try:
        # OpenRouter requires extra headers
        extra_kwargs = {}
        if provider == "openrouter":
            extra_kwargs["extra_headers"] = {
                "HTTP-Referer": "https://github.com/claude-code",
                "X-Title": "Claude Code Lean Expert",
            }

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.4,
            max_tokens=4096,
            **extra_kwargs,
        )
        return response.choices[0].message.content
    except Exception as e:
        error_msg = str(e)

        return f"ERROR querying {provider}: {type(e).__name__}: {e}"


def run_consultation(
    initial_input: str,
    rounds: int = DEFAULT_ROUNDS,
    context: str = "",
    model_type: str = "chat",
) -> list:
    """Run multi-round consultation."""
    client, model, provider = get_working_client(model_type)
    conversation_history = []
    responses = []

    rounds = min(rounds, MAX_ROUNDS)
    current_input = initial_input

    for i in range(1, rounds + 1):
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"ROUND {i}/{rounds} - Lean Expert ({PROVIDERS[provider]['name']})", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

        response = query_expert(
            client=client,
            model=model,
            provider=provider,
            user_input=current_input,
            context=context if i == 1 else "",  # Context only on first round
            conversation_history=conversation_history,
        )

        # Add to history for next round
        conversation_history.append({"role": "user", "content": current_input})
        conversation_history.append({"role": "assistant", "content": response})

        responses.append({
            "round": i,
            "input": current_input,
            "response": response,
            "provider": provider,
        })

        print(response)

        # For next round, Claude would provide refined input
        if i < rounds:
            current_input = "[Awaiting Claude's follow-up question or refinement]"

    return responses


def format_output(responses: list, compact: bool = False) -> str:
    """Format consultation output.

    Args:
        responses: List of response dictionaries
        compact: If True, return synthesis only (for subagent mode)

    Opus 4.6 note: With 1M context window, full mode is now the default.
    Compact mode is still available for explicit --subagent calls.
    """
    if compact:
        return format_synthesis(responses)

    output = []

    for r in responses:
        provider_name = PROVIDERS.get(r.get('provider', 'deepseek'), {}).get('name', 'Expert')
        output.append(f"\n## Lean Expert ({provider_name}) - Round {r['round']}\n")
        output.append(r['response'])

    # In full mode with multiple rounds, add consolidated synthesis
    if len(responses) > 1:
        output.append("\n## Consolidated Synthesis (All Rounds)")
        synthesis = format_synthesis(responses)
        output.append(synthesis)

    return "\n".join(output)


def format_synthesis(responses: list) -> str:
    """Generate a compact synthesis of all rounds for subagent mode."""
    if not responses:
        return "ERROR: No consultation rounds completed"

    last_response = responses[-1]['response']
    provider = responses[-1].get('provider', 'deepseek')
    provider_name = PROVIDERS.get(provider, {}).get('name', 'Expert')

    # Extract sections from last response
    analysis = ""
    issues = ""
    solution = ""
    mathlib = ""
    alternatives = ""

    sections = {
        "## Analysis": "analysis",
        "## Issues or Gaps": "issues",
        "## Suggested Solution": "solution",
        "## Relevant Mathlib": "mathlib",
        "## Alternative Approaches": "alternatives",
    }

    current_section = None
    current_content = []

    for line in last_response.split("\n"):
        # Check if this line starts a new section
        for header, var_name in sections.items():
            if line.strip().startswith(header.replace("## ", "")):
                # Save previous section
                if current_section:
                    if current_section == "analysis":
                        analysis = "\n".join(current_content)
                    elif current_section == "issues":
                        issues = "\n".join(current_content)
                    elif current_section == "solution":
                        solution = "\n".join(current_content)
                    elif current_section == "mathlib":
                        mathlib = "\n".join(current_content)
                    elif current_section == "alternatives":
                        alternatives = "\n".join(current_content)
                current_section = var_name
                current_content = []
                break
        else:
            if current_section:
                current_content.append(line)

    # Save last section
    if current_section and current_content:
        if current_section == "analysis":
            analysis = "\n".join(current_content)
        elif current_section == "issues":
            issues = "\n".join(current_content)
        elif current_section == "solution":
            solution = "\n".join(current_content)
        elif current_section == "mathlib":
            mathlib = "\n".join(current_content)
        elif current_section == "alternatives":
            alternatives = "\n".join(current_content)

    # Build compact synthesis
    synthesis = []
    synthesis.append(f"# Lean Expert Synthesis ({provider_name})")
    synthesis.append(f"\n**Rounds completed**: {len(responses)}")

    if analysis.strip():
        synthesis.append("\n## Analysis")
        synthesis.append(analysis.strip()[:300])

    if issues.strip():
        synthesis.append("\n## Issues Identified")
        synthesis.append(issues.strip()[:300])

    if solution.strip():
        synthesis.append("\n## Suggested Solution")
        synthesis.append(solution.strip()[:800])  # Allow more for code

    if mathlib.strip():
        synthesis.append("\n## Relevant Mathlib")
        synthesis.append(mathlib.strip()[:300])

    return "\n".join(synthesis)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Ask Lean Expert - Consult DeepSeek/OpenRouter for Lean 4 help",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic question
  ask_lean.py "How do I prove n + m = m + n in Lean 4?"

  # With rounds
  ask_lean.py --rounds 3 "Review this proof strategy"

  # With context
  ask_lean.py --context "Working on NTT verification" "What tactics for sum manipulation?"

  # With reference file
  ask_lean.py --reference mi_teorema.lean "Help me complete the sorry"

  # Use reasoner model (chain-of-thought)
  ask_lean.py --model reasoner "Complex proof strategy?"

Providers (in order of preference):
  1. DeepSeek Direct (DEEPSEEK_API_KEY)
  2. OpenRouter fallback (OPENROUTER_API_KEY) - $5 free credits
"""
    )

    parser.add_argument("input", nargs="?", default="",
                        help="Question or code to review")
    parser.add_argument("--rounds", "-r", type=int, default=DEFAULT_ROUNDS,
                        help=f"Number of consultation rounds (max {MAX_ROUNDS})")
    parser.add_argument("--context", "-c", type=str, default="",
                        help="Additional context description")
    parser.add_argument("--reference", "-ref", type=str, default="",
                        help="Reference file (.lean, .md) to include")
    parser.add_argument("--model", "-m", type=str, default="chat",
                        choices=["chat", "reasoner"],
                        help="Model type: chat (fast) or reasoner (chain-of-thought)")
    parser.add_argument("--subagent", "-s", action="store_true",
                        help="Subagent mode: return compact synthesis only (alias for --detail compact)")
    parser.add_argument("--detail", "-d", type=str, default="auto",
                        choices=["full", "compact", "auto"],
                        help="Detail level: full (complete responses), compact (~500 tok), auto (full if context available)")

    args = parser.parse_args()

    # Get input
    if args.input:
        initial_input = args.input
    elif not sys.stdin.isatty():
        initial_input = sys.stdin.read()
    else:
        print("ERROR: No input provided. Pass as argument or pipe to stdin.",
              file=sys.stderr)
        sys.exit(1)

    # Build context
    full_context = args.context

    # Add reference file if provided
    if args.reference:
        ref_content = read_file_if_exists(args.reference)
        if ref_content:
            full_context += f"\n\n## Reference: {args.reference}\n```\n{ref_content}\n```"
            print(f"Loaded reference: {args.reference} ({len(ref_content)} chars)", file=sys.stderr)
        else:
            print(f"Warning: Reference file not found: {args.reference}", file=sys.stderr)

    # Run consultation
    responses = run_consultation(
        initial_input=initial_input,
        rounds=args.rounds,
        context=full_context,
        model_type=args.model,
    )

    # Resolve detail level: --subagent forces compact, auto defaults to full
    detail = args.detail
    if args.subagent:
        detail = "compact"
    elif detail == "auto":
        detail = "full"  # Opus 4.6: 1M context allows full output by default

    # Output (compact if subagent mode)
    print(format_output(responses, compact=(detail == "compact")))


if __name__ == "__main__":
    main()
