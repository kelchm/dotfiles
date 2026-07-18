---
name: grok-review
description: >-
  Ask the Grok CLI (grok-4.5) for an independent, read-only code review of
  uncommitted changes, a branch diff, a single commit, or specific files. Use
  when the user wants a second-pass review, or when a change is broad or risky
  enough that a separate model's perspective is worth it. Grok reviews only —
  it runs read-only and never edits.
---

# Grok Review

Grok is an independent reviewer — reach for it when the user wants a second opinion, or when a diff is broad enough that another model's eyes help. It runs read-only: it can read and grep the repo but cannot write or reach the network.

## Workflow

1. Identify the review target: uncommitted changes, current branch vs a base, a commit SHA, a PR checkout, or specific files.
2. Create a temporary artifact directory for the prompt and Grok's report.
3. Compose `$PROMPT` from the Review Prompt stance (below) plus the diff for the target, then run Grok read-only.
4. Read Grok's report and verify important claims against the code before presenting them.

Use one of these command shapes:

```bash
ARTIFACT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/grok-review.XXXXXX")"
REPORT="$ARTIFACT_DIR/report.md"
PROMPT="$ARTIFACT_DIR/prompt.md"

# Write the ## Review Prompt stance into $PROMPT, then append the target diff.
# (Claude writes the stance; uncomment the diff line matching the target.)
{
  echo; echo '--- CHANGES ---'
  git --no-pager diff HEAD            # uncommitted (staged + unstaged)
  # git --no-pager diff main...HEAD   # current branch vs a base
  # git --no-pager show <sha>         # a single commit
} >> "$PROMPT"

grok --no-auto-update --cwd "$PWD" \
  -m grok-4.5 --output-format json \
  --sandbox read-only --always-approve \
  -p "$(cat "$PROMPT")" > "$REPORT"
```

`--sandbox read-only` is what makes this a review: Grok can read and run read-only commands but physically can't write or hit the network. `--always-approve` only stops it hanging on a tool prompt. Grok has no dedicated `review` subcommand, so the read-only stance lives in the sandbox flag and the prompt, not a CLI verb.

## Review Prompt

Give Grok a plain code-review stance — don't prompt it the way you'd prompt yourself:

```text
Review these changes for bugs, regressions, missing tests, security issues, and requirement mismatches.

Prioritize findings over summary. For each finding include:
- severity
- file and line reference
- concrete failure mode
- suggested fix direction

Do not edit anything. If there are no substantive findings, say so and name any residual test gaps.
```

Add task-specific context when useful: requirements, risky areas, expected behavior, relevant tests, or files you're unsure about.

## Reporting back

Before relaying a Grok finding, inspect the cited code or diff enough to decide whether it's real. In the response to the user, separate confirmed issues from Grok suggestions you did not verify.

If Grok finds nothing, say that clearly and name the review target it inspected — don't silently re-run.

If `grok` isn't installed, isn't authenticated, or the command fails, report the error and offer to review the changes yourself instead.
