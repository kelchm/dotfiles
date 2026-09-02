---
name: delegate-implementation
description: Hand a bounded, clearly-specified implementation task to another agent CLI (Grok, or Claude) to run on an isolated git worktree — migrations, mechanical refactors, spec-driven changes. Use when the work is well-defined enough to delegate and you want the delegate's edits kept off the main checkout until reviewed. Not for taste-sensitive or user-facing code.
---

# Delegate Implementation

Use a delegate for bounded, clearly-specified implementation work you want done outside your own context — migrations, mechanical refactors, spec-driven changes. The delegate works on a separate git worktree, so in normal use its edits land there rather than in the main checkout.

Treat that as a convention, not a jail. A target-directory flag sets where the delegate starts, not where it can write, and an implementation delegate runs autonomously with approvals off. Confirm with `git -C "$REPO_ROOT" status` before you trust that the main checkout is untouched.

Grok is the default implementer for this kind of work. Keep taste-sensitive work — public APIs, UI, copy — off this path; that needs a higher-taste model, and often needs you.

## Workflow

1. Define the bounded task: exact scope, files in play, and the acceptance check (build/test/lint that must pass).
2. Create a git worktree so the delegate can't disturb the main checkout.
3. Create a temporary artifact directory for the prompt and the report.
4. Run the delegate against the worktree with a self-contained prompt.
5. Read the report, review the worktree diff, then create and integrate the task commit yourself before removing the worktree.

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE_PARENT="$(mktemp -d "$(dirname "$REPO_ROOT")/delegate-task.XXXXXX")"
WORKTREE="$WORKTREE_PARENT/worktree"
TASK_BRANCH="delegate/$(basename "$WORKTREE_PARENT")"
ARTIFACT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/delegate-impl.XXXXXX")"
PROMPT="$ARTIFACT_DIR/prompt.md"
REPORT="$ARTIFACT_DIR/report.json"

git -C "$REPO_ROOT" worktree add --detach "$WORKTREE"
git -C "$WORKTREE" switch -c "$TASK_BRANCH"
```

Always isolate with **plain `git worktree add`** plus the delegate's own target-directory flag. Never use a vendor worktree flag: Grok's `-w` / `--worktree` is silently ignored in headless mode — no worktree is created, edits land in the real checkout, and nothing is printed to stderr.

## The delegate must run outside your sandbox

If `CODEX_SANDBOX` is set, every command you spawn inherits a seatbelt profile, and **no delegate CLI can start inside it** — Grok cannot initialize its sandbox or write session state to `~/.grok`, and no combination of writable roots or network settings fixes it. Request escalated permissions for the delegate command, explaining that it needs its own home directory and network. If escalation is refused, report that delegation is unavailable and offer to do the work yourself; the worktree isolation above is what protects the main checkout, and it is unaffected either way.

## Completion contract

Run the delegate from the persistent main session, poll it to completion, and update the user while it is active. A redirected process can be silent for several minutes; do not infer a hang from silence or interrupt it inside the historical ten-minute completion window. Treat an empty report or terminal sentinel such as `Execution error`, `max turns reached`, or `error_max_turns` as failure even when the CLI exits 0. For implementation, success additionally requires the intended worktree diff and acceptance checks; the delegate is not responsible for committing.

## Grok

```bash
XDELEGATE_DEPTH=1 grok --no-auto-update --no-subagents --cwd "$WORKTREE" -m grok-4.5 --output-format json \
  --always-approve --deny "Bash(claude:*)" --deny "Bash(codex:*)" \
  --prompt-file "$PROMPT" > "$REPORT"
```

Use `--prompt-file` rather than `-p` for anything long — it dodges shell quoting entirely. For structured output add `--json-schema '{...}'`, and describe the shape in prose in the prompt too so it survives quoting.

Grok's `--deny` rules match the command string, so they stop a bare `grok`/`claude` but not an absolute path. They are a nudge, not containment — the real recursion guard is the `[skills] ignore` entry in `~/.grok/config.toml` plus the callee line in the prompt below.

## Claude

```bash
ACCEPTANCE_TOOL='Bash(<exact acceptance command>:*)'
( cd "$WORKTREE" && XDELEGATE_DEPTH=1 claude -p --no-session-persistence --model fable \
    --safe-mode --strict-mcp-config \
    --permission-mode acceptEdits \
    --disallowed-tools "Bash(claude:*)" "Bash(grok:*)" "Bash(codex:*)" \
    --allowed-tools "$ACCEPTANCE_TOOL" \
    < "$PROMPT" > "$REPORT" )
```

Claude has no target-directory flag — set the process working directory to the worktree, as the subshell above does. The `Bash(...)` denies hold even under `acceptEdits`: a callee reported both delegate commands as permission-denied and did not route around them.

Safe mode removes user/project hooks, plugins, MCP servers, skills, and settings from the delegated process. Keep the recursion prohibition in the prompt because safe mode also disables discovery of the global rule. `acceptEdits` does not approve shell commands, so explicitly allow the exact acceptance command named in the prompt; add one narrow `Bash(...)` rule per command when the check genuinely requires several commands.

## Implementation prompt

Keep it tight and self-contained — the delegate does not see your conversation:

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

## Parallel delegates

Give each one its own worktree, or their edits collide. One `git worktree add` per task, one target-directory flag per invocation.

## Reporting back

Review the worktree diff yourself before integrating — this path is autonomous and runs with approvals disabled. Confirm every changed file is intended and rerun the acceptance check. Then stage only those files, create the task commit in the delegate worktree, and integrate that verified commit into the target checkout.

Only after integration succeeds, clean up with `git -C "$REPO_ROOT" worktree remove "$WORKTREE" && rmdir "$WORKTREE_PARENT"`; the task branch stays as a recovery point until you delete it deliberately. If integration fails, leave the worktree in place and export a complete patch before deciding how to recover.

Summarize what actually changed, call out anything risky, and run the acceptance check in the main checkout after merge. If the delegate's changes miss the bar, redo the work with a higher-taste model rather than polishing its output.

If the delegate CLI isn't installed, isn't authenticated, or the command fails, report the error and offer to do the implementation yourself instead.
