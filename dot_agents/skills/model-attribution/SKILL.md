---
name: model-attribution
description: >
  Append model-attribution footers or commit trailers when creating or editing issues, PRs, comments, or commit messages on the user's behalf. Use for the user's own repositories; skip in others' projects unless asked.
---

# Model attribution

When you write an issue, PR, comment, or commit message on the user's behalf, append attribution metadata so the artifact records which model and harness produced it. This skill is the habit layer only: no scripts, no hooks, nothing to run. Every value is resolved from the current runtime; a value that cannot be resolved is omitted, never invented.

## Resolve values first

Before formatting, resolve each value from harness context:

- `model` — the exact runtime model ID, never a marketing name. If it is unknown, ask the user before writing any footer.
- `thread` — the bare T3 thread UUID, no URL. If it is not known, omit the `thread:` line; never fabricate an ID.
- `agent` — the harness name as the runtime reports it, including any wrapper (for example a T3 Code session running on OpenCode).
- `date` — today in ISO 8601. The default formats below print no date; add one only when the user asks or a repo's attribution section calls for it.

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

Comment in a thread — one visible line plus the same hidden block, both at the end:

```
<sub>model: <id> · agent: <harness></sub>

<!-- attribution
model: <id>
agent: <harness>
role: authored
thread: <uuid>
-->
```

Model quote inside a human comment — put the attribution line on the quote block itself, directly beneath it; the surrounding human text stays unannotated:

```
> <quoted model statement>

<sub>model: <id> · agent: <harness></sub>
```

PR body — the hidden block, plus the two trailers listed inside it for reuse at squash-merge:

```
<!-- attribution
model: <id>
agent: <harness>
role: authored
thread: <uuid>
trailers:
Co-Authored-By: <model> <noreply@vendor>
X-Generated-With: <harness> (<id>)
-->
```

Commit — the same two trailers as the last lines of the message:

```
<subject and body>

Co-Authored-By: <model> <noreply@vendor>
X-Generated-With: <harness> (<id>)
```

In `Co-Authored-By: <model> <noreply@vendor>`, `<model>` is the resolved model ID and `<vendor>` is that model vendor's noreply domain — ask rather than guess if unknown.

The footer is always truly last: nothing after it. In a commit, the trailers are literally the final lines. When editing an artifact that already carries a footer, update it in place and keep it last.

## Context policy

- Public repos: drop the `thread:` line everywhere — a session UUID is a private-session leak. The rest of the footer stays.
- Others' projects: do not annotate unless asked, regardless of what the defaults say.
- Delegated subagents (Codex, Grok, and similar): each callee annotates with its own model ID and harness, not the caller's. Delegation prompts must invoke this skill so the callee resolves its own values.
- A repo may keep its own attribution section in AGENTS.md. It wins over the formats above.

## Precedence

1. The user's explicit skip — always wins.
2. The repo's AGENTS.md attribution section — may override format, fields, or visibility.
3. This skill's defaults.

## Pre-submit self-check

Before submitting, verify:

- The footer is the last content — nothing follows it.
- No template placeholders remain: every `<...>` was replaced with a resolved value or its line was omitted.
- Every value was resolved from context or omitted; none invented.
- No emoji anywhere in the footer; no vendor links.
