---
description: Verify that Lean 4 proofs use only standard mathlib axioms
allowed-tools: Bash(bash:*)
---

# Axiom Hygiene Verification

Quick verification that your Lean 4 proofs use only standard axioms (propext, quot.sound, Classical.choice).

**IMPORTANT:** The axiom checker script is bundled with this plugin - do not look for it in the current directory. Always use the full path with ${CLAUDE_PLUGIN_ROOT}.

## Workflow

### 1. Determine Scope

**Ask user if file not specified:**
```
Check axioms in:
1. Current file ([detect from context])
2. All changed files (git diff)
3. Entire project
4. Custom file/pattern

Which scope? (1/2/3/4)
```

### 2. Run Verification

Check that the tool is available, then run verification:

```bash
# Verify the tool is staged
test -f .claude/tools/lean4/check_axioms.sh || {
  echo "ERROR: check_axioms.sh not staged. Restart session after reinstalling plugin."
  exit 1
}
```

**For single or multiple files** (replace `MyTheorems.lean` with your actual file):
```bash
bash .claude/tools/lean4/check_axioms.sh MyTheorems.lean
```

**For multiple files or glob patterns:**
```bash
bash .claude/tools/lean4/check_axioms.sh src/*.lean
```

**If the script is not available or fails, fall back to manual Lean checks:**

For individual theorems:
```bash
lake env lean --run <<EOF
#print axioms theoremName
EOF
```

For all theorems in a file (replace `MyFile.lean` with your actual file):
```bash
grep "^theorem\|^lemma\|^def" MyFile.lean | while read line; do
  name=$(echo "$line" | awk '{print $2}' | cut -d'(' -f1 | cut -d':' -f1)
  echo "Checking $name..."
  lake env lean --run -c "#print axioms $name" MyFile.lean
done
```

**IMPORTANT:** Replace `MyTheorems.lean` and `MyFile.lean` with your actual file paths. Never use placeholders like `<file>` in executed commands.

### 3. Interpret Results

**If all axioms are standard:**
```
✅ Axiom hygiene check PASSED

All declarations use only standard axioms:
- propext (propositional extensionality)
- quot.sound / Quot.sound (quotient soundness)
- Classical.choice (axiom of choice)

Files checked: [N]
Declarations verified: [M]

Ready to commit!
```

**If non-standard axioms found:**
```
⚠️ Non-standard axioms detected!

[file]:[line] - [theorem_name]
  Uses axiom: [axiom_name]

[file]:[line] - [theorem_name]
  Uses axiom: [axiom_name]

Total: [N] declarations with non-standard axioms

These axioms need elimination plans before merging to main.
```

### 4. Offer Next Steps

**If non-standard axioms found:**

a) **Document elimination plan:**
```
Would you like me to:
1. Create TODO comments documenting elimination strategy
2. Search mathlib for proof patterns to eliminate these axioms
3. Dispatch axiom-eliminator subagent to work on these systematically

What would help? (1/2/3/skip)
```

b) **Search for proof patterns:**
```bash
# For each axiom, search mathlib for similar proven theorems
./scripts/search_mathlib.sh "[theorem_type_pattern]" type
```

c) **Generate elimination template:**
```lean
-- TODO: Eliminate axiom [axiom_name]
-- Strategy: [search_results_summary]
-- Required lemmas:
--   1. [lemma_from_mathlib]
--   2. [lemma_from_mathlib]
-- Difficulty: [easy/medium/hard]
-- Priority: [high/medium/low]

axiom [axiom_name] : [type]
```

**If using lean4-subagents plugin:**
```
The lean4-axiom-eliminator subagent can systematically work through
these axioms. Dispatch it? (yes/no)
```

### 5. Track Progress

**For projects with many axioms:**

```
Axiom Elimination Progress:

Total axioms: [N]
Standard axioms: [M] ✓
Custom axioms remaining: [K]

Custom axioms by priority:
- HIGH: [X] (blocking issues)
- MEDIUM: [Y] (nice to have)
- LOW: [Z] (future work)

Next recommended target: [theorem_name] at [file]:[line]
Reason: [why it's a good next target]
```

## Common Scenarios

### Scenario 1: Pre-Commit Check

**Quick verification before committing:**
```bash
# Check only changed files
git diff --name-only '*.lean' | xargs ./scripts/check_axioms_inline.sh
```

### Scenario 2: PR Review

**Verify new code doesn't introduce axioms:**
```bash
# Check files changed since main branch
./scripts/check_axioms_inline.sh "$(git diff main --name-only '*.lean')"
```

### Scenario 3: Systematic Elimination

**Working through axiom cleanup:**
```
1. Run check_axioms_inline.sh to get full list
2. Document elimination plan for each axiom
3. Work through list by priority
4. Re-run check to verify progress
5. Repeat until only standard axioms remain
```

## Integration with Quality Gates

**If lean4-quality-gates plugin installed:**
```
Note: With quality gates enabled, axiom checks run automatically
on commit commands. This manual check is for:
- Mid-development verification
- Checking specific files
- Planning elimination work
```

## Error Handling

**If project doesn't build:**
```
❌ Cannot check axioms: Project doesn't compile

Error from lake build:
[show error]

Action required:
Fix compilation errors first, then re-run axiom check.
See /build-lean for detailed error analysis.
```

**If check_axioms_inline.sh not found:**
```
⚠️ Script not found: scripts/check_axioms_inline.sh

You may be in the wrong directory. Axiom checker requires:
1. Lean 4 project with lake configuration
2. lean4-theorem-proving skill scripts available

Current directory: [pwd]
```

## Best Practices

✅ **Do:**
- Run before every commit (or use quality gates)
- Document elimination strategy for each custom axiom
- Work through axioms systematically by priority
- Verify elimination with re-run of check

❌ **Don't:**
- Commit code with undocumented axioms
- Leave "temporary" axioms indefinitely
- Skip axiom checks because "it's just a prototype"
- Forget to update elimination plans when strategy changes

## Related Commands

- `/analyze-sorries` - Check for incomplete proofs (sorries)
- `/search-mathlib` - Find lemmas to help eliminate axioms
- `/build-lean` - Verify project compiles before axiom check

## References

- [scripts/README.md](../scripts/README.md#check_axioms_inlinesh) - Detailed tool documentation
- [SKILL.md](../SKILL.md#phase-4-managing-type-class-issues) - Axiom elimination workflows
