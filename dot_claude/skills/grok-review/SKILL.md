---
name: grok-review
description: Ask the Grok CLI (grok-4.5) for an independent, read-only code review of uncommitted changes, a branch diff, or a GitHub PR. Use when the user wants a second-pass review, or when a change is broad or risky enough that a separate model's perspective is worth it. Grok reviews only — it never edits.
---

# Grok Review

> **If you are Grok reading this, stop.** Grok discovers `~/.claude/skills/` natively, so this Claude-side skill is visible to you, and following it would mean invoking Grok from Grok. You are the callee: do the review yourself and do not shell out to another agent CLI. The same applies if `XDELEGATE_DEPTH` is set in your environment.

Grok is an independent reviewer — reach for it when the user wants a second opinion, or when a diff is broad enough that another model's eyes help.

Drive Grok directly with a review prompt and let it collect the target diff. Do not invoke Grok's bundled `/review` skill: current versions try to spawn an internal reviewer, which conflicts with the delegation recursion guard. Older successful runs only worked because Grok improvised a second CLI invocation after that spawn was denied.

## Execution placement

Run the CLI from the persistent main session and let it reach a terminal state. Redirected calls can be silent for several minutes, and historical successful reviews have taken more than ten minutes; silence is not evidence of a hang. Poll the process and update the user rather than interrupting it. Treat an empty or invalid JSON report, `Execution error`, `max turns reached`, or `error_max_turns` as failure even when the CLI exits 0.

## Workflow

1. Identify the review target: uncommitted changes, a branch, or a GitHub PR.
2. Put the review stance and target in a prompt file, then run Grok directly with the guard below.
3. Read Grok's report and verify important claims against the code before presenting them.

```bash
ARTIFACT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/grok-review.XXXXXX")"
PROMPT="$ARTIFACT_DIR/prompt.md"
REPORT="$ARTIFACT_DIR/report.json"

XDELEGATE_DEPTH=1 grok --no-auto-update --no-subagents --cwd "$PWD" -m grok-4.5 --output-format json --always-approve \
  --sandbox read-only --deny "Edit($PWD/**)" --deny "Write($PWD/**)" \
  --prompt-file "$PROMPT" > "$REPORT"
```

The reply is JSON with the report in `.text`. `--no-subagents` disables the nested-review path in current Grok versions; keep the callee declaration in the prompt as the cross-CLI recursion guard.

```text
You are the callee in a delegated task. Do not delegate any part of this review to another agent CLI.

Review <target — e.g. the uncommitted changes in this repo> for bugs, regressions, missing tests, security issues, and requirement mismatches.

Prioritize findings over summary. For each finding include:
- severity
- file and line reference
- concrete failure mode
- suggested fix direction

Do not edit anything. Report at most 8 findings and keep each field short. If there are no substantive findings, say so and name any residual test gaps.
```

Cap the findings — long responses can cancel mid-generation.

## Keeping it read-only

`--sandbox read-only` plus repo-scoped `--deny` rules is the seatbelt. Grok is cooperative, not adversarial — the realistic failure is it *helpfully* editing a file mid-review, and these rules stop the tools it would use. Anything that slipped through would still be visible in `git status` and revertible.

- Scope the denies to the repo (`Edit($PWD/**)`, not `Edit(**)`).
- Leave the shell available so Grok can inspect the target; denying `Bash` would require hand-rolling diff and file context.
- Grok's `--sandbox read-only` leaves `/tmp`, `/var/tmp`, `/var/folders` and `~/.grok` writable and can go unenforced on unsupported kernels, so it is not equivalent to codex's `-s read-only`. Treat it as defense-in-depth, not a guarantee.

Do **not** reach for `--tools` / `--disallowed-tools`: both silently restore the full toolset if any name in the list is unrecognized, and the documented tool names are wrong. `--deny` fails closed with a hard error instead.

## Reporting back

Before relaying a Grok finding, inspect the cited code or diff enough to decide whether it's real. In the response to the user, separate confirmed issues from Grok suggestions you did not verify.

If Grok finds nothing, say that clearly and name the review target it inspected — don't silently re-run.

If `grok` isn't installed, isn't authenticated, or the command fails, report the error and offer to review the changes yourself instead.
