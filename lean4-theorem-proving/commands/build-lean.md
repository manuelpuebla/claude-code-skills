---
description: Build Lean 4 project and provide formatted error analysis
---

# Build and Error Analysis

Quick build verification with formatted error reporting and fix suggestions.

## Workflow

### 1. Determine Scope

**Ask if not obvious from context:**
```
Build:
1. Current file only
2. All changed files (git diff)
3. Entire project
4. Specific file/target

Which scope? (1/2/3/4)
```

### 2. Run Build

**For full project:**
```bash
lake build
```

**For single file:**
```bash
lake build [file_target]
```

**Show progress:**
```
Building Lean project...
This may take a minute for first build.

[If slow]:
Tip: Use /profile-build to identify bottlenecks
```

### 3. Report Results

**If build succeeds:**
```
✅ BUILD SUCCESSFUL

All files compiled without errors!

Files built: [N]
Build time: [X]s
Warnings: [Y] (if any)

[If warnings exist]:
⚠️ [Y] warnings detected (build succeeded but see below)

Next steps:
- Run /check-axioms to verify axiom hygiene
- Run /golf-proofs to optimize proof size
- Commit your changes!
```

**If build fails:**
```
❌ BUILD FAILED

Errors detected: [N] error(s) in [M] file(s)

I'll analyze each error and suggest fixes...
```

### 4. Analyze Errors

**Group errors by type:**

```
Error Summary:

Type Mismatch: [N] errors
  - [file]:[line] - [brief description]
  - [file]:[line] - [brief description]

Failed to Synthesize Instance: [M] errors
  - [file]:[line] - [brief description]

Unknown Identifier: [K] errors
  - [file]:[line] - [brief description]

Other: [O] errors
  - [file]:[line] - [brief description]
```

### 5. Provide Fix Suggestions

**For each error, offer specific guidance:**

**Type Mismatch:**
```
Error at [file]:[line]

type mismatch
  [term]
has type
  [type_A]
but is expected to have type
  [type_B]

Analysis:
[Identify issue: coercion needed / wrong lemma / incorrect argument order]

Suggested fixes:
1. [specific fix with code]
2. [alternative approach]
3. [general guidance]

Which error to fix first? (this-one/next/show-all)
```

**Failed to Synthesize Instance:**
```
Error at [file]:[line]

failed to synthesize instance
  [instance_type]

Analysis:
[Check if instance exists / needs explicit declaration / wrong type structure]

Common causes:
1. Missing import (search: "instance [instance_type]")
2. Need explicit haveI/letI declaration
3. Type structure mismatch (check your types)

Suggested fix:
[specific code to add]

Reference: See compilation-errors.md section on instance synthesis

Apply fix? (yes/search-for-instance/read-docs)
```

**Unknown Identifier:**
```
Error at [file]:[line]

unknown identifier '[name]'

Analysis:
[Typo / missing import / not in scope / needs qualification]

Likely cause: Missing import

Searching mathlib for '[name]'...

Found in: [import_path]

Add import? (yes/no/search-more)
```

### 6. Interactive Error Fixing

**Offer to fix errors interactively:**

```
Would you like me to:
1. Fix errors one by one (interactive)
2. Show all errors and let you decide
3. Dispatch error-fixer subagent (if available)
4. Generate error report for later

Choose: (1/2/3/4)
```

**If option 1 (interactive):**
```
Error 1 of [N]: [file]:[line]

[Show error details and suggestions]

Fix this error? (yes/skip/explain-more/stop)
```

**After each fix:**
```
Applied fix at [file]:[line]

Rebuilding to verify...

[Run lake build]

[If successful]:
✓ Fix verified! Error eliminated.

Remaining errors: [N-1]
Continue? (yes/no)

[If new errors]:
⚠️ Fix created new error:
[Show new error]

Revert? (yes/try-different-fix)
```

### 7. Track Progress

**For multiple-error sessions:**
```
Error Fixing Progress:

Original errors: [N]
Fixed: [M]
Remaining: [K]
New (from fixes): [O]

Success rate: [M/(M+K) * 100]%
Time invested: ~[X] minutes

Current error: [description]

Keep going? (yes/take-break/commit-progress)
```

## Common Error Patterns

### Pattern 1: Import Chain Issues

```
Error: unknown identifier 'MeasurableSpace'

Cause: Missing import
Fix: import Mathlib.MeasureTheory.MeasurableSpace.Defs

Prevention: Use /search-mathlib to find imports
```

### Pattern 2: Type Class Instance Missing

```
Error: failed to synthesize instance
  IsProbabilityMeasure μ

Cause: Instance exists but Lean can't infer it
Fix: Add explicit declaration
  haveI : IsProbabilityMeasure μ := h_prob

Reference: See measure-theory.md for instance management
```

### Pattern 3: Coercion Confusion

```
Error: type mismatch
  has type: ℕ
  expected: ℝ

Cause: Natural number used where real number expected
Fix: Add coercion: (n : ℝ)

Common: Arithmetic expressions mixing types
```

### Pattern 4: Definitional vs Propositional Equality

```
Error: type mismatch after simplification
  [complex equality]

Cause: Lean can't see they're equal by definition
Fix: Add simp lemma or use calc chain

Example: See calc-patterns.md
```

### Pattern 5: Scope and Namespace Issues

```
Error: unknown identifier 'List.map'

Cause: 'List' not opened
Fix: Either:
  1. Use qualified name: List.map
  2. Open namespace: open List

Choice: Prefer qualified names for clarity
```

## Integration with Other Tools

**With compilation-errors.md:**
```
For detailed error explanation, see:
[link to specific section in compilation-errors.md]

Common patterns:
- Instance synthesis: Section 2
- Type class issues: Section 3
- Calc chain problems: Section 4
```

**With lean-lsp-mcp:**
```
If MCP available, get real-time diagnostics:

mcp__lean-lsp__lean_diagnostic_messages(file)

This provides:
- Exact error locations
- Error severity levels
- Full error context
```

**With profile-build:**
```
If build is slow:

Use /profile-build to identify:
- Which files take longest
- Import chain bottlenecks
- Optimization opportunities
```

## Build Performance Tips

**First build slow:**
```
First build taking [X] minutes...

This is normal! Subsequent builds will be faster (~[Y]s).

What's happening:
- Building all dependencies (mathlib, etc.)
- Creating build cache
- Compiling project files

Tip: Let it finish once, then builds are incremental.
```

**Subsequent builds slow:**
```
Build taking longer than expected...

Possible causes:
1. Changed core file (rebuilds many dependents)
2. Import chain issues
3. Large proof file

Run /profile-build to diagnose? (yes/no)
```

## Error Handling

**If lake not found:**
```
❌ 'lake' command not found

You may not be in a Lean project directory.

Expected structure:
  lakefile.lean  (or lakefile.toml)
  lean-toolchain
  [source files]

Current directory: [pwd]

Are you in the right directory? (yes/cd-to-project)
```

**If lean-toolchain mismatch:**
```
⚠️ Lean version mismatch

Project expects: lean-4.x.y
You have: lean-4.a.b

This may cause build errors.

Fix: Install correct Lean version
  elan default leanprover/lean4:v4.x.y

Install correct version? (yes/no/ignore)
```

**If out of memory:**
```
❌ Build failed: Out of memory

Your proof files may be too large.

Solutions:
1. Break large proofs into smaller lemmas
2. Increase available memory
3. Build with fewer parallel jobs: lake build -j1

Try building with -j1? (yes/no)
```

## Best Practices

✅ **Do:**
- Build frequently (after each small change)
- Fix errors as they appear (don't accumulate)
- Read error messages carefully
- Use references (compilation-errors.md) for patterns
- Commit after successful builds

❌ **Don't:**
- Ignore warnings (they may indicate real issues)
- Accumulate many errors before fixing
- Skip understanding errors (leads to cargo-cult fixes)
- Forget to rebuild after fixes
- Commit without building

## Advanced Features

**Watch mode (if available):**
```
For continuous building during development:

lake build --watch

This rebuilds automatically when files change.
Useful during active development.
```

**Parallel builds:**
```
Speed up builds with parallel compilation:

lake build -j4  # Use 4 cores

Caveat: May use more memory
```

**Targeted builds:**
```
Build specific theorem/definition:

lake build [module_name].[theorem_name]

Faster than full project build.
```

## Related Commands

- `/check-axioms` - Verify axioms after successful build
- `/golf-proofs` - Optimize after build succeeds
- `/analyze-sorries` - Check incomplete proofs before building
- `/fill-sorry` - Fix sorries that prevent building

## References

- [compilation-errors.md](../references/compilation-errors.md) - Detailed error patterns
- [measure-theory.md](../references/measure-theory.md) - Domain-specific error solutions
- [SKILL.md](../SKILL.md) - General development workflow
