---
name: codex-implementation
description: >-
  Hand a bounded, clearly-specified implementation task to the Codex CLI
  (gpt-5.6-sol) to run on an isolated git worktree — migrations, mechanical
  refactors, spec-driven changes. Use when the work is well-defined enough to
  delegate and you want Codex's edits kept off the main checkout until reviewed.
  Not for taste-sensitive or user-facing code.
---

# Codex Implementation

Use Codex (gpt-5.6-sol) for bounded, clearly-specified implementation work you want done outside your own context. Codex works on an isolated git worktree so its edits never touch the main checkout until you review them. Keep taste-sensitive work (public APIs, UI, copy) off this path.

## Execution placement

Run the CLI from the persistent main session and let it reach a terminal state. Redirected calls can be silent for several minutes; poll the process and update the user rather than interrupting it. Treat an empty report or terminal sentinel such as `Execution error`, `max turns reached`, or `error_max_turns` as failure even when the CLI exits 0. Success requires the intended worktree diff and acceptance checks; Codex is not responsible for committing because `workspace-write` deliberately keeps Git metadata read-only.

## Workflow

1. Define the bounded task: exact scope, files in play, and the acceptance check (build/test/lint that must pass).
2. Create a git worktree so Codex can't disturb the main checkout.
3. Create a temporary artifact directory for the prompt and Codex's report.
4. Run `codex exec` (workspace-write) against the worktree with a self-contained prompt.
5. Read Codex's report, review the worktree diff, then create and integrate the task commit yourself before removing the worktree.

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE_PARENT="$(mktemp -d "$(dirname "$REPO_ROOT")/codex-task.XXXXXX")"
WORKTREE="$WORKTREE_PARENT/worktree"
TASK_BRANCH="codex/$(basename "$WORKTREE_PARENT")"
ARTIFACT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/codex-impl.XXXXXX")"
REPORT="$ARTIFACT_DIR/report.md"
PROMPT="$ARTIFACT_DIR/prompt.md"

git -C "$REPO_ROOT" worktree add --detach "$WORKTREE"
git -C "$WORKTREE" switch -c "$TASK_BRANCH"
XDELEGATE_DEPTH=1 codex -C "$WORKTREE" exec -m gpt-5.6-sol -s workspace-write - < "$PROMPT" > "$REPORT"
```

## Implementation Prompt

Keep the prompt tight and self-contained — Codex doesn't see our conversation:

```text
You are the callee in a delegated task. Do not delegate any part of this work to another agent CLI.

Implement <exact change> in this repo.

Scope:
- <files / modules in play>
- <constraints: keep the public API stable, match existing patterns, etc.>

When done:
- run <build/test/lint> and make it pass
- leave the intended changes uncommitted for the caller to review
- summarize what you changed and why, and flag anything you were unsure about

Do not touch anything outside the stated scope.
```

## Reporting Back

Review the worktree diff yourself before merging — Codex is capable, but this path is autonomous. Confirm every changed file is intended, rerun the acceptance check, then stage only those files and create the task commit yourself. Integrate that verified commit, summarize what actually changed, call out anything risky, and run the acceptance check in the main checkout after merge.

Only after integration succeeds, clean up with `git -C "$REPO_ROOT" worktree remove "$WORKTREE" && rmdir "$WORKTREE_PARENT"`. The task branch remains as a recovery point until you deliberately delete it. If integration fails, leave the worktree in place and export a complete patch before deciding how to recover.

If Codex's changes miss the bar, redo the work with a higher-taste model rather than polishing its output.

If `codex` is not installed or the command fails, report the error and offer to do the implementation directly instead.
