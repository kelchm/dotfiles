---
name: model-attribution
description: >
  Append model-attribution footers or commit trailers to issues, PRs, comments, and commit messages written on the user's behalf. Use proactively before creating or editing any of these in the user's own repositories, even when attribution is not mentioned, and when quoting model output in a comment. Skip in others' projects unless asked.
---

# Model attribution

When you write an issue, PR, comment, or commit message on the user's behalf, append attribution metadata so the artifact records which model and harness produced it. This skill is the habit layer only: no scripts, no hooks, nothing to run. Every value is resolved from the current runtime; an optional value that cannot be resolved is omitted, never invented.

## Resolve values first

Before formatting, resolve each value from harness context:

- `model` — the exact runtime model ID, never a marketing name. If unknown, ask the user; if you cannot ask (delegated or non-interactive run), write no footer and say so in your report.
- `thread` — the bare T3 thread UUID, no URL. If it is not known, omit the `thread:` line; never fabricate an ID. A non-T3 session ID is not a substitute.
- `agent` — the harness name as the runtime reports it, for example `opencode`.
- `date` — today in ISO 8601. Not printed by default; add it only when the user asks or the repo's attribution section calls for it.

The role is always `authored` unless the user says otherwise. Never self-assign a different role.

## Format by artifact

Issue body (agent-authored) — hidden-only HTML comment as the last lines:

```
<!-- attribution
model: <id>
agent: <harness>
role: authored
thread: <uuid>
-->
```

Comment in a thread — one visible line plus the same hidden block, both at the end (this includes PR review comments and inline comments):

```
<sub>model: <id> · agent: <harness></sub>

<!-- attribution
model: <id>
agent: <harness>
role: authored
thread: <uuid>
-->
```

Model quote inside a comment the user wrote or dictated — put the attribution line directly beneath the quote block; the surrounding human text stays unannotated:

```
> <quoted model statement>

<sub>model: <id> · agent: <harness></sub>
```

PR body — the hidden block:

```
<!-- attribution
model: <id>
agent: <harness>
role: authored
thread: <uuid>
-->
```

Commit — the same two trailers as the last lines of the message:

```
<subject and body>

Co-Authored-By: <model> <noreply@vendor>
X-Generated-With: <harness> (<id>)
```

In `Co-Authored-By: <model> <noreply@vendor>`, `<model>` is the resolved model ID and `<noreply@vendor>` is that model vendor's noreply domain — ask rather than guess if unknown; if you cannot ask, omit the `Co-Authored-By` trailer.

The footer is always truly last: nothing after it. In a commit, the trailers are literally the final lines. When editing an artifact that already carries a footer, update it in place and keep it last. Do not add a footer to an artifact a human wrote; editing it does not make it agent-authored.

These footers replace any attribution the harness would add by default (marketing-name `Co-Authored-By`, "Generated with" lines); never emit both.

## Context policy

- Public repos: drop the `thread:` line everywhere — a session UUID is a private-session leak. The rest of the footer stays. If you have not confirmed the repo is private, treat it as public.
- Others' projects: follow that project's own AI-disclosure policy if it has one; otherwise do not annotate unless asked.
- Delegated subagents (Codex, Grok, and similar): a callee that writes an artifact itself uses its own model ID and harness; tell it in the delegation prompt to apply this skill. When the caller commits a callee's work, the commit carries the callee's model in `Co-Authored-By`.

## Precedence

1. The user's explicit skip — always wins.
2. The repo's AGENTS.md attribution section — may override format, fields, or visibility, or turn attribution off.
3. This skill's defaults.

## Pre-submit self-check

Before submitting, verify:

- The footer is the last content — nothing follows it.
- No placeholder text remains (`<id>`, `<model>`, `<harness>`, `<uuid>`, `vendor`, `<subject and body>`). The `<sub>` tags, the comment markers, and the angle brackets around the email are literal.
- Every value was resolved from context or omitted; none invented.
- No emoji anywhere in the footer; no vendor links.
