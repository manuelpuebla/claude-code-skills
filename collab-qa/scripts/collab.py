#!/usr/bin/env python3
"""
Collaborative QA Script - Claude + Gemini Multi-Round Debate

Uses google-genai SDK (new unified SDK) with gemini-2.5-pro for
mathematics and code-focused QA collaboration.

Roles:
- Claude: Lead Developer / Architect
- Gemini: Senior QA Software Engineer

The goal is collaborative refinement through constructive debate,
where each party can propose improvements or consolidate the other's proposals.
"""

import os
import sys
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from enum import Enum

# New Google GenAI SDK
from google import genai

# Configuration
DEFAULT_MODEL = "gemini-2.5-pro"  # Best for math/code reasoning
DEFAULT_ROUNDS = 2
MAX_ROUNDS = 5


class Role(Enum):
    CLAUDE = "claude"
    GEMINI = "gemini"


@dataclass
class DebateRound:
    """Represents one round of the debate."""
    round_num: int
    claude_input: str
    gemini_response: str
    proposals: list[str]


GEMINI_SYSTEM_PROMPT = """You are a Senior QA Software Engineer with 15+ years of experience in:
- Formal verification and theorem proving (Lean 4, Coq, Agda)
- Mathematical correctness and proof strategies
- Code quality, testing strategies, and edge cases
- Performance optimization and algorithmic complexity

Your role in this collaboration:
1. REVIEW the proposal/code from the Lead Developer (Claude)
2. IDENTIFY potential issues, risks, edge cases, or mathematical gaps
3. PROPOSE IMPROVEMENTS when you have superior alternatives
4. CONSOLIDATE good ideas from the other party
5. Be constructive - the goal is the best possible solution

Response format:
## Assessment
[Brief assessment of the current state]

## Issues Found
[Numbered list of concerns, if any]

## Proposed Improvements
[Your superior proposals, if any - be specific and actionable]

## Consolidated Points
[Good ideas from the other party that should be kept]

## Recommendation
[APPROVE / NEEDS_REVISION / PROPOSE_ALTERNATIVE]
[Brief justification]
"""


def create_client() -> genai.Client:
    """Create Google GenAI client with API key."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        # Try loading from known .env locations
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


def query_gemini(
    client: genai.Client,
    prompt: str,
    context: str = "",
    model: str = DEFAULT_MODEL,
) -> str:
    """Query Gemini with the QA Senior role."""

    full_prompt = f"""{GEMINI_SYSTEM_PROMPT}

## Context
{context}

## Current Proposal to Review
{prompt}

Provide your QA assessment following the format above."""

    try:
        response = client.models.generate_content(
            model=model,
            contents=full_prompt,
            config={
                "temperature": 0.4,  # Lower for more focused reasoning
                "max_output_tokens": 4096,
            }
        )
        # Handle None response (safety filters, empty response, etc.)
        if response is None:
            return "ERROR: Gemini returned no response (possibly blocked by safety filters)"
        if response.text is None:
            # Check if blocked by safety
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'finish_reason'):
                    return f"ERROR: Gemini response blocked. Reason: {candidate.finish_reason}"
            return "ERROR: Gemini returned empty response (possibly blocked by safety filters)"
        return response.text
    except Exception as e:
        return f"ERROR querying Gemini: {type(e).__name__}: {e}"


def run_collaboration(
    initial_input: str,
    rounds: int = DEFAULT_ROUNDS,
    context: str = "",
    model: str = DEFAULT_MODEL,
) -> list[DebateRound]:
    """Run multi-round collaboration between Claude and Gemini.

    Args:
        initial_input: Claude's initial proposal/code/question
        rounds: Number of debate rounds
        context: Additional context (project info, constraints, etc.)
        model: Gemini model to use

    Returns:
        List of DebateRound objects with the full conversation
    """
    client = create_client()
    debate_history: list[DebateRound] = []
    current_proposal = initial_input

    rounds = min(rounds, MAX_ROUNDS)

    for i in range(1, rounds + 1):
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"ROUND {i}/{rounds} - Gemini QA Review", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

        # Build context with history
        history_context = context
        if debate_history:
            history_context += "\n\n## Previous Rounds\n"
            for prev in debate_history:
                history_context += f"\n### Round {prev.round_num}\n"
                history_context += f"Gemini's feedback:\n{prev.gemini_response[:500]}...\n"

        # Query Gemini
        gemini_response = query_gemini(
            client=client,
            prompt=current_proposal,
            context=history_context,
            model=model,
        )

        # Extract proposals from response
        proposals = []
        if gemini_response and "## Proposed Improvements" in gemini_response:
            prop_section = gemini_response.split("## Proposed Improvements")[1]
            if "##" in prop_section:
                prop_section = prop_section.split("##")[0]
            proposals = [p.strip() for p in prop_section.strip().split("\n") if p.strip()]

        # Ensure gemini_response is never None
        if gemini_response is None:
            gemini_response = "ERROR: No response received from Gemini API"

        round_data = DebateRound(
            round_num=i,
            claude_input=current_proposal,
            gemini_response=gemini_response,
            proposals=proposals,
        )
        debate_history.append(round_data)

        # Print Gemini's response
        print(gemini_response)

        # For next round, the "proposal" would come from Claude's synthesis
        # In skill mode, Claude will see this output and can respond
        current_proposal = f"[Awaiting Claude's synthesis of Round {i}]"

    return debate_history


def format_output(rounds: list[DebateRound], compact: bool = False) -> str:
    """Format the debate output for Claude to process.

    Args:
        rounds: List of debate rounds
        compact: If True, return only synthesis (for subagent mode)

    Opus 4.6 note: With 1M context window, full mode is now the default.
    Compact mode is still available for explicit --subagent calls.
    """
    if compact:
        return format_synthesis(rounds)

    output = []

    for r in rounds:
        output.append(f"\n## Gemini QA - Round {r.round_num}\n")
        output.append(r.gemini_response)

        if r.proposals:
            output.append(f"\n### Key Proposals from Round {r.round_num}:")
            for p in r.proposals[:5]:
                output.append(f"- {p}")

    # In full mode, add a consolidated summary at the end
    if len(rounds) > 1:
        output.append("\n## Consolidated Summary (All Rounds)")
        synthesis = format_synthesis(rounds)
        output.append(synthesis)

    return "\n".join(output)


def format_synthesis(rounds: list[DebateRound]) -> str:
    """Generate a compact synthesis of all rounds for subagent mode.

    Returns only the essential information to minimize context usage.
    """
    if not rounds:
        return "ERROR: No debate rounds completed"

    last_round = rounds[-1]

    # Extract recommendation from last round
    recommendation = "UNKNOWN"
    if "APPROVE" in last_round.gemini_response:
        recommendation = "APPROVE"
    elif "NEEDS_REVISION" in last_round.gemini_response:
        recommendation = "NEEDS_REVISION"
    elif "PROPOSE_ALTERNATIVE" in last_round.gemini_response:
        recommendation = "PROPOSE_ALTERNATIVE"

    # Collect all unique proposals
    all_proposals = []
    all_issues = []

    for r in rounds:
        # Extract issues
        if "## Issues Found" in r.gemini_response:
            issues_section = r.gemini_response.split("## Issues Found")[1]
            if "##" in issues_section:
                issues_section = issues_section.split("##")[0]
            for line in issues_section.strip().split("\n"):
                line = line.strip()
                if line and line not in all_issues and len(line) > 3:
                    all_issues.append(line)

        # Add proposals
        for p in r.proposals:
            if p not in all_proposals:
                all_proposals.append(p)

    # Build compact synthesis
    synthesis = []
    synthesis.append("# QA Synthesis (Gemini)")
    synthesis.append(f"\n**Rounds completed**: {len(rounds)}")
    synthesis.append(f"**Recommendation**: {recommendation}")

    if all_issues:
        synthesis.append("\n## Issues Identified")
        for issue in all_issues[:10]:  # Limit to top 10
            synthesis.append(f"- {issue}")

    if all_proposals:
        synthesis.append("\n## Key Proposals")
        for prop in all_proposals[:10]:  # Limit to top 10
            synthesis.append(f"- {prop}")

    # Extract consolidated points from last round
    if "## Consolidated Points" in last_round.gemini_response:
        consolidated = last_round.gemini_response.split("## Consolidated Points")[1]
        if "##" in consolidated:
            consolidated = consolidated.split("##")[0]
        synthesis.append("\n## Consolidated Points")
        synthesis.append(consolidated.strip()[:500])  # Limit length

    return "\n".join(synthesis)


def read_file_if_exists(path: str) -> Optional[str]:
    """Read a file if it exists, return None otherwise."""
    try:
        p = Path(path)
        if p.exists():
            return p.read_text()
        # Try relative to current dir
        if not p.is_absolute():
            for base in [Path.cwd(), Path.home() / "Documents" / "claudio"]:
                full = base / path
                if full.exists():
                    return full.read_text()
        return None
    except Exception as e:
        print(f"Warning: Could not read {path}: {e}", file=sys.stderr)
        return None


def main():
    """Main entry point for the skill."""
    import argparse

    parser = argparse.ArgumentParser(description="Claude-Gemini QA Collaboration")
    parser.add_argument("--rounds", "-r", type=int, default=DEFAULT_ROUNDS,
                        help=f"Number of debate rounds (max {MAX_ROUNDS})")
    parser.add_argument("--model", "-m", type=str, default=DEFAULT_MODEL,
                        help="Gemini model to use")
    parser.add_argument("--context", "-c", type=str, default="",
                        help="Additional context description")
    parser.add_argument("--reference", "-ref", type=str, default="",
                        help="Reference file (.md) to include as context")
    parser.add_argument("--subagent", "-s", action="store_true",
                        help="Subagent mode: return compact synthesis only (alias for --detail compact)")
    parser.add_argument("--detail", "-d", type=str, default="auto",
                        choices=["full", "compact", "auto"],
                        help="Detail level: full (all rounds verbatim), compact (~500 tok), auto (full if context available)")
    parser.add_argument("input", nargs="?", type=str, default="",
                        help="Initial input (or read from stdin)")

    args = parser.parse_args()

    # Get main input (Claude's last response)
    if args.input:
        initial_input = args.input
    elif not sys.stdin.isatty():
        initial_input = sys.stdin.read()
    else:
        print("ERROR: No input provided. Pass as argument or pipe to stdin.",
              file=sys.stderr)
        sys.exit(1)

    # Build full context
    full_context = args.context

    # Add reference file if provided
    if args.reference:
        ref_content = read_file_if_exists(args.reference)
        if ref_content:
            full_context += f"\n\n## Reference Document: {args.reference}\n{ref_content}"
            print(f"Loaded reference: {args.reference} ({len(ref_content)} chars)", file=sys.stderr)
        else:
            print(f"Warning: Reference file not found: {args.reference}", file=sys.stderr)

    # Run collaboration
    rounds = run_collaboration(
        initial_input=initial_input,
        rounds=args.rounds,
        context=full_context,
        model=args.model,
    )

    # Resolve detail level: --subagent forces compact, auto defaults to full
    detail = args.detail
    if args.subagent:
        detail = "compact"
    elif detail == "auto":
        detail = "full"  # Opus 4.6: 1M context allows full output by default

    # Output formatted result
    print(format_output(rounds, compact=(detail == "compact")))


if __name__ == "__main__":
    main()
