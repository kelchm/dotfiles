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

## Completion contract

Run the delegate from the persistent main session and let the process reach a terminal state. Redirected headless calls can be completely silent for several minutes; silence is not evidence of a hang. Historical successful reviews have taken more than ten minutes, so do not impose a shorter timeout or interrupt a live process merely to regain the turn. Poll the running process and send the user a progress update instead.

Treat the report body, not the process exit code, as the result. Exit 0 is still a failure when the report is empty, is not valid JSON when JSON was requested, or contains a terminal sentinel such as `Execution error`, `max turns reached`, or `error_max_turns`. Preserve the artifact and report the failure directly.

## The delegate must run outside your sandbox

If `CODEX_SANDBOX` is set, every command you spawn inherits a seatbelt profile, and **no delegate CLI can start inside it**. Grok either refuses to run because its own sandbox cannot initialize (`Operation not permitted`) or cannot write its session state to `~/.grok` (`FS_PERMISSION_DENIED`). Adding writable roots or re-enabling network does not help; there is no configuration that makes nesting work.

Request escalated permissions for the delegate command, and say why: the delegate needs its own home directory and network access, and it carries its own read-only guard. If escalation is refused, do not silently downgrade the guard — report that the delegation is unavailable and offer to do the review yourself.

## Grok

Drive Grok directly with a review prompt and let it collect the target diff. Do not invoke Grok's bundled `/review` skill: current versions try to spawn an internal reviewer, which conflicts with the delegation recursion guard. Older successful runs only worked because Grok improvised a second CLI invocation after that spawn was denied.

```bash
# Name the target in $PROMPT: uncommitted changes, <base>...HEAD, a commit, or a PR.
XDELEGATE_DEPTH=1 grok --no-auto-update --no-subagents --cwd "$PWD" -m grok-4.5 --output-format json \
  --always-approve --sandbox read-only \
  --deny "Edit($PWD/**)" --deny "Write($PWD/**)" \
  --prompt-file "$PROMPT" > "$REPORT"
```

The reply is JSON with the report in `.text`. `--no-subagents` is required even with `XDELEGATE_DEPTH=1`: the environment marker and prompt govern cooperative behavior, while the CLI flag disables the failure-prone nested-review path in current Grok versions.

Keep the denies scoped to the repo. Denying `Bash` removes the shell Grok needs to inspect the target. Do **not** reach for `--tools` / `--disallowed-tools`: one unrecognized name silently restores the entire toolset with exit 0 and no warning. `--deny` fails closed with a hard error instead.

Grok's `--sandbox read-only` is not equivalent to `codex -s read-only` — it leaves `/tmp`, `/var/tmp`, `/var/folders` and `~/.grok` writable and can go unenforced on unsupported kernels. Treat it as defense-in-depth; the `--deny` rules carry the guarantee.

## Claude

Claude has no review subcommand. Give it a review-stance prompt under an explicit allow-list, which is what makes the run read-only.

```bash
XDELEGATE_DEPTH=1 claude -p --no-session-persistence --model fable \
  --safe-mode --strict-mcp-config \
  --permission-mode manual \
  --disallowed-tools Edit Write NotebookEdit Task \
  --allowed-tools "Read" "Grep" "Glob" "Bash(git status:*)" "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" \
  < "$PROMPT" > "$REPORT"
```

Claude has no target-directory flag — it inherits the process working directory, so run it with the cwd already set to the repo.

`--safe-mode --strict-mcp-config` prevents unrelated user/project hooks, plugins, MCP servers, skills, and settings from entering the delegated run. The callee declaration therefore must remain in the prompt; safe mode deliberately disables discovery of the global recursion rule.

Claude's Bash allow-list matches the command prefix literally. Tell the reviewer to use plain `git status`, `git diff`, `git log`, and `git show` forms, without `git -C` or `git --no-pager` before the verb; those prefixed forms require approval and cannot proceed non-interactively.

`--permission-mode manual` plus the allow-list is the guard: anything outside the list needs an approval that non-interactive mode can never grant, so it fails closed without hanging. Verified: `git` reads succeed while the edit tool, shell redirection, a python interpreter, a subagent, and writes outside the repo are all blocked. Do not substitute `--permission-mode plan` — it restricts writes only behaviorally, leaving the shell in place.

This stops a reviewer from *helpfully* editing what it found, which is the realistic failure. It is not containment: `Bash(git diff:*)` is a prefix match, and `git diff --output=PATH` writes an arbitrary file — confirmed, including outside the repo. `git log` and `git show` take `--output=` too. Don't describe this guard as read-only, and don't rely on it against anything but ordinary helpfulness.

For a machine-readable report add `--output-format json --json-schema '<schema>'`; the validated object comes back at `.structured_output`.

## Review prompt

```text
You are the callee in a delegated task. Do not delegate any part of this work to another agent CLI.

Review <target> for bugs, regressions, missing tests, security issues, and requirement mismatches.

For repository inspection, use only plain git status, git diff, git log, and git show forms. Do not prefix them with git -C or git --no-pager.

Prioritize findings over summary. For each finding include:
- severity
- file and line reference
- concrete failure mode
- suggested fix direction

Do not edit anything. Report at most 8 findings and keep each field short. If there are no substantive findings, say so and name any residual test gaps.
```

Cap the findings — long responses can cancel mid-generation. Add task-specific context when useful: requirements, risky areas, expected behavior, or files you are unsure about.

## Reporting back

Before relaying a finding, inspect the cited code or diff enough to decide whether it is real.
Separate confirmed issues from suggestions you did not verify.

The delegate's report is evidence, not authority. Give the acting agent's own verdict, including
where it disagrees with the reviewer or prefers a smaller fix. Show the concrete finding and why it
matters before recommending action; do not hide an unexplained concern behind the delegate's name.
Agreement between models is not proof.

For example, an independent review correctly found that a recovery command would not inherit the
volume mounts it needed, so the acting agent replaced the procedure. The same review proposed an
egress restriction that would not prevent the claimed exfiltration, so the agent rejected that fix
and documented the boundary the policy actually provided. Useful review retained both judgments.

If the delegate finds nothing, say so clearly and name the target it inspected — don't silently re-run.

If the delegate CLI isn't installed, isn't authenticated, or the command fails, report the error and offer to review the changes yourself instead.
