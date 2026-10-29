---
name: t3-thread-search
description: >
  Last-resort local recovery for T3 Code: search archived message text and PR links,
  find retained deleted-thread records, list archived or deleted threads bound to a
  checkout or worktree path, or map provider thread/session/native IDs to T3 thread
  IDs. Use only for these gaps in native functionality.
---

# T3 thread recovery

Use native T3 functionality first. `t3_thread_search` handles ordinary active-thread and PR lookup; `t3_thread_list` handles project inventory, including subagents. Settings → Archived threads browses archives across connected environments. `t3_thread_read` opens a known archived ID and provides conversation and execution state. This skill adds only:

- Searching archived content and recorded PR links without unarchiving threads.
- Finding whatever metadata and indexed messages remain for deleted threads, which native reads reject.
- Mapping an exact provider thread/session/native ID to its T3 thread ID, including active threads.
- Listing the archived (and, with `--include-deleted`, deleted) threads bound to a checkout or worktree path. Native project listings return active threads only, so moves and retirements need this to see every binding.

Inside a thread, native search without `projectId` (including `projectId: null`) searches only the caller's project. If the project is unknown, use `t3_project_list` and search the returned projects with explicit IDs, paging as needed. A miss in the current project is not a reason to use recovery. This also applies when the user explicitly invokes this skill for an ordinary lookup.

Native read's “no longer available” error can mean a deleted thread or an ID that was never a T3 thread. For an ambiguous UUID, try `--provider-id` before `--include-deleted --thread`. This script does not provide status inference, conversation detail, general active-thread search, or remote access.

## Command

```bash
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread-search" 'phrase from an archived message'
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread-search" --include-deleted --thread '<threadId>'
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread-search" --provider-id '<provider session or native ID>'
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread-search" --pr 'https://github.com/owner/repository/pull/123'
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread-search" --include-deleted --path /path/to/checkout --limit 1000
```

Text queries match archived titles, branches, and indexed messages. `--include-deleted` also searches retained deleted records. `--thread` requires `--include-deleted` and returns only the deleted record’s compact metadata; it does not establish whether messages remain. Known surviving IDs go to native read. `--provider-id` matches only exact thread/session/native identifiers and searches active and archived records, plus deleted ones when requested. Results contain identity, project, dates, provider IDs, and bounded matching context. Use native read for the selected surviving thread.

`--path` is an exact match, not a prefix. A primary checkout's path matches every thread of the project rooted there, including threads bound to its worktrees elsewhere. A worktree's path matches only the threads bound to that worktree. It accepts `--limit` up to 1000, so a whole project fits in one result. Check the `truncated` flag before treating the list as complete.

`--project TEXT` filters by project title or workspace path. `--limit N` defaults to 20, maximum 100. `--json` gives structured output. See `--help` for all options. The skill's `mise.toml` supplies Python if needed.

## Store and safety

The default is `$T3CODE_HOME/userdata/statev2.sqlite` when set, otherwise `~/.t3/userdata/statev2.sqlite`. Use `--db PATH` to select an exact local file, including a development or worktree store. `--list-dbs` reports the selected path and any legacy `state.sqlite` sibling as stale/unsupported. Legacy schemas are never searched. Results report the adjacent `environment-id`; scoped thread IDs must match the selected store. A local miss says nothing about other machines or stores. For another machine's recovery records, run the helper on that machine; a connected T3 app does not provide this script with remote database access.

Connections use `mode=ro`, `PRAGMA query_only=ON`, parameterized queries, and normal SQLite reader locking even when no WAL is present. Never copy a live database, vacuum, index, migrate, mutate it, or start a server against it. SQLite may create or update WAL sidecars needed for read access. Database paths and environment identity follow symlinks to the actual store.

## Coverage limits

Message search uses T3's existing FTS index with literal phrases, never a full message `LIKE` scan. Queries shorter than three characters search metadata only. At most 10,000 matching recovery messages have their text retrieved; scope and project filters apply before that cap. A warning and `truncated` flag report when older matches may be omitted.

The index excludes streaming messages, **all agent-authored user prompts**, and subagent transcripts. Archived subagents can still be found by title; use native read once their ID is known. Deleted records may contain little or no message history; this is residual-data lookup, not full conversation restoration.

For PRs, try native search first. The recovery `--pr` lookup uses recorded links on archived/deleted threads and reports which field matched: `pullRequests`, `branchPullRequest`, or `linkedPullRequest`. Branch associations can be inherited by subagents sharing a checkout and do not establish PR authorship. If absent, inspect the PR body's attribution block for its `thread:` line, then use native read or recovery lookup as appropriate. A missing link does not establish that no thread produced the PR.
