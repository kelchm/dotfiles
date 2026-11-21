---
name: harness-memory
description: Sort what a coding harness saved in its own memory (Claude auto-memory, Grok memory) into reviewed files in the project's repo, or into the dotfiles for cross-project preferences. Use when harness memory turns up, or when asked to sort, migrate, clean up or empty memory, or to move memory notes into a repo.
---

# Harness memory

Harness memory belongs to one machine, often to one checkout path, and other harnesses can't see it. Sorting moves what is worth keeping into reviewed files and drops the rest.

## Find every store for the project

Each machine keeps its own stores, so check every machine the project was worked on.

- **Claude:** `~/.claude/projects/<path>/memory/`, where `<path>` is the checkout's path with `/` and `.` turned into `-`. A project can have several: one for each path its checkout has had, and one for each session run outside the repo, such as a T3 scratch folder. Match on the project's name, not only its current path. `MEMORY.md` is only an index.
- **Grok:** `~/.grok/memory-v2/workspaces/<name>-<hash>/`, shared by clones and worktrees. Read `topics/` and the unconsolidated `observations/_inbox/`; leave `MEMORY.md` and the database files alone. Older notes can remain under `~/.grok/memory/`, and `~/.grok/memory-v2/global/` holds cross-project notes.
- **Codex:** `~/.codex/memories/`, if its `memories` feature was ever on.

## Sort

1. Read every note against the repo's current docs, `AGENTS.md` and code, and check who can read each destination (`gh repo view --json visibility`).
2. Propose a verdict for each: move it to the narrowest place it applies (the repo's docs, its workspace repo's docs, or the shared instructions or a skill in `kelchm/dotfiles`), already covered (cite where), belongs to another repo, or stale and dropped. A note can split across verdicts.
3. Show the user each note in full beside its verdict, one batch at a time, and wait for their decisions before the next.
4. Write what they keep as one reviewed PR, following the two rules below.
5. After the PR merges, and only when the user says so, delete the notes you sorted and their lines in Claude's `MEMORY.md`. Grok rebuilds its own index.

## Writing it up

**Reframe, don't paste.** Memory records what happened; docs state what is true now. Check each fact you keep against the current repo, since memory goes stale, then write it as a present-tense statement in the destination's voice, without dates, quotes, session IDs or who said what. Keep a reason only when it would change a decision.

**Mind who can read it.** Personal or private details go into a public repo only with the user's explicit confirmation of each one: names, quotes, private repos and hosts, internal addresses, unpublished findings. Otherwise leave them out, or put them in a private repo the user names. A pushed commit stays in history even after it's reverted.
