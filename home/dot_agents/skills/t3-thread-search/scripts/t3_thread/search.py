"""Read-only search over T3 Code's live or legacy projection database."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlparse

from . import store
from .store import (
    Candidate,
    DatabaseSchema,
    SESSION_COLUMNS,
    SearchError,
    UUID_RE,
    UsageError,
    bind_candidate,
    candidate_metadata,
    connect_readonly,
    discover_candidates,
    expand_path,
    inspect_schema,
    parse_thread_ref,
    quote_ident,
    require_projection_schema,
    scoped_identity,
    v2_from,
    v2_select,
    v2_warnings,
)

LIKE_ESCAPE = "!"
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
SNIPPET_MAX = 240
SNIPPET_BODY = 236
SNIPPET_CONTEXT = 72
SECRET_KEY_RE = re.compile(
    r"(token|secret|password|bearer|pairing|authorization|credential|cookie|private[_-]?key)",
    re.IGNORECASE,
)
NOT_QUERIED_REMOTE_MESSAGE = (
    "Not found in the environments searched; remote environments were not queried."
)
REMOTE_REQUEST_HINT = (
    "Request the full thread URL, environment ID, authenticated endpoint, or SSH target."
)
RELATIVE_WHEN_RE = re.compile(r"^(\d+)([dhm])$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$"
)


RANK = {
    "thread_id": 0,
    "title": 1,
    "user": 2,
    "assistant": 3,
    "project": 4,
    "provider": 5,
    "branch": 6,
}
UI_RANK = {
    "thread_id": 0,
    "user": 0,
    "title": 1,
    "project": 1,
    "branch": 1,
    "assistant": 2,
    "provider": 3,
}


@dataclass
class RemoteEnvironment:
    environment_id: str | None
    status: str
    provenance: str
    host: str | None = None
    matches: list[dict[str, Any]] = field(default_factory=list)
    details: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


@dataclass
class Match:
    thread_id: str
    title: str
    project_id: str | None
    project_title: str | None
    workspace_root: str | None
    branch: str | None
    worktree_path: str | None
    created_at: str | None
    updated_at: str | None
    archived: bool
    deleted: bool
    project_deleted: bool
    source: str
    sources: list[str]
    snippet: str | None
    message_created_at: str | None
    provider_name: str | None
    provider_session_id: str | None
    provider_thread_id: str | None
    provider_instance_id: str | None
    database: str
    database_kind: str
    rank: int
    environment_id: str | None = None
    host: str | None = None
    provenance: str = "sqlite"
    scoped_id: str | None = None


@dataclass
class ThreadDetail:
    thread_id: str
    title: str
    project_id: str | None
    project_title: str | None
    workspace_root: str | None
    branch: str | None
    worktree_path: str | None
    created_at: str | None
    updated_at: str | None
    archived: bool
    deleted: bool
    project_deleted: bool
    provider_name: str | None
    provider_session_id: str | None
    provider_thread_id: str | None
    provider_instance_id: str | None
    message_counts: dict[str, int]
    first_user_snippet: str | None
    last_assistant_snippet: str | None
    database: str
    database_kind: str
    environment_id: str | None = None
    host: str | None = None
    provenance: str = "sqlite"
    scoped_id: str | None = None


@dataclass
class SearchReport:
    mode: str
    query: str | None
    databases: list[dict[str, Any]]
    results: list[dict[str, Any]]
    warnings: list[str]
    truncated: bool
    limit: int
    environments: list[dict[str, Any]] = field(default_factory=list)
    remote_queried: bool = False
    not_found_kind: str | None = None


def escape_like_pattern(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def like_contains(value: str) -> str:
    return f"%{escape_like_pattern(value)}%"


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: redact_secrets(item)
            for key, item in value.items()
            if not SECRET_KEY_RE.search(str(key))
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str) and value.lower().startswith("bearer "):
        return "[redacted]"
    return value


def load_remote_json(path: Path) -> list[RemoteEnvironment]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UsageError(f"Failed to read --remote-json {str(path)!r}: {error}") from error
    payload = redact_secrets(payload)
    rows = payload.get("environments") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise UsageError("--remote-json must contain an environments array.")
    remotes: list[RemoteEnvironment] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        remotes.append(
            RemoteEnvironment(
                environment_id=row.get("environment_id") or row.get("environmentId"),
                status=row.get("status") or "searched",
                provenance=row.get("provenance") or "rpc",
                host=row.get("host") or row.get("endpoint"),
                matches=list(row.get("matches") or []),
                details=list(row.get("details") or []),
                error=row.get("error"),
            )
        )
    return remotes


def remote_match_to_result(remote: RemoteEnvironment, item: dict[str, Any], *, rank: int = 0) -> dict[str, Any]:
    thread_id = item.get("thread_id") or item.get("threadId")
    environment_id = item.get("environment_id") or item.get("environmentId") or remote.environment_id
    payload = redact_secrets(dict(item))
    payload.update(
        {
            "thread_id": thread_id,
            "environment_id": environment_id,
            "scoped_id": scoped_identity(environment_id, thread_id),
            "host": payload.get("host") or remote.host,
            "provenance": remote.provenance,
            "database": payload.get("database") or remote.host or remote.provenance,
            "database_kind": remote.provenance,
            "source": payload.get("source") or "remote",
            "sources": payload.get("sources") or [payload.get("source") or "remote"],
            "rank": rank,
            "status": payload.get("status") or "active",
        }
    )
    return payload


def fold_ascii_case(value: str) -> str:
    return re.sub(r"[A-Z]", lambda match: match.group(0).lower(), value)


def build_snippet(text: str | None, query: str | None) -> str | None:
    if text is None:
        return None
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return None
    if len(normalized) <= SNIPPET_MAX:
        return normalized
    if not query or not query.strip():
        return normalized[:SNIPPET_BODY] + "…"
    needle = fold_ascii_case(re.sub(r"\s+", " ", query).strip())
    haystack = fold_ascii_case(normalized)
    match_index = haystack.find(needle) if needle else -1
    ideal_start = 0 if match_index < 0 else max(0, match_index - SNIPPET_CONTEXT)
    start = min(ideal_start, max(0, len(normalized) - SNIPPET_BODY))
    end = min(len(normalized), start + SNIPPET_BODY)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(normalized) else ""
    return f"{prefix}{normalized[start:end]}{suffix}"


def parse_when(value: str, *, now: datetime | None = None, end_of_day: bool = False) -> str:
    raw = value.strip()
    relative = RELATIVE_WHEN_RE.fullmatch(raw)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        delta = {"d": timedelta(days=amount), "h": timedelta(hours=amount), "m": timedelta(minutes=amount)}[
            unit
        ]
        origin = now or datetime.now(timezone.utc)
        origin = origin.replace(tzinfo=origin.tzinfo or timezone.utc).astimezone(timezone.utc)
        return (origin - delta).strftime("%Y-%m-%dT%H:%M:%S")
    if ISO_DATE_RE.fullmatch(raw):
        return f"{raw}T23:59:59.999" if end_of_day else f"{raw}T00:00:00"
    if ISO_DT_RE.fullmatch(raw):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            parsed = parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
            return parsed.isoformat().replace("+00:00", "Z")
    raise UsageError(
        f"Invalid date {value!r}. Use ISO-8601 (`2026-05-01` or `2026-05-01T12:00:00`) or a relative value like `7d`, `24h`, `30m`."
    )


def sql_null_if_missing(schema: DatabaseSchema, table: str, column: str, alias: str) -> str:
    if schema.has_column(table, column):
        return f"{quote_ident(table)}.{quote_ident(column)} AS {quote_ident(alias)}"
    return f"NULL AS {quote_ident(alias)}"


def thread_status_filters(
    schema: DatabaseSchema,
    *,
    active_only: bool,
    include_deleted: bool,
    table_alias: str = "projection_threads",
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    if schema.has_column("projection_threads", "deleted_at") and not include_deleted:
        clauses.append(f"{quote_ident(table_alias)}.{quote_ident('deleted_at')} IS NULL")
    if active_only and schema.has_column("projection_threads", "archived_at"):
        clauses.append(f"{quote_ident(table_alias)}.{quote_ident('archived_at')} IS NULL")
    if active_only and schema.has_column("projection_projects", "deleted_at"):
        clauses.append(f"{quote_ident('projection_projects')}.{quote_ident('deleted_at')} IS NULL")
    if not clauses:
        return "", []
    return " AND " + " AND ".join(clauses), []


def project_filter_sql(
    schema: DatabaseSchema, project: str | None
) -> tuple[str, list[Any]]:
    if not project:
        return "", []
    clauses = [f"{quote_ident('projection_projects')}.{quote_ident('title')} LIKE ? ESCAPE '{LIKE_ESCAPE}'"]
    params: list[Any] = [like_contains(project)]
    if schema.has_column("projection_projects", "workspace_root"):
        clauses.append(
            f"{quote_ident('projection_projects')}.{quote_ident('workspace_root')} LIKE ? ESCAPE '{LIKE_ESCAPE}'"
        )
        params.append(like_contains(project))
    return " AND (" + " OR ".join(clauses) + ")", params


def recency_filter_sql(
    schema: DatabaseSchema, since: str | None, until: str | None
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    column = (
        f"{quote_ident('projection_threads')}.{quote_ident('updated_at')}"
        if schema.has_column("projection_threads", "updated_at")
        else None
    )
    if column is None:
        return "", []
    if since:
        clauses.append(f"julianday({column}) >= julianday(?)")
        params.append(since)
    if until:
        clauses.append(f"julianday({column}) <= julianday(?)")
        params.append(until)
    if not clauses:
        return "", []
    return " AND " + " AND ".join(clauses), params


def thread_id_filter_sql(thread_id: str | None) -> tuple[str, list[Any]]:
    if not thread_id:
        return "", []
    return f" AND {quote_ident('projection_threads')}.{quote_ident('thread_id')} = ?", [thread_id]


def thread_select(schema: DatabaseSchema) -> str:
    pieces = [
        f"{quote_ident('projection_threads')}.{quote_ident('thread_id')} AS {quote_ident('thread_id')}",
        f"{quote_ident('projection_threads')}.{quote_ident('project_id')} AS {quote_ident('project_id')}",
        f"{quote_ident('projection_threads')}.{quote_ident('title')} AS {quote_ident('title')}",
        sql_null_if_missing(schema, "projection_threads", "created_at", "created_at"),
        sql_null_if_missing(schema, "projection_threads", "updated_at", "updated_at"),
        sql_null_if_missing(schema, "projection_threads", "deleted_at", "deleted_at"),
        sql_null_if_missing(schema, "projection_threads", "archived_at", "archived_at"),
        sql_null_if_missing(schema, "projection_threads", "branch", "branch"),
        sql_null_if_missing(schema, "projection_threads", "worktree_path", "worktree_path"),
        f"{quote_ident('projection_projects')}.{quote_ident('title')} AS {quote_ident('project_title')}",
        sql_null_if_missing(schema, "projection_projects", "workspace_root", "workspace_root"),
        sql_null_if_missing(schema, "projection_projects", "deleted_at", "project_deleted_at"),
    ]
    if can_join_sessions(schema):
        pieces.extend(
            [
                sql_null_if_missing(schema, "projection_thread_sessions", "provider_name", "provider_name"),
                sql_null_if_missing(
                    schema, "projection_thread_sessions", "provider_session_id", "provider_session_id"
                ),
                sql_null_if_missing(
                    schema, "projection_thread_sessions", "provider_thread_id", "provider_thread_id"
                ),
                sql_null_if_missing(
                    schema, "projection_thread_sessions", "provider_instance_id", "provider_instance_id"
                ),
            ]
        )
    else:
        pieces.extend(
            [
                "NULL AS provider_name",
                "NULL AS provider_session_id",
                "NULL AS provider_thread_id",
                "NULL AS provider_instance_id",
            ]
        )
    return ",\n          ".join(pieces)


def can_join_sessions(schema: DatabaseSchema) -> bool:
    return schema.has_column("projection_thread_sessions", "thread_id")


def thread_from(schema: DatabaseSchema) -> str:
    sql = f"""
        FROM {quote_ident("projection_threads")}
        LEFT JOIN {quote_ident("projection_projects")}
          ON {quote_ident("projection_projects")}.{quote_ident("project_id")}
           = {quote_ident("projection_threads")}.{quote_ident("project_id")}
    """
    if can_join_sessions(schema):
        sql += f"""
        LEFT JOIN {quote_ident("projection_thread_sessions")}
          ON {quote_ident("projection_thread_sessions")}.{quote_ident("thread_id")}
           = {quote_ident("projection_threads")}.{quote_ident("thread_id")}
        """
    return sql


def row_to_match(
    row: sqlite3.Row,
    *,
    source: str,
    snippet: str | None,
    message_created_at: str | None,
    database: Candidate,
    rank: int,
) -> Match:
    return Match(
        thread_id=row["thread_id"],
        title=row["title"],
        project_id=row["project_id"],
        project_title=row["project_title"],
        workspace_root=row["workspace_root"],
        branch=row["branch"],
        worktree_path=row["worktree_path"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived=row["archived_at"] is not None,
        deleted=row["deleted_at"] is not None,
        project_deleted=row["project_deleted_at"] is not None,
        source=source,
        sources=[source],
        snippet=snippet,
        message_created_at=message_created_at,
        provider_name=row["provider_name"] if "provider_name" in row.keys() else None,
        provider_session_id=row["provider_session_id"] if "provider_session_id" in row.keys() else None,
        provider_thread_id=row["provider_thread_id"] if "provider_thread_id" in row.keys() else None,
        provider_instance_id=row["provider_instance_id"] if "provider_instance_id" in row.keys() else None,
        database=str(database.path),
        database_kind=database.kind,
        rank=rank,
        environment_id=database.environment_id,
        host=database.host,
        provenance=database.provenance,
        scoped_id=scoped_identity(database.environment_id, row["thread_id"]),
    )


def merge_matches(matches: Iterable[Match]) -> list[Match]:
    best: dict[tuple[str, str, str], Match] = {}
    for match in matches:
        key = (match.environment_id or "", match.database, match.thread_id)
        current = best.get(key)
        if current is None:
            best[key] = match
            continue
        sources = list(dict.fromkeys([*current.sources, *match.sources]))
        match_key = (match.rank, match.updated_at is None, match.updated_at or "", match.thread_id)
        current_key = (current.rank, current.updated_at is None, current.updated_at or "", current.thread_id)
        if match_key < current_key:
            winner = match
            snippet = match.snippet or current.snippet
            message_created_at = match.message_created_at or current.message_created_at
        else:
            winner = current
            snippet = current.snippet or match.snippet
            message_created_at = current.message_created_at or match.message_created_at
        best[key] = Match(
            **{
                **asdict(winner),
                "sources": sources,
                "snippet": snippet,
                "message_created_at": message_created_at,
            }
        )
    ordered = list(best.values())
    ordered.sort(key=lambda item: item.thread_id)
    ordered.sort(key=lambda item: item.updated_at or "", reverse=True)
    ordered.sort(key=lambda item: item.rank)
    return ordered


def search_metadata(
    conn: sqlite3.Connection,
    schema: DatabaseSchema,
    candidate: Candidate,
    query: str,
    *,
    active_only: bool,
    include_deleted: bool,
    project: str | None,
    since: str | None,
    until: str | None,
    thread_id: str | None,
    limit: int,
) -> list[Match]:
    status_sql, status_params = thread_status_filters(
        schema, active_only=active_only, include_deleted=include_deleted
    )
    project_sql, project_params = project_filter_sql(schema, project)
    recency_sql, recency_params = recency_filter_sql(schema, since, until)
    thread_sql, thread_params = thread_id_filter_sql(thread_id)
    pattern = like_contains(query)
    exact = query

    where_common = f"{status_sql}{project_sql}{recency_sql}{thread_sql}"
    common_params = [*status_params, *project_params, *recency_params, *thread_params]

    clauses: list[tuple[str, str, list[Any], str]] = [
        (
            "thread_id",
            f"{quote_ident('projection_threads')}.{quote_ident('thread_id')} = ?",
            [exact],
            "thread_id",
        ),
        (
            "title",
            f"{quote_ident('projection_threads')}.{quote_ident('title')} LIKE ? ESCAPE '{LIKE_ESCAPE}'",
            [pattern],
            "title",
        ),
        (
            "project",
            f"{quote_ident('projection_projects')}.{quote_ident('title')} LIKE ? ESCAPE '{LIKE_ESCAPE}'",
            [pattern],
            "project_title",
        ),
    ]
    if schema.has_column("projection_projects", "workspace_root"):
        clauses.append(
            (
                "project",
                f"{quote_ident('projection_projects')}.{quote_ident('workspace_root')} LIKE ? ESCAPE '{LIKE_ESCAPE}'",
                [pattern],
                "workspace_root",
            )
        )
    if schema.has_column("projection_threads", "branch"):
        clauses.append(
            (
                "branch",
                f"{quote_ident('projection_threads')}.{quote_ident('branch')} LIKE ? ESCAPE '{LIKE_ESCAPE}'",
                [pattern],
                "branch",
            )
        )
    if schema.has_column("projection_threads", "worktree_path"):
        clauses.append(
            (
                "branch",
                f"{quote_ident('projection_threads')}.{quote_ident('worktree_path')} LIKE ? ESCAPE '{LIKE_ESCAPE}'",
                [pattern],
                "worktree_path",
            )
        )
    if schema.has_column("projection_threads", "thread_id"):
        clauses.append(
            (
                "thread_id",
                f"{quote_ident('projection_threads')}.{quote_ident('thread_id')} LIKE ? ESCAPE '{LIKE_ESCAPE}'",
                [pattern],
                "thread_id",
            )
        )

    matches: list[Match] = []
    rank_table = UI_RANK if active_only else RANK
    seen_sql: set[tuple[str, str]] = set()
    for source, clause, params, snippet_field in clauses:
        key = (source, clause)
        if key in seen_sql:
            continue
        seen_sql.add(key)
        sql = f"""
            SELECT {thread_select(schema)}
            {thread_from(schema)}
            WHERE ({clause})
            {where_common}
            ORDER BY {quote_ident("projection_threads")}.{quote_ident("updated_at") if schema.has_column("projection_threads", "updated_at") else "thread_id"} DESC
            LIMIT ?
        """
        rows = conn.execute(sql, [*params, *common_params, limit]).fetchall()
        for row in rows:
            snippet = row[snippet_field] if snippet_field in row.keys() else row["title"]
            matches.append(
                row_to_match(
                    row,
                    source=source,
                    snippet=build_snippet(snippet, query),
                    message_created_at=None,
                    database=candidate,
                    rank=rank_table.get(source, 9),
                )
            )
    return matches


def search_providers(
    conn: sqlite3.Connection,
    schema: DatabaseSchema,
    candidate: Candidate,
    query: str,
    *,
    active_only: bool,
    include_deleted: bool,
    project: str | None,
    since: str | None,
    until: str | None,
    thread_id: str | None,
    limit: int,
) -> list[Match]:
    if active_only or not can_join_sessions(schema):
        return []
    columns = [
        column
        for column in ("provider_session_id", "provider_thread_id", "provider_instance_id", "provider_name")
        if schema.has_column("projection_thread_sessions", column)
    ]
    if not columns:
        return []
    status_sql, status_params = thread_status_filters(
        schema, active_only=active_only, include_deleted=include_deleted
    )
    project_sql, project_params = project_filter_sql(schema, project)
    recency_sql, recency_params = recency_filter_sql(schema, since, until)
    thread_sql, thread_params = thread_id_filter_sql(thread_id)
    likes = " OR ".join(
        f"{quote_ident('projection_thread_sessions')}.{quote_ident(column)} LIKE ? ESCAPE '{LIKE_ESCAPE}'"
        for column in columns
    )
    exacts = " OR ".join(
        f"{quote_ident('projection_thread_sessions')}.{quote_ident(column)} = ?" for column in columns
    )
    pattern = like_contains(query)
    sql = f"""
        SELECT {thread_select(schema)}
        {thread_from(schema)}
        WHERE (({exacts}) OR ({likes}))
        {status_sql}{project_sql}{recency_sql}{thread_sql}
        LIMIT ?
    """
    params = [
        *([query] * len(columns)),
        *([pattern] * len(columns)),
        *status_params,
        *project_params,
        *recency_params,
        *thread_params,
        limit,
    ]
    matches: list[Match] = []
    folded = fold_ascii_case(query)
    for row in conn.execute(sql, params):
        snippet = None
        for column in columns:
            if column not in row.keys() or row[column] is None:
                continue
            value = str(row[column])
            haystack = fold_ascii_case(value)
            if haystack == folded or folded in haystack:
                snippet = value
                break
        if snippet is None:
            snippet = next((str(row[column]) for column in columns if column in row.keys() and row[column]), None)
        matches.append(
            row_to_match(
                row,
                source="provider",
                snippet=build_snippet(snippet, query),
                message_created_at=None,
                database=candidate,
                rank=RANK["provider"],
            )
        )
    return matches


def search_messages(
    conn: sqlite3.Connection,
    schema: DatabaseSchema,
    candidate: Candidate,
    query: str,
    *,
    active_only: bool,
    include_deleted: bool,
    project: str | None,
    since: str | None,
    until: str | None,
    thread_id: str | None,
    limit: int,
) -> list[Match]:
    if not schema.has_table("projection_thread_messages"):
        return []
    messages = schema.table("projection_thread_messages")
    assert messages is not None
    for needed in ("thread_id", "role", "text"):
        if not messages.has(needed):
            return []

    status_sql, status_params = thread_status_filters(
        schema, active_only=active_only, include_deleted=include_deleted
    )
    project_sql, project_params = project_filter_sql(schema, project)
    recency_sql, recency_params = recency_filter_sql(schema, since, until)
    thread_sql, thread_params = thread_id_filter_sql(thread_id)
    pattern = like_contains(query)
    streaming_sql = ""
    if messages.has("is_streaming"):
        streaming_sql = f" AND {quote_ident('projection_thread_messages')}.{quote_ident('is_streaming')} = 0"

    if active_only:
        if not (
            schema.has_column("projection_turns", "assistant_message_id")
            and schema.has_column("projection_thread_messages", "message_id")
        ):
            assistant_sql = ""
        else:
            assistant_sql = f"""
                OR (
                  {quote_ident("projection_thread_messages")}.{quote_ident("role")} = 'assistant'
                  AND {quote_ident("projection_thread_messages")}.{quote_ident("message_id")} IN (
                    SELECT {quote_ident("projection_turns")}.{quote_ident("assistant_message_id")}
                    FROM {quote_ident("projection_turns")}
                    WHERE {quote_ident("projection_turns")}.{quote_ident("assistant_message_id")} IS NOT NULL
                  )
                )
            """
        role_sql = f"""
            AND (
              {quote_ident("projection_thread_messages")}.{quote_ident("role")} = 'user'
              {assistant_sql}
            )
        """
        message_created_expr = (
            f"{quote_ident('projection_thread_messages')}.{quote_ident('created_at')}"
            if schema.has_column("projection_thread_messages", "created_at")
            else "NULL"
        )
        message_id_expr = (
            f"{quote_ident('projection_thread_messages')}.{quote_ident('message_id')}"
            if schema.has_column("projection_thread_messages", "message_id")
            else f"{quote_ident('projection_threads')}.{quote_ident('thread_id')}"
        )
        sql = f"""
            WITH ranked AS (
              SELECT
                {thread_select(schema)},
                CASE {quote_ident("projection_thread_messages")}.{quote_ident("role")}
                  WHEN 'user' THEN 'user'
                  ELSE 'assistant'
                END AS match_source,
                {quote_ident("projection_thread_messages")}.{quote_ident("text")} AS match_text,
                {message_created_expr} AS message_created_at,
                CASE {quote_ident("projection_thread_messages")}.{quote_ident("role")}
                  WHEN 'user' THEN 0
                  ELSE 1
                END AS match_rank,
                ROW_NUMBER() OVER (
                  PARTITION BY {quote_ident("projection_threads")}.{quote_ident("thread_id")}
                  ORDER BY
                    CASE {quote_ident("projection_thread_messages")}.{quote_ident("role")}
                      WHEN 'user' THEN 0
                      ELSE 1
                    END ASC,
                    {message_created_expr} DESC,
                    {message_id_expr} ASC
                ) AS thread_match_rank
              FROM {quote_ident("projection_thread_messages")}
              INNER JOIN {quote_ident("projection_threads")}
                ON {quote_ident("projection_threads")}.{quote_ident("thread_id")}
                 = {quote_ident("projection_thread_messages")}.{quote_ident("thread_id")}
              INNER JOIN {quote_ident("projection_projects")}
                ON {quote_ident("projection_projects")}.{quote_ident("project_id")}
                 = {quote_ident("projection_threads")}.{quote_ident("project_id")}
              {"LEFT JOIN " + quote_ident("projection_thread_sessions") + " ON " + quote_ident("projection_thread_sessions") + "." + quote_ident("thread_id") + " = " + quote_ident("projection_threads") + "." + quote_ident("thread_id") if can_join_sessions(schema) else ""}
              WHERE {quote_ident("projection_thread_messages")}.{quote_ident("text")} LIKE ? ESCAPE '{LIKE_ESCAPE}'
              {streaming_sql}
              {role_sql}
              {status_sql}{project_sql}{recency_sql}{thread_sql}
            )
            SELECT * FROM ranked
            WHERE thread_match_rank = 1
            ORDER BY match_rank ASC, updated_at DESC, thread_id ASC
            LIMIT ?
        """
        params = [pattern, *status_params, *project_params, *recency_params, *thread_params, limit]
        rows = conn.execute(sql, params).fetchall()
        matches: list[Match] = []
        for row in rows:
            source = row["match_source"]
            matches.append(
                row_to_match(
                    row,
                    source=source,
                    snippet=build_snippet(row["match_text"], query),
                    message_created_at=row["message_created_at"],
                    database=candidate,
                    rank=UI_RANK.get(source, 2),
                )
            )
        return matches

    message_created_expr = (
        f"{quote_ident('projection_thread_messages')}.{quote_ident('created_at')}"
        if schema.has_column("projection_thread_messages", "created_at")
        else "NULL"
    )
    message_id_expr = (
        f"{quote_ident('projection_thread_messages')}.{quote_ident('message_id')}"
        if schema.has_column("projection_thread_messages", "message_id")
        else f"{quote_ident('projection_threads')}.{quote_ident('thread_id')}"
    )
    sql = f"""
        WITH ranked AS (
          SELECT
            {thread_select(schema)},
            CASE {quote_ident("projection_thread_messages")}.{quote_ident("role")}
              WHEN 'user' THEN 'user'
              ELSE 'assistant'
            END AS match_source,
            {quote_ident("projection_thread_messages")}.{quote_ident("text")} AS match_text,
            {message_created_expr} AS message_created_at,
            CASE {quote_ident("projection_thread_messages")}.{quote_ident("role")}
              WHEN 'user' THEN 0 ELSE 1
            END AS match_rank,
            ROW_NUMBER() OVER (
              PARTITION BY {quote_ident("projection_threads")}.{quote_ident("thread_id")}
              ORDER BY
                CASE {quote_ident("projection_thread_messages")}.{quote_ident("role")}
                  WHEN 'user' THEN 0 ELSE 1
                END ASC,
                {message_created_expr} DESC,
                {message_id_expr} ASC
            ) AS thread_match_rank
          FROM {quote_ident("projection_thread_messages")}
          INNER JOIN {quote_ident("projection_threads")}
            ON {quote_ident("projection_threads")}.{quote_ident("thread_id")}
             = {quote_ident("projection_thread_messages")}.{quote_ident("thread_id")}
          LEFT JOIN {quote_ident("projection_projects")}
            ON {quote_ident("projection_projects")}.{quote_ident("project_id")}
             = {quote_ident("projection_threads")}.{quote_ident("project_id")}
          {"LEFT JOIN " + quote_ident("projection_thread_sessions") + " ON " + quote_ident("projection_thread_sessions") + "." + quote_ident("thread_id") + " = " + quote_ident("projection_threads") + "." + quote_ident("thread_id") if can_join_sessions(schema) else ""}
          WHERE {quote_ident("projection_thread_messages")}.{quote_ident("text")} LIKE ? ESCAPE '{LIKE_ESCAPE}'
            AND {quote_ident("projection_thread_messages")}.{quote_ident("role")} IN ('user', 'assistant')
            {streaming_sql}
            {status_sql}{project_sql}{recency_sql}{thread_sql}
        )
        SELECT * FROM ranked
        WHERE thread_match_rank = 1
        ORDER BY match_rank ASC, updated_at DESC, thread_id ASC
        LIMIT ?
    """
    params = [pattern, *status_params, *project_params, *recency_params, *thread_params, limit]
    matches = []
    for row in conn.execute(sql, params):
        source = row["match_source"]
        matches.append(
            row_to_match(
                row,
                source=source,
                snippet=build_snippet(row["match_text"], query),
                message_created_at=row["message_created_at"],
                database=candidate,
                rank=RANK.get(source, 3),
            )
        )
    return matches


def v2_filters(*, active_only: bool, include_deleted: bool, project: str | None,
               since: str | None, until: str | None, thread_id: str | None) -> tuple[str, list[Any]]:
    clauses, params = [], []
    if not include_deleted:
        clauses.append("t.deleted_at IS NULL")
    if active_only:
        clauses.extend(["t.archived_at IS NULL", "p.deleted_at IS NULL"])
    if project:
        clauses.append(f"(p.title LIKE ? ESCAPE '{LIKE_ESCAPE}' OR p.workspace_root LIKE ? ESCAPE '{LIKE_ESCAPE}')")
        params.extend([like_contains(project)] * 2)
    for value, expression in ((since, "julianday(t.updated_at) >= julianday(?)"),
                              (until, "julianday(t.updated_at) <= julianday(?)"),
                              (thread_id, "t.thread_id = ?")):
        if value:
            clauses.append(expression)
            params.append(value)
    return (" AND " + " AND ".join(clauses) if clauses else ""), params


def parse_pr(value: str) -> tuple[int, str | None, str | None]:
    if value.isdigit() and int(value) > 0:
        return int(value), None, None
    parsed = urlparse(value)
    match = re.fullmatch(r"/([^/]+/[^/]+)/pull/([1-9][0-9]*)/?", parsed.path)
    if parsed.scheme in {"http", "https"} and parsed.hostname and match and not parsed.username and not parsed.password:
        return int(match[2]), parsed.hostname, match[1]
    raise UsageError("--pr must be a positive PR number or an HTTP(S) owner/repository/pull/number URL.")


def search_pull_requests(conn: sqlite3.Connection, schema: DatabaseSchema, candidate: Candidate,
                         pr: str, *, limit: int, **filters: Any) -> tuple[list[Match], list[str]]:
    v2 = schema.has_table("orchestration_v2_projection_threads")
    if not v2 and not schema.has_table("projection_thread_pull_requests"):
        return [], [f"{candidate.path}: PR links unavailable; check the PR body's attribution thread: line."]
    number, host, repository = parse_pr(pr)
    number_expr = "json_extract(pr.value, '$.number')" if v2 else "pr.number"
    host_expr = "json_extract(pr.value, '$.host')" if v2 else "pr.host"
    repository_expr = "json_extract(pr.value, '$.repository')" if v2 else "pr.repository"
    url_expr = "json_extract(pr.value, '$.url')" if v2 else "pr.url"
    predicate = f"{number_expr} = ?"
    params: list[Any] = [number]
    if host:
        predicate += f" AND {host_expr} = ? AND {repository_expr} = ?"
        params.extend([host, repository])
    if v2:
        select, from_sql = v2_select(schema), v2_from(schema)
        where, filter_params = v2_filters(**filters)
        join = "JOIN json_each(t.payload_json, '$.pullRequests') AS pr"
        order = "t.updated_at DESC, t.thread_id"
    else:
        select, from_sql = thread_select(schema), thread_from(schema)
        pieces = [thread_status_filters(schema, active_only=filters['active_only'], include_deleted=filters['include_deleted']),
                  project_filter_sql(schema, filters['project']),
                  recency_filter_sql(schema, filters['since'], filters['until']),
                  thread_id_filter_sql(filters['thread_id'])]
        where = "".join(piece[0] for piece in pieces)
        filter_params = [param for piece in pieces for param in piece[1]]
        thread_expr = "projection_threads.thread_id"
        join = f"JOIN projection_thread_pull_requests AS pr ON pr.thread_id = {thread_expr}"
        order = "projection_threads.updated_at DESC, projection_threads.thread_id" if schema.has_column('projection_threads', 'updated_at') else thread_expr
    rows = conn.execute(f"""SELECT {select}, {url_expr} AS pr_url {from_sql} {join}
        WHERE {predicate} {where} ORDER BY {order} LIMIT ?""",
        [*params, *filter_params, limit])
    matches = [row_to_match(row, source="pr", snippet=row['pr_url'], message_created_at=None,
                            database=candidate, rank=0) for row in rows]
    warnings = v2_warnings(schema) if v2 else []
    if not matches:
        warnings.append("No stored PR link found; check the PR body's attribution thread: line.")
    return matches, warnings


def search_v2(conn: sqlite3.Connection, schema: DatabaseSchema, candidate: Candidate,
              query: str, *, limit: int, pr: str | None = None, **filters: Any) -> tuple[list[Match], list[str]]:
    if pr:
        return search_pull_requests(conn, schema, candidate, pr, limit=limit, **filters)
    where, params = v2_filters(**filters)
    matches: list[Match] = []
    warnings = v2_warnings(schema)
    metadata = {
        "thread_id": ["t.thread_id"], "title": ["t.title"],
        "project": ["p.title", "p.workspace_root"],
        "branch": ["json_extract(t.payload_json, '$.branch')"],
        "provider": [f"s.{column}" for column in SESSION_COLUMNS[1:]
                     if schema.has_column('orchestration_v2_projection_provider_threads', column)],
    }
    # V2 calls the provider field `provider`, not the legacy `provider_name`.
    if schema.has_table('orchestration_v2_projection_provider_threads'):
        metadata['provider'].append('s.provider')
        if schema.has_column('orchestration_v2_projection_provider_threads', 'payload_json'):
            metadata['provider'].append("json_extract(s.payload_json, '$.nativeThreadRef.nativeId')")
    else:
        del metadata['provider']
    for source, expressions in metadata.items():
        predicate = " OR ".join(f"{expr} LIKE ? ESCAPE '{LIKE_ESCAPE}'" for expr in expressions)
        rows = conn.execute(f"""SELECT {v2_select(schema)} {v2_from(schema, all_providers=source == 'provider')}
            WHERE ({predicate}) {where} ORDER BY t.updated_at DESC, t.thread_id LIMIT ?""",
            [*[like_contains(query)] * len(expressions), *params, limit])
        for row in rows:
            snippet = row['title'] if source == 'title' else None
            matches.append(row_to_match(row, source=source, snippet=snippet, message_created_at=None,
                                        database=candidate, rank=RANK[source]))
    if len(query) < 3 or not schema.has_table('orchestration_v2_projection_messages'):
        return matches, warnings
    fts = conn.execute("SELECT sql FROM sqlite_schema WHERE name = ? AND type = 'table'",
                       ('orchestration_v2_message_search',)).fetchone()
    if not fts or not re.search(r"USING\s+fts5\s*\(", fts[0], re.IGNORECASE):
        warnings.append(f"{candidate.path}: v2 FTS5 message index unavailable; searched metadata only (no message scan).")
        return matches, warnings
    # This is a contentless trigram index. Its rowids refer to message rowids;
    # retrieve text from the payload only after the MATCH index has found rows.
    # Quote the whole phrase so FTS operators and punctuation stay literal.
    phrase = query.replace('’', "'").replace('‘', "'")
    phrase = '"' + phrase.replace('"', '""') + '"'
    rows = conn.execute(f"""
        WITH ranked AS (
            SELECT {v2_select(schema)}, m.role AS match_source,
                   json_extract(m.payload_json, '$.text') AS match_text,
                   m.created_at AS message_created_at,
                   ROW_NUMBER() OVER (PARTITION BY t.thread_id ORDER BY
                       CASE m.role WHEN 'user' THEN 0 ELSE 1 END, m.created_at DESC, m.message_id) AS n
            {v2_from(schema)}
            JOIN orchestration_v2_projection_messages AS m ON m.thread_id = t.thread_id
            WHERE m.rowid IN (SELECT rowid FROM orchestration_v2_message_search
                              WHERE orchestration_v2_message_search MATCH ?)
              AND m.streaming = 0 AND m.role IN ('user', 'assistant') {where}
        )
        SELECT * FROM ranked WHERE n = 1
        ORDER BY CASE match_source WHEN 'user' THEN 0 ELSE 1 END, updated_at DESC, thread_id LIMIT ?
    """, [phrase, *params, limit])
    for row in rows:
        source = row['match_source']
        matches.append(row_to_match(row, source=source, snippet=build_snippet(row['match_text'], query),
                                    message_created_at=row['message_created_at'], database=candidate,
                                    rank=(UI_RANK if filters['active_only'] else RANK)[source]))
    return matches, warnings


def show_thread_v2(conn: sqlite3.Connection, schema: DatabaseSchema, candidate: Candidate,
                   thread_id: str, *, include_deleted: bool) -> tuple[ThreadDetail | None, list[str]]:
    where = "" if include_deleted else " AND t.deleted_at IS NULL"
    row = conn.execute(f"SELECT {v2_select(schema)} {v2_from(schema)} WHERE t.thread_id = ? {where}",
                       (thread_id,)).fetchone()
    if row is None:
        return None, []
    warnings = v2_warnings(schema)
    if not schema.has_table('orchestration_v2_projection_messages'):
        match = row_to_match(row, source="thread_id", snippet=None, message_created_at=None, database=candidate, rank=0)
        fields = asdict(match)
        for key in ('source', 'sources', 'snippet', 'message_created_at', 'rank'):
            del fields[key]
        return ThreadDetail(**fields, message_counts={}, first_user_snippet=None, last_assistant_snippet=None), warnings
    counts = dict(conn.execute("""SELECT role, COUNT(*) FROM orchestration_v2_projection_messages
                                 WHERE thread_id = ? GROUP BY role""", (thread_id,)))
    snippets = []
    for role, direction in (("user", "ASC"), ("assistant", "DESC")):
        message = conn.execute(f"""SELECT json_extract(payload_json, '$.text')
            FROM orchestration_v2_projection_messages WHERE thread_id = ? AND role = ? AND streaming = 0
            ORDER BY created_at {direction}, message_id LIMIT 1""", (thread_id, role)).fetchone()
        snippets.append(build_snippet(message[0], None) if message else None)
    match = row_to_match(row, source="thread_id", snippet=None, message_created_at=None, database=candidate, rank=0)
    fields = asdict(match)
    for key in ('source', 'sources', 'snippet', 'message_created_at', 'rank'):
        del fields[key]
    return ThreadDetail(**fields, message_counts=counts, first_user_snippet=snippets[0],
                        last_assistant_snippet=snippets[1]), warnings


def search_database(
    candidate: Candidate,
    query: str,
    *,
    active_only: bool,
    include_deleted: bool,
    project: str | None,
    since: str | None,
    until: str | None,
    thread_id: str | None,
    limit: int,
    pr: str | None = None,
) -> tuple[list[Match], list[str]]:
    warnings: list[str] = []
    conn = connect_readonly(candidate.path)
    try:
        schema = inspect_schema(conn, candidate.path)
        require_projection_schema(schema)
        if schema.has_table("orchestration_v2_projection_threads"):
            return search_v2(conn, schema, candidate, query, active_only=active_only,
                             include_deleted=include_deleted, project=project, since=since,
                             until=until, thread_id=thread_id, limit=limit, pr=pr)
        if pr:
            return search_pull_requests(conn, schema, candidate, pr, active_only=active_only,
                                        include_deleted=include_deleted, project=project,
                                        since=since, until=until, thread_id=thread_id, limit=limit)
        if schema.missing_optional:
            warnings.append(
                f"{candidate.path}: optional table(s) missing: {', '.join(schema.missing_optional)}."
            )
        if schema.missing_columns:
            details = "; ".join(
                f"{table}: {', '.join(columns)}" for table, columns in schema.missing_columns.items()
            )
            warnings.append(f"{candidate.path}: optional column(s) missing: {details}.")
        if active_only:
            if not schema.has_column("projection_threads", "deleted_at"):
                warnings.append(
                    f"{candidate.path}: missing projection_threads.deleted_at; --active-only cannot exclude deleted threads."
                )
            if not schema.has_column("projection_threads", "archived_at"):
                warnings.append(
                    f"{candidate.path}: missing projection_threads.archived_at; --active-only cannot exclude archived threads."
                )
            if not schema.has_column("projection_thread_messages", "is_streaming"):
                warnings.append(
                    f"{candidate.path}: missing is_streaming; --active-only cannot exclude streaming messages."
                )
        matches = [
            *search_metadata(
                conn,
                schema,
                candidate,
                query,
                active_only=active_only,
                include_deleted=include_deleted,
                project=project,
                since=since,
                until=until,
                thread_id=thread_id,
                limit=limit,
            ),
            *search_providers(
                conn,
                schema,
                candidate,
                query,
                active_only=active_only,
                include_deleted=include_deleted,
                project=project,
                since=since,
                until=until,
                thread_id=thread_id,
                limit=limit,
            ),
            *search_messages(
                conn,
                schema,
                candidate,
                query,
                active_only=active_only,
                include_deleted=include_deleted,
                project=project,
                since=since,
                until=until,
                thread_id=thread_id,
                limit=limit,
            ),
        ]
        return matches, warnings
    except sqlite3.Error as error:
        raise SearchError(f"{candidate.path}: SQLite error: {error}") from error
    finally:
        conn.close()


def show_thread(
    candidate: Candidate, thread_id: str, *, include_deleted: bool
) -> tuple[ThreadDetail | None, list[str]]:
    warnings: list[str] = []
    conn = connect_readonly(candidate.path)
    try:
        schema = inspect_schema(conn, candidate.path)
        require_projection_schema(schema)
        if schema.has_table("orchestration_v2_projection_threads"):
            return show_thread_v2(conn, schema, candidate, thread_id, include_deleted=include_deleted)
        status_sql, status_params = thread_status_filters(
            schema, active_only=False, include_deleted=include_deleted
        )
        sql = f"""
            SELECT {thread_select(schema)}
            {thread_from(schema)}
            WHERE {quote_ident("projection_threads")}.{quote_ident("thread_id")} = ?
            {status_sql}
            LIMIT 1
        """
        row = conn.execute(sql, [thread_id, *status_params]).fetchone()
        if row is None:
            return None, warnings

        counts: dict[str, int] = {}
        first_user = None
        last_assistant = None
        messages_ok = all(
            schema.has_column("projection_thread_messages", column)
            for column in ("thread_id", "role", "text")
        )
        if schema.has_table("projection_thread_messages") and messages_ok:
            count_rows = conn.execute(
                f"""
                SELECT {quote_ident("role")} AS role, COUNT(*) AS n
                FROM {quote_ident("projection_thread_messages")}
                WHERE {quote_ident("thread_id")} = ?
                GROUP BY {quote_ident("role")}
                """,
                [thread_id],
            ).fetchall()
            counts = {item["role"]: item["n"] for item in count_rows}
            order_column = (
                "created_at"
                if schema.has_column("projection_thread_messages", "created_at")
                else ("message_id" if schema.has_column("projection_thread_messages", "message_id") else None)
            )
            order_sql = f"ORDER BY {quote_ident(order_column)} ASC" if order_column else ""
            user_row = conn.execute(
                f"""
                SELECT {quote_ident("text")} AS text
                FROM {quote_ident("projection_thread_messages")}
                WHERE {quote_ident("thread_id")} = ?
                  AND {quote_ident("role")} = 'user'
                {order_sql}
                LIMIT 1
                """,
                [thread_id],
            ).fetchone()
            if user_row:
                first_user = build_snippet(user_row["text"], None)
            assistant_sql = f"""
                SELECT {quote_ident("projection_thread_messages")}.{quote_ident("text")} AS text
                FROM {quote_ident("projection_thread_messages")}
                WHERE {quote_ident("projection_thread_messages")}.{quote_ident("thread_id")} = ?
                  AND {quote_ident("projection_thread_messages")}.{quote_ident("role")} = 'assistant'
            """
            params: list[Any] = [thread_id]
            can_canonical = (
                schema.has_column("projection_turns", "assistant_message_id")
                and schema.has_column("projection_thread_messages", "message_id")
            )
            if can_canonical:
                assistant_sql += f"""
                  AND {quote_ident("projection_thread_messages")}.{quote_ident("message_id")} IN (
                    SELECT {quote_ident("projection_turns")}.{quote_ident("assistant_message_id")}
                    FROM {quote_ident("projection_turns")}
                    WHERE {quote_ident("projection_turns")}.{quote_ident("assistant_message_id")} IS NOT NULL
                      {"AND " + quote_ident("projection_turns") + "." + quote_ident("thread_id") + " = ?" if schema.has_column("projection_turns", "thread_id") else ""}
                  )
                """
                if schema.has_column("projection_turns", "thread_id"):
                    params.append(thread_id)
            else:
                warnings.append(
                    f"{candidate.path}: canonical assistant linkage unavailable; omitting last assistant snippet."
                )
            if can_canonical:
                desc_order = (
                    f"{quote_ident('projection_thread_messages')}.{quote_ident('created_at')}"
                    if schema.has_column("projection_thread_messages", "created_at")
                    else (
                        f"{quote_ident('projection_thread_messages')}.{quote_ident('message_id')}"
                        if schema.has_column("projection_thread_messages", "message_id")
                        else None
                    )
                )
                assistant_sql += f" ORDER BY {desc_order} DESC LIMIT 1" if desc_order else " LIMIT 1"
                assistant_row = conn.execute(assistant_sql, params).fetchone()
                if assistant_row:
                    last_assistant = build_snippet(assistant_row["text"], None)
        elif schema.has_table("projection_thread_messages"):
            warnings.append(
                f"{candidate.path}: projection_thread_messages is missing thread_id/role/text; skipping snippets."
            )

        detail = ThreadDetail(
            thread_id=row["thread_id"],
            title=row["title"],
            project_id=row["project_id"],
            project_title=row["project_title"],
            workspace_root=row["workspace_root"],
            branch=row["branch"],
            worktree_path=row["worktree_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            archived=row["archived_at"] is not None,
            deleted=row["deleted_at"] is not None,
            project_deleted=row["project_deleted_at"] is not None,
            provider_name=row["provider_name"],
            provider_session_id=row["provider_session_id"],
            provider_thread_id=row["provider_thread_id"],
            provider_instance_id=row["provider_instance_id"] if "provider_instance_id" in row.keys() else None,
            message_counts=counts,
            first_user_snippet=first_user,
            last_assistant_snippet=last_assistant,
            database=str(candidate.path),
            database_kind=candidate.kind,
            environment_id=candidate.environment_id,
            host=candidate.host,
            provenance=candidate.provenance,
            scoped_id=scoped_identity(candidate.environment_id, row["thread_id"]),
        )
        return detail, warnings
    except sqlite3.Error as error:
        raise SearchError(f"{candidate.path}: SQLite error: {error}") from error
    finally:
        conn.close()


def match_to_dict(match: Match) -> dict[str, Any]:
    payload = asdict(match)
    status = []
    if match.deleted:
        status.append("deleted")
    if match.archived:
        status.append("archived")
    if match.project_deleted:
        status.append("project-deleted")
    if not status:
        status.append("active")
    payload["status"] = "+".join(status)
    payload["scoped_id"] = match.scoped_id or scoped_identity(match.environment_id, match.thread_id)
    return payload


def format_status(match: Match | ThreadDetail) -> str:
    labels = []
    if match.deleted:
        labels.append("DELETED")
    if match.archived:
        labels.append("archived")
    if match.project_deleted:
        labels.append("project-deleted")
    return ", ".join(labels) if labels else "active"


def format_text_report(report: SearchReport) -> str:
    lines: list[str] = []
    lines.append(f"mode: {report.mode}")
    if report.query:
        lines.append(f"query: {report.query}")
    if report.environments:
        lines.append("environments:")
        for environment in report.environments:
            env_id = environment.get("environment_id") or "unknown"
            status = environment.get("status") or "listed"
            extra = []
            if environment.get("host"):
                extra.append(f"host={environment['host']}")
            if environment.get("database"):
                extra.append(environment["database"])
            suffix = f"  {' '.join(extra)}" if extra else ""
            lines.append(
                f"  - {env_id}  {status}  via {environment.get('provenance') or environment.get('source') or '-'}{suffix}"
            )
    lines.append("databases:")
    for database in report.databases:
        marker = "searched" if database.get("searched") else ("missing" if not database.get("exists") else "listed")
        extra = ""
        if database.get("exists"):
            extra = f"  size={database.get('size_bytes')} mtime={database.get('mtime')}"
        env = f" env={database['environment_id']}" if database.get("environment_id") else ""
        lines.append(
            f"  - [{database['kind']}, {database.get('role', 'unknown')}] {database['path']} ({marker}, via {database['source']}){env}{extra}"
        )
    if report.warnings:
        lines.append("warnings:")
        for warning in report.warnings:
            lines.append(f"  - {warning}")
    if not report.results:
        lines.append("results: 0")
        if report.not_found_kind == "not_queried":
            lines.append(NOT_QUERIED_REMOTE_MESSAGE)
            lines.append(REMOTE_REQUEST_HINT)
        elif report.not_found_kind == "not_found":
            lines.append("Not found in the environments searched.")
        else:
            lines.append("No matching threads. Try a shorter query, --include-deleted, or --list-dbs.")
        return "\n".join(lines) + "\n"

    lines.append(f"results: {len(report.results)}{' (truncated)' if report.truncated else ''}")
    for index, item in enumerate(report.results, start=1):
        lines.append("")
        title = item.get("title") or "(untitled)"
        identity = item.get("scoped_id") or item.get("thread_id")
        lines.append(f"{index}. {identity}  {title!r}")
        env_line = f"   environment: {item.get('environment_id') or 'unknown'}"
        if item.get("host"):
            env_line += f"  host: {item['host']}"
        lines.append(env_line)
        project = item.get("project_title") or "(no project)"
        workspace = item.get("workspace_root") or ""
        lines.append(f"   project: {project}  {workspace}".rstrip())
        location = []
        if item.get("branch"):
            location.append(f"branch {item['branch']}")
        if item.get("worktree_path"):
            location.append(f"worktree {item['worktree_path']}")
        if location:
            lines.append("   " + " · ".join(location))
        lines.append(
            f"   created: {item.get('created_at') or '-'}  updated: {item.get('updated_at') or '-'}"
        )
        lines.append(f"   status: {item.get('status')}")
        sources = ", ".join(item.get("sources") or [item["source"]])
        match_line = f"   match: {sources}"
        if item.get("message_created_at"):
            match_line += f" @ {item['message_created_at']}"
        lines.append(match_line)
        if item.get("snippet"):
            lines.append(f"   snippet: {item['snippet']}")
        if item.get("provider_thread_id") or item.get("provider_session_id") or item.get("provider_instance_id"):
            lines.append(
                "   provider: "
                + " ".join(
                    part
                    for part in (
                        item.get("provider_name"),
                        item.get("provider_instance_id"),
                        item.get("provider_thread_id"),
                        item.get("provider_session_id"),
                    )
                    if part
                )
            )
        lines.append(
            f"   provenance: {item.get('provenance') or item.get('database_kind')}  {item.get('database')}"
        )
    if report.query and len(report.query) < 3:
        lines.append("")
        lines.append("note: short queries become broad %term% LIKE scans and can be slow on large databases.")
    lines.append("")
    lines.append("Follow up with --db <path> --thread <thread_id> for one thread's metadata and bounded snippets.")
    return "\n".join(lines) + "\n"


def format_thread_detail(detail: ThreadDetail) -> str:
    lines = [
        f"identity: {detail.scoped_id or scoped_identity(detail.environment_id, detail.thread_id)}",
        f"environment: {detail.environment_id or 'unknown'}",
        f"thread: {detail.thread_id}",
        f"title: {detail.title}",
        f"project: {detail.project_title or '-'}  {detail.workspace_root or ''}".rstrip(),
        f"branch: {detail.branch or '-'}  worktree: {detail.worktree_path or '-'}",
        f"created: {detail.created_at or '-'}  updated: {detail.updated_at or '-'}",
        f"status: {format_status(detail)}",
        f"provider: {detail.provider_name or '-'}  instance={detail.provider_instance_id or '-'}  session={detail.provider_session_id or '-'}  thread={detail.provider_thread_id or '-'}",
        f"messages: {detail.message_counts or '{}'}",
        f"host: {detail.host or '-'}",
        f"provenance: {detail.provenance}  {detail.database}",
    ]
    if detail.first_user_snippet:
        lines.append(f"first user: {detail.first_user_snippet}")
    if detail.last_assistant_snippet:
        lines.append(f"last assistant: {detail.last_assistant_snippet}")
    lines.append("Full conversation text is intentionally omitted.")
    return "\n".join(lines) + "\n"


def standalone_search_source() -> bytes:
    """Bundle shared storage and search in memory for `python3 -I -` over SSH.

    Local commands use ordinary package imports. The remote host needs only
    Python: no skill installation, temporary code files, or database copies.
    """
    shared = Path(store.__file__).read_text(encoding="utf-8")
    module = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.level:
            store_names = node.module == 'store' and all(
                name.name != '*' and not name.asname for name in node.names
            )
            store_module = node.module is None and len(node.names) == 1 and (
                node.names[0].name == 'store' and not node.names[0].asname
            )
            if node.level != 1 or node not in module.body or not (store_names or store_module):
                raise SearchError("Cannot bundle SSH search: unsupported package dependency.")
    module.body = [node for node in module.body if not (
        isinstance(node, ast.ImportFrom) and (node.level or node.module == "__future__")
    )]
    return (shared + "\n" + ast.unparse(module) + "\nraise SystemExit(main())\n").encode("utf-8")


def run_ssh_search(
    target: str,
    *,
    remote_argv: list[str],
    ssh_exec: Callable[[list[str], bytes], Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    # OpenSSH joins the remote command into a string and runs it through the
    # remote shell. Quote every argument so query/path values cannot inject.
    remote_command = " ".join(["python3", "-I", "-", *(shlex.quote(arg) for arg in remote_argv)])
    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "--",
        target,
        remote_command,
    ]
    stdin = standalone_search_source()
    try:
        if ssh_exec is not None:
            completed = ssh_exec(argv, stdin)
        else:
            completed = subprocess.run(argv, input=stdin, capture_output=True, check=False)
    except OSError as error:
        return None, str(error)
    if getattr(completed, "returncode", 1) != 0:
        stderr = getattr(completed, "stderr", b"") or b""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return None, str(stderr).strip() or f"ssh exit {completed.returncode}"
    stdout = getattr(completed, "stdout", b"") or b""
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8")
    try:
        return redact_secrets(json.loads(stdout)), None
    except json.JSONDecodeError as error:
        return None, f"Remote helper returned invalid JSON: {error}"


def run_search(
    *,
    query: str | None,
    cwd: Path,
    home: Path,
    env: Mapping[str, str],
    db: str | None = None,
    base_dir: str | None = None,
    project: str | None = None,
    since: str | None = None,
    until: str | None = None,
    active_only: bool = False,
    include_deleted: bool = False,
    limit: int = DEFAULT_LIMIT,
    thread_id: str | None = None,
    list_dbs: bool = False,
    now: datetime | None = None,
    environment_id: str | None = None,
    endpoint: str | None = None,
    ssh: str | None = None,
    ssh_base_dir: str | None = None,
    remote_json: str | None = None,
    remotes: list[RemoteEnvironment] | None = None,
    ssh_exec: Callable[[list[str], bytes], Any] | None = None,
    pr: str | None = None,
) -> SearchReport:
    if active_only and include_deleted:
        raise UsageError("--active-only already excludes deleted threads; do not combine it with --include-deleted.")
    if limit < 1 or limit > MAX_LIMIT:
        raise UsageError(f"--limit must be between 1 and {MAX_LIMIT}.")
    if pr:
        parse_pr(pr)
        if query or thread_id or remote_json or remotes or endpoint:
            raise UsageError("Use --pr without a query, --thread, or remote RPC results; --ssh is supported.")

    # A positional UUID can be an app thread ID or a provider's native ID.
    # Keep it as a search across both; --thread is the unambiguous exact lookup.
    query_ref = parse_thread_ref(query) if query and not UUID_RE.fullmatch(query.strip()) else None
    thread_ref = parse_thread_ref(thread_id, explicit=True)
    if thread_id is not None and thread_ref is None:
        raise UsageError("--thread must be a non-empty thread ID, environment/thread ID, or T3 URL.")
    if thread_ref is None and query_ref is not None and query is not None and query.strip() == query_ref.raw:
        thread_ref = query_ref
    env_filter = environment_id
    host_from_url = None
    if thread_ref is not None:
        if thread_ref.thread_id:
            thread_id = thread_ref.thread_id
        if environment_id and thread_ref.environment_id and environment_id != thread_ref.environment_id:
            raise UsageError("--environment does not match the environment in --thread.")
        if env_filter is None:
            env_filter = thread_ref.environment_id
        host_from_url = thread_ref.host
        if query is not None and query.strip() == thread_ref.raw:
            query = None

    if not list_dbs and not (thread_id or pr or (query and query.strip())):
        raise UsageError("Provide a search query, or use --list-dbs / --thread / --pr.")

    since_value = parse_when(since, now=now) if since else None
    until_value = parse_when(until, now=now, end_of_day=True) if until else None
    candidates = [bind_candidate(candidate) for candidate in discover_candidates(cwd=cwd, home=home, env=env, db=db, base_dir=base_dir)]
    databases = [candidate_metadata(candidate) for candidate in candidates]
    environment_records: list[dict[str, Any]] = []
    warnings: list[str] = []
    remote_queried = False

    loaded_remotes = list(remotes or [])
    if remote_json:
        loaded_remotes.extend(load_remote_json(Path(remote_json)))

    if list_dbs:
        environment_records = [
            {
                "environment_id": item.get("environment_id"),
                "status": "listed" if item.get("exists") else "missing",
                "provenance": "sqlite",
                "host": None,
                "database": item.get("path"),
                "kind": item.get("kind"),
            }
            for item in databases
        ]
        for remote in loaded_remotes:
            environment_records.append(
                {
                    "environment_id": remote.environment_id,
                    "status": remote.status,
                    "provenance": remote.provenance,
                    "host": remote.host,
                    "database": remote.host,
                    "kind": remote.provenance,
                    "error": remote.error,
                }
            )
        return SearchReport(
            mode="list-dbs",
            query=None,
            databases=databases,
            results=[],
            warnings=[],
            truncated=False,
            limit=limit,
            environments=environment_records,
            remote_queried=bool(loaded_remotes),
        )

    existing = [candidate for candidate in candidates if candidate.path.is_file() and candidate.searchable]
    if env_filter:
        searchable = [candidate for candidate in existing if candidate.environment_id == env_filter]
        skipped = [candidate for candidate in existing if candidate.environment_id != env_filter]
        for candidate in skipped:
            meta = next(item for item in databases if item["path"] == str(candidate.path))
            meta["status"] = "not_searched"
            meta["reason"] = "environment mismatch" if candidate.environment_id else "unidentified environment"
            environment_records.append(
                {
                    "environment_id": candidate.environment_id,
                    "status": "not_searched",
                    "provenance": "sqlite",
                    "host": None,
                    "database": str(candidate.path),
                    "kind": candidate.kind,
                    "note": meta["reason"],
                }
            )
        existing = searchable
    files_exist = any(candidate.path.is_file() for candidate in candidates)
    if not existing and not loaded_remotes and not ssh and not endpoint and not files_exist:
        if db or base_dir:
            target = candidates[0].path if candidates else db or base_dir
            raise SearchError(
                f"Database does not exist at {str(target)!r}. Pass a real SQLite file or T3 base dir."
            )
        considered = "\n".join(f"  - {item['kind']}: {item['path']}" for item in databases) or "  (none)"
        raise SearchError(
            "No T3 SQLite database found. Considered:\n"
            f"{considered}\n"
            "Pass --db PATH or --base-dir PATH. This tool does not recursively scan the home directory."
        )

    lookup_only = bool(thread_id and not query and not pr)
    mode = "thread" if lookup_only else ("ui" if active_only else "recovery")
    results: list[dict[str, Any]] = []
    matches: list[Match] = []

    for candidate in existing:
        db_meta = next(item for item in databases if item["path"] == str(candidate.path))
        try:
            if lookup_only:
                detail, detail_warnings = show_thread(
                    candidate, thread_id, include_deleted=include_deleted
                )
                warnings.extend(detail_warnings)
                db_meta["searched"] = True
                environment_records.append(
                    {
                        "environment_id": candidate.environment_id,
                        "status": "searched",
                        "provenance": "sqlite",
                        "host": None,
                        "database": str(candidate.path),
                        "kind": candidate.kind,
                    }
                )
                if detail is not None:
                    payload = asdict(detail) | {"status": format_status(detail)}
                    payload["scoped_id"] = detail.scoped_id or scoped_identity(
                        detail.environment_id, detail.thread_id
                    )
                    results.append(payload)
                continue
            found, db_warnings = search_database(
                candidate,
                query or "",
                active_only=active_only,
                include_deleted=include_deleted,
                project=project,
                since=since_value,
                until=until_value,
                thread_id=thread_id,
                limit=limit,
                pr=pr,
            )
        except SearchError as error:
            db_meta["error"] = str(error)
            warnings.append(str(error))
            environment_records.append(
                {
                    "environment_id": candidate.environment_id,
                    "status": "error",
                    "provenance": "sqlite",
                    "host": None,
                    "database": str(candidate.path),
                    "kind": candidate.kind,
                    "error": str(error),
                }
            )
            continue
        db_meta["searched"] = True
        matches.extend(found)
        warnings.extend(db_warnings)
        if not lookup_only:
            environment_records.append(
                {
                    "environment_id": candidate.environment_id,
                    "status": "searched",
                    "provenance": "sqlite",
                    "host": None,
                    "database": str(candidate.path),
                    "kind": candidate.kind,
                }
            )

    for remote in loaded_remotes:
        if env_filter and remote.environment_id and remote.environment_id != env_filter:
            environment_records.append(
                {
                    "environment_id": remote.environment_id,
                    "status": "not_searched",
                    "provenance": remote.provenance,
                    "host": remote.host,
                    "database": remote.host,
                    "kind": remote.provenance,
                    "note": "environment mismatch",
                }
            )
            continue
        environment_records.append(
            {
                "environment_id": remote.environment_id,
                "status": remote.status,
                "provenance": remote.provenance,
                "host": remote.host,
                "database": remote.host,
                "kind": remote.provenance,
                "error": remote.error,
            }
        )
        if remote.status == "disconnected":
            warnings.append(
                f"Environment {remote.environment_id or remote.host or 'unknown'} is disconnected."
            )
            continue
        if remote.status != "searched":
            continue
        remote_queried = True
        if lookup_only:
            remote_details = remote.details or [
                item for item in remote.matches if (item.get("thread_id") or item.get("threadId")) == thread_id
            ]
            for item in remote_details:
                if (item.get("thread_id") or item.get("threadId")) != thread_id:
                    continue
                results.append(remote_match_to_result(remote, item))
        else:
            for item in remote.matches:
                results.append(remote_match_to_result(remote, item))

    if ssh:
        remote_argv = ["--json"]
        if pr:
            remote_argv.extend(["--pr", pr])
        if lookup_only:
            remote_argv.extend(["--thread", thread_id or ""])
        elif query:
            remote_argv.append(query)
        if include_deleted:
            remote_argv.append("--include-deleted")
        if active_only:
            remote_argv.append("--active-only")
        if env_filter:
            remote_argv.extend(["--environment", env_filter])
        remote_home = ssh_base_dir or "~/.t3"
        remote_argv.extend(["--base-dir", remote_home])
        payload, ssh_error = run_ssh_search(
            ssh,
            remote_argv=remote_argv,
            ssh_exec=ssh_exec,
        )
        if ssh_error is not None:
            environment_records.append(
                {
                    "environment_id": env_filter,
                    "status": "disconnected",
                    "provenance": "ssh",
                    "host": ssh,
                    "database": None,
                    "kind": "ssh",
                    "error": ssh_error,
                }
            )
            warnings.append(f"SSH environment {ssh} is disconnected.")
        else:
            remote_queried = True
            environment_records.extend(payload.get("environments") or [])
            results.extend(payload.get("results") or [])
            warnings.extend(payload.get("warnings") or [])

    if endpoint:
        covered = any(
            record.get("host") == endpoint or record.get("database") == endpoint
            for record in environment_records
        )
        if not covered:
            environment_records.append(
                {
                    "environment_id": env_filter,
                    "status": "not_queried",
                    "provenance": "endpoint",
                    "host": endpoint or host_from_url,
                    "database": None,
                    "kind": "endpoint",
                    "note": "No authenticated T3 RPC results were supplied for this endpoint.",
                }
            )
            warnings.append(
                f"Endpoint {endpoint} was not queried. Provide --remote-json from an authenticated T3 RPC session, or --ssh with authorization."
            )

    if not lookup_only:
        merged = merge_matches(matches)
        results = [match_to_dict(match) for match in merged] + results

    truncated = len(results) > limit
    results = results[:limit]
    if query is not None and len(query) < 3:
        warnings.append(
            "Queries shorter than three characters search metadata only on v2; trigram message search requires at least three characters. Legacy message search uses LIKE."
        )

    searched_any = any(item.get("searched") for item in databases) or remote_queried
    if not searched_any and not remote_queried and (db or base_dir) and any(item.get("error") for item in databases):
        raise SearchError(
            "No searchable T3 database among the candidates.\n" + "\n".join(warnings)
        )

    not_found_kind = None
    if not results and (lookup_only or thread_id):
        if remote_queried:
            not_found_kind = "not_found"
            warnings.append("Not found in the environments searched.")
        else:
            not_found_kind = "not_queried"
            warnings.append(NOT_QUERIED_REMOTE_MESSAGE)
            warnings.append(REMOTE_REQUEST_HINT)

    return SearchReport(
        mode=mode,
        query=query,
        databases=databases,
        results=redact_secrets(results),
        warnings=warnings,
        truncated=truncated,
        limit=limit,
        environments=redact_secrets(environment_records),
        remote_queried=remote_queried,
        not_found_kind=not_found_kind,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="t3-thread search",
        description="Read-only search of T3 Code projection threads in statev2.sqlite (legacy supported).",
        epilog=(
            "Opens SQLite with mode=ro and PRAGMA query_only=ON. Never copies, vacuums, "
            "indexes, or starts a T3 server against the database. Default recovery search "
            "includes archived non-deleted threads. --active-only excludes archived/deleted threads "
            "and deleted projects. V2 message search uses T3's FTS5 index."
        ),
    )
    parser.add_argument("query", nargs="?", help="Text to search in titles, messages, projects, or provider IDs.")
    parser.add_argument("--pr", help="Find threads linked to a PR number or full pull request URL.")
    parser.add_argument("--db", help="Exact SQLite file, userdata directory, or T3 base directory (prefers statev2.sqlite).")
    parser.add_argument(
        "--base-dir",
        "--home-dir",
        dest="base_dir",
        help="T3 base/home directory. Prefers <base-dir>/userdata/statev2.sqlite (legacy fallback).",
    )
    parser.add_argument("--project", help="Restrict to project title or workspace path (LIKE, parameterized).")
    parser.add_argument("--since", help="Only threads updated at/after this time (ISO date/time or 7d/24h/30m).")
    parser.add_argument(
        "--until",
        help="Only threads updated at/before this time. A date-only value is the end of that day.",
    )
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Exclude archived/deleted threads and deleted projects. V2 uses indexed non-streaming messages.",
    )
    parser.add_argument(
        "--include-deleted",
        action="store_true",
        help="Include deleted threads (labeled). Default recovery search excludes them.",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Max results (default {DEFAULT_LIMIT}, max {MAX_LIMIT}).")
    parser.add_argument(
        "--thread",
        dest="thread_id",
        help="Thread ID, environmentId/threadId, or a full T3 thread URL.",
    )
    parser.add_argument(
        "--environment",
        dest="environment_id",
        help="Restrict to this T3 environmentId. Combined with --thread this is the canonical identity.",
    )
    parser.add_argument(
        "--endpoint",
        help="Remote T3 HTTP(S) endpoint. Does not scrape credentials; without --remote-json it is recorded as not queried.",
    )
    parser.add_argument(
        "--ssh",
        help="Explicit SSH target that owns the database. Runs this helper remotely; never copies the remote DB.",
    )
    parser.add_argument(
        "--ssh-base-dir",
        help="Remote T3 base/home directory for --ssh (default ~/.t3 → userdata/statev2.sqlite).",
    )
    parser.add_argument(
        "--remote-json",
        help="Sanitized RPC/search results from connected environments (no tokens). Used to merge federated search.",
    )
    parser.add_argument("--list-dbs", action="store_true", help="List candidate databases and exit.")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON on stdout.")
    parser.add_argument("--cwd", help="Directory used for linked-worktree discovery (default: process cwd).")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


def run(args: argparse.Namespace) -> int:
    cwd = expand_path(args.cwd, cwd=Path.cwd()) if args.cwd else Path.cwd()
    try:
        report = run_search(
            query=args.query,
            cwd=cwd,
            home=Path.home(),
            env=os.environ,
            db=args.db,
            base_dir=args.base_dir,
            project=args.project,
            since=args.since,
            until=args.until,
            active_only=args.active_only,
            include_deleted=args.include_deleted,
            limit=args.limit,
            thread_id=args.thread_id,
            list_dbs=args.list_dbs,
            environment_id=args.environment_id,
            endpoint=args.endpoint,
            ssh=args.ssh,
            ssh_base_dir=args.ssh_base_dir,
            remote_json=args.remote_json,
            pr=args.pr,
        )
    except SearchError as error:
        if args.json:
            json.dump({"error": str(error)}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(error, file=sys.stderr)
        return error.exit_code

    if args.json:
        json.dump(redact_secrets(asdict(report)), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if report.mode == "list-dbs":
        print(format_text_report(report), end="")
        return 0
    if report.mode == "thread":
        for index, item in enumerate(report.results):
            if index:
                print("---")
            detail = ThreadDetail(
                thread_id=item["thread_id"],
                title=item["title"],
                project_id=item.get("project_id"),
                project_title=item.get("project_title"),
                workspace_root=item.get("workspace_root"),
                branch=item.get("branch"),
                worktree_path=item.get("worktree_path"),
                created_at=item.get("created_at"),
                updated_at=item.get("updated_at"),
                archived=item.get("archived", False),
                deleted=item.get("deleted", False),
                project_deleted=item.get("project_deleted", False),
                provider_name=item.get("provider_name"),
                provider_session_id=item.get("provider_session_id"),
                provider_thread_id=item.get("provider_thread_id"),
                provider_instance_id=item.get("provider_instance_id"),
                message_counts=item.get("message_counts") or {},
                first_user_snippet=item.get("first_user_snippet"),
                last_assistant_snippet=item.get("last_assistant_snippet"),
                database=item["database"],
                database_kind=item["database_kind"],
                environment_id=item.get("environment_id"),
                host=item.get("host"),
                provenance=item.get("provenance") or "sqlite",
                scoped_id=item.get("scoped_id"),
            )
            print(format_thread_detail(detail), end="")
        for warning in report.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0

    print(format_text_report(report), end="")
    return 0
