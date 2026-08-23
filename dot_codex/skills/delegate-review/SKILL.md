---
name: delegate-review
description: Ask another agent CLI (Grok, or Claude) for an independent read-only code review of uncommitted changes, a branch diff, a commit, or a GitHub PR. Use when the user wants a second-pass review, or when a change is broad or risky enough that a separate model's perspective is worth it. The delegate reviews only — it never edits.
---

# Delegate Review

Reach for a different model when the user wants a second opinion, or when a diff is broad enough that independent eyes help. A model reviewing its own output is a weak check, so prefer a delegate whose vendor differs from whoever wrote the code.

Grok is the default reviewer. Use Claude when the change is taste-sensitive — public API shape, UI, or user-facing copy.

## Workflow

1. Identify the review target: uncommitted changes, a branch, a commit, or a PR.
2. Create a temporary artifact directory for the prompt and the report.
3. Run the delegate under its read-only guard.
4. Read the report and verify important claims against the code before relaying them.

```bash
ARTIFACT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/delegate-review.XXXXXX")"
PROMPT="$ARTIFACT_DIR/prompt.md"
REPORT="$ARTIFACT_DIR/report.json"
```

Artifacts are scratch output and belong in `$TMPDIR`. This is the one place the temp hierarchy is fine — never put a *containment canary* there, because Grok's read-only sandbox leaves it writable.

## The delegate must run outside your sandbox

If `CODEX_SANDBOX` is set, every command you spawn inherits a seatbelt profile, and **no delegate CLI can start inside it**. Grok either refuses to run because its own sandbox cannot initialize (`Operation not permitted`) or cannot write its session state to `~/.grok` (`FS_PERMISSION_DENIED`). Adding writable roots or re-enabling network does not help; there is no configuration that makes nesting work.

Request escalated permissions for the delegate command, and say why: the delegate needs its own home directory and network access, and it carries its own read-only guard. If escalation is refused, do not silently downgrade the guard — report that the delegation is unavailable and offer to do the review yourself.

## Grok

Grok ships a bundled `/review` skill that works headless, takes **no prompt**, and collects the diff itself. It is the closest analogue to `codex exec review`, so don't hand-roll diff materialization.

```bash
# --local (uncommitted) | --branch <name> | --pr <number-or-url>
XDELEGATE_DEPTH=1 grok --no-auto-update --cwd "$PWD" -m grok-4.5 --output-format json \
  --always-approve --sandbox read-only \
  --deny "Edit($PWD/**)" --deny "Write($PWD/**)" -p '/review --local' > "$REPORT"
```

The reply is JSON with the report in `.text`; `/review` also writes a notes file under `$TMPDIR` whose path it prints. PR mode only *stages* a pending GitHub review for the user to submit.

When the review needs a specific stance, `/review` can't take one — drive Grok directly with `--prompt-file "$PROMPT"` instead of `-p '/review ...'`, naming the target in the prompt and letting Grok collect the diff itself.

Keep the denies scoped to the repo. A blanket `Write(**)` blocks `/review` from writing its own notes file and breaks the run, and denying `Bash` removes the shell it needs to read the diff. Do **not** reach for `--tools` / `--disallowed-tools`: one unrecognized name silently restores the entire toolset with exit 0 and no warning. `--deny` fails closed with a hard error instead.

Grok's `--sandbox read-only` is not equivalent to `codex -s read-only` — it leaves `/tmp`, `/var/tmp`, `/var/folders` and `~/.grok` writable and can go unenforced on unsupported kernels. Treat it as defense-in-depth; the `--deny` rules carry the guarantee.

## Claude

Claude has no review subcommand. Give it a review-stance prompt under an explicit allow-list, which is what makes the run read-only.

```bash
XDELEGATE_DEPTH=1 claude -p --no-session-persistence --model fable \
  --permission-mode manual \
  --disallowed-tools Edit Write NotebookEdit Task \
  --allowed-tools "Read" "Grep" "Glob" "Bash(git status:*)" "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" \
  < "$PROMPT" > "$REPORT"
```

Claude has no target-directory flag — it inherits the process working directory, so run it with the cwd already set to the repo.

`--permission-mode manual` plus the allow-list is the guard: anything outside the list needs an approval that non-interactive mode can never grant, so it fails closed without hanging. Verified: `git` reads succeed while the edit tool, shell redirection, a python interpreter, a subagent, and writes outside the repo are all blocked. Do not substitute `--permission-mode plan` — it restricts writes only behaviorally, leaving the shell in place.

For a machine-readable report add `--output-format json --json-schema '<schema>'`; the validated object comes back at `.structured_output`.

## Review prompt

```text
You are the callee in a delegated task. Do not delegate any part of this work to another agent CLI.

Review <target> for bugs, regressions, missing tests, security issues, and requirement mismatches.

Prioritize findings over summary. For each finding include:
- severity
- file and line reference
- concrete failure mode
- suggested fix direction

Do not edit anything. Report at most 8 findings and keep each field short. If there are no substantive findings, say so and name any residual test gaps.
```

Cap the findings — long responses can cancel mid-generation. Add task-specific context when useful: requirements, risky areas, expected behavior, or files you are unsure about.

## Reporting back

Before relaying a finding, inspect the cited code or diff enough to decide whether it is real. Separate confirmed issues from suggestions you did not verify.

If the delegate finds nothing, say so clearly and name the target it inspected — don't silently re-run.

If the delegate CLI isn't installed, isn't authenticated, or the command fails, report the error and offer to review the changes yourself instead.
