---
name: delegate-claude
description: Delegate a bounded implementation task or independent code review to the Claude CLI. Use when a separate Claude session provides useful isolation or another perspective.
---

# Delegate to Claude

Choose implementation or review from the task; model preferences live in the calling harness's global instructions. If `XDELEGATE_DEPTH` is set, do the work directly and do not launch another delegate.

Set `MODEL` and `EFFORT` explicitly, and write a self-contained prompt to `PROMPT` in a temporary artifact directory. Use a text `REPORT` path there too. Name the scope or exact review target, relevant requirements, and acceptance checks. Begin the prompt with: “You are the callee in a delegated task. Do not delegate any part of this work to another agent or CLI.” Claude safe mode disables global instructions, so include any task-relevant repository conventions in the prompt.

Run from the persistent parent session and poll to completion, updating the user. Several quiet minutes are normal; successful calls have taken more than ten minutes. A zero exit code is insufficient: check for a nonempty report, terminal errors such as `Execution error`, `max turns reached`, or `error_max_turns`, and evidence that the task was completed. Preserve failed-run artifacts. If the CLI is unavailable or cannot start within the current permissions, report the limitation and continue directly when possible; never silently weaken the guard or change the billing route.

If `CODEX_SANDBOX` indicates a sandboxed caller, the child may be unable to initialize its sandbox or access authentication/session state. Use a permitted per-command escalation if the host supports it; if unavailable, continue directly. Do not remove the child's guards or change the entire parent session to unrestricted execution to work around nesting.

## Implementation

Create a plain Git worktree from the intended starting commit. Uncommitted parent changes are not included; explicitly carry any required input into the worktree. Use one worktree per task, with the worktree outside temporary directories for meaningful sandbox behavior:

```bash
REPO_ROOT="$(rtk git rev-parse --show-toplevel)"
WORKTREE_PARENT="$(rtk mktemp -d "$(dirname "$REPO_ROOT")/claude-task.XXXXXX")"
WORKTREE="$WORKTREE_PARENT/worktree"
TASK_BRANCH="delegate/$(basename "$WORKTREE_PARENT")"
rtk git -C "$REPO_ROOT" worktree add -b "$TASK_BRANCH" "$WORKTREE" HEAD
```

Ask Claude to edit only the stated scope, run the named checks, leave changes uncommitted, and report uncertainties. Set the process cwd to the worktree; Claude has no target-directory flag. Allow the exact acceptance command, with one narrow rule per command if several are needed:

```bash
ACCEPTANCE_TOOL='Bash(<exact acceptance command>:*)'
( cd "$WORKTREE" && XDELEGATE_DEPTH=1 rtk claude -p --no-session-persistence \
    --model "$MODEL" --effort "$EFFORT" --safe-mode --strict-mcp-config \
    --permission-mode acceptEdits \
    --disallowed-tools Task Agent "Bash(claude:*)" "Bash(grok:*)" "Bash(codex:*)" "Bash(opencode:*)" \
    --allowed-tools "$ACCEPTANCE_TOOL" \
    < "$PROMPT" > "$REPORT" )
```

`acceptEdits` does not approve arbitrary shell commands. Match the prompt's acceptance command exactly, including `rtk` if used. Safe mode preserves authentication while disabling custom hooks, skills, plugins, and settings; `--strict-mcp-config` excludes configured MCP servers. Command-prefix denies are a recursion backstop, not containment against alternate executable paths.

A worktree separates edits; it is not a filesystem jail. Check the parent checkout's status before and after, inspect the entire task diff, and verify the acceptance evidence. The parent stages intended files and creates the commit, integrates it within the user's authorized scope, and validates the integrated result. Keep the worktree and recovery branch if integration fails. Remove the worktree only after its changes are safely integrated or the user has chosen to discard them.

## Review

Run with the process cwd set to the repository. Name the exact diff, commit, or files in the prompt. Ask for concrete bugs and requirement mismatches, with severity, file/line, failure mode, and fix direction; cap findings at eight. Explicitly prohibit edits and tell the reviewer to report no findings when appropriate.

```bash
XDELEGATE_DEPTH=1 rtk claude -p --no-session-persistence \
  --model "$MODEL" --effort "$EFFORT" --safe-mode --strict-mcp-config \
  --permission-mode manual --disallowed-tools Edit Write NotebookEdit Task Agent \
  --allowed-tools Read Grep Glob "Bash(git status:*)" "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" \
  < "$PROMPT" > "$REPORT"
```

Tell Claude to use plain `git status`, `git diff`, `git log`, and `git show`, without `rtk`, `git -C`, or `git --no-pager`: those prefixes do not match this allow-list. Other commands cannot obtain approval unattended. Do not substitute plan mode.

This guard stops ordinary unsolicited fixes, but is **not filesystem containment**: allowed Git commands accept write-capable flags such as `--output`. Prohibit those flags in the prompt and check repository status/diff after review. Verify each substantive finding before acting; agreement between models is not proof. Report the target, actual model/effort, confirmed findings, and unresolved limits. Do not turn a clean review into another review automatically.
