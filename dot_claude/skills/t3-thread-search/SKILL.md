---
name: t3-thread-search
description: >
  Find T3 Code threads in a local state.sqlite projection database by title, thread ID,
  user or assistant message text, project title or workspace path, provider session/thread ID,
  or approximate date. Use for recovering archived conversations, looking up thread-… IDs,
  and reproducing T3 command-palette search. Use when the user runs /t3-thread-search or
  /find-t3-thread, or asks to find, search, locate, or look up a T3 thread, chat, or conversation.
---

# T3 thread search

Search T3 Code's materialized read model. Never write to it.

## Command

Prefer the helper. It is read-only (`sqlite3` URI `mode=ro` plus `PRAGMA query_only=ON`), parameterizes every user value, inspects `sqlite_schema` / `PRAGMA table_info`, and prints the database it used.

```bash
python3 "$HOME/.claude/skills/t3-thread-search/scripts/t3-thread-search" [query] [flags]
```

If `python3` is missing, retry with `python` or `mise exec -- python3`. Do not interpolate the query into SQL. Do not start a T3 server against an existing database. Do not `cp` a live `state.sqlite`. Do not `VACUUM`, migrate, index, or otherwise mutate the source.

| Flag | Purpose |
|---|---|
| `--db PATH` | Exact `state.sqlite`, a `userdata` dir, or a T3 base dir |
| `--base-dir PATH` / `--home-dir PATH` | `<path>/userdata/state.sqlite` (explicit-home rule) |
| `--project TEXT` | Restrict by project title or workspace path |
| `--since` / `--until` | ISO date/time or relative `7d` / `24h` / `30m` |
| `--active-only` | Command-palette / UI semantics |
| `--include-deleted` | Opt in to deleted threads (labeled) |
| `--thread ID` | One thread's metadata and bounded snippets, or restrict a search |
| `--list-dbs` | Show candidate databases without searching |
| `--limit N` | Default 20, max 100 |
| `--json` | Machine-readable output |
| `--cwd PATH` | Discover worktree-local `.t3` as if started from this directory |

Default search is **recovery**: active + archived, non-deleted, titles, projects, provider IDs, user messages, and all non-streaming assistant messages. `--active-only` is the optional UI-parity mode.

## Agent flow

1. Resolve the database. If the user did not name one, run `--list-dbs` (or search the listed candidates). Always report the path actually queried.
2. Run a recovery search with the user's words first (title + messages + project + provider in one invocation).
3. If that is noisy, refine with `--project`, `--since`, `--thread`, or `--active-only`.
4. Return a compact ranked list. Do not dump full conversations.
5. For a chosen thread, run `--db <path> --thread <id>`. That prints metadata, provider IDs, message counts, the first user snippet, and the last canonical assistant snippet.

Natural-language mapping:

- "Find the T3 thread where we discussed X" → recovery search for `X`
- "Find recent threads for `/path/to/project` mentioning Y" → `--project /path/to/project --since 7d Y`
- "Search archived T3 threads for this error" → recovery search (archived is already on)
- "Look up thread `thread-…`" → `--thread thread-…`
- "Same semantics as T3's command palette" → `--active-only`

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

Canonical files live in `~/.claude/skills/t3-thread-search/` (Claude Code and Grok both discover this tree). Codex sees the same directory via `~/.codex/skills/t3-thread-search`.

Examples:

```bash
# Claude / Grok / Codex — recovery search
python3 "$HOME/.claude/skills/t3-thread-search/scripts/t3-thread-search" "projection rebuild performance"

# Codex may use the symlink path instead
python3 "$HOME/.codex/skills/t3-thread-search/scripts/t3-thread-search" --active-only "reconnect"

# Explicit live install
python3 "$HOME/.claude/skills/t3-thread-search/scripts/t3-thread-search" --db "$HOME/.t3/userdata/state.sqlite" "provider_thread_id"

# Follow-up
python3 "$HOME/.claude/skills/t3-thread-search/scripts/t3-thread-search" --db "$HOME/.t3/userdata/state.sqlite" --thread 'thread-…'
```

On Windows, invoke `python` on the same script path under `%USERPROFILE%\.claude\skills\t3-thread-search\scripts\t3-thread-search`.

If the helper cannot run, use `sqlite3 -readonly "file:<abs>/state.sqlite?mode=ro"` with `.parameter init` / `.parameter set` and `PRAGMA query_only=ON`. Never build SQL by concatenating the user's text.
