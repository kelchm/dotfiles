---
name: codex-review
description: >-
  Ask the Codex CLI (gpt-5.6-sol) for an independent code review of uncommitted
  changes, a branch diff, a commit, or a specific implementation. Use Codex as
  an independent reviewer when the user wants a second-pass review, or when a
  change is broad enough that another agent's perspective is useful. Codex
  reviews only — it does not edit.
---

# Codex Review

Codex (gpt-5.6-sol) is an independent reviewer. Reach for it when the user wants a second-pass review, or when a change is broad enough that a separate model's perspective helps.

## Execution placement

Run the CLI from the persistent main session and let it reach a terminal state. Redirected calls can be silent for several minutes; poll the process and update the user rather than interrupting it. Historical successful cross-harness reviews have taken more than ten minutes, so silence is not evidence of a hang. Treat an empty report or terminal sentinel such as `Execution error`, `max turns reached`, or `error_max_turns` as failure even when the CLI exits 0.

## Workflow

1. Identify the review target: uncommitted changes, base branch, commit SHA, PR checkout, or specific files.
2. Create a temporary artifact directory for the Codex report.
3. Run `codex review` with a focused review prompt.
4. Read Codex's report and verify important claims against the code before presenting them.

Use one of these command shapes:

```bash
ARTIFACT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/codex-review.XXXXXX")"
REPORT="$ARTIFACT_DIR/report.md"
PROMPT="$ARTIFACT_DIR/prompt.md"

# Review staged, unstaged, and untracked changes.
XDELEGATE_DEPTH=1 codex -C "$PWD" exec -s read-only review -m gpt-5.6-sol --uncommitted < /dev/null > "$REPORT"

# Review current branch against a base branch.
XDELEGATE_DEPTH=1 codex -C "$PWD" exec -s read-only review -m gpt-5.6-sol --base main < /dev/null > "$REPORT"

# Review a single commit.
XDELEGATE_DEPTH=1 codex -C "$PWD" exec -s read-only review -m gpt-5.6-sol --commit <sha> < /dev/null > "$REPORT"

# Custom review stance. Name the target in the prompt — target flags and a
# prompt are mutually exclusive, and passing both exits 2 without running.
XDELEGATE_DEPTH=1 codex -C "$PWD" exec -s read-only review -m gpt-5.6-sol - < "$PROMPT" > "$REPORT"
```

A target flag and `[PROMPT]` cannot be combined: `error: the argument '--base <BRANCH>' cannot be used with '[PROMPT]'`. Pick one. With no target flag, `review` defaults to the uncommitted changes, so say which target you mean inside the prompt when you need a stance. Flag-only reviews rely on `XDELEGATE_DEPTH=1` plus the global recursion rule because they cannot also carry a custom callee prompt.

## Review Prompt

Ask Codex to use a code-review stance:

```text
You are the callee in a delegated task. Do not delegate any part of this work to another agent CLI.

Review these changes for bugs, regressions, missing tests, security issues, and requirement mismatches.

Prioritize findings over summary. For each finding include:
- severity
- file and line reference
- concrete failure mode
- suggested fix direction

Do not edit files. If there are no substantive findings, say so and name any residual test gaps.
```

Add task-specific context when useful: requirements, risky areas, expected behavior, relevant tests, or files Claude is unsure about.

## Reporting Back

Before relaying a Codex finding, inspect the cited code or diff enough to decide whether the finding is real. In the user-facing response, separate confirmed issues from Codex suggestions you did not verify.

If Codex finds nothing, say that clearly and mention what review target it inspected.

If `codex` is not installed or the command fails, report the error and offer to review the changes directly instead.
