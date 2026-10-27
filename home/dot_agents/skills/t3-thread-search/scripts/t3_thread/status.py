"""Read-only execution status for a T3 Code thread.

This intentionally reports projection state only.  It never sends a turn,
approves a request, retries a provider, or changes the SQLite database.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import store


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


def parse_duration(raw: str) -> timedelta:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([smhd])", raw.strip().lower())
    if not match:
        raise StatusError("duration must look like 30s, 5m, 2h, or 1d")
    value, unit = float(match.group(1)), match.group(2)
    if unit == "s":
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


def row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        value = row[key]
    except (IndexError, KeyError, TypeError):
        return default
    return default if value is None else value


def inspect_v2(conn: Any, candidate: Any, thread_id: str,
               stale_after: timedelta, now: datetime) -> ThreadStatus:
    row = conn.execute(f"""SELECT {store.v2_select()}, s.status AS session_status,
        s.updated_at AS session_updated_at {store.v2_from()} WHERE t.thread_id = ?""", (thread_id,)).fetchone()
    if row is None:
        raise StatusError(f"thread {thread_id} was not found in {candidate.path}")
    warnings: list[str] = []
    run = conn.execute("""SELECT run_id, status, requested_at, completed_at,
        json_extract(payload_json, '$.startedAt') AS started_at
        FROM orchestration_v2_projection_runs WHERE thread_id = ?
        ORDER BY CASE WHEN status IN ('running','waiting') THEN 0
                      WHEN status IN ('queued','preparing','starting') THEN 1
                      ELSE 2 END, ordinal DESC LIMIT 1""", (thread_id,)).fetchone()
    run_id = row_value(run, 'run_id')
    run_state = row_value(run, 'status')
    provider_status = row_value(row, 'session_status')
    activity = None
    if run_id:
        activity = conn.execute("""SELECT type AS kind, updated_at AS created_at,
            json_extract(payload_json, '$.title') AS summary
            FROM orchestration_v2_projection_turn_items WHERE thread_id = ? AND run_id = ?
            ORDER BY updated_at DESC, ordinal DESC LIMIT 1""", (thread_id, run_id)).fetchone()
    else:
        warnings.append('no run is available; liveness is weaker')
    activity_at = row_value(activity, 'created_at')
    activity_kind = row_value(activity, 'kind')
    activity_summary = safe_summary(row_value(activity, 'summary'))
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
    if run_id:
        # Do not let an unresolved request from an older run override completion.
        counts = dict(conn.execute("""SELECT r.kind, COUNT(*)
            FROM orchestration_v2_projection_runtime_requests AS r
            JOIN orchestration_v2_projection_nodes AS n ON n.node_id = r.node_id
            WHERE r.thread_id = ? AND n.run_id = ? AND r.status = 'pending'
            GROUP BY r.kind""", (thread_id, run_id)))
        approvals = sum(count for kind, count in counts.items() if kind != 'user_input')
        inputs = counts.get('user_input', 0)
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


def inspect_thread(candidate: store.Candidate, thread_id: str, stale_after: timedelta,
                   now: datetime | None = None) -> ThreadStatus:
    conn = store.connect_readonly(candidate.path)
    try:
        store.require_projection_schema(conn, candidate.path)
        return inspect_v2(conn, candidate, thread_id, stale_after, now or datetime.now(timezone.utc))
    except sqlite3.Error as error:
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
    parser.add_argument("--base-dir", "--home-dir", dest="base_dir", help="T3 base directory containing userdata/statev2.sqlite")
    parser.add_argument("--cwd", help="working directory used for database discovery")
    parser.add_argument("--stale-after", default="5m", help="no-activity warning threshold (default: 5m)")
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
        discovery_warnings: list[str] = []
        for candidate in candidates:
            if not candidate.path.is_file() and not (args.db or args.base_dir):
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
        if not statuses:
            detail = "; " + "; ".join(discovery_warnings) if discovery_warnings else ""
            raise StatusError(f"thread {thread_id} was not found in the local databases searched{detail}")

        for item in statuses:
            item.warnings.extend(discovery_warnings)
        if args.json:
            payload = [asdict(item) for item in statuses]
            print(json.dumps(payload if len(payload) > 1 else payload[0], indent=2, sort_keys=True))
        else:
            for index, item in enumerate(statuses):
                if index:
                    print("---")
                print(format_text(item), end="")
        return 0
    except (StatusError, store.SearchError) as error:
        if args.json:
            print(json.dumps({"error": safe_summary(str(error))}, indent=2))
        else:
            print(error, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
