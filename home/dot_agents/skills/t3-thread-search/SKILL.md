---
name: t3-thread-search
description: >
  Recover T3 Code threads from local statev2.sqlite by title, thread ID or URL,
  message text, project, provider ID, PR, or date. Covers archived threads and
  read-only execution status. Use when integrated T3 thread tools are unavailable
  or insufficient, or for /t3-thread-search or /find-t3-thread.
---

# T3 thread search

Prefer integrated `t3_thread_search` for connected searches, including PR lookup,
and `t3_thread_read` for a known thread's conversation or current state.
`t3_thread_search` skips subagents and defaults to the current project;
`t3_thread_list` supports `titleContains` and `includeSubagents: true` for project
inventory. Use these helpers for archived recovery, native provider IDs, date
filters, other local stores, or offline diagnostics. A miss applies only to the
environments and filters searched.

For waiting, use `t3_thread_wait`.
For a delegate, follow `delegate_task`'s returned `next`; do not poll it with these
helpers. Status inspection does not authorize sending input, approving, retrying,
or interrupting a thread.

## Commands

```bash
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread" search "Spark BIOS"
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread" search --thread "<environmentId>/<threadId>"
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread" status --thread "<environmentId>/<threadId>"
```

The older `scripts/t3-thread-search` and `scripts/t3-thread-status` paths still
work. Each subcommand has `--help`. The skill's `mise.toml` supplies Python if
needed.

The helpers use SQLite `mode=ro`, `PRAGMA query_only=ON`, and parameterized queries.
Never copy a live database, vacuum, index, migrate, mutate it, or start a T3 server
against it. Without a WAL or rollback journal beside the resolved database path,
reads use `immutable=1` to avoid creating sidecars. A live WAL requires normal
read-only locking; SQLite may update `-shm` to read uncheckpointed data.

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
| `--ssh TARGET` / `--ssh-base-dir PATH` | Search the owning host; remote base defaults to `~/.t3` |
| `--limit N` | Default 20, maximum 100 |
| `--json` | Machine-readable output |
| `--cwd PATH` | Directory used for linked-worktree discovery |

A positional bare UUID searches both app thread IDs and native provider IDs.
Use `--thread` for an exact app-thread lookup; opaque delegated IDs also work.
Identity is `(environmentId, threadId)`; a bare ID or `t3-thread://` link need not
identify an environment. Report the scoped identity and database or API used.

Message search uses T3's FTS index, with literal phrases and no message `LIKE`
scan. Queries shorter than three characters search metadata only. The index
omits streaming messages, generated user notifications, and subagent transcripts;
try ID, title, or provider lookup when text misses. Recovery includes archived,
non-deleted threads. `--active-only` does not promise integrated-search parity.

## Database locations

Discovery checks linked-worktree `.t3/userdata/statev2.sqlite`,
`$T3CODE_HOME/userdata/statev2.sqlite`, `~/.t3/userdata/statev2.sqlite`, and
`~/.t3/dev/statev2.sqlite`; it does not recurse the home directory. Explicit
`--db` or `--base-dir` replaces discovery. Environment IDs come from the adjacent
`environment-id` file. Main-file mtime alone does not show WAL freshness.

`state.sqlite` is listed as legacy/stale and never searched; an explicit lookup
of a legacy store fails. Incomplete or incompatible v2 schemas fail
clearly, without a message-scan fallback. Invalid stores found during discovery
are skipped with a warning; an explicit invalid store fails.

With user authorization, `--ssh` streams the helper to `python3 -I -` on the owning
host. The host needs only Python 3: no skill installation, temporary code files,
or database copies. Report integrated-tool results separately.

## PR lookup

Try integrated search with the PR URL, or `search --pr <url>` for stored links,
including archived threads. If none is recorded, inspect the PR body's attribution
block for its `thread:` line, then read or look up that thread. A missing link does
not establish that no thread produced the PR.

## Status

`status --thread <id>` accepts the database, environment, cwd, and JSON flags above,
plus `--stale-after` (default `5m`). It takes one snapshot of the selected run,
provider state, recent message/tool activity, and pending approval or input
requests. Older-run requests do not override a completed run.

States are `running/recent`, `queued`, `awaiting-approval`, `awaiting-input`,
`completed`, `error`, `interrupted`, `idle/ready`, `idle/stopped`, `stale-suspect`,
or `unknown`. `stale-suspect` means activity is older
than the threshold; it does not prove a hang. Compare identity, database path,
run, and timestamps if the snapshot disagrees with an integrated read. Output is
bounded; it does not dump full conversations or request payloads.
