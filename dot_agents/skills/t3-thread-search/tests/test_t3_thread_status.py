#!/usr/bin/env python3
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "t3-thread-status"
LOADER = importlib.machinery.SourceFileLoader("t3_thread_status", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None and SPEC.loader is not None
status = importlib.util.module_from_spec(SPEC)
sys.modules[LOADER.name] = status
SPEC.loader.exec_module(status)


SCHEMA = """
CREATE TABLE projection_projects (
  project_id TEXT PRIMARY KEY, title TEXT NOT NULL, workspace_root TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT
);
CREATE TABLE projection_threads (
  thread_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
  latest_turn_id TEXT, updated_at TEXT NOT NULL, latest_user_message_at TEXT,
  pending_approval_count INTEGER NOT NULL DEFAULT 0,
  pending_user_input_count INTEGER NOT NULL DEFAULT 0,
  deleted_at TEXT, archived_at TEXT
);
CREATE TABLE projection_thread_sessions (
  thread_id TEXT PRIMARY KEY, status TEXT NOT NULL, provider_name TEXT,
  active_turn_id TEXT, last_error TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE projection_turns (
  row_id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL,
  turn_id TEXT, assistant_message_id TEXT, state TEXT NOT NULL,
  requested_at TEXT NOT NULL, started_at TEXT, completed_at TEXT
);
CREATE TABLE projection_thread_activities (
  activity_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, turn_id TEXT,
  tone TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL,
  payload_json TEXT NOT NULL, created_at TEXT NOT NULL, sequence INTEGER
);
"""


class StatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "state.sqlite"
        conn = sqlite3.connect(self.db)
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO projection_projects VALUES (?, ?, ?, ?, ?, NULL)",
                     ("p", "Project", "/repo", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
        conn.execute("INSERT INTO projection_threads VALUES (?, ?, ?, ?, ?, ?, 0, 0, NULL, NULL)",
                     ("t", "p", "Status test", "turn", "2026-08-29T00:00:00Z", "2026-08-29T00:00:00Z"))
        conn.commit()
        conn.close()
        self.candidate = status.search.Candidate(path=self.db, kind="explicit", source="test", environment_id="env")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def seed(self, *, session: str, turn: str, activity_kind: str, activity_time: str,
             pending_approval: int = 0, last_error: str | None = None) -> None:
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE projection_threads SET pending_approval_count=? WHERE thread_id='t'", (pending_approval,))
        conn.execute("INSERT INTO projection_thread_sessions VALUES (?, ?, ?, ?, ?, ?)",
                     ("t", session, "test-provider", "turn", last_error, activity_time))
        conn.execute("INSERT INTO projection_turns (thread_id, turn_id, state, requested_at, started_at) VALUES (?, ?, ?, ?, ?)",
                     ("t", "turn", turn, "2026-08-29T00:00:00Z", "2026-08-29T00:00:01Z"))
        conn.execute("INSERT INTO projection_thread_activities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     ("a", "t", "turn", "info", activity_kind, "safe summary token=do-not-leak", "{}", activity_time, 1))
        conn.commit()
        conn.close()

    def inspect(self, now: str = "2026-08-29T00:00:30Z") -> object:
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
        return status.inspect_thread(self.candidate, "t", timedelta(minutes=5), current)

    def test_running_recent_is_not_called_hung(self) -> None:
        self.seed(session="running", turn="running", activity_kind="task.progress", activity_time="2026-08-29T00:00:10Z")
        result = self.inspect()
        self.assertEqual(result.state, "running/recent")
        self.assertEqual(result.activity_age_seconds, 20)
        self.assertNotIn("do-not-leak", result.last_activity_summary or "")

    def test_pending_approval_beats_stale_classification(self) -> None:
        self.seed(session="running", turn="running", activity_kind="tool.denied", activity_time="2026-08-28T23:00:00Z", pending_approval=1)
        result = self.inspect()
        self.assertEqual(result.state, "awaiting-approval")
        self.assertNotIn("stale", result.state)

    def test_pending_approval_beats_current_denial_error(self) -> None:
        self.seed(session="running", turn="running", activity_kind="tool.denied", activity_time="2026-08-29T00:00:10Z", pending_approval=1)
        result = self.inspect()
        self.assertEqual(result.state, "awaiting-approval")

    def test_historical_denial_does_not_override_completed_turn(self) -> None:
        self.seed(session="ready", turn="completed", activity_kind="tool.denied", activity_time="2026-08-29T00:00:10Z")
        result = self.inspect()
        self.assertEqual(result.state, "completed")

    def test_provider_error_is_reported(self) -> None:
        self.seed(session="stopped", turn="error", activity_kind="provider.turn.start.failed", activity_time="2026-08-29T00:00:10Z", last_error="provider token=private-value")
        result = self.inspect()
        self.assertEqual(result.state, "error")
        self.assertNotIn("private-value", result.last_error or "")

    def test_json_shaped_secrets_are_redacted(self) -> None:
        for key in ("token", "password", "authorization", "private_key"):
            with self.subTest(key=key):
                sanitized = status.safe_summary('{"' + key + '":"SECRET123"}')
                self.assertNotIn("SECRET123", sanitized or "")
                self.assertIn("[REDACTED]", sanitized or "")

    def test_bearer_values_after_secret_keys_are_fully_redacted(self) -> None:
        for summary in (
            "Authorization: Bearer SECRET123",
            "token: Bearer SECRET123",
        ):
            with self.subTest(summary=summary):
                sanitized = status.safe_summary(summary)
                self.assertNotIn("SECRET123", sanitized or "")
                self.assertIn("[REDACTED]", sanitized or "")

    def test_running_without_activity_is_stale_suspect(self) -> None:
        self.seed(session="running", turn="running", activity_kind="task.progress", activity_time="2026-08-28T23:00:00Z")
        result = self.inspect()
        self.assertEqual(result.state, "stale-suspect")
        self.assertIn("does not prove", result.reason)

    def test_new_user_message_after_completed_turn_is_queued(self) -> None:
        self.seed(session="ready", turn="completed", activity_kind="tool.completed", activity_time="2026-08-29T00:00:10Z")
        conn = sqlite3.connect(self.db)
        conn.execute(
            "UPDATE projection_threads SET latest_user_message_at=? WHERE thread_id='t'",
            ("2026-08-29T00:00:20Z",),
        )
        conn.commit()
        conn.close()
        result = self.inspect()
        self.assertEqual(result.state, "queued")

    def test_historical_session_error_does_not_override_completed_turn(self) -> None:
        self.seed(
            session="running",
            turn="completed",
            activity_kind="tool.completed",
            activity_time="2026-08-29T00:00:10Z",
            last_error='{"token":"SECRET123"}',
        )
        result = self.inspect()
        self.assertEqual(result.state, "completed")
        self.assertNotIn("SECRET123", result.last_error or "")
        self.assertTrue(any("historical" in warning for warning in result.warnings))

    def test_watch_repolls_only_databases_that_matched_the_thread(self) -> None:
        self.seed(session="running", turn="running", activity_kind="task.progress", activity_time="2026-08-29T00:00:10Z")
        missing_db = Path(self.tmp.name) / "missing.sqlite"
        conn = sqlite3.connect(missing_db)
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO projection_projects VALUES (?, ?, ?, ?, ?, NULL)",
            ("p", "Project", "/repo", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO projection_threads VALUES (?, ?, ?, ?, ?, ?, 0, 0, NULL, NULL)",
            ("other", "p", "Other", None, "2026-08-29T00:00:00Z", "2026-08-29T00:00:00Z"),
        )
        conn.commit()
        conn.close()
        missing_candidate = status.search.Candidate(path=missing_db, kind="implicit", source="test", environment_id="other-env")

        with (
            patch.object(status, "resolve_candidates", return_value=([missing_candidate, self.candidate], "t")),
            patch.object(status.time, "monotonic", side_effect=[0.0, 1.0, 20.0]),
            patch.object(status.time, "sleep"),
            redirect_stdout(io.StringIO()) as stdout,
            redirect_stderr(io.StringIO()),
        ):
            result = status.main(["--thread", "t", "--watch-for", "10s", "--interval", "10s", "--stale-after", "1d"])

        self.assertEqual(result, 0)
        self.assertIn("state: running/recent", stdout.getvalue())

    def test_watch_continues_polling_after_stale_suspect(self) -> None:
        self.seed(session="running", turn="running", activity_kind="task.progress", activity_time="2026-08-28T23:00:00Z")

        with (
            patch.object(status, "resolve_candidates", return_value=([self.candidate], "t")),
            patch.object(status.time, "monotonic", side_effect=[0.0, 1.0, 20.0]),
            patch.object(status.time, "sleep") as sleep,
            redirect_stdout(io.StringIO()) as stdout,
            redirect_stderr(io.StringIO()),
        ):
            result = status.main(["--thread", "t", "--watch-for", "10s", "--interval", "10s"])

        self.assertEqual(result, 0)
        sleep.assert_called_once_with(10.0)
        self.assertIn("state: stale-suspect", stdout.getvalue())

    def test_input_resolution_compares_timestamp_instants(self) -> None:
        self.seed(session="running", turn="running", activity_kind="task.progress", activity_time="2026-08-29T00:00:10Z")
        conn = sqlite3.connect(self.db)
        conn.executemany(
            "INSERT INTO projection_thread_activities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("request", "t", "turn", "info", "user-input.requested", "input", "{}", "2026-08-29T01:00:00+01:00", 2),
                ("resolved", "t", "turn", "info", "user-input.resolved", "resolved", "{}", "2026-08-29T00:30:00Z", 3),
            ],
        )
        conn.commit()
        conn.close()

        result = self.inspect(now="2026-08-29T00:31:00Z")
        self.assertNotEqual(result.state, "awaiting-input")


if __name__ == "__main__":
    unittest.main()
