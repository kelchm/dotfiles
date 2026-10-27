"""Read-only search over T3 Code's v2 projection database."""

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
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlparse

from . import store
from .store import (
    Candidate,
    SearchError,
    UUID_RE,
    UsageError,
    bind_candidate,
    candidate_metadata,
    connect_readonly,
    discover_candidates,
    expand_path,
    parse_thread_ref,
    require_projection_schema,
    scoped_identity,
    v2_from,
    v2_select,
)

LIKE_ESCAPE = "!"
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
SNIPPET_MAX = 240
SNIPPET_BODY = 236
SNIPPET_CONTEXT = 72
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


def escape_like_pattern(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def like_contains(value: str) -> str:
    return f"%{escape_like_pattern(value)}%"


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
        provider_name=row["provider_name"],
        provider_session_id=row["provider_session_id"],
        provider_thread_id=row["provider_thread_id"],
        provider_instance_id=row["provider_instance_id"],
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


def search_pull_requests(conn: sqlite3.Connection, candidate: Candidate,
                         pr: str, *, limit: int, **filters: Any) -> tuple[list[Match], list[str]]:
    number, host, repository = parse_pr(pr)
    predicate = "json_extract(pr.value, '$.number') = ?"
    params: list[Any] = [number]
    if host:
        predicate += " AND json_extract(pr.value, '$.host') = ? AND json_extract(pr.value, '$.repository') = ?"
        params.extend([host, repository])
    where, filter_params = v2_filters(**filters)
    rows = conn.execute(f"""SELECT {v2_select()}, json_extract(pr.value, '$.url') AS pr_url
        {v2_from()} JOIN json_each(t.payload_json, '$.pullRequests') AS pr
        WHERE {predicate} {where} ORDER BY t.updated_at DESC, t.thread_id LIMIT ?""",
        [*params, *filter_params, limit])
    matches = [row_to_match(row, source="pr", snippet=row['pr_url'], message_created_at=None,
                            database=candidate, rank=0) for row in rows]
    warnings = [] if matches else ["No stored PR link found; check the PR body's attribution thread: line."]
    return matches, warnings


def search_v2(conn: sqlite3.Connection, candidate: Candidate,
              query: str, *, limit: int, pr: str | None = None, **filters: Any) -> tuple[list[Match], list[str]]:
    if pr:
        return search_pull_requests(conn, candidate, pr, limit=limit, **filters)
    where, params = v2_filters(**filters)
    matches: list[Match] = []
    warnings: list[str] = []
    metadata = {
        "thread_id": ["t.thread_id"], "title": ["t.title"],
        "project": ["p.title", "p.workspace_root"],
        "branch": ["json_extract(t.payload_json, '$.branch')"],
        "provider": ["s.provider", "s.provider_session_id", "s.provider_thread_id", "s.provider_instance_id",
                     "json_extract(s.payload_json, '$.nativeThreadRef.nativeId')"],
    }
    for source, expressions in metadata.items():
        predicate = " OR ".join(f"{expr} LIKE ? ESCAPE '{LIKE_ESCAPE}'" for expr in expressions)
        rows = conn.execute(f"""SELECT {v2_select()} {v2_from(all_providers=source == 'provider')}
            WHERE ({predicate}) {where} ORDER BY t.updated_at DESC, t.thread_id LIMIT ?""",
            [*[like_contains(query)] * len(expressions), *params, limit])
        for row in rows:
            snippet = row['title'] if source == 'title' else None
            matches.append(row_to_match(row, source=source, snippet=snippet, message_created_at=None,
                                        database=candidate, rank=RANK[source]))
    if len(query) < 3:
        return matches, warnings
    # This is a contentless trigram index. Its rowids refer to message rowids;
    # retrieve text from the payload only after the MATCH index has found rows.
    # Quote the whole phrase so FTS operators and punctuation stay literal.
    phrase = query.replace('’', "'").replace('‘', "'")
    phrase = '"' + phrase.replace('"', '""') + '"'
    rows = conn.execute(f"""
        WITH ranked AS (
            SELECT {v2_select()}, m.role AS match_source,
                   json_extract(m.payload_json, '$.text') AS match_text,
                   m.created_at AS message_created_at,
                   ROW_NUMBER() OVER (PARTITION BY t.thread_id ORDER BY
                       CASE m.role WHEN 'user' THEN 0 ELSE 1 END, m.created_at DESC, m.message_id) AS n
            {v2_from()}
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
                                    rank=RANK[source]))
    return matches, warnings


def show_thread_v2(conn: sqlite3.Connection, candidate: Candidate,
                   thread_id: str, *, include_deleted: bool) -> tuple[ThreadDetail | None, list[str]]:
    where = "" if include_deleted else " AND t.deleted_at IS NULL"
    row = conn.execute(f"SELECT {v2_select()} {v2_from()} WHERE t.thread_id = ? {where}",
                       (thread_id,)).fetchone()
    if row is None:
        return None, []
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
                        last_assistant_snippet=snippets[1]), []


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
    conn = connect_readonly(candidate.path)
    try:
        require_projection_schema(conn, candidate.path)
        return search_v2(conn, candidate, query, active_only=active_only,
                         include_deleted=include_deleted, project=project, since=since,
                         until=until, thread_id=thread_id, limit=limit, pr=pr)
    except sqlite3.Error as error:
        raise SearchError(f"{candidate.path}: SQLite error: {error}") from error
    finally:
        conn.close()


def show_thread(candidate: Candidate, thread_id: str, *, include_deleted: bool
                ) -> tuple[ThreadDetail | None, list[str]]:
    conn = connect_readonly(candidate.path)
    try:
        require_projection_schema(conn, candidate.path)
        return show_thread_v2(conn, candidate, thread_id, include_deleted=include_deleted)
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
        lines.append("No matching threads in the databases searched. Try --include-deleted or --list-dbs.")
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
        return json.loads(stdout), None
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
    ssh: str | None = None,
    ssh_base_dir: str | None = None,
    ssh_exec: Callable[[list[str], bytes], Any] | None = None,
    pr: str | None = None,
) -> SearchReport:
    if active_only and include_deleted:
        raise UsageError("--active-only already excludes deleted threads; do not combine it with --include-deleted.")
    if limit < 1 or limit > MAX_LIMIT:
        raise UsageError(f"--limit must be between 1 and {MAX_LIMIT}.")
    if query and not pr and not thread_id and urlparse(query).scheme in {"http", "https"}:
        try:
            parse_pr(query)
        except UsageError:
            pass
        else:
            pr, query = query, None
    if pr:
        parse_pr(pr)
        if query or thread_id:
            raise UsageError("Use --pr without a query or --thread.")

    # A positional UUID can be an app thread ID or a provider's native ID.
    # Keep it as a search across both; --thread is the unambiguous exact lookup.
    query_ref = parse_thread_ref(query) if query and not UUID_RE.fullmatch(query.strip()) else None
    thread_ref = parse_thread_ref(thread_id, explicit=True)
    if thread_id is not None and thread_ref is None:
        raise UsageError("--thread must be a non-empty thread ID, environment/thread ID, or T3 URL.")
    if thread_ref is None:
        thread_ref = query_ref
    if thread_ref:
        thread_id = thread_ref.thread_id
        if environment_id and thread_ref.environment_id and environment_id != thread_ref.environment_id:
            raise UsageError("--environment does not match the environment in --thread.")
        environment_id = environment_id or thread_ref.environment_id
        if query and query.strip() == thread_ref.raw:
            query = None
    if not list_dbs and not (thread_id or pr or (query and query.strip())):
        raise UsageError("Provide a search query, or use --list-dbs / --thread / --pr.")

    since_value = parse_when(since, now=now) if since else None
    until_value = parse_when(until, now=now, end_of_day=True) if until else None
    candidates = [bind_candidate(candidate) for candidate in discover_candidates(
        cwd=cwd, home=home, env=env, db=db, base_dir=base_dir
    )]
    databases = [candidate_metadata(candidate) for candidate in candidates]
    warnings: list[str] = []
    if list_dbs:
        return SearchReport("list-dbs", None, databases, [], [], False, limit)
    existing = [candidate for candidate in candidates if candidate.searchable and candidate.path.is_file()]
    if environment_id and existing and not ssh and not any(
        candidate.environment_id == environment_id for candidate in existing
    ):
        raise UsageError("no local database matched the requested environment")

    lookup_only = bool(thread_id and not query and not pr)
    results: list[dict[str, Any]] = []
    matches: list[Match] = []
    for candidate, metadata in zip(candidates, databases):
        if not candidate.searchable or not candidate.path.is_file():
            continue
        if environment_id and candidate.environment_id != environment_id:
            metadata.update(status="not_searched", reason="environment mismatch or unidentified environment")
            continue
        try:
            if lookup_only:
                detail, db_warnings = show_thread(candidate, thread_id, include_deleted=include_deleted)
                if detail:
                    results.append(asdict(detail) | {"status": format_status(detail)})
            else:
                found, db_warnings = search_database(
                    candidate, query or "", active_only=active_only, include_deleted=include_deleted,
                    project=project, since=since_value, until=until_value, thread_id=thread_id,
                    limit=limit + 1, pr=pr,
                )
                matches.extend(found)
            metadata["searched"] = True
            warnings.extend(db_warnings)
        except SearchError as error:
            if db or base_dir:
                raise
            metadata["error"] = str(error)
            warnings.append(f"Skipped database {candidate.path}: {error}")
    results = [match_to_dict(match) for match in merge_matches(matches)] + results
    truncated = len(results) > limit

    if ssh:
        remote_argv = ["--json", "--limit", str(limit), "--base-dir", ssh_base_dir or "~/.t3"]
        for flag, value in (("--pr", pr), ("--thread", thread_id), ("--environment", environment_id),
                            ("--project", project), ("--since", since_value), ("--until", until_value)):
            if value:
                remote_argv.extend([flag, value])
        if include_deleted:
            remote_argv.append("--include-deleted")
        if active_only:
            remote_argv.append("--active-only")
        if query:
            remote_argv.extend(["--", query])
        payload, error = run_ssh_search(ssh, remote_argv=remote_argv, ssh_exec=ssh_exec)
        if error:
            raise SearchError(f"SSH search on {ssh} failed: {error}")
        for metadata in payload["databases"]:
            metadata.update(host=ssh, provenance="ssh")
            databases.append(metadata)
        for item in payload["results"]:
            item.update(host=ssh, provenance="ssh")
            results.append(item)
        warnings.extend(payload["warnings"])
        truncated = truncated or payload["truncated"] or len(results) > limit

    if not any(item.get("searched") for item in databases):
        errors = [item["error"] for item in databases if item.get("error")]
        if errors:
            raise SearchError("No searchable T3 database among the candidates.\n" + "\n".join(errors))
        if not any(item.get("exists") for item in databases):
            considered = "\n".join(f"  - {item['kind']}: {item['path']}" for item in databases)
            raise SearchError(f"No T3 v2 SQLite database found. Considered:\n{considered}\nPass --db PATH or --base-dir PATH.")
        if any(item.get("role", "").startswith("legacy") for item in databases) and not any(
            item.get("exists") and item.get("searchable") for item in databases
        ):
            raise SearchError("Only legacy state.sqlite stores found; this helper requires T3's statev2.sqlite.")
    if query is not None and len(query) < 3:
        warnings.append("Queries shorter than three characters search metadata only; trigram message search requires at least three characters.")
    if not results:
        warnings.append("Not found in the databases searched; other environments were not queried.")
    return SearchReport(
        mode="thread" if lookup_only else "recovery", query=query, databases=databases,
        results=results[:limit], warnings=warnings, truncated=truncated, limit=limit,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="t3-thread search",
        description="Read-only search of T3 Code projection threads in statev2.sqlite.",
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
        help="T3 base/home directory. Prefers <base-dir>/userdata/statev2.sqlite.",
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
        "--ssh",
        help="Explicit SSH target that owns the database. Runs this helper remotely; never copies the remote DB.",
    )
    parser.add_argument(
        "--ssh-base-dir",
        help="Remote T3 base/home directory for --ssh (default ~/.t3 → userdata/statev2.sqlite).",
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
            ssh=args.ssh,
            ssh_base_dir=args.ssh_base_dir,
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
        json.dump(asdict(report), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if report.mode == "list-dbs":
        print(format_text_report(report), end="")
        return 0
    if report.mode == "thread":
        for index, item in enumerate(report.results):
            if index:
                print("---")
            detail = ThreadDetail(**{field.name: item[field.name] for field in fields(ThreadDetail)})
            print(format_thread_detail(detail), end="")
        for warning in report.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0

    print(format_text_report(report), end="")
    return 0
