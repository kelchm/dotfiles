---
name: t3-thread-search
description: >
  Find T3 Code threads by title, thread ID, T3 thread URL, environmentId, user or assistant
  message text, project, provider ID, PR, or date. Searches local statev2.sqlite and can merge
  remote environments. Canonical identity is (environmentId, threadId). Use for recovering
  archived conversations, looking up UUIDs or T3 thread URLs,
  command-palette search, remote/multi-environment lookup, and read-only execution status
  checks such as “status?”, “is it hung?”, or “what is blocking this thread?”. Use when the
  user runs /t3-thread-search or /find-t3-thread.
---

# T3 thread search

Find threads and inspect T3 Code's materialized read model without writing to it. Prefer the integrated tools for normal work in a connected environment; use the local helpers for recovery, broader lookup, and offline diagnostics.

## Integrated tools or local helpers?

Check the tools available in the current harness before choosing a path. As of 2026-10-27:

- **Known thread ID, conversation, or current status:** prefer `t3_thread_read`. It returns the thread's status, recent runs, pending-request count, PR links, and bounded timeline items. Use small `limit`, `maxCharsPerItem`, and `runLimit` values; use `view: "activity"` for tool activity. Read a known thread before answering about its current state, and use its returned `link` verbatim.
- **Find an active thread, including by PR number or URL:** prefer `t3_thread_search`. It searches title, branch, PR, project, then messages, but is not exhaustive and skips subagent threads. Inside a thread it defaults to the current project; supply the intended `projectId` for another project. `t3_thread_list` gives paginated project inventory with `titleContains`, status, settled, and snoozed filters, and `includeSubagents: true` covers the subagent threads search skips. A miss is scoped to those filters and the connected environment.
- **Archived recovery, provider/native IDs, PR links on archived threads or other projects, date filters, multiple local stores, or no integrated tools:** use this skill's helpers. Recovery search includes archived non-deleted threads. The SQLite FTS index has coverage limits described below; direct ID/title lookup remains useful when message search misses.
- **Approval or user-input details:** use integrated reads when connected. `t3_pending_request` lists/reads user questions; it does not list permission approvals. A status result is never authorization to answer, approve, retry, interrupt, or send a message.
- **A delegate this thread started:** follow `delegate_task`'s returned `next` and the harness's completion notifications. Do not poll a running delegate with this helper, `task_status`, or another monitor. Use integrated PR watching for PR monitoring, not SQLite status loops.

`t3-thread status` is an offline/read-only diagnostic fallback. Its state is an interpretation of stored projections, while `t3_thread_read` supplies T3's application-level view. If they disagree, check environment identity, database path, timestamps, and current run before drawing conclusions. Neither a stale projection nor a tool's `waiting` status proves a hang. Do not use the skill to bypass integrated-tool limits or assume that an authenticated connection covers every environment.

## Command

For local recovery and diagnostics, prefer the helper over ad hoc SQL. It is read-only (`sqlite3` URI `mode=ro` plus `PRAGMA query_only=ON`), parameterizes every user value, inspects `sqlite_schema` / `PRAGMA table_info`, and prints the database it used.

```bash
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread" search [query] [flags]
```

The other subcommand is `status --thread <id>` (see below). Flags go after the subcommand, and each subcommand has `--help`. The older `scripts/t3-thread-search` and `scripts/t3-thread-status` paths still work with the same arguments.

`--ssh` sends the search program to `python3 -I -` on the remote host, so that host needs only `python3`, not this skill. No code files or database copies are written there; the search reads the host's own database.

If `python3` is missing, retry with `python`, then `mise -C "$HOME/.agents/skills/t3-thread-search" exec -- python3 scripts/t3-thread search ...` so the skill's `mise.toml` is used. Do not interpolate the query into SQL. Do not start a T3 server against an existing database. Do not copy a live database (`statev2.sqlite` or legacy `state.sqlite`). Do not `VACUUM`, migrate, index, or otherwise mutate the source. Checkpointed files are opened with `immutable=1` so `-wal`/`-shm` are not created; a live WAL file cannot be immutable (that would hide uncheckpointed writes), and SQLite may then update `-shm` in order to read the WAL.

| Flag | Purpose |
|---|---|
| `--db PATH` | Exact SQLite file, a `userdata` dir, or a T3 base dir (prefers `statev2.sqlite`) |
| `--base-dir PATH` / `--home-dir PATH` | `<path>/userdata/statev2.sqlite`, with legacy fallback (explicit-home rule) |
| `--project TEXT` | Restrict by project title or workspace path |
| `--since` / `--until` | ISO date/time or relative `7d` / `24h` / `30m`. Date-only `--until` is end of that day. |
| `--active-only` | Exclude archived/deleted threads and deleted projects |
| `--include-deleted` | Opt in to deleted threads (labeled) |
| `--thread ID` | Thread ID, `environmentId/threadId`, or a full T3 thread URL |
| `--pr NUMBER_OR_URL` | Find threads through stored PR links; a number can match several repositories |
| `--environment ID` | Restrict to this environment. Combined with `--thread` this is the canonical identity |
| `--endpoint URL` | Remote T3 HTTP(S) endpoint. Recorded as not queried unless `--remote-json` supplies RPC results |
| `--ssh TARGET` | Explicit SSH host that owns the database. Never copies the remote DB |
| `--remote-json PATH` | Sanitized federated RPC results (`orchestration.searchThreads` per environment). No tokens |
| `--list-dbs` | Show candidate databases and environment IDs |
| `--limit N` | Default 20, max 100 |
| `--json` | Machine-readable output |
| `--cwd PATH` | Discover worktree-local `.t3` as if started from this directory |

Default search is **recovery**: active + archived, non-deleted, titles, projects, branches, provider IDs, and indexed messages. `--active-only` restricts to active threads and projects; it does not promise exact parity with the integrated search ranking or coverage.

## Thread status and monitoring

Prefer `t3_thread_read` for a connected thread. When it is unavailable, or when investigating local projection state, use the status subcommand:

```bash
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread" status \
  --thread "<environmentId>/<threadId>"
```

On v2 it reads `orchestration_v2_projection_threads`, `orchestration_v2_projection_provider_threads`, `orchestration_v2_projection_runs`, `orchestration_v2_projection_turn_items`, messages, and pending runtime requests joined to their run through nodes. Project names still come from `projection_projects`. It never uses the stale legacy thread/session tables when v2 exists. The JSON output retains `turn_id` / `turn_state` for compatibility; on v2 they identify the selected run and its status.

It reports `running/recent`, `awaiting-approval`, `awaiting-input`, `queued`, `completed`, `error`, `interrupted`, `idle/ready`, `idle/stopped`, `stale-suspect`, or `unknown`. Pending requests from older runs do not override a terminal run. Message/tool timestamps are stronger liveness evidence than provider timestamps; missing tables produce warnings. Activity summaries are sanitized and full payload JSON/messages are never printed. The default stale threshold is five minutes; `stale-suspect` does **not** prove that a provider is hung.

Use `--watch-for 10m --interval 15s` only when the user explicitly requests finite local monitoring and the harness has no applicable integrated monitoring/completion mechanism. Maximum 30 minutes; stop on terminal state or an explicit approval/input blocker. Never auto-approve, retry, kill, restart, or send input. Harness restrictions on polling delegates and PRs take precedence.

## Agent flow

1. Choose integrated tools or helpers using the guidance above. For a helper lookup, parse the user's request for a thread URL, `(environmentId, threadId)`, or a bare UUID. Native `t3-thread://v1/<threadId>` links are accepted but do not identify an environment. Canonical identity is `(environmentId, threadId)`. A bare UUID does **not** identify the environment. As a positional query it searches both app thread IDs and native provider IDs; use `--thread` for an exact app-thread lookup. Explicit `--thread` also accepts opaque IDs such as `thread:delegated-task:…`.
2. Resolve local databases (`--list-dbs`). Each DB is associated with `<stateDir>/environment-id` when that file exists. Always report environment ID, database path, and provenance.
3. Search matching local databases.
4. If the harness has an authenticated T3 RPC/MCP session, federate like the web client: use `t3_thread_search` in each intended project/environment (or `orchestration.searchThreads` if that RPC is actually exposed) and attach `environmentId` to each hit. Feed sanitized results through `--remote-json` (never tokens). Integrated search is **active/UI** search only; archived recovery needs SQLite or SSH on the owning host.
5. There is no official T3 search CLI today. With **explicit user authorization**, `--ssh user@host` runs this same read-only helper on the owner. Do not `scp`/`cp` a live remote database.
6. Return scoped identities (`environmentId/threadId`), host/endpoint, and database or API queried.
7. For a chosen thread: `--environment <id> --thread <id>` (or the URL). Do not dump full conversations.

A local miss is not a global miss. If remotes were not queried, say exactly:

> Not found in the environments searched; remote environments were not queried.

Then ask for the full thread URL, environment ID, authenticated endpoint, or SSH target.

Distinguish: authoritative not found in a searched environment, environment disconnected, environment not searched, stale cache hint. Do not scrape browser/desktop credential stores. Do not print bearer, relay, pairing, or SSH credentials. Do not pass secrets on the command line.

Natural-language mapping:

- `https://app.t3.codes/<environmentId>/<threadId>` → parse both IDs and look up that identity
- Bare UUID → search every local environment, then connected remotes; never conclude "does not exist"
- "Search as T3 does" → prefer integrated `t3_thread_search`; `--active-only` is a local active-thread filter, not an exact UI-parity guarantee

## Database locations

Do not invent paths and do not recurse the home directory. The helper only considers:

- `--db` / `--base-dir` / `--home-dir` when given
- linked git worktree `.t3/userdata/statev2.sqlite` (a `.git` *file* pointing at `…/worktrees/<name>`; this outranks ambient `T3CODE_HOME` as a candidate, matching T3)
- `$T3CODE_HOME/userdata/statev2.sqlite` when `T3CODE_HOME` is set (explicit home always uses `userdata`, not `dev`)
- `~/.t3/userdata/statev2.sqlite` (production)
- `~/.t3/dev/statev2.sqlite` (implicit development on the main checkout)

Within each state directory, prefer `statev2.sqlite`. A sibling `state.sqlite` is listed as **legacy/stale (superseded)** and is not searched by default. If only `state.sqlite` exists, legacy support remains available; `--db /exact/path/state.sqlite` explicitly opts into it. Directory and base-dir arguments also prefer v2. Several independent live stores are searched and every hit identifies its database and environment. Do not use main-file mtime alone to determine freshness: live writes can be in the WAL.

Schema choice is based on tables, not the filename. In the live store checked on 2026-10-27, legacy thread/message/session writes stopped on October 3, while v2 projections are current. `projection_projects` is still maintained, so both schemas use it for project metadata. Legacy search/status support remains for old stores; it does not supply current thread data from a v2 store. No copying, vacuuming, new indexes, or migrations are permitted.

Worktree-local state can outrank ambient `T3CODE_HOME` for T3 itself; still list production if it exists so a search started inside a worktree does not hide the live install.

## Message search and active-only coverage

The helper verifies that `orchestration_v2_message_search` is an FTS5 virtual table, then uses parameterized `MATCH` with a quoted literal phrase and joins index rowids to `orchestration_v2_projection_messages.rowid`. Text is extracted from message `payload_json` only for indexed matches. No full message `LIKE` scan is used on v2. The live index is contentless and uses `trigram remove_diacritics 1`; apostrophes are normalized to match T3's index writes. Quotes, `%`, `_`, and FTS operators are treated as text.

Queries shorter than three characters search metadata only and warn; a trigram index cannot answer them. If FTS is missing or unrecognized, search metadata and report the limitation instead of scanning messages. SQLite must support the live store's FTS5/tokenizer features; an incompatible runtime produces an error, never a scan fallback.

The live FTS triggers index non-streaming assistant messages and user-authored user messages. They omit generated user notifications and subagent transcripts. Recovery includes archived indexed messages; it cannot recover text that T3 did not index. Use ID/title/provider lookup and bounded integrated reads for those threads. `--active-only` additionally excludes archived/deleted threads and deleted projects. V2 has no legacy `projection_turns.assistant_message_id` linkage, so the old canonical-final-only assistant restriction does not apply. Legacy stores retain their existing parameterized `LIKE` search and canonical-final restriction in active-only mode.

## Find the thread for a PR

When connected, try `t3_thread_search` with the PR URL first. Otherwise use `--pr 1046` or, preferably, `--pr https://github.com/owner/repository/pull/1046`. The URL scopes by host and repository as well as number; numbers alone can be ambiguous. This is a small lookup over recorded PR links, not a message scan. The live v2 store records links in each thread's projection (`$.pullRequests`); the legacy `projection_thread_pull_requests` table stopped updating with the other legacy projections. The lookup finds only recorded links and excludes deleted threads unless requested. For example, home-lab PR #1046 has no legacy table row, but does have a v2 payload link; a legacy-table miss must not trigger an attribution fallback until the v2 links have been checked.

If no link is found, inspect the PR body's hidden attribution block for its `thread:` line (for example, with `gh pr view <url> --json body`). Read that thread with `t3_thread_read` when connected, or look it up with `--thread`. Do not create a link merely to answer a lookup question. A missing link is not evidence that no thread produced the PR; PRs are not always linked.

## Harness notes

Canonical files live in `~/.agents/skills/t3-thread-search/` (Codex user-level, Grok, Cursor, and repo-relative Claude/T3 discovery). Claude Code's user tree does not read `~/.agents`, so a thin wrapper lives at `~/.claude/skills/t3-thread-search/` and points here. Do not put a second copy under `~/.codex/skills/` — Codex's documented user path is `~/.agents/skills` (`$CODEX_HOME/skills` is a deprecated fallback). Harness-specific skills (delegate-review, grok-review) stay in their vendor trees.

Examples:

```bash
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread" search "projection rebuild performance"
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread" search --pr "https://github.com/owner/repository/pull/1046"
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread" search --json --thread "https://app.t3.codes/<environmentId>/<threadId>"
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread" search --environment "<environmentId>" --thread "<threadId>"
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread" search --remote-json /tmp/t3-search-rpc.json --active-only "reconnect"
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread" search --ssh user@host --ssh-base-dir '~/.t3' --thread "<threadId>"
```

On Windows, invoke `python` on the same script path under `%USERPROFILE%\.agents\skills\t3-thread-search\scripts\t3-thread` followed by `search` or `status`.

If the helper cannot run, use `sqlite3 -readonly "file:<abs>/statev2.sqlite?mode=ro"` with `.parameter init` / `.parameter set` and `PRAGMA query_only=ON`. Never build SQL by concatenating the user's text.
