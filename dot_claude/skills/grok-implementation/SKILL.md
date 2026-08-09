---
name: grok-implementation
description: >-
  Hand a bounded, clearly-specified implementation task to the Grok CLI
  (grok-4.5) to run on an isolated git worktree — migrations, mechanical
  refactors, spec-driven changes. Grok is the default implementer for this kind
  of work. Use when the task is well-defined enough to delegate and you want
  Grok's edits kept off the main checkout until reviewed. Not for taste-sensitive
  or user-facing code.
---

# Grok Implementation

Grok-4.5 is the default delegate for bounded, clearly-specified implementation work — migrations, mechanical refactors, spec-driven changes. It works on an isolated git worktree so its edits never touch the main checkout until you review them. Keep taste-sensitive work (public APIs, UI, copy) off this path; that needs a higher-taste model.

## Workflow

1. Define the bounded task: exact scope, files in play, and the acceptance check (build/test/lint that must pass).
2. Create a git worktree so Grok can't disturb the main checkout.
3. Create a temporary artifact directory for the prompt and Grok's report.
4. Run Grok against the worktree with a self-contained prompt.
5. Read Grok's report, then review the worktree diff before merging anything.

```bash
git -C "$PWD" worktree add --detach ../grok-task
WORKTREE="../grok-task"
ARTIFACT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/grok-impl.XXXXXX")"
PROMPT="$ARTIFACT_DIR/prompt.md"
REPORT="$ARTIFACT_DIR/report.json"

grok --no-auto-update --cwd "$WORKTREE" -m grok-4.5 --output-format json \
  --always-approve --prompt-file "$PROMPT" > "$REPORT"
```

Create the worktree with **plain `git worktree add`**, then point Grok at it with `--cwd`. Do not use Grok's own `-w` / `--worktree` flag: in headless mode it is silently ignored — no worktree is created, edits land in the real checkout, and nothing is printed to stderr. This mirrors how `codex-implementation` isolates Codex.

Clean up the worktree when done: `git worktree remove ../grok-task`.

## Implementation Prompt

Keep the prompt tight and self-contained — Grok doesn't see our conversation:

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

For structured output, add `--json-schema '{...}'`; describe the shape in prose in the prompt too, so it survives shell quoting.

## Parallel implementers

Give each one its own worktree, or their edits collide. One `git worktree add` per task, one `--cwd` per invocation.

## Reporting Back

Review the worktree diff yourself before merging — Grok is capable, but this path is autonomous and runs with `--always-approve`. Summarize what actually changed, call out anything risky, and run the acceptance check in the main checkout after merge.

If Grok's changes miss the bar, redo the work with a higher-taste model rather than polishing its output.

If `grok` isn't installed, isn't authenticated, or the command fails, report the error and offer to do the implementation directly instead.
