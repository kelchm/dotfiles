---
name: t3-thread-search
description: >
  Last-resort local SQLite recovery for T3 Code: discover archived/deleted threads,
  look up provider thread/session/native IDs, filter by date or local store, and
  inspect projections when native reads are unavailable. Use only for a concrete
  gap in native T3 functionality. Handles /t3-thread-search or /find-t3-thread.
---

# T3 thread search

This skill is a method of last resort. Identify the native capability that cannot answer the request before using the database helper.

Use `t3_thread_search` for ordinary title, message, branch, project, and PR lookup. It searches active threads, skips subagents, and defaults to the current project. Use `t3_thread_list` with `titleContains` and `includeSubagents: true` for project inventory, including subagents. Use `t3_thread_read` for a known ID's conversation or current state, including a known archived thread. Check project and environment scope before treating a native search miss as a recovery problem.

The local helper adds these capabilities:

- Discover archived or deleted threads by metadata or indexed message text; native search excludes them and has no recovery switch.
- Find a thread from its provider thread, session, or native ID; native tools have no lookup input for those identifiers.
- Search with update-date bounds or across local production, development, and worktree stores. Native search has no date filters or database-path selector; this session's MCP tools address one server, not every local store.
- Inspect local projections when native reads cannot run, or diagnose a specific disagreement between stored state and an integrated read. Status is a diagnostic snapshot, not a more authoritative execution state.

These helpers search local databases only. Use T3's connected-environment search for remote threads. A miss applies only to the stores and filters searched.

For waiting, use `t3_thread_wait`. For a delegate, follow `delegate_task`'s returned `next`; do not poll it with these helpers. Status inspection does not authorize sending input, approving, retrying, or interrupting a thread.

## Commands

```bash
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread" search --since 7d "Spark BIOS"
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread" search --thread "<environmentId>/<threadId>"
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread" status --thread "<environmentId>/<threadId>"
```

The older `scripts/t3-thread-search` and `scripts/t3-thread-status` paths still work. Each subcommand has `--help`. The skill's `mise.toml` supplies Python if needed.

The helpers use SQLite `mode=ro`, `PRAGMA query_only=ON`, and parameterized queries. Never copy a live database, vacuum, index, migrate, mutate it, or start a T3 server against it. Without a WAL or rollback journal beside the resolved database path, reads use `immutable=1` to avoid creating sidecars. A live WAL requires normal read-only locking; SQLite may update `-shm` to read uncheckpointed data.

| Search flag | Purpose |
|---|---|
| `--thread ID` | Exact thread ID, `environmentId/threadId`, or T3 URL; returns metadata and bounded snippets |
| `--environment ID` | Restrict to this environment |
| `--pr NUMBER_OR_URL` | Stored PR links; prefer the URL to disambiguate repositories |
| `--project TEXT` | Project title or workspace path |
| `--since` / `--until` | ISO date/time or relative `7d` / `24h` / `30m`; UTC when no offset is given; date-only `--until` includes the whole day |
| `--active-only` | Exclude archived/deleted threads and deleted projects |
| `--include-deleted` | Include deleted threads, labeled in results |
| `--db PATH` | SQLite file, userdata directory, or T3 base directory |
| `--base-dir PATH` / `--home-dir PATH` | `<path>/userdata/statev2.sqlite` |
| `--list-dbs` | Candidate paths, environment IDs, and live/stale labels |
| `--limit N` | Default 20, maximum 100 |
| `--json` | Machine-readable output |
| `--cwd PATH` | Directory used for linked-worktree discovery |

A positional bare UUID searches both app thread IDs and native provider IDs. Use `--thread` for an exact app-thread lookup; opaque delegated IDs also work. Identity is `(environmentId, threadId)`; a bare ID or `t3-thread://` link need not identify an environment. Report the scoped identity and database or API used.

Message search uses T3's FTS index, with literal phrases and no message `LIKE` scan. Queries shorter than three characters search metadata only. The index omits streaming messages, generated user notifications, and subagent transcripts; try ID, title, or provider lookup when text misses. Recovery includes archived, non-deleted threads. `--active-only` does not promise integrated-search parity.

## Database locations

Discovery checks linked-worktree `.t3/userdata/statev2.sqlite`, `$T3CODE_HOME/userdata/statev2.sqlite`, `~/.t3/userdata/statev2.sqlite`, and `~/.t3/dev/statev2.sqlite`; it does not recurse the home directory. Explicit `--db` or `--base-dir` replaces discovery. Environment IDs come from the adjacent `environment-id` file. Main-file mtime alone does not show WAL freshness.

`state.sqlite` is listed as legacy/stale and never searched; an explicit lookup of a legacy store fails. Incomplete or incompatible v2 schemas fail clearly, without a message-scan fallback. Invalid stores found during discovery are skipped with a warning; an explicit invalid store fails.

## PR lookup

Try native search with the PR URL first. Use `search --pr <url>` when recovery requires links on archived/deleted threads or another local store. If no link is recorded, inspect the PR body's attribution block for its `thread:` line, then read or look up that thread. A missing link does not establish that no thread produced the PR.

## Status

Use `t3_thread_read` for routine status checks. Use this subcommand only for the local diagnostic cases above.

`status --thread <id>` accepts the database, environment, cwd, and JSON flags above, plus `--stale-after` (default `5m`). It takes one snapshot of the selected run, provider state, recent message/tool activity, and pending approval or input requests. Older-run requests do not override a completed run.

States are `running/recent`, `queued`, `awaiting-approval`, `awaiting-input`, `completed`, `error`, `interrupted`, `idle/ready`, `idle/stopped`, `stale-suspect`, or `unknown`. `stale-suspect` means activity is older than the threshold; it does not prove a hang. Compare identity, database path, run, and timestamps if the snapshot disagrees with an integrated read. Output is bounded; it does not dump full conversations or request payloads.
