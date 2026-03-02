---
description: Systematically clean up Lean 4 linter warnings after successful build
allowed-tools: Bash(bash:*), Bash(lake:*)
---

# Clean Linter Warnings

Systematic cleanup of linter warnings by category (unused variables, simp arguments, etc.) after successful build.

## Workflow

### 1. Verify Build Success

**Before cleaning warnings:**
```
Checking if project builds successfully...

Note: Clean warnings ONLY after build succeeds.
Fixing warnings with compilation errors will waste time.
```

```bash
lake build
```

**If build fails:**
```
❌ Build has errors - fix compilation errors first!

Use /build-lean for error analysis.
Cannot clean warnings until project compiles.
```

**If build succeeds with warnings:**
```
✅ Build successful with [N] warnings

Ready to clean warnings systematically.
Continue? (yes/no)
```

### 2. Categorize Warnings

**Parse build output to group warnings:**

```bash
# Extract and categorize warnings from lake build output
lake build 2>&1 | grep -E "^warning:" | sort | uniq -c | sort -rn
```

**Present categories:**
```
Warning Summary:

By type:
- unused_variable: [X] warnings (variables declared but not used)
- simp_arg: [Y] warnings (simp lemmas with unnecessary args)
- unreachable_code: [Z] warnings (dead code paths)
- deprecated: [W] warnings (deprecated functions)
- other: [V] warnings (miscellaneous)

Total: [N] warnings

Recommendation: Fix by category (start with easiest/safest).
```

### 3. Choose Category to Fix

**Offer fix order by safety:**
```
Suggested fix order:
1. unused_variable (safest - just delete/rename with _)
2. simp_arg (safe - remove unnecessary arguments)
3. deprecated (medium - replace with new API)
4. unreachable_code (needs review - may indicate logic bug)
5. other (varies - case by case)

Which category to fix? (1/2/3/4/5/skip)
```

### 4. Fix Category Systematically

**For each warning in chosen category:**

a) **Show context:**
```
Warning [M]/[N]: unused_variable

File: [file]:[line]
Context:
  [show 3 lines before and after]

Warning: unused variable `x`

Suggested fixes:
1. Rename to `_x` (if might be needed later)
2. Delete entirely (if definitely not needed)
3. Skip this one

Choose: (1/2/3)
```

b) **Apply fix:**
```
Applying fix: [chosen_option]

Changes:
- [old code]
+ [new code]

Verifying fix...
```

```bash
lake build [file]
```

**If build succeeds:**
```
✅ Fix verified - warning eliminated!

Progress: [M]/[N] warnings fixed in this category
Continue to next? (yes/no/skip-rest)
```

**If build fails:**
```
❌ Fix broke compilation - reverting!

Error: [show error]

This warning requires manual investigation.
Skipping to next warning.
```

### 5. Track Progress

**After each category:**
```
Category Summary: [category_name]

Attempted: [X] warnings
Fixed: [Y] warnings
Skipped: [Z] warnings
Failed: [W] warnings (need manual review)

Remaining categories: [list]

Continue to next category? (yes/no/done)
```

### 6. Final Verification

**After all selected categories:**
```bash
# Full rebuild to verify all changes
lake build
```

**Report results:**
```
✅ Warning cleanup complete!

Final Statistics:
- Initial warnings: [N]
- Warnings fixed: [X]
- Remaining warnings: [Y]
- Reduction: [percentage]%

Remaining warnings by type:
[list remaining categories and counts]

Build status: ✓ (still compiles successfully)

Next steps:
- Commit cleaned code: git commit -m "chore: clean linter warnings"
- Tackle remaining warnings (if any): /clean-warnings
- Move to next quality task: /check-axioms, /golf-proofs
```

## Warning Types and Fix Strategies

### unused_variable

**Pattern:** Variable declared but never used

**Safe fixes:**
- Rename to `_varname` if might be needed for documentation
- Delete if truly unnecessary
- Use `_` placeholder if just pattern matching

**Example:**
```lean
-- Before (warning)
theorem foo (x y : ℕ) (h : x < y) : True := trivial

-- Fix 1: Rename unused
theorem foo (_x y : ℕ) (_h : x < y) : True := trivial

-- Fix 2: Delete unused
theorem foo (y : ℕ) : True := trivial

-- Fix 3: Use _ for pattern match
match xs with
| [] => 0
| _::tail => length tail  -- was: x::tail with x unused
```

### simp_arg

**Pattern:** Arguments passed to `simp` that simp already knows

**Safe fix:** Remove the redundant arguments

**Example:**
```lean
-- Before (warning: simp knows add_zero)
simp [add_zero]

-- After
simp
```

### deprecated

**Pattern:** Using deprecated functions/lemmas

**Fix:** Replace with recommended alternative from warning message

**Example:**
```lean
-- Before (warning: nat.add is deprecated, use Nat.add)
example : nat.add x y = x + y := rfl

-- After
example : Nat.add x y = x + y := rfl
```

### unreachable_code

**Pattern:** Code paths that can never execute

**Caution:** May indicate logic bug! Review carefully before deleting.

**Example:**
```lean
-- Before (warning: unreachable after return)
def foo (x : ℕ) : ℕ :=
  if x = 0 then
    return 1
    return 2  -- unreachable!
  else
    x

-- After
def foo (x : ℕ) : ℕ :=
  if x = 0 then
    1
  else
    x
```

## Common Scenarios

### Scenario 1: Post-Development Cleanup

**After completing feature work:**
```
1. /build-lean (verify everything works)
2. /clean-warnings (fix warnings systematically)
3. /check-axioms (verify proof hygiene)
4. /golf-proofs (optimize proof size)
5. Commit clean code
```

### Scenario 2: Pre-Commit Quality Gate

**Before committing:**
```bash
lake build 2>&1 | grep -c "^warning:"
```

If warnings exist, run `/clean-warnings` to clean them up.

### Scenario 3: Large Codebase with Many Warnings

**For 50+ warnings:**
```
1. Run /clean-warnings
2. Start with unused_variable (usually 50-70% of warnings)
3. Fix in batches of 10-20
4. Take breaks between categories
5. Track progress: [X]/[N] completed
```

## Best Practices

✅ **Do:**
- Always verify build succeeds before starting
- Fix by category (unused first, then simp args)
- Verify each fix with incremental build
- Commit after each category is done
- Review unreachable_code warnings carefully

❌ **Don't:**
- Try to fix warnings with compilation errors present
- Fix all warnings blindly without reviewing
- Delete code without understanding why it's unused
- Skip verification builds between fixes
- Commit broken code if a fix goes wrong

## Error Handling

**If fix breaks build:**
```
❌ Fix caused compilation error

Reverting: [file]:[line] to previous state

Error message: [show error]

Action: Skipping this warning (needs manual investigation)

This might happen if:
- Warning was incorrect
- Code has complex dependencies
- Fix was too aggressive

Mark for manual review and continue.
```

**If unable to parse warnings:**
```
⚠️ Could not automatically categorize warnings

Showing raw warning output:
[display lake build warnings]

Manual categorization needed.
Would you like me to help fix these one by one? (yes/no)
```

## Integration with Other Commands

**Typical workflow:**
```
/build-lean              # Verify compilation
  ↓
/clean-warnings          # Clean up warnings  ← YOU ARE HERE
  ↓
/check-axioms            # Verify proof hygiene
  ↓
/golf-proofs             # Optimize proof size
  ↓
Commit!
```

## Related Commands

- `/build-lean` - Verify project compiles before cleaning warnings
- `/golf-proofs` - Optimize proofs after warnings are cleaned
- `/check-axioms` - Verify axiom hygiene after cleanup

## References

- [Lean 4 Linter Documentation](https://leanprover-community.github.io/mathlib4_docs/Mathlib/Tactic/Linter.html)
- [SKILL.md](../SKILL.md#quality-gates) - Quality gate workflows
