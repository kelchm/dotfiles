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

# T3 thread search

Search T3 Code's materialized read model. Never write to it.

## Command

Prefer the helper. It is read-only (`sqlite3` URI `mode=ro` plus `PRAGMA query_only=ON`), parameterizes every user value, inspects `sqlite_schema` / `PRAGMA table_info`, and prints the database it used.

```bash
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread-search" [query] [flags]
```

If `python3` is missing, retry with `python`, then `mise -C "$HOME/.agents/skills/t3-thread-search" exec -- python3 scripts/t3-thread-search ...` so the skill's `mise.toml` is used. Do not interpolate the query into SQL. Do not start a T3 server against an existing database. Do not `cp` a live `state.sqlite`. Do not `VACUUM`, migrate, index, or otherwise mutate the source. Checkpointed files are opened with `immutable=1` so `-wal`/`-shm` are not created; a live WAL file cannot be immutable (that would hide uncheckpointed writes), and SQLite may then update `-shm` in order to read the WAL.

| Flag | Purpose |
|---|---|
| `--db PATH` | Exact `state.sqlite`, a `userdata` dir, or a T3 base dir |
| `--base-dir PATH` / `--home-dir PATH` | `<path>/userdata/state.sqlite` (explicit-home rule) |
| `--project TEXT` | Restrict by project title or workspace path |
| `--since` / `--until` | ISO date/time or relative `7d` / `24h` / `30m`. Date-only `--until` is end of that day. |
| `--active-only` | Command-palette / UI semantics |
| `--include-deleted` | Opt in to deleted threads (labeled) |
| `--thread ID` | Thread ID, `environmentId/threadId`, or a full T3 thread URL |
| `--environment ID` | Restrict to this environment. Combined with `--thread` this is the canonical identity |
| `--endpoint URL` | Remote T3 HTTP(S) endpoint. Recorded as not queried unless `--remote-json` supplies RPC results |
| `--ssh TARGET` | Explicit SSH host that owns the database. Never copies the remote DB |
| `--remote-json PATH` | Sanitized federated RPC results (`orchestration.searchThreads` per environment). No tokens |
| `--list-dbs` | Show candidate databases and environment IDs |
| `--limit N` | Default 20, max 100 |
| `--json` | Machine-readable output |
| `--cwd PATH` | Discover worktree-local `.t3` as if started from this directory |

Default search is **recovery**: active + archived, non-deleted, titles, projects, provider IDs, user messages, and all non-streaming assistant messages. `--active-only` is the optional UI-parity mode.

## Agent flow

1. Parse the user's request for a thread URL, `(environmentId, threadId)`, or a bare UUID. Canonical identity is `(environmentId, threadId)`. A bare UUID does **not** identify the environment.
2. Resolve local databases (`--list-dbs`). Each DB is associated with `<stateDir>/environment-id` when that file exists. Always report environment ID, database path, and provenance.
3. Search matching local databases.
4. If the harness has an authenticated T3 RPC/MCP session, federate like the web client: call `orchestration.searchThreads` once per connected environment and attach `environmentId` to each hit. Feed sanitized results through `--remote-json` (never tokens). That RPC is **active/UI** search only; archived recovery needs SQLite or SSH on the owning host.
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
- "Same semantics as T3's command palette" → `--active-only` (local SQLite plus per-environment `searchThreads` RPC)

## Database locations

Do not invent paths and do not recurse the home directory. The helper only considers:

- `--db` / `--base-dir` / `--home-dir` when given
- linked git worktree `.t3/userdata/state.sqlite` (a `.git` *file* pointing at `…/worktrees/<name>`; this outranks ambient `T3CODE_HOME` as a candidate, matching T3)
- `$T3CODE_HOME/userdata/state.sqlite` when `T3CODE_HOME` is set (explicit home always uses `userdata`, not `dev`)
- `~/.t3/userdata/state.sqlite` (production)
- `~/.t3/dev/state.sqlite` (implicit development on the main checkout)

If several exist, the helper lists them and searches every file that is present, tagging each hit with its database. Ask the user to pick only when the result set is genuinely ambiguous. Missing files, schema drift, and parameterized `%` / `_` / quotes are handled by the helper.

Worktree-local state can outrank ambient `T3CODE_HOME` for T3 itself; still list production if it exists so a search started inside a worktree does not hide the live install.

## UI-parity mode (`--active-only`)

Matches T3's current built-in message search (`searchActiveThreadRows`):

- excludes deleted and archived threads and deleted projects
- excludes streaming messages
- searches user messages
- searches only canonical final assistant messages referenced by `projection_turns.assistant_message_id`
- one match per thread, preferring user matches then newer threads
- SQLite `LIKE` (ASCII case-insensitive by default)

It also searches active thread titles, project titles, and branches, which the command palette does client-side. Message search in the UI starts after two characters; warn that short queries become broad `%term%` scans. Do not add indexes.

## Harness notes

Canonical files live in `~/.agents/skills/t3-thread-search/` (Codex user-level, Grok, Cursor, and repo-relative Claude/T3 discovery). Claude Code's user tree does not read `~/.agents`, so a thin wrapper lives at `~/.claude/skills/t3-thread-search/` and points here. Do not put a second copy under `~/.codex/skills/` — Codex's documented user path is `~/.agents/skills` (`$CODEX_HOME/skills` is a deprecated fallback). Harness-specific skills (delegate-review, grok-review) stay in their vendor trees.

Examples:

```bash
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread-search" "projection rebuild performance"
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread-search" --json --thread "https://app.t3.codes/<environmentId>/<threadId>"
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread-search" --environment "<environmentId>" --thread "<threadId>"
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread-search" --remote-json /tmp/t3-search-rpc.json --active-only "reconnect"
python3 "$HOME/.agents/skills/t3-thread-search/scripts/t3-thread-search" --ssh user@host --ssh-base-dir '~/.t3' --thread "<threadId>"
```

On Windows, invoke `python` on the same script path under `%USERPROFILE%\.agents\skills\t3-thread-search\scripts\t3-thread-search`.

If the helper cannot run, use `sqlite3 -readonly "file:<abs>/state.sqlite?mode=ro"` with `.parameter init` / `.parameter set` and `PRAGMA query_only=ON`. Never build SQL by concatenating the user's text.
