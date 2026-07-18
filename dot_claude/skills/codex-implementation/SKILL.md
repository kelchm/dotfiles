---
name: codex-implementation
description: >-
  Hand a bounded, clearly-specified implementation task to the Codex CLI
  (gpt-5.5) to run on an isolated git worktree — migrations, mechanical
  refactors, spec-driven changes. Use when the work is well-defined enough to
  delegate and you want Codex's edits kept off the main checkout until reviewed.
  Not for taste-sensitive or user-facing code.
---

# Codex Implementation

Use Codex (gpt-5.5) for bounded, clearly-specified implementation work you want done outside your own context. Codex works on an isolated git worktree so its edits never touch the main checkout until you review them. Keep taste-sensitive work (public APIs, UI, copy) off this path.

## Workflow

1. Define the bounded task: exact scope, files in play, and the acceptance check (build/test/lint that must pass).
2. Create a git worktree so Codex can't disturb the main checkout.
3. Create a temporary artifact directory for the prompt and Codex's report.
4. Run `codex exec` (workspace-write) against the worktree with a self-contained prompt.
5. Read Codex's report, then review the worktree diff before merging anything.

```bash
git -C "$PWD" worktree add --detach ../codex-task
WORKTREE="../codex-task"
ARTIFACT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/codex-impl.XXXXXX")"
REPORT="$ARTIFACT_DIR/report.md"
PROMPT="$ARTIFACT_DIR/prompt.md"

codex -C "$WORKTREE" exec -s workspace-write - < "$PROMPT" > "$REPORT"
```

## Implementation Prompt

Keep the prompt tight and self-contained — Codex doesn't see our conversation:

```text
Implement <exact change> in this repo.

Scope:
- <files / modules in play>
- <constraints: keep the public API stable, match existing patterns, etc.>

When done:
- run <build/test/lint> and make it pass
- summarize what you changed and why, and flag anything you were unsure about

Do not touch anything outside the stated scope.
```

## Reporting Back

Review the worktree diff yourself before merging — Codex is capable, but this path is autonomous. Summarize what actually changed, call out anything risky, and run the acceptance check in the main checkout after merge.

If Codex's changes miss the bar, redo the work with a higher-taste model rather than polishing its output.

If `codex` is not installed or the command fails, report the error and offer to do the implementation directly instead.
