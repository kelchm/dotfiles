---
name: delegate-grok
description: Delegate a bounded implementation task or independent code review to the Grok CLI. Use when a separate Grok session provides useful isolation or another perspective.
---

# Delegate to Grok

Choose implementation or review from the task; model preferences live in the calling harness's global instructions. If `XDELEGATE_DEPTH` is set, do the work directly and do not launch another delegate.

Set `MODEL` and `EFFORT` explicitly, and write a self-contained prompt to `PROMPT` in a temporary artifact directory. Use a JSON `REPORT` path there too. Name the scope or exact review target, relevant requirements, and acceptance checks. Begin the prompt with: “You are the callee in a delegated task. Do not delegate any part of this work to another agent or CLI.”

Run from the persistent parent session and poll to completion, updating the user. Several quiet minutes are normal; successful calls have taken more than ten minutes. A zero exit code is insufficient: parse the JSON, require nonempty `.text`, check for terminal errors such as `Execution error`, `max turns reached`, or `error_max_turns`, and verify that the task was completed. Preserve failed-run artifacts. If the CLI is unavailable or cannot start within the current permissions, report the limitation and continue directly when possible; never silently weaken the guard or change the billing route.

If `CODEX_SANDBOX` indicates a sandboxed caller, Grok may fail to initialize its own sandbox or write session state. Use a permitted per-command escalation if the host supports it; if unavailable, continue directly. Do not remove Grok's review guards or change the entire parent session to unrestricted execution to work around nesting.

## Implementation

Create a plain Git worktree from the intended starting commit. Uncommitted parent changes are not included; explicitly carry any required input into the worktree. Use one worktree per task, outside temporary directories:

```bash
REPO_ROOT="$(rtk git rev-parse --show-toplevel)"
WORKTREE_PARENT="$(rtk mktemp -d "$(dirname "$REPO_ROOT")/grok-task.XXXXXX")"
WORKTREE="$WORKTREE_PARENT/worktree"
TASK_BRANCH="delegate/$(basename "$WORKTREE_PARENT")"
rtk git -C "$REPO_ROOT" worktree add -b "$TASK_BRANCH" "$WORKTREE" HEAD

XDELEGATE_DEPTH=1 rtk grok --no-auto-update --no-subagents --cwd "$WORKTREE" \
  -m "$MODEL" --effort "$EFFORT" --output-format json --always-approve \
  --deny "Bash(claude:*)" --deny "Bash(codex:*)" --deny "Bash(opencode:*)" \
  --deny "Bash(rtk claude:*)" --deny "Bash(rtk codex:*)" --deny "Bash(rtk opencode:*)" \
  --prompt-file "$PROMPT" > "$REPORT"
```

Do not rely on Grok's vendor worktree flag: previous headless versions silently ignored it. A worktree separates edits but is not a filesystem jail, especially with approvals disabled. Command-prefix denies do not block alternate executable paths. Keep the prompt prohibition, `XDELEGATE_DEPTH=1`, `--no-subagents`, and the user-level skill-discovery ignore for `delegate-grok`.

Ask Grok to edit only the stated scope, run the named checks, leave changes uncommitted, and report uncertainties. Check the parent checkout's status before and after, inspect the entire task diff, and verify the acceptance evidence. The parent stages intended files and creates the commit, integrates it within the user's authorized scope, and validates the integrated result. Keep the worktree and recovery branch if integration fails. Remove the worktree only after its changes are safely integrated or the user has chosen to discard them.

## Review

Drive Grok with a direct review prompt. Do not invoke its bundled `/review`: that path has attempted recursive reviewer dispatch. Name the exact target in the prompt and run from the repository root:

```bash
XDELEGATE_DEPTH=1 rtk grok --no-auto-update --no-subagents --cwd "$PWD" \
  -m "$MODEL" --effort "$EFFORT" --output-format json \
  --always-approve --sandbox read-only \
  --deny "Edit($PWD/**)" --deny "Write($PWD/**)" \
  --prompt-file "$PROMPT" > "$REPORT"
```

Keep the repo-scoped denies as well as the sandbox. Do not deny Bash: the reviewer needs it to inspect Git. Do not substitute `--tools` or `--disallowed-tools`; prior versions silently restored the full toolset for an unrecognized name. `--deny` fails closed on an invalid rule.

Grok's sandbox is defense-in-depth, not portable containment: temporary directories and `~/.grok` remain writable on macOS, and unsupported kernels may not enforce it. Never use a temporary-directory fixture to claim filesystem containment.

Ask for concrete bugs and requirement mismatches, with severity, file/line, failure mode, and fix direction; cap findings at eight. Explicitly prohibit edits and tell the reviewer to report no findings when appropriate. Check repository status/diff afterward and verify each substantive finding before acting; agreement between models is not proof. Report the target, actual model/effort, confirmed findings, and unresolved limits. Do not turn a clean review into another review automatically.
