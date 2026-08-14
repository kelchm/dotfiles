---
name: grok-review
description: Ask the Grok CLI (grok-4.5) for an independent, read-only code review of uncommitted changes, a branch diff, or a GitHub PR. Use when the user wants a second-pass review, or when a change is broad or risky enough that a separate model's perspective is worth it. Grok reviews only — it never edits.
---

# Grok Review

Grok is an independent reviewer — reach for it when the user wants a second opinion, or when a diff is broad enough that another model's eyes help.

Grok ships a bundled `/review` skill that works headless and is the closest analogue to `codex review`. It collects the diff itself, so don't hand-roll diff materialization.

## Workflow

1. Identify the review target: uncommitted changes, a branch, or a GitHub PR.
2. Run `/review` in the matching mode with the guard below.
3. Read Grok's report and verify important claims against the code before presenting them.

```bash
# Uncommitted changes (staged + unstaged + untracked).
grok --no-auto-update --cwd "$PWD" -m grok-4.5 --output-format json --always-approve \
  --sandbox read-only --deny "Edit($PWD/**)" --deny "Write($PWD/**)" -p '/review --local'

# A branch against its merge-base with the default base branch.
grok --no-auto-update --cwd "$PWD" -m grok-4.5 --output-format json --always-approve \
  --sandbox read-only --deny "Edit($PWD/**)" --deny "Write($PWD/**)" -p '/review --branch <name>'

# A GitHub PR. Posts findings as a PENDING review for the user to submit.
grok --no-auto-update --cwd "$PWD" -m grok-4.5 --output-format json --always-approve \
  --sandbox read-only --deny "Edit($PWD/**)" --deny "Write($PWD/**)" -p '/review --pr <number-or-url>'
```

The reply is JSON; the report is in `.text`, and `/review` also writes a notes file under `$TMPDIR` whose path it prints. PR mode only *stages* a pending review — the user submits it through GitHub.

## Custom review stance

`/review` accepts no prompt, so when the review needs a specific focus (a named risk, a requirement to check against, particular files), drive Grok directly. Grok still has the shell, so let it collect the diff itself — just tell it the target:

```bash
ARTIFACT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/grok-review.XXXXXX")"
PROMPT="$ARTIFACT_DIR/prompt.md"   # stance below + "review the uncommitted changes" / "review <base>...HEAD"
REPORT="$ARTIFACT_DIR/report.json"

grok --no-auto-update --cwd "$PWD" -m grok-4.5 --output-format json --always-approve \
  --sandbox read-only --deny "Edit($PWD/**)" --deny "Write($PWD/**)" \
  --prompt-file "$PROMPT" > "$REPORT"
```

```text
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

- Scope the denies to the repo (`Edit($PWD/**)`, not `Edit(**)`). A blanket `Write(**)` blocks `/review` from writing its own notes file and breaks the run.
- Leave the shell available. `/review` needs it to collect the diff, and denying `Bash` means hand-rolling diff materialization for no real gain.
- Grok's `--sandbox read-only` leaves `/tmp`, `/var/tmp`, `/var/folders` and `~/.grok` writable and can go unenforced on unsupported kernels, so it is not equivalent to codex's `-s read-only`. Treat it as defense-in-depth, not a guarantee.

Do **not** reach for `--tools` / `--disallowed-tools`: both silently restore the full toolset if any name in the list is unrecognized, and the documented tool names are wrong. `--deny` fails closed with a hard error instead.

## Reporting back

Before relaying a Grok finding, inspect the cited code or diff enough to decide whether it's real. In the response to the user, separate confirmed issues from Grok suggestions you did not verify.

If Grok finds nothing, say that clearly and name the review target it inspected — don't silently re-run.

If `grok` isn't installed, isn't authenticated, or the command fails, report the error and offer to review the changes yourself instead.
