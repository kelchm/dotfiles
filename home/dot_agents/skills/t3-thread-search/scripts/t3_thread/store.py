"""Shared read-only SQLite access, discovery, and identities."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlparse

BUSY_TIMEOUT_MS = 5000
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
RESERVED_URL_SEGMENTS = {
    "pair", "connect", "settings", "login", "auth", "oauth", "api", "ws",
    "health", "ready", ".", "..",
}
REQUIRED_TABLES = (
    "projection_projects",
    "orchestration_v2_projection_threads",
    "orchestration_v2_projection_provider_threads",
    "orchestration_v2_projection_messages",
    "orchestration_v2_projection_runs",
    "orchestration_v2_projection_turn_items",
    "orchestration_v2_projection_runtime_requests",
    "orchestration_v2_projection_nodes",
    "orchestration_v2_message_search",
)


class SearchError(Exception):
    """User-facing failure with a stable exit code."""

    exit_code = 1


class UsageError(SearchError):
    exit_code = 2


@dataclass(frozen=True)
class Candidate:
    path: Path
    kind: str
    source: str
    environment_id: str | None = None
    host: str | None = None
    provenance: str = "sqlite"
    searchable: bool = True

    def resolved(self) -> Path:
        return self.path.expanduser()


@dataclass(frozen=True)
class ThreadRef:
    raw: str
    thread_id: str | None = None
    environment_id: str | None = None
    url: str | None = None
    host: str | None = None


def scoped_identity(environment_id: str | None, thread_id: str | None) -> str | None:
    if not thread_id:
        return None
    return f"{environment_id or 'unknown'}/{thread_id}"


def looks_like_thread_id(value: str) -> bool:
    raw = value.strip()
    return bool(UUID_RE.fullmatch(raw.removeprefix("mcp:")) or raw.startswith(("thread-", "thread:")))


def _parse_thread_url(raw: str) -> ThreadRef | None:
    parsed = urlparse(raw)
    # T3's native links embed namespaced IDs verbatim, including percent escapes
    # inside those IDs. Also accept conventional URL-encoded ID segments.
    def decode_segment(value: str) -> str:
        return value if looks_like_thread_id(value) else unquote(value)

    if parsed.scheme == "t3-thread" and parsed.netloc == "v1":
        path = "/".join(decode_segment(part) for part in parsed.path.strip("/").split("/"))
        ref = parse_thread_ref(path, explicit=True)
        return ThreadRef(raw=raw, thread_id=ref.thread_id, environment_id=ref.environment_id, url=raw) if ref else None
    if parsed.scheme not in {"http", "https"}:
        return None
    query = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
    env_from_query = query.get("environmentId") or query.get("environment_id")
    thread_from_query = query.get("threadId") or query.get("thread_id")
    segments = [decode_segment(part) for part in parsed.path.split("/") if part]
    env = env_from_query
    thread = thread_from_query
    if segments and segments[0].lower() not in RESERVED_URL_SEGMENTS:
        if env is None and len(segments) >= 1:
            env = segments[0]
        if thread is None and len(segments) >= 2:
            thread = segments[1]
    if thread is None and env is not None and looks_like_thread_id(env) and len(segments) < 2:
        thread = env
        env = env_from_query
    if thread is None:
        return None
    return ThreadRef(
        raw=raw,
        thread_id=thread,
        environment_id=env,
        url=raw,
        host=parsed.netloc or None,
    )


def parse_thread_ref(value: str | None, *, explicit: bool = False) -> ThreadRef | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if "://" in raw:
        return _parse_thread_url(raw)
    stripped = raw.strip("/")
    parts = stripped.split("/", 1)
    if (
        len(parts) == 2
        and all(parts)
        and parts[0].lower() not in RESERVED_URL_SEGMENTS
        and UUID_RE.fullmatch(parts[0])
    ):
        return ThreadRef(raw=raw, environment_id=parts[0], thread_id=parts[1])
    tokens = raw.split()
    if len(tokens) == 2 and looks_like_thread_id(tokens[0]) and looks_like_thread_id(tokens[1]):
        return ThreadRef(raw=raw, environment_id=tokens[0], thread_id=tokens[1])
    if explicit or looks_like_thread_id(raw):
        return ThreadRef(raw=raw, thread_id=raw)
    return None


def read_environment_id(db_path: Path) -> str | None:
    path = db_path.parent / "environment-id"
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return raw or None


def expand_path(value: str | Path, *, cwd: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path


def is_linked_worktree(cwd: Path) -> Path | None:
    """Return the linked worktree root containing cwd, else None.

    Matches T3's rule in packages/shared/src/devHome.ts: a `.git` *file* whose
    `gitdir:` path has `worktrees` as the penultimate segment. A `.git`
    directory is the main checkout. A submodule `.git` file pointing at
    `modules/<name>` is not a worktree.
    """

    directory = cwd.resolve()
    while True:
        git_path = directory / ".git"
        if git_path.is_dir():
            return None
        if git_path.is_file():
            gitdir = None
            try:
                contents = git_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
            for line in contents.splitlines():
                stripped = line.strip()
                if stripped.lower().startswith("gitdir:"):
                    gitdir = stripped.split(":", 1)[1].strip()
                    break
            if not gitdir:
                return None
            segments = [part for part in Path(gitdir.replace("\\", "/")).parts if part not in ("/",)]
            if len(segments) >= 3 and segments[-2] == "worktrees":
                return directory
            return None
        parent = directory.parent
        if parent == directory:
            return None
        directory = parent


def resolve_sqlite_candidate(path: Path) -> Path | None:
    if path.is_file():
        return path
    if not path.is_dir():
        return None
    for directory in (path / "userdata", path):
        for name in ("statev2.sqlite",):
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def discover_candidates(
    *,
    cwd: Path,
    home: Path,
    env: Mapping[str, str],
    db: str | None = None,
    base_dir: str | None = None,
) -> list[Candidate]:
    if db and base_dir:
        raise UsageError("Use only one of --db or --base-dir/--home-dir.")

    if db:
        explicit = expand_path(db, cwd=cwd)
        sqlite_path = resolve_sqlite_candidate(explicit) or (
            explicit if explicit.suffix == ".sqlite" else explicit / "userdata" / "statev2.sqlite"
        )
        return [Candidate(path=sqlite_path, kind="explicit", source="--db")]

    if base_dir:
        base = expand_path(base_dir, cwd=cwd)
        return [
            Candidate(
                path=resolve_sqlite_candidate(base / "userdata") or base / "userdata" / "statev2.sqlite",
                kind="explicit-base",
                source="--base-dir/--home-dir",
            )
        ]

    candidates: list[Candidate] = []
    seen: set[Path] = set()

    def add(path: Path, kind: str, source: str, searchable: bool = True) -> None:
        resolved = path.expanduser()
        try:
            key = resolved.resolve() if resolved.exists() else resolved
        except OSError:
            key = resolved
        if key in seen:
            return
        seen.add(key)
        candidates.append(Candidate(path=resolved, kind=kind, source=source, searchable=searchable))

    def add_directory(directory: Path, kind: str, source: str) -> None:
        live = directory / "statev2.sqlite"
        legacy = directory / "state.sqlite"
        add(live, kind, source)
        if legacy.is_file():
            add(legacy, kind, source, searchable=False)

    worktree = is_linked_worktree(cwd)
    if worktree is not None:
        add_directory(worktree / ".t3" / "userdata", "worktree", f"linked worktree {worktree}")

    t3_home = env.get("T3CODE_HOME", "").strip()
    if t3_home:
        add_directory(expand_path(t3_home, cwd=cwd) / "userdata", "env", "T3CODE_HOME")

    add_directory(home / ".t3" / "userdata", "production", "~/.t3/userdata")
    add_directory(home / ".t3" / "dev", "development", "~/.t3/dev")
    return candidates


def candidate_metadata(candidate: Candidate) -> dict[str, Any]:
    path = candidate.path
    exists = path.is_file()
    environment_id = candidate.environment_id or (read_environment_id(path) if exists else None)
    info: dict[str, Any] = {
        "path": str(path),
        "kind": candidate.kind,
        "source": candidate.source,
        "exists": exists,
        "environment_id": environment_id,
        "host": candidate.host,
        "provenance": candidate.provenance,
        "searchable": candidate.searchable,
        "role": "legacy/stale (unsupported)" if path.name == "state.sqlite" else "live",
    }
    if exists:
        stat = path.stat()
        info["size_bytes"] = stat.st_size
        info["mtime"] = datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        info["wal"] = path.with_name(path.name + "-wal").is_file()
        info["shm"] = path.with_name(path.name + "-shm").is_file()
    return info


def sqlite_uri(path: Path) -> str:
    """Read-only URI.

    `mode=ro` blocks writes to the main file. If no WAL or rollback journal exists the
    database is treated as `immutable=1` so SQLite will not create `-wal`/`-shm`.
    A live WAL database cannot use immutable mode (that would hide uncheckpointed
    writes); SQLite may then update `-shm` to *read* the WAL. That is not a
    projection mutation, but it is why idle/checkpointed files take the immutable path.
    """

    resolved = path.resolve()
    uri = resolved.as_uri() + "?mode=ro"
    if not any(resolved.with_name(resolved.name + suffix).is_file() for suffix in ("-wal", "-journal")):
        uri += "&immutable=1"
    return uri


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise SearchError(
            f"Database does not exist at {str(path)!r}. Pass --db or --base-dir, or run --list-dbs."
        )
    try:
        conn = sqlite3.connect(sqlite_uri(path), uri=True)
    except sqlite3.Error as error:
        raise SearchError(f"Failed to open {str(path)!r} read-only: {error}") from error
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA query_only = ON")
    except sqlite3.Error as error:
        conn.close()
        raise SearchError(f"Failed to lock {str(path)!r} to query-only: {error}") from error
    return conn


def require_projection_schema(conn: sqlite3.Connection, path: Path) -> None:
    present = {row[0] for row in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
    missing = set(REQUIRED_TABLES) - present
    if missing:
        raise SearchError(
            f"{path}: unsupported T3 schema; requires statev2.sqlite with the v2 projections. "
            f"Missing table(s): {', '.join(sorted(missing))}. Legacy stores are no longer supported."
        )


def v2_select() -> str:
    return """
        t.thread_id, t.project_id, t.title, t.created_at, t.updated_at,
        t.archived_at, t.deleted_at,
        json_extract(t.payload_json, '$.branch') AS branch,
        json_extract(t.payload_json, '$.worktreePath') AS worktree_path,
        p.title AS project_title, p.workspace_root, p.deleted_at AS project_deleted_at,
        s.provider AS provider_name, s.provider_thread_id, s.provider_session_id,
        s.provider_instance_id
    """


def v2_from(*, all_providers: bool = False) -> str:
    # Metadata/detail use the active provider, never an arbitrary historical session.
    provider_join = "s.thread_id = t.thread_id" if all_providers else """
        s.provider_thread_id = COALESCE(t.active_provider_thread_id, (
            SELECT provider_thread_id FROM orchestration_v2_projection_provider_threads
            WHERE thread_id = t.thread_id ORDER BY updated_at DESC, provider_thread_id LIMIT 1
        )) AND s.thread_id = t.thread_id
    """
    return f"""
        FROM orchestration_v2_projection_threads AS t
        LEFT JOIN projection_projects AS p ON p.project_id = t.project_id
        LEFT JOIN orchestration_v2_projection_provider_threads AS s ON {provider_join}
    """


def bind_candidate(candidate: Candidate) -> Candidate:
    env_id = candidate.environment_id
    if env_id is None and candidate.path.is_file():
        env_id = read_environment_id(candidate.path)
    return Candidate(
        path=candidate.path,
        kind=candidate.kind,
        source=candidate.source,
        environment_id=env_id,
        host=candidate.host,
        provenance=candidate.provenance,
        searchable=candidate.searchable,
    )
