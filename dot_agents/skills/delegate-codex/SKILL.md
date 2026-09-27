---
name: delegate-codex
description: Delegate a bounded implementation task or independent code review to the Codex CLI. Use when a separate Codex session provides useful isolation or another perspective.
---

# Delegate to Codex

Choose implementation or review from the task; model preferences live in the calling harness's global instructions. If `XDELEGATE_DEPTH` is set, do the work directly and do not launch another delegate.

Set `MODEL` and `EFFORT` explicitly, and write a self-contained prompt to `PROMPT` in a temporary artifact directory. Use a text `REPORT` path there too. Name the scope or exact review target, relevant requirements, and acceptance checks. Begin the prompt with: “You are the callee in a delegated task. Do not delegate any part of this work to another agent or CLI.”

Run from the persistent parent session and poll to completion, updating the user. Several quiet minutes are normal; successful calls have taken more than ten minutes. A zero exit code is insufficient: check for a nonempty report, terminal errors such as `Execution error`, `max turns reached`, or `error_max_turns`, and evidence that the task was completed. Preserve failed-run artifacts. If the CLI is unavailable or cannot start within the current permissions, report the limitation and continue directly when possible; never silently weaken the guard or change the billing route.

If `CODEX_SANDBOX` indicates a sandboxed caller, the child may be unable to initialize its sandbox or access authentication/session state. Use a permitted per-command escalation if the host supports it; if unavailable, continue directly. Do not remove the child's guards or change the entire parent session to unrestricted execution to work around nesting.

## Implementation

Create a plain Git worktree from the intended starting commit. Uncommitted parent changes are not included; explicitly carry any required input into the worktree. Use one worktree per task:

```bash
REPO_ROOT="$(rtk git rev-parse --show-toplevel)"
WORKTREE_PARENT="$(rtk mktemp -d "$(dirname "$REPO_ROOT")/codex-task.XXXXXX")"
WORKTREE="$WORKTREE_PARENT/worktree"
TASK_BRANCH="delegate/$(basename "$WORKTREE_PARENT")"
rtk git -C "$REPO_ROOT" worktree add -b "$TASK_BRANCH" "$WORKTREE" HEAD

XDELEGATE_DEPTH=1 rtk codex -C "$WORKTREE" exec \
  -m "$MODEL" -c "model_reasoning_effort=$EFFORT" -s workspace-write \
  - < "$PROMPT" > "$REPORT"
```

Ask Codex to edit only the stated scope, run the named checks, leave changes uncommitted, and report uncertainties. `workspace-write` deliberately keeps Git metadata read-only; the parent owns the commit. Always close stdin with a file or `/dev/null`, or the CLI can wait indefinitely for EOF.

Check the parent checkout's status before and after, inspect the entire task diff, and verify the acceptance evidence. The parent stages intended files and creates the commit, integrates it within the user's authorized scope, and validates the integrated result. Keep the worktree and recovery branch if integration fails. Remove the worktree only after its changes are safely integrated or the user has chosen to discard them.

## Review

Use a custom review prompt naming the exact target, so the callee prohibition and task-specific scope travel with the request:

```bash
XDELEGATE_DEPTH=1 rtk codex -C "$PWD" exec -s read-only review \
  -m "$MODEL" -c "model_reasoning_effort=$EFFORT" \
  - < "$PROMPT" > "$REPORT"
```

Do not combine a custom prompt with `--base`, `--commit`, or `--uncommitted`; Codex rejects that combination. Without an explicit target in the custom prompt, review defaults to uncommitted changes. Use the repository's actual base branch, not an assumed `main`.

Ask for concrete bugs and requirement mismatches, with severity, file/line, failure mode, and fix direction; cap findings at eight. Explicitly prohibit edits and tell the reviewer to report no findings when appropriate. Check repository status/diff afterward and verify each substantive finding before acting; agreement between models is not proof. Report the target, actual model/effort, confirmed findings, and unresolved limits. Do not turn a clean review into another review automatically.
