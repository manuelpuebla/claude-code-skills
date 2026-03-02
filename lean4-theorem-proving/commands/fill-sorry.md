---
description: Guided workflow for filling a Lean 4 sorry with tactics and lemma search
allowed-tools: Bash(bash:*)
---

# Guided Sorry Filling

Interactive workflow for filling incomplete proofs (sorries) using mathlib search, tactic suggestions, and multi-candidate testing.

**IMPORTANT:** Tactic and search scripts are bundled with this plugin - do not look for them in the current directory. Always use the full path with ${CLAUDE_PLUGIN_ROOT}.

## Workflow

### 1. Locate Sorry

**If sorry not specified:**
```
Which sorry would you like to fill?

Options:
1. Current cursor position (if in .lean file)
2. Show all sorries in current file (use /analyze-sorries)
3. Specify file and line number

Choose: (1/2/3)
```

**If user specifies location:**
```
Reading sorry at [file]:[line]...
```

### 2. Understand Context

**Extract proof context:**

a) **Read surrounding code:**
```lean
-- Context around [file]:[line]

theorem [theorem_name] ([parameters]) : [goal_type] := by
  [previous tactics...]
  sorry  -- ← We're filling this
  [following tactics if any...]
```

b) **Identify goal structure:**
```
Analyzing sorry...

Goal type: [goal_type]
Category: [equality/forall/exists/implication/conjunction/etc]
Complexity: [simple/medium/complex]
```

c) **If MCP available, get live goal state:**
```bash
# Use lean-lsp to get actual goal
mcp__lean-lsp__lean_goal(file, line, column)
```

```
Current goal state:
  ⊢ [actual goal from LSP]

Hypotheses available:
  h1 : [type]
  h2 : [type]
  ...
```

### 3. Suggest Tactics

**Based on goal structure:**

a) **Suggest tactics** (replace with your actual goal text):
```bash
bash .claude/tools/lean4/suggest_tactics.sh --goal "∀ x : ℕ, x + 0 = x"
```

**Fallback if script is not available or fails:**
- Use tactics-reference.md table: match goal pattern to suggested tactic
- Example: `⊢ a = b` → try `rfl`, `simp`, or `ring`

**IMPORTANT:** Replace `"∀ x : ℕ, x + 0 = x"` with your actual goal text. Never use placeholders like `<goal_text>` in executed commands.

b) **Present suggestions:**
```
Suggested tactics for this goal:

Primary approach: [main tactic]
Reason: [why this tactic fits]

Alternatives:
1. [alternative_tactic_1] - [when to use]
2. [alternative_tactic_2] - [when to use]
3. [alternative_tactic_3] - [when to use]

Recommended starting point:
[suggested initial tactic sequence]
```

**Common patterns:**

| Goal Pattern | Suggested Tactics | Reason |
|--------------|-------------------|---------|
| `⊢ a = b` | `rfl`, `simp`, `ring` | Equality goals |
| `⊢ ∀ x, P x` | `intro x` | Universal quantifier |
| `⊢ ∃ x, P x` | `use [term]` | Existential proof |
| `⊢ A → B` | `intro h` | Implication |
| `⊢ A ∧ B` | `constructor` | Conjunction |
| `⊢ A ∨ B` | `left`/`right` | Disjunction |
| `⊢ a ≤ b` | `linarith`, `omega` | Inequality |

### 4. Search for Required Lemmas

**Based on goal and context:**

a) **Identify needed lemmas:**
```
To prove: [goal]
You likely need:
1. [lemma_type_1] (e.g., "continuous function property")
2. [lemma_type_2] (e.g., "measure theory inequality")

Searching mathlib...
```

b) **Run searches:**
```bash
# For each needed lemma type
bash ${CLAUDE_PLUGIN_ROOT}/skills/lean4-theorem-proving/scripts/smart_search.sh "<lemma_description>" --source=leansearch
```

Replace `<lemma_description>` with the actual lemma to search for.

**Fallback if script fails:**
- Use WebFetch with leansearch API directly (https://leansearch.net/)
- Or use /lean4-theorem-proving:search-mathlib command

c) **Present findings:**
```
Found relevant lemmas:

1. [lemma_name_1]
   Type: [signature]
   Import: [import_path]
   Usage: [how_to_apply]

2. [lemma_name_2]
   Type: [signature]
   Import: [import_path]
   Usage: [how_to_apply]

Add these imports? (yes/pick-specific/search-more)
```

### 5. Generate Proof Candidates

**Create 2-3 approaches:**

**Candidate A: Direct application**
```lean
-- Strategy: Apply found lemmas directly
[lemma_1] [args...] (by [sub_proof])
```

**Candidate B: Tactic-based**
```lean
-- Strategy: Step-by-step tactics
intro x
have h1 := [lemma_1] x
simp [h1]
apply [lemma_2]
```

**Candidate C: Automation-first**
```lean
-- Strategy: Let automation handle it
simp [lemma_1, lemma_2, *]
-- or --
aesop
```

**Present candidates:**
```
Generated 3 proof approaches:

Candidate A (direct, 1 line):
  Pros: Shortest, most concise
  Cons: May fail if types don't align perfectly
  Code: [show candidate A]

Candidate B (tactics, 4 lines):
  Pros: Most likely to work, clear steps
  Cons: Longer, may need tweaking
  Code: [show candidate B]

Candidate C (automation, 1 line):
  Pros: Shortest if it works
  Cons: Least likely to work, hard to debug
  Code: [show candidate C]

Which to try first? (A/B/C/all-in-parallel)
```

### 6. Test Candidates

**If user chooses "all-in-parallel" and MCP available:**
```
Using lean_multi_attempt to test all 3 candidates in parallel...
```

```lean
-- Use MCP to test candidates
mcp__lean-lsp__lean_multi_attempt(
  file = "[file]",
  line = [line],
  tactics = [
    "[candidate_A_code]",
    "[candidate_B_code]",
    "[candidate_C_code]"
  ]
)
```

**Report results:**
```
Test Results:
✓ Candidate A: SUCCESS (compiles)
✗ Candidate B: FAILED (type mismatch at line 3)
✗ Candidate C: FAILED (tactic 'aesop' failed)

Recommendation: Use Candidate A (shortest working solution)

Apply Candidate A? (yes/see-error-from-B/try-fixing-C)
```

**If user chooses sequential testing:**
```
Testing Candidate A...
[Apply edit]
[Run lake build]

Result: [success/failure]
[If failure: show error and offer to try next]
```

### 7. Apply Working Solution

**If candidate succeeds:**

a) **Show the change:**
```
✅ Proof compiles!

Changes to [file]:[line]:

- sorry
+ [working_proof_code]

Verification: lake build ✓

Apply this change? (yes/tweak-first/no)
```

b) **If user wants to tweak:**
```
What would you like to change?
- Simplify (try shorter version)
- Add comments (explain steps)
- Use different lemma
- Custom edit

Choose: (simplify/comment/lemma/custom)
```

c) **Commit the change:**
```
Applied proof at [file]:[line]

Summary:
- Sorry eliminated: ✓
- Proof type: [direct/tactics/automation]
- Length: [N] lines
- Imports added: [M] (if any)
- Compiled: ✓

Ready to commit this change? See /check-axioms to verify no axioms introduced.
```

### 8. Handle Failures

**If all candidates fail:**
```
❌ None of the generated candidates worked.

Analysis of failures:
Candidate A: [error_type] - [brief explanation]
Candidate B: [error_type] - [brief explanation]
Candidate C: [error_type] - [brief explanation]

Common issue: [identify pattern in failures]

Next steps:
1. Search for different lemmas (current ones may not fit)
2. Try different tactic approach
3. Break sorry into smaller sub-sorries
4. Ask for help (Lean Zulip, mathlib docs)

Which approach? (1/2/3/4/give-up-for-now)
```

**If breaking into sub-sorries:**
```
I'll help you structure this proof with intermediate sorries:

-- Strategy: Break [big_goal] into steps
have step1 : [subgoal_1] := sorry
have step2 : [subgoal_2] := sorry
exact [combine step1 step2]

This creates 2 smaller sorries that may be easier to tackle individually.

Apply this structure? (yes/adjust/no)
```

## Integration with Subagents

**If lean4-sorry-filler subagent available:**
```
The sorry-filler subagent can:
- Generate multiple candidates automatically
- Test them in parallel
- Pick the shortest working solution
- Handle batch sorry-filling

This sorry looks like a good candidate for the subagent.
Dispatch it? (yes/no/manual-filling-first)
```

## Common Sorry Types

### Type 1: "Forgot to search mathlib"

**Symptom:** Goal looks like it should exist
```
⊢ Continuous f → IsCompact s → IsCompact (f '' s)
```

**Solution:** `/search-mathlib "continuous compact image"`
**Outcome:** Find existing lemma, apply it, done!

### Type 2: "Just needs right tactic"

**Symptom:** Goal is obviously true
```
⊢ n + 0 = n
```

**Solution:** Try `rfl`, `simp`, or `ring`
**Outcome:** One-line proof

### Type 3: "Missing intermediate step"

**Symptom:** Gap between hypotheses and goal
```
Have: h : P x
Need: ⊢ Q x
```

**Solution:** Add `have intermediate : P x → Q x := [lemma]`
**Outcome:** Two-step proof

### Type 4: "Complex structural proof"

**Symptom:** Needs induction, cases, or extensive calculation
```
⊢ ∀ n : ℕ, P n
```

**Solution:** Use proof template from `/proof-templates induction`
**Outcome:** Structured multi-line proof

### Type 5: "Actually needs new lemma"

**Symptom:** Truly novel result, mathlib doesn't have it
```
⊢ [your_domain_specific_result]
```

**Solution:** Prove as separate lemma, then use it here
**Outcome:** Extract to helper lemma, fill both

## Best Practices

✅ **Do:**
- Always try mathlib search first
- Test candidates before choosing
- Use MCP multi_attempt when available
- Add comments to complex proofs
- Verify with lake build before moving on

❌ **Don't:**
- Skip the mathlib search (it's usually there!)
- Apply candidate without testing
- Give up after first failure
- Fill sorry without understanding the proof
- Forget to add necessary imports

## Error Recovery

**Type mismatch:**
```
Error: type mismatch
  [term]
has type
  [type_A]
but is expected to have type
  [type_B]

Analysis: [identify mismatch reason]
Fix: [suggest coercion/conversion/different lemma]
```

**Tactic failure:**
```
Error: tactic 'simp' failed to simplify

Analysis: simp doesn't know the needed rewrite rule
Fix: Add specific lemmas to simp: simp [lemma1, lemma2]
```

**Import missing:**
```
Error: unknown identifier '[lemma_name]'

Analysis: Lemma exists but import missing
Fix: Adding import [detected_import_path]
```

## Related Commands

- `/search-mathlib` - Find lemmas before filling sorry
- `/analyze-sorries` - See all sorries and plan which to fill
- `/check-axioms` - Verify no axioms accidentally introduced
- `/build-lean` - Quick build verification

## References

- [tactics-reference.md](../references/tactics-reference.md) - Complete tactic catalog
- [mathlib-guide.md](../references/mathlib-guide.md) - Search strategies
- [SKILL.md](../SKILL.md#phase-3-incremental-filling) - Sorry-filling workflow
