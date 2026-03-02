---
description: Interactively optimize Lean 4 proofs by shortening length or runtime without sacrificing readability
allowed-tools: Bash(python:*)
---

# Interactive Proof Optimization

Apply systematic proof-golfing patterns to optimize Lean 4 proofs after compilation.

**IMPORTANT:** Proof-golfing scripts are bundled with this plugin - do not look for them in the current directory. Always use the full path with ${CLAUDE_PLUGIN_ROOT}.

## Workflow

Follow this systematic process to achieve 30-40% size reduction while avoiding the 93% false-positive trap:

### 1. Verify File is Ready

**Before starting, confirm:**
- File compiles successfully (`lake build`)
- No uncommitted changes (or user is okay with edits)
- Not actively being worked on (avoid conflicts)

**Ask user:**
```
Ready to optimize [file]? This will:
- Find optimization patterns (filtering out false positives)
- Apply changes interactively with your approval
- Test each change with lake build

Continue? (yes/no)
```

### 2. Find High-Value Patterns

Check that the tool is available, then run pattern detection.

**Verify tool is staged:**
```bash
test -f .claude/tools/lean4/find_golfable.py || {
  echo "ERROR: find_golfable.py not staged. Restart session after reinstalling plugin."
  exit 1
}
```

**Run pattern detection with false-positive filtering** (replace `MyFile.lean` with your actual file):
```bash
python3 .claude/tools/lean4/find_golfable.py MyFile.lean --filter-false-positives --verbose
```

**Fallback if script is not available or fails** (replace `MyFile.lean` with your actual file):
```bash
# Manual pattern detection - search for common patterns
grep -n "let.*:=.*have.*:=.*exact" MyFile.lean  # let+have+exact pattern
grep -n "by$" MyFile.lean | grep -A1 "exact"     # by-exact pattern
```

**IMPORTANT:** Never use placeholders like `<file>` in executed commands. Always use the actual file path.

**If 0 patterns found:**
```
✅ No optimization opportunities found in [file].
This means either:
- File is already well-optimized
- Patterns are marginal (not worth the effort)
- Codebase has reached saturation

Recommendation: Move on to other files or declare victory!
```

**If patterns found:**
Show summary and proceed to next step.

### 3. Prioritize by Impact

**Group patterns by priority:**
- HIGH (let+have+exact): 60-80% reduction → **Do these first**
- MEDIUM (by-exact, ext-simp): 30-50% reduction → **Do after HIGH**
- LOW (other): 10-30% reduction → **Skip if time-limited**

**Focus strategy:**
```
Found [N] patterns:
- [X] HIGH priority (60-80% reduction each)
- [Y] MEDIUM priority (30-50% reduction)
- [Z] LOW priority (10-30% reduction)

Recommendation: Focus on HIGH priority patterns first for best ROI.
Tackle HIGH patterns? (yes/no)
```

### 4. Verify Safety (Critical Step!)

**For each HIGH priority pattern:**

a) **Check if let binding is safe to inline** (replace with your actual file and line number):
```bash
python3 .claude/tools/lean4/analyze_let_usage.py MyFile.lean --line 42
```

**Fallback if script is not available or fails:**
- Manually count let binding uses in the proof
- If used ≥3 times → SKIP (false positive)

**IMPORTANT:** Replace `MyFile.lean` and `42` with your actual file path and line number.
- If used ≤2 times → Proceed carefully

b) **Interpret results:**
- ✅ "SAFE TO INLINE" (used ≤1 time) → Proceed with optimization
- ⚡ "MARGINAL" (used 2 times) → Ask user if readability is okay
- ⚠️ "DON'T INLINE" (used ≥3 times) → **SKIP THIS PATTERN** (false positive!)

**If false positive detected:**
```
⚠️ Pattern at line [N] is a false positive!
Let binding '[name]' used [X] times.
Inlining would INCREASE code by ~[Y] tokens.

Skipping this pattern (would make code worse).
```

### 5. Apply Optimizations

**For each safe pattern:**

a) **Show user the before/after:**
```
Pattern: [pattern_type] at line [N]
Estimated savings: [X] lines, [Y]% reduction

BEFORE:
[show 5-10 lines of current code]

PROPOSED CHANGE:
[show optimized version]

Apply this optimization? (yes/no/skip-remaining)
```

b) **If user says yes:**
- Apply the edit
- Run `lake build` to verify
- If build fails: revert and report error
- If build succeeds: move to next pattern

c) **Track cumulative savings:**
```
Applied [N] optimizations so far:
- Lines saved: [X]
- Estimated token reduction: [Y]%
```

### 6. Check for Saturation

**After each batch of 5-10 optimizations, check indicators:**

**Saturation signs:**
- Optimization success rate drops below 20%
- Time per optimization exceeds 15 minutes
- Most remaining patterns are false positives
- Debating whether 2-token savings is worth it

**If saturation detected:**
```
🏁 Saturation point reached!

Statistics:
- Optimizations applied: [N]
- Lines saved: [X]
- Token reduction: ~[Y]%
- Time invested: ~[Z] minutes

Remaining patterns are marginal (low ROI).
Recommendation: Declare victory and move on!

Continue optimizing anyway? (yes/no)
```

### 7. Final Verification

**After all optimizations:**
```bash
# Verify file still compiles
lake build [file]

# Show final statistics
```

**Report results:**
```
✅ Proof optimization complete!

Final Statistics:
- Patterns found: [total]
- Patterns applied: [applied] ([success_rate]%)
- False positives skipped: [skipped]
- Lines saved: [lines]
- Estimated token reduction: [percent]%
- Time invested: ~[minutes] minutes

File compiles successfully: ✓

Ready to commit these changes? See /check-axioms to verify quality.
```

## Common Patterns to Look For

Based on references/proof-golfing.md:

**Pattern 1: let + have + exact** (60-80% reduction)
- Most valuable pattern
- MUST verify with analyze_let_usage.py (93% false positive rate!)
- Only inline if binding used ≤2 times

**Pattern 2: Smart ext** (50% reduction)
- `apply Subtype.ext; apply Fin.ext` → `ext`
- ext handles nested extensionality automatically

**Pattern 3: simp closes goals directly** (67% reduction)
- `simp only [...]; exact lemma` → `simp [...]`
- When simp knows the final fact

**Pattern 4: ext-simp chains** (≥2 line savings)
- Combine sequential steps: `ext x; simp; use y; simp`
- Only when natural and saves ≥2 lines

## Error Handling

**If lake build fails after optimization:**
```
❌ Build failed after optimization at line [N]

Error: [show error message]

Action: Reverting change and continuing with next pattern.
This pattern requires manual investigation.
```

**If analyze_let_usage.py fails:**
```
⚠️ Could not analyze let binding usage.
Recommendation: Skip this pattern (safety first).
```

## Integration with Other Tools

**Use count_tokens.py for unclear cases** (replace with your actual file and code):
```bash
python3 .claude/tools/lean4/count_tokens.py --before-file MyFile.lean:10-25 --after "optimized code here"
```

**Fallback if script is not available or fails:**
- Use token counting quick reference from proof-golfing.md
- Each line ≈ 8-12 tokens, each have+proof ≈ 15-20 tokens
- Compare line counts first, then estimate token density

**IMPORTANT:** Replace `MyFile.lean:10-25` and `"optimized code here"` with your actual values.

**Use lean_multi_attempt (if MCP available):**
```
For complex optimizations, generate 2-3 candidates and test in parallel
```

## Best Practices

✅ **Do:**
- Always verify safety with analyze_let_usage.py
- Test each change with lake build before proceeding
- Stop at saturation indicators
- Focus on HIGH priority patterns first

❌ **Don't:**
- Skip the safety verification (leads to worse code!)
- Continue past saturation (diminishing returns)
- Optimize for the sake of optimizing
- Ignore readability for small token savings

## Related Commands

- `/check-axioms` - Verify axiom hygiene after optimization
- `/build-lean` - Quick build verification
- `/analyze-sorries` - Check for remaining sorries

## References

- [proof-golfing.md](../references/proof-golfing.md) - Complete pattern catalog
- [scripts/README.md](../scripts/README.md#find_golfablepy) - Tool documentation
