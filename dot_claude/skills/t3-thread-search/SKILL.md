---
name: t3-thread-search
description: >
  Find T3 Code threads by title, thread ID, T3 thread URL, environmentId, user or assistant
  message text, project, provider ID, or date. Searches local state.sqlite and can merge
  remote environments. Canonical identity is (environmentId, threadId). Use for recovering
  archived conversations, looking up UUIDs or https://app.t3.codes/<env>/<thread> URLs,
  command-palette search, and remote/multi-environment lookup. Use when the user runs
  /t3-thread-search or /find-t3-thread.
---

# T3 thread search (Claude adapter)

Canonical skill: `~/.agents/skills/t3-thread-search/`.

Claude Code's user tree does not read `~/.agents/skills/`. Load that SKILL.md and run its helper. Do not copy or rewrite the implementation here.

```bash
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread-search" [query] [flags]
```

If `python3` is missing: `python`, then `mise -C "$HOME/.agents/skills/t3-thread-search" exec -- python3 scripts/t3-thread-search ...`.
