---
name: collab-qa
description: Multi-round collaborative QA debate between Claude and Gemini 2.5 Pro. Gemini reviews Claude's last response with optional reference documents. Supports subagent mode for context-efficient integration.
allowed-tools: Bash(python3 *)
argument-hint: "[--rounds N] [--context \"desc\"] [--reference file.md] [--subagent]"
---

# Collaborative QA: Claude + Gemini Debate

This skill sends your last response to Gemini 2.5 Pro (Senior QA Engineer) for review and collaborative refinement.

## Help Request Detection

If the user invokes with `?`, `--help`, `help`, or asks how to use it, show this quick reference instead of running the script:

```
/collab-qa - Collaborative QA with Gemini 2.5 Pro

USAGE:
  /collab-qa [options]

OPTIONS:
  --rounds N, -r N       Number of debate rounds (1-5, default: 2)
  --context "text"       Brief description of context
  --reference file.md    Reference document for QA review
  --subagent, -s         Subagent mode: return compact synthesis only

EXAMPLES:
  /collab-qa                                    # Basic review of last response
  /collab-qa --rounds 3                         # 3 rounds of debate
  /collab-qa --context "NTT optimization"       # With context description
  /collab-qa --reference spec.md                # With reference document
  /collab-qa -r 2 --reference proyecto.md       # Combined options
  /collab-qa --subagent --rounds 3              # For use by subagents

MODES:
  Direct:    Full debate output (default)
  Subagent:  Compact synthesis (~500 tokens vs ~6K tokens)

WORKFLOW:
  1. You give a response (code, proof, plan...)
  2. Invoke /collab-qa
  3. Gemini QA reviews and provides feedback
  4. Claude synthesizes improvements
  5. Repeat for additional rounds
```

## How to Use

When the user invokes this skill, you (Claude) must:

1. **Capture your last substantive response** (code, proof, plan, etc.)
2. **Run the collaboration script** with that content
3. **Present Gemini's feedback** to the user
4. **Synthesize** both perspectives if doing multiple rounds

## Execution

Run this command, replacing `{CLAUDE_LAST_RESPONSE}` with your actual last response:

```bash
python3 $SKILL_DIR/scripts/collab.py --rounds {ROUNDS} --context "{CONTEXT}" --reference "{REFERENCE_FILE}" "{CLAUDE_LAST_RESPONSE}"
```

Or for longer responses, use a heredoc:

```bash
python3 $SKILL_DIR/scripts/collab.py --rounds {ROUNDS} --context "{CONTEXT}" --reference "{REFERENCE_FILE}" "$(cat <<'CLAUDE_INPUT'
{CLAUDE_LAST_RESPONSE}
CLAUDE_INPUT
)"
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--rounds N` | Number of debate rounds | 2 |
| `--context "text"` | Brief description of context | "" |
| `--reference file.md` | Reference document for QA to review | none |

## Examples

### Basic: Review last response
```
User: /collab-qa
→ Sends Claude's last response to Gemini for QA review
```

### With context
```
User: /collab-qa --context "capa 4 de fase 3"
→ Gemini knows the work is about "layer 4 of phase 3"
```

### With reference document
```
User: /collab-qa --rounds 3 --reference proyecto_fresco.md
→ Gemini reviews Claude's response with the reference doc as context
```

### Full example
```
User: /collab-qa --rounds 2 --context "NTT optimization for post-quantum crypto" --reference docs/ntt_spec.md
```

## Workflow

```
┌─────────────────────────────────────────────────────────┐
│ 1. Claude gives a response (code, proof, plan...)       │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│ 2. User: /collab-qa --rounds 2 --reference spec.md      │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│ 3. Claude captures last response + sends to Gemini      │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│ 4. Gemini QA reviews and responds with:                 │
│    - Assessment                                         │
│    - Issues Found                                       │
│    - Proposed Improvements                              │
│    - Consolidated Points                                │
│    - Recommendation (APPROVE/NEEDS_REVISION)            │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│ 5. Claude synthesizes and improves based on feedback    │
│    (repeat for additional rounds)                       │
└─────────────────────────────────────────────────────────┘
```

## Roles

| Agent | Role | Focus |
|-------|------|-------|
| **Claude** | Lead Developer | Architecture, implementation, proofs |
| **Gemini 2.5 Pro** | Senior QA Engineer | Edge cases, rigor, improvements |

## After Gemini Responds

You (Claude) should:
1. **Acknowledge** valid concerns from Gemini
2. **Address** each issue raised
3. **Adopt** superior proposals
4. **Counter** with better alternatives if you have them
5. **Synthesize** into an improved version

## Model Info

- **Model**: `gemini-2.5-pro`
- **Strengths**: Mathematical reasoning (86.7% AIME), code analysis (63.8% SWE-Bench)
- **Temperature**: 0.4 (focused reasoning)

## Subagent Mode

When invoked with `--subagent`, the skill returns a compact synthesis instead of the full debate:

### Benefits
- **Context efficiency**: ~500 tokens vs ~6K tokens for 3 rounds
- **Automatic integration**: Used by `/plan-project` during planning workflow
- **Direct availability**: Users can still invoke directly without `--subagent`

### Synthesis Format
```
# QA Synthesis (Gemini)

**Rounds completed**: 3
**Recommendation**: NEEDS_REVISION

## Issues Identified
- Issue 1
- Issue 2

## Key Proposals
- Proposal 1
- Proposal 2

## Consolidated Points
Points that should be kept...
```

### Usage in Subagents
```bash
python3 $SKILL_DIR/scripts/collab.py --subagent --rounds 3 --context "..." "proposal"
```

The full debate happens internally; only the synthesis is returned to the calling agent.
