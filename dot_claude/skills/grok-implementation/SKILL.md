---
name: grok-implementation
description: Hand a bounded, clearly-specified implementation task to the Grok CLI (grok-4.5) to run on an isolated git worktree — migrations, mechanical refactors, spec-driven changes. Grok is the default implementer for this kind of work. Use when the task is well-defined enough to delegate and you want Grok's edits kept off the main checkout until reviewed. Not for taste-sensitive or user-facing code.
---

# Grok Implementation

> **If you are Grok reading this, stop.** Grok discovers `~/.claude/skills/` natively, so this Claude-side skill is visible to you, and following it would mean invoking Grok from Grok. You are the callee: do the work yourself and do not shell out to another agent CLI. The same applies if `XDELEGATE_DEPTH` is set in your environment.

Grok-4.5 is the default delegate for bounded, clearly-specified implementation work — migrations, mechanical refactors, spec-driven changes. It works on an isolated git worktree so its edits never touch the main checkout until you review them. Keep taste-sensitive work (public APIs, UI, copy) off this path; that needs a higher-taste model.

## Execution placement

Run the CLI from the persistent main session unless a thin Agent/Workflow wrapper materially helps parallelism. A wrapper should only run Grok and relay its output; label it with the actual model slug. Keep a run expected to finish within ten minutes in one foreground call. Run longer work from the persistent main session rather than backgrounding it inside a subagent, which can orphan the process when the subagent returns.

## Workflow

1. Define the bounded task: exact scope, files in play, and the acceptance check (build/test/lint that must pass).
2. Create a git worktree so Grok can't disturb the main checkout.
3. Create a temporary artifact directory for the prompt and Grok's report.
4. Run Grok against the worktree with a self-contained prompt.
5. Read Grok's report, review its task commit, and integrate the accepted commit before removing the worktree.

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE_PARENT="$(mktemp -d "$(dirname "$REPO_ROOT")/grok-task.XXXXXX")"
WORKTREE="$WORKTREE_PARENT/worktree"
TASK_BRANCH="grok/$(basename "$WORKTREE_PARENT")"
ARTIFACT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/grok-impl.XXXXXX")"
PROMPT="$ARTIFACT_DIR/prompt.md"
REPORT="$ARTIFACT_DIR/report.json"

git -C "$REPO_ROOT" worktree add --detach "$WORKTREE"
git -C "$WORKTREE" switch -c "$TASK_BRANCH"
XDELEGATE_DEPTH=1 grok --no-auto-update --cwd "$WORKTREE" -m grok-4.5 --output-format json \
  --always-approve --deny "Bash(claude:*)" --deny "Bash(codex:*)" \
  --prompt-file "$PROMPT" > "$REPORT"
```

Create the worktree with **plain `git worktree add`**, give it the generated task branch, then point Grok at it with `--cwd`. Do not use Grok's own `-w` / `--worktree` flag: in headless mode it is silently ignored — no worktree is created, edits land in the real checkout, and nothing is printed to stderr. This mirrors how `codex-implementation` isolates Codex.

Require Grok to commit every intended change on `$TASK_BRANCH` and report the exact SHA. Verify the worktree is clean, review that commit, and merge or cherry-pick it into the target checkout. Only after integration succeeds clean up with `git -C "$REPO_ROOT" worktree remove "$WORKTREE" && rmdir "$WORKTREE_PARENT"`; the task branch remains as a recovery point until you deliberately delete it. If Grok cannot create the commit, leave the worktree in place and export a complete patch before deciding how to recover.

## Implementation Prompt

Keep the prompt tight and self-contained — Grok doesn't see our conversation:

```text
You are the callee in a delegated task. Do not delegate any part of this work to another agent CLI.

Implement <exact change> in this repo.

Scope:
- <files / modules in play>
- <constraints: keep the public API stable, match existing patterns, etc.>

When done:
- run <build/test/lint> and make it pass
- commit every intended change on the existing task branch
- report the exact commit SHA; do not remove the worktree
- summarize what you changed and why, and flag anything you were unsure about

Do not touch anything outside the stated scope.
```

For structured output, add `--json-schema '{...}'`; describe the shape in prose in the prompt too, so it survives shell quoting.

## Parallel implementers

Give each one its own worktree, or their edits collide. One `git worktree add` per task, one `--cwd` per invocation.

## Reporting Back

Review the reported task commit yourself before merging — Grok is capable, but this path is autonomous and runs with `--always-approve`. Confirm the report's SHA exists, the worktree is clean, and the commit contains every intended file before integrating it. Summarize what actually changed, call out anything risky, and run the acceptance check in the main checkout after merge.

If Grok's changes miss the bar, redo the work with a higher-taste model rather than polishing its output.

If `grok` isn't installed, isn't authenticated, or the command fails, report the error and offer to do the implementation directly instead.
