"""Read-only execution status for a T3 Code thread.

This intentionally reports projection state only.  It never sends a turn,
approves a request, retries a provider, or changes the SQLite database.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import store


DEFAULT_STALE_AFTER = timedelta(minutes=5)
DEFAULT_INTERVAL = timedelta(seconds=15)
MAX_WATCH = timedelta(minutes=30)
TERMINAL_STATES = {
    "completed",
    "error",
    "interrupted",
    "awaiting-approval",
    "awaiting-input",
    "idle/ready",
    "idle/stopped",
}
ERROR_KINDS = {
    "runtime.error",
    "provider.turn.start.failed",
    "provider.user-input.respond.failed",
    "checkpoint.capture.failed",
    "checkpoint.revert.failed",
}

# Summaries are useful diagnostics, but may contain command lines or credentials.
SECRET_VALUE = re.compile(
    r'''(?ix)
    (["']?(?:api[_ -]?key|token|secret|password|authorization|bearer|cookie|credential|private[_ -]?key)["']?
    \s*[:=]\s*)
    (?:(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}]+)
    '''
)
BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)
CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


class StatusError(Exception):
    pass


@dataclass
class ThreadStatus:
    thread_id: str
    scoped_id: str | None
    environment_id: str | None
    database: str
    database_kind: str
    provenance: str
    title: str
    project: str | None
    provider: str | None
    session_status: str | None
    session_updated_at: str | None
    turn_id: str | None
    turn_state: str | None
    state: str
    reason: str
    updated_at: str | None
    latest_user_message_at: str | None
    requested_at: str | None
    started_at: str | None
    completed_at: str | None
    last_activity_at: str | None
    last_activity_kind: str | None
    last_activity_summary: str | None
    activity_age_seconds: float | None
    pending_approvals: int
    pending_user_input: int
    last_error: str | None
    warnings: list[str] = field(default_factory=list)


def parse_duration(raw: str, *, allow_seconds: bool = True) -> timedelta:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([smhd])", raw.strip().lower())
    if not match:
        raise StatusError("duration must look like 30s, 5m, 2h, or 1d")
    value, unit = float(match.group(1)), match.group(2)
    if unit == "s":
        if not allow_seconds:
            raise StatusError("seconds are not allowed here")
        return timedelta(seconds=value)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    return timedelta(days=value)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)


def age_seconds(value: str | None, now: datetime) -> float | None:
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def safe_summary(value: str | None, limit: int = 180) -> str | None:
    if not value:
        return None
    text = CONTROL.sub(" ", str(value))
    text = SECRET_VALUE.sub(r"\1[REDACTED]", text)
    text = BEARER.sub("Bearer [REDACTED]", text)
    text = URL.sub("[URL]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def col(schema: Any, table: str, name: str, alias: str | None = None) -> str:
    target = alias or name
    if schema.has_column(table, name):
        return f"{qident(table)}.{qident(name)} AS {qident(target)}"
    return f"NULL AS {qident(target)}"


def row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        value = row[key]
    except (IndexError, KeyError, TypeError):
        return default
    return default if value is None else value


def latest_turn(conn: Any, schema: Any, thread_id: str) -> Any:
    if not schema.has_table("projection_turns") or not schema.has_column("projection_turns", "thread_id"):
        return None
    fields = [
        col(schema, "projection_turns", name)
        for name in (
            "row_id",
            "turn_id",
            "assistant_message_id",
            "state",
            "requested_at",
            "started_at",
            "completed_at",
        )
    ]
    order = "requested_at DESC, row_id DESC" if schema.has_column("projection_turns", "requested_at") else "row_id DESC"
    return conn.execute(
        f"SELECT {', '.join(fields)} FROM {qident('projection_turns')} "
        f"WHERE {qident('projection_turns')}.{qident('thread_id')} = ? ORDER BY {order} LIMIT 1",
        (thread_id,),
    ).fetchone()


def activity_rows(conn: Any, schema: Any, thread_id: str, turn_id: str | None) -> tuple[Any, Any, dict[str, str | None]]:
    if not schema.has_table("projection_thread_activities"):
        return None, None, {"input_requested": None, "input_resolved": None}
    table = "projection_thread_activities"
    fields = [col(schema, table, name) for name in ("activity_id", "turn_id", "kind", "tone", "summary", "created_at", "sequence")]
    where = f"{qident(table)}.{qident('thread_id')} = ?"
    params: list[Any] = [thread_id]
    order_parts = []
    if schema.has_column(table, "created_at"):
        order_parts.append(f"{qident(table)}.{qident('created_at')} DESC")
    if schema.has_column(table, "activity_id"):
        order_parts.append(f"{qident(table)}.{qident('activity_id')} DESC")
    order = ", ".join(order_parts) or "rowid DESC"
    overall = conn.execute(
        f"SELECT {', '.join(fields)} FROM {qident(table)} WHERE {where} ORDER BY {order} LIMIT 1",
        params,
    ).fetchone()
    active = overall
    if turn_id and schema.has_column(table, "turn_id"):
        active = conn.execute(
            f"SELECT {', '.join(fields)} FROM {qident(table)} WHERE {where} "
            f"AND ({qident(table)}.{qident('turn_id')} = ? OR {qident(table)}.{qident('turn_id')} IS NULL) "
            f"ORDER BY {order} LIMIT 1",
            [thread_id, turn_id],
        ).fetchone()
    unresolved = {"input_requested": None, "input_resolved": None}
    if (
        turn_id
        and schema.has_column(table, "turn_id")
        and schema.has_column(table, "kind")
        and schema.has_column(table, "created_at")
    ):
        times = conn.execute(
            f"SELECT MAX(CASE WHEN kind = 'user-input.requested' THEN created_at END), "
            f"MAX(CASE WHEN kind = 'user-input.resolved' THEN created_at END) "
            f"FROM {qident(table)} WHERE thread_id = ? AND turn_id = ?",
            (thread_id, turn_id),
        ).fetchone()
        if times:
            unresolved = {"input_requested": times[0], "input_resolved": times[1]}
    return overall, active, unresolved


def inspect_v2(conn: Any, schema: Any, candidate: Any, thread_id: str,
               stale_after: timedelta, now: datetime) -> ThreadStatus:
    row = conn.execute(f"""SELECT {store.v2_select(schema)}, s.status AS session_status,
        s.updated_at AS session_updated_at {store.v2_from(schema)} WHERE t.thread_id = ?""", (thread_id,)).fetchone()
    if row is None:
        raise StatusError(f"thread {thread_id} was not found in {candidate.path}")
    warnings = store.v2_warnings(schema)
    run = None
    if schema.has_table('orchestration_v2_projection_runs'):
        run = conn.execute("""SELECT run_id, status, requested_at, completed_at,
            json_extract(payload_json, '$.startedAt') AS started_at
            FROM orchestration_v2_projection_runs WHERE thread_id = ?
            ORDER BY CASE WHEN status IN ('running','waiting') THEN 0
                          WHEN status IN ('queued','preparing','starting') THEN 1
                          ELSE 2 END, ordinal DESC LIMIT 1""", (thread_id,)).fetchone()
    else:
        warnings.append('v2 runs unavailable; execution state is incomplete')
    run_id = row_value(run, 'run_id')
    run_state = row_value(run, 'status')
    provider_status = row_value(row, 'session_status')
    activity = None
    if schema.has_table('orchestration_v2_projection_turn_items') and run_id:
        activity = conn.execute("""SELECT type AS kind, updated_at AS created_at,
            json_extract(payload_json, '$.title') AS summary
            FROM orchestration_v2_projection_turn_items WHERE thread_id = ? AND run_id = ?
            ORDER BY updated_at DESC, ordinal DESC LIMIT 1""", (thread_id, run_id)).fetchone()
    else:
        warnings.append('v2 turn-item activity unavailable; liveness is weaker')
    activity_at = row_value(activity, 'created_at')
    activity_kind = row_value(activity, 'kind')
    activity_summary = safe_summary(row_value(activity, 'summary'))
    latest_user_message = None
    if schema.has_table('orchestration_v2_projection_messages'):
        user = conn.execute("""SELECT updated_at FROM orchestration_v2_projection_messages
            WHERE thread_id = ? AND role = 'user' AND streaming = 0
              AND json_extract(payload_json, '$.notification') IS NULL
              AND json_extract(payload_json, '$.delegatedCompletion') IS NULL
            ORDER BY updated_at DESC LIMIT 1""", (thread_id,)).fetchone()
        latest_user_message = user[0] if user else None
        if run_id:
            message = conn.execute("""SELECT updated_at FROM orchestration_v2_projection_messages
                WHERE thread_id = ? AND run_id = ? ORDER BY updated_at DESC LIMIT 1""", (thread_id, run_id)).fetchone()
            if message and (parse_timestamp(message[0]) or datetime.min.replace(tzinfo=timezone.utc)) > (
                parse_timestamp(activity_at) or datetime.min.replace(tzinfo=timezone.utc)
            ):
                activity_at, activity_kind, activity_summary = message[0], 'message.updated', None
    approvals = inputs = 0
    requests_available = schema.has_table('orchestration_v2_projection_runtime_requests')
    nodes_available = schema.has_table('orchestration_v2_projection_nodes')
    if requests_available and nodes_available and run_id:
        # Do not let an unresolved request from an older run override completion.
        counts = dict(conn.execute("""SELECT r.kind, COUNT(*)
            FROM orchestration_v2_projection_runtime_requests AS r
            JOIN orchestration_v2_projection_nodes AS n ON n.node_id = r.node_id
            WHERE r.thread_id = ? AND n.run_id = ? AND r.status = 'pending'
            GROUP BY r.kind""", (thread_id, run_id)))
        approvals = sum(count for kind, count in counts.items() if kind != 'user_input')
        inputs = counts.get('user_input', 0)
    elif not requests_available or not nodes_available:
        warnings.append('v2 runtime requests/nodes unavailable; approval and input blockers cannot be checked')
    if not activity_at:
        activity_at = row_value(run, 'started_at') or row_value(run, 'requested_at') or row_value(row, 'session_updated_at')
        warnings.append('no message/tool timestamp available; using run/provider time as weaker liveness evidence')
    age = age_seconds(activity_at, now)
    terminal = run_state in {'completed', 'failed', 'interrupted', 'cancelled', 'rolled_back'}
    if approvals and not terminal:
        state, reason = 'awaiting-approval', 'permission approval is pending for the active run'
    elif inputs and not terminal:
        state, reason = 'awaiting-input', 'user input is pending for the active run'
    elif run_state == 'failed':
        state, reason = 'error', 'latest run failed'
    elif run_state == 'completed':
        state, reason = 'completed', 'latest run completed'
    elif run_state in {'interrupted', 'cancelled', 'rolled_back'}:
        state, reason = 'interrupted', f'latest run is {run_state}'
    elif run_state in {'queued', 'preparing', 'starting'}:
        state, reason = 'queued', f'run is {run_state}'
    elif run_state in {'running', 'waiting'} or provider_status == 'active':
        state, reason = 'running/recent', 'active run has recent projection activity'
        if age is None or age > stale_after.total_seconds():
            state, reason = 'stale-suspect', 'no recent projection activity; this does not prove a hang'
        if run_state == 'waiting':
            warnings.append('run is waiting; no explicit approval/input blocker was found')
    elif provider_status == 'idle':
        state, reason = 'idle/ready', 'provider thread is idle'
    elif provider_status == 'not_loaded':
        state, reason = 'idle/stopped', 'provider thread is not loaded'
    else:
        state, reason = 'unknown', 'v2 projection has no recognized execution state'
    if terminal and provider_status == 'active':
        warnings.append('provider reports active while the latest run is terminal')
    for field in ('archived_at', 'deleted_at'):
        if row_value(row, field):
            warnings.append(f'thread is {field.removesuffix("_at")}')
    env_id = candidate.environment_id or store.read_environment_id(candidate.path)
    return ThreadStatus(
        thread_id=thread_id, scoped_id=store.scoped_identity(env_id, thread_id), environment_id=env_id,
        database=str(candidate.path), database_kind=candidate.kind, provenance=candidate.provenance,
        title=safe_summary(row['title'], 160) or '', project=safe_summary(row['project_title'], 120),
        provider=safe_summary(row['provider_name'], 80), session_status=provider_status,
        session_updated_at=row_value(row, 'session_updated_at'), turn_id=run_id, turn_state=run_state,
        state=state, reason=reason, updated_at=row['updated_at'], latest_user_message_at=latest_user_message,
        requested_at=row_value(run, 'requested_at'), started_at=row_value(run, 'started_at'),
        completed_at=row_value(run, 'completed_at'), last_activity_at=activity_at, last_activity_kind=activity_kind,
        last_activity_summary=activity_summary, activity_age_seconds=age, pending_approvals=approvals,
        pending_user_input=inputs, last_error=None, warnings=warnings,
    )


def inspect_thread(candidate: Any, thread_id: str, stale_after: timedelta, now: datetime | None = None) -> ThreadStatus:
    now = now or datetime.now(timezone.utc)
    conn = store.connect_readonly(candidate.path)
    warnings: list[str] = []
    try:
        schema = store.inspect_schema(conn, candidate.path)
        store.require_projection_schema(schema)
        if schema.has_table("orchestration_v2_projection_threads"):
            return inspect_v2(conn, schema, candidate, thread_id, stale_after, now)
        if not schema.has_column("projection_threads", "thread_id"):
            raise StatusError(f"{candidate.path}: projection_threads has no thread_id")
        thread_fields = [
            col(schema, "projection_threads", name)
            for name in (
                "thread_id",
                "title",
                "project_id",
                "latest_turn_id",
                "updated_at",
                "latest_user_message_at",
                "pending_approval_count",
                "pending_user_input_count",
                "deleted_at",
                "archived_at",
            )
        ]
        project_join = ""
        project_field = "NULL AS project_title"
        if schema.has_table("projection_projects") and schema.has_column("projection_projects", "project_id"):
            project_join = f"LEFT JOIN {qident('projection_projects')} ON {qident('projection_projects')}.{qident('project_id')} = {qident('projection_threads')}.{qident('project_id')}"
            project_field = col(schema, "projection_projects", "title", "project_title")
        row = conn.execute(
            f"SELECT {', '.join(thread_fields)}, {project_field} FROM {qident('projection_threads')} "
            f"{project_join} WHERE {qident('projection_threads')}.{qident('thread_id')} = ? LIMIT 1",
            (thread_id,),
        ).fetchone()
        if row is None:
            raise StatusError(f"thread {thread_id} was not found in {candidate.path}")

        session = None
        if schema.has_table("projection_thread_sessions") and schema.has_column("projection_thread_sessions", "thread_id"):
            session_fields = [col(schema, "projection_thread_sessions", name) for name in ("status", "provider_name", "active_turn_id", "last_error", "updated_at")]
            session = conn.execute(
                f"SELECT {', '.join(session_fields)} FROM {qident('projection_thread_sessions')} WHERE thread_id = ? LIMIT 1",
                (thread_id,),
            ).fetchone()
        turn = latest_turn(conn, schema, thread_id)
        turn_id = row_value(turn, "turn_id") or row_value(session, "active_turn_id")
        overall, active, unresolved = activity_rows(conn, schema, thread_id, turn_id)
        activity = active or overall

        turn_state = row_value(turn, "state")
        session_status = row_value(session, "status")
        pending_approvals = int(row_value(row, "pending_approval_count", 0) or 0)
        pending_input = int(row_value(row, "pending_user_input_count", 0) or 0)
        latest_requested = row_value(turn, "requested_at")
        latest_user_message = row_value(row, "latest_user_message_at")
        latest_error = safe_summary(row_value(session, "last_error"))
        session_updated = row_value(session, "updated_at")
        activity_kind = row_value(activity, "kind")
        activity_at = row_value(activity, "created_at")
        activity_summary = safe_summary(row_value(activity, "summary"))
        last_activity_age = age_seconds(activity_at, now)
        requested_time = parse_timestamp(latest_requested)
        latest_user_time = parse_timestamp(latest_user_message)
        session_updated_time = parse_timestamp(session_updated)
        activity_time = parse_timestamp(activity_at)
        input_requested_time = parse_timestamp(unresolved["input_requested"])
        input_resolved_time = parse_timestamp(unresolved["input_resolved"])

        # A denied tool on the active turn is actionable even if the projection's
        # pending count has already been cleared.  Historical denials are ignored.
        denied_active = activity_kind == "tool.denied" and (
            not turn_id or row_value(activity, "turn_id") in (None, turn_id)
        ) and turn_state not in {"completed", "interrupted", "error"}
        input_wait = pending_input > 0 or (
            input_requested_time is not None
            and (
                input_resolved_time is None
                or input_requested_time > input_resolved_time
            )
        )
        error_activity = activity_kind in ERROR_KINDS and (
            requested_time is None or activity_time is None or activity_time >= requested_time
        )

        current_session_error = latest_error and turn_state not in {"completed", "interrupted"} and session_status == "running" and (
            requested_time is None or session_updated_time is None or session_updated_time >= requested_time
        )
        queued_message = (
            latest_user_time is not None
            and requested_time is not None
            and latest_user_time > requested_time
            and turn_state not in {"pending", "running"}
        )
        if turn_state == "error" or current_session_error:
            state, reason = "error", "provider/runtime error recorded"
        elif pending_approvals > 0 or denied_active:
            state, reason = "awaiting-approval", "permission approval is pending"
        elif input_wait:
            state, reason = "awaiting-input", "provider is waiting for user input"
        elif error_activity:
            state, reason = "error", "provider/runtime error recorded"
        elif queued_message:
            state, reason = "queued", "a newer user message is waiting for a turn"
        elif turn_state == "completed":
            state, reason = "completed", "latest turn completed"
        elif turn_state == "interrupted":
            state, reason = "interrupted", "latest turn was interrupted"
        elif turn_state == "pending":
            state, reason = "queued", "turn is pending start"
        elif turn_state == "running" or session_status == "running":
            state = "running/recent"
            reason = "active turn has recent projection activity"
            if last_activity_age is None:
                warnings.append("no activity timestamp is available")
            elif last_activity_age > stale_after.total_seconds():
                state = "stale-suspect"
                reason = "no projection activity exceeded the stale threshold; this does not prove a hang"
        elif session_status == "ready":
            state, reason = "idle/ready", "session is ready with no active turn"
        elif session_status == "stopped":
            state, reason = "idle/stopped", "session is stopped"
        else:
            state, reason = "unknown", "projection has no recognized execution state"

        if turn_state == "completed" and session_status == "running":
            warnings.append("session reports running while latest turn is completed")
        if latest_error and turn_state in {"completed", "interrupted"}:
            warnings.append("session last_error is historical relative to the latest terminal turn")
        if turn_state == "running" and session_status == "stopped":
            warnings.append("session reports stopped while latest turn is running")
        if not schema.has_table("projection_thread_activities"):
            warnings.append("projection_thread_activities is unavailable; liveness is weaker")
        if row_value(row, "deleted_at"):
            warnings.append("thread is deleted")
        if row_value(row, "archived_at"):
            warnings.append("thread is archived")

        env_id = candidate.environment_id or store.read_environment_id(candidate.path)
        return ThreadStatus(
            thread_id=thread_id,
            scoped_id=store.scoped_identity(env_id, thread_id),
            environment_id=env_id,
            database=str(candidate.path),
            database_kind=candidate.kind,
            provenance=candidate.provenance,
            title=safe_summary(row_value(row, "title"), 160) or "",
            project=safe_summary(row_value(row, "project_title"), 120),
            provider=safe_summary(row_value(session, "provider_name"), 80),
            session_status=session_status,
            session_updated_at=session_updated,
            turn_id=turn_id,
            turn_state=turn_state,
            state=state,
            reason=reason,
            updated_at=row_value(row, "updated_at"),
            latest_user_message_at=latest_user_message,
            requested_at=latest_requested,
            started_at=row_value(turn, "started_at"),
            completed_at=row_value(turn, "completed_at"),
            last_activity_at=activity_at,
            last_activity_kind=activity_kind,
            last_activity_summary=activity_summary,
            activity_age_seconds=last_activity_age,
            pending_approvals=pending_approvals,
            pending_user_input=pending_input,
            last_error=latest_error,
            warnings=warnings,
        )
    except store.SearchError:
        raise
    except Exception as error:
        if isinstance(error, StatusError):
            raise
        raise StatusError(f"{candidate.path}: SQLite status query failed: {error}") from error
    finally:
        conn.close()


def resolve_candidates(args: argparse.Namespace) -> tuple[list[Any], str]:
    ref = store.parse_thread_ref(args.thread, explicit=True)
    if ref is None or ref.thread_id is None:
        raise StatusError("--thread must be a non-empty thread ID, environment/thread ID, or T3 URL")
    if args.environment and ref.environment_id and args.environment != ref.environment_id:
        raise StatusError("--environment does not match the environment in --thread")
    env_id = args.environment or ref.environment_id
    cwd = Path(args.cwd).expanduser() if args.cwd else Path.cwd()
    home = Path.home()
    candidates = store.discover_candidates(cwd=cwd, home=home, env=dict(os.environ), db=args.db, base_dir=args.base_dir)
    candidates = [c for c in candidates if c.searchable]
    if env_id:
        candidates = [c for c in candidates if (c.environment_id or store.read_environment_id(c.path)) == env_id]
    if not candidates:
        raise StatusError("no local database matched the requested environment")
    return candidates, ref.thread_id


def format_text(item: ThreadStatus) -> str:
    lines = [
        f"state: {item.state}",
        f"identity: {item.scoped_id or item.thread_id}",
        f"thread: {item.thread_id}",
        f"title: {item.title}",
        f"project: {item.project or '-'}",
        f"provider: {item.provider or '-'}  session={item.session_status or '-'}",
        f"session updated: {item.session_updated_at or '-'}",
        f"turn: {item.turn_id or '-'}  state={item.turn_state or '-'}",
        f"reason: {item.reason}",
        f"last activity: {item.last_activity_at or '-'}  kind={item.last_activity_kind or '-'}  age={format_age(item.activity_age_seconds)}",
        f"pending: approvals={item.pending_approvals} user_input={item.pending_user_input}",
        f"database: {item.database} ({item.database_kind}, env={item.environment_id or 'unknown'})",
    ]
    if item.last_activity_summary:
        lines.append(f"activity summary: {item.last_activity_summary}")
    if item.last_error:
        lines.append(f"last error: {item.last_error}")
    for warning in item.warnings:
        lines.append(f"warning: {warning}")
    return "\n".join(lines) + "\n"


def format_age(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t3-thread status", description="Read-only T3 Code thread status")
    parser.add_argument("--thread", required=True, help="thread ID, environment/thread ID, or T3 URL")
    parser.add_argument("--environment", help="restrict to this environment ID")
    parser.add_argument("--db", help="exact SQLite file, userdata directory, or T3 base directory (prefers statev2.sqlite)")
    parser.add_argument("--base-dir", "--home-dir", dest="base_dir", help="T3 base directory containing userdata/statev2.sqlite (legacy fallback)")
    parser.add_argument("--cwd", help="working directory used for database discovery")
    parser.add_argument("--stale-after", default="5m", help="no-activity warning threshold (default: 5m)")
    parser.add_argument("--watch-for", help="finite monitoring duration, e.g. 10m (maximum 30m)")
    parser.add_argument("--interval", default="15s", help="monitoring interval (minimum 10s)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


def run(args: argparse.Namespace) -> int:
    try:
        stale_after = parse_duration(args.stale_after)
        if stale_after <= timedelta(0):
            raise StatusError("--stale-after must be positive")
        candidates, thread_id = resolve_candidates(args)
        statuses: list[ThreadStatus] = []
        matched_candidates: list[Any] = []
        discovery_warnings: list[str] = []
        for candidate in candidates:
            if not candidate.path.is_file():
                continue
            try:
                item = inspect_thread(candidate, thread_id, stale_after)
            except (StatusError, store.SearchError) as error:
                if args.db or args.base_dir:
                    raise
                if "was not found in" not in str(error):
                    discovery_warnings.append(f"Skipped database {candidate.path}: {error}")
                continue
            statuses.append(item)
            matched_candidates.append(candidate)
        if not statuses:
            detail = "; " + "; ".join(discovery_warnings) if discovery_warnings else ""
            raise StatusError(f"thread {thread_id} was not found in the local databases searched{detail}")

        watch_for = parse_duration(args.watch_for) if args.watch_for else None
        interval = parse_duration(args.interval)
        if watch_for is not None:
            if watch_for <= timedelta(0) or watch_for > MAX_WATCH:
                raise StatusError("--watch-for must be positive and no more than 30m")
            if interval < timedelta(seconds=10):
                raise StatusError("--interval must be at least 10s")
        deadline = time.monotonic() + watch_for.total_seconds() if watch_for else None
        previous_signature: tuple[Any, ...] | None = None
        while True:
            for item in statuses:
                item.warnings.extend(discovery_warnings)
            signature = tuple(
                (
                    item.scoped_id,
                    item.state,
                    item.turn_id,
                    item.turn_state,
                    item.last_activity_at,
                    item.pending_approvals,
                    item.pending_user_input,
                    item.last_error,
                )
                for item in statuses
            )
            terminal = any(item.state in TERMINAL_STATES for item in statuses)
            expired = deadline is not None and time.monotonic() >= deadline
            payload = [asdict(item) for item in statuses]
            if signature != previous_signature or expired:
                if args.json:
                    print(json.dumps(payload if len(payload) > 1 else payload[0], indent=2, sort_keys=True))
                else:
                    for index, item in enumerate(statuses):
                        if index:
                            print("---")
                        print(format_text(item), end="")
                previous_signature = signature
            if deadline is None or terminal or expired:
                return 0
            time.sleep(interval.total_seconds())
            statuses = [inspect_thread(candidate, thread_id, stale_after) for candidate in matched_candidates if candidate.path.is_file()]
    except (StatusError, store.SearchError) as error:
        if args.json:
            print(json.dumps({"error": safe_summary(str(error))}, indent=2))
        else:
            print(error, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
