#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2] / "home/dot_agents/skills/t3-thread-search"
sys.path.insert(0, str(ROOT / "scripts"))
from t3_thread import status


class V2StatusTests(unittest.TestCase):
    def setUp(self) -> None:
        from .t3_v2_fixture import fixture, THREAD, ENVIRONMENT
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / '.t3/userdata/statev2.sqlite'
        fixture(self.db)
        self.thread = THREAD
        self.environment = ENVIRONMENT
        self.candidate = status.store.Candidate(self.db, 'test', 'test', environment_id=ENVIRONMENT)
        self.now = datetime(2026, 10, 25, 13, 40, 40, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def inspect(self):
        return status.inspect_thread(self.candidate, self.thread, timedelta(minutes=5), self.now)

    def execute(self, sql, params=()):
        conn = sqlite3.connect(self.db)
        conn.execute(sql, params)
        conn.commit()
        conn.close()

    def test_terminal_and_idle_states(self) -> None:
        result = self.inspect()
        self.assertEqual(result.state, 'completed')
        self.assertEqual(result.provider, 'claudeAgent')
        self.assertEqual(result.project, 'home-lab')
        self.assertEqual(result.turn_id, 'run-1')
        self.assertNotIn('do-not-leak', result.last_activity_summary or '')
        for run, state in [('failed', 'error'), ('cancelled', 'interrupted'), ('interrupted', 'interrupted'),
                           ('rolled_back', 'interrupted'), ('queued', 'queued'), ('preparing', 'queued'), ('starting', 'queued')]:
            self.execute('UPDATE orchestration_v2_projection_runs SET status=?', (run,))
            self.assertEqual(self.inspect().state, state)
        self.execute('DELETE FROM orchestration_v2_projection_runs')
        self.assertEqual(self.inspect().state, 'idle/ready')
        self.execute("UPDATE orchestration_v2_projection_provider_threads SET status='not_loaded'")
        self.assertEqual(self.inspect().state, 'idle/stopped')

    def test_active_and_stale_states(self) -> None:
        self.execute("UPDATE orchestration_v2_projection_runs SET status='running', completed_at=NULL")
        self.assertEqual(self.inspect().state, 'running/recent')
        self.now += timedelta(minutes=10)
        result = self.inspect()
        self.assertEqual(result.state, 'stale-suspect')
        self.assertIn('does not prove', result.reason)
        self.execute("UPDATE orchestration_v2_projection_turn_items SET updated_at='2026-10-25T13:50:39Z'")
        self.assertEqual(self.inspect().state, 'running/recent')
        self.execute("UPDATE orchestration_v2_projection_turn_items SET updated_at='2026-10-25T13:40:31Z'")
        self.execute("UPDATE orchestration_v2_projection_messages SET updated_at='2026-10-25T13:50:39Z'")
        self.assertEqual(self.inspect().last_activity_kind, 'message.updated')

    def test_requests_are_scoped_to_current_run(self) -> None:
        self.execute("""INSERT INTO orchestration_v2_projection_runtime_requests
            VALUES ('request', ?, 'node-1', 'command', 'pending', '2026-10-25T13:40:31Z', NULL, '{}')""", (self.thread,))
        self.assertEqual(self.inspect().state, 'completed')
        self.execute("UPDATE orchestration_v2_projection_runs SET status='running'")
        self.assertEqual(self.inspect().state, 'awaiting-approval')
        self.execute("UPDATE orchestration_v2_projection_runtime_requests SET kind='user_input'")
        self.assertEqual(self.inspect().state, 'awaiting-input')
        self.execute("UPDATE orchestration_v2_projection_nodes SET run_id='older-run'")
        self.assertEqual(self.inspect().state, 'running/recent')
        self.execute("UPDATE orchestration_v2_projection_nodes SET run_id='run-1'")
        self.execute("UPDATE orchestration_v2_projection_runtime_requests SET status='resolved'")
        self.assertEqual(self.inspect().state, 'running/recent')

    def test_active_run_precedes_terminal_run_and_historical_activity(self) -> None:
        self.execute("""INSERT INTO orchestration_v2_projection_runs
            VALUES ('run-2', ?, 2, 'claudeAgent', ?, 'running', '2026-10-25T13:40:32Z', NULL, '{}')""",
            (self.thread, 'provider-' + self.thread))
        result = self.inspect()
        self.assertEqual(result.turn_id, 'run-2')
        self.assertIn('weaker', ' '.join(result.warnings))
        self.assertNotEqual(result.last_activity_kind, 'command_execution')


    def test_scoped_cli_and_discovery_use_live_store(self) -> None:
        from .test_t3_thread_search import legacy_fixture
        legacy_fixture(self.db.with_name('state.sqlite'))
        stdout = io.StringIO()
        with patch.object(status.Path, 'home', return_value=Path(self.tmp.name)), redirect_stdout(stdout):
            result = status.main(['--thread', self.environment + '/' + self.thread, '--json'])
        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload['database'], str(self.db))
        self.assertEqual(payload['state'], 'completed')

    def test_unknown_pending_request_kind_is_an_approval(self) -> None:
        self.execute("UPDATE orchestration_v2_projection_runs SET status='running'")
        self.execute("""INSERT INTO orchestration_v2_projection_runtime_requests
            VALUES ('request', ?, 'node-1', 'file_change', 'pending', '2026-10-25T13:40:31Z', NULL, '{}')""", (self.thread,))
        result = self.inspect()
        self.assertEqual(result.state, 'awaiting-approval')
        self.assertEqual(result.pending_approvals, 1)


    def test_delegated_thread_id_forms(self) -> None:
        from .t3_v2_fixture import DELEGATED_ID
        from urllib.parse import quote
        for ref in (DELEGATED_ID, self.environment + '/' + DELEGATED_ID,
                    't3-thread://v1/' + DELEGATED_ID, 't3-thread://v1/' + quote(DELEGATED_ID, safe='')):
            with self.subTest(ref=ref), redirect_stdout(io.StringIO()) as stdout:
                result = status.main(['--db', str(self.db), '--thread', ref, '--json'])
                self.assertEqual(result, 0)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload['thread_id'], DELEGATED_ID)
                self.assertEqual(payload['state'], 'unknown')

    def test_running_run_takes_precedence_over_later_queued_run(self) -> None:
        self.execute("UPDATE orchestration_v2_projection_runs SET status='running'")
        self.execute("""INSERT INTO orchestration_v2_projection_runs
            VALUES ('run-2', ?, 2, 'claudeAgent', ?, 'queued', '2026-10-25T13:40:32Z', NULL, '{}')""",
            (self.thread, 'provider-' + self.thread))
        self.assertEqual(self.inspect().turn_id, 'run-1')
        self.assertEqual(self.inspect().state, 'running/recent')

    def test_latest_user_message_excludes_generated_and_streaming_rows(self) -> None:
        from .t3_v2_fixture import TIME
        self.execute("""UPDATE orchestration_v2_projection_messages
            SET updated_at='2026-10-25T13:55:00Z' WHERE message_id='generated'""")
        self.execute("""INSERT INTO orchestration_v2_projection_messages
            VALUES ('streaming-user', ?, 'run-1', 'node-1', 'user', 1,
                    '2026-10-25T13:56:00Z', '2026-10-25T13:56:00Z', ?)""",
                     (self.thread, json.dumps({'text': 'unfinished user row', 'createdBy': 'user'})))
        self.execute("""INSERT INTO orchestration_v2_projection_messages
            VALUES ('completion', ?, 'run-1', 'node-1', 'user', 0,
                    '2026-10-25T13:56:30Z', '2026-10-25T13:56:30Z', ?)""",
                     (self.thread, json.dumps({'text': 'delegate finished', 'createdBy': 'agent',
                                              'delegatedCompletion': {'taskIds': ['task-1']}})))
        result = self.inspect()
        self.assertEqual(result.latest_user_message_at, TIME)
        self.assertEqual(result.state, 'completed')
        self.execute("""INSERT INTO orchestration_v2_projection_messages
            VALUES ('new-user', ?, 'run-1', 'node-1', 'user', 0,
                    '2026-10-25T13:57:00Z', '2026-10-25T13:57:00Z', ?)""",
                     (self.thread, json.dumps({'text': 'a user-authored message', 'createdBy': 'user'})))
        self.assertEqual(self.inspect().latest_user_message_at, '2026-10-25T13:57:00Z')
        self.execute("""INSERT INTO orchestration_v2_projection_messages
            VALUES ('agent-prompt', ?, 'run-1', 'node-1', 'user', 0,
                    '2026-10-25T13:58:00Z', '2026-10-25T13:58:00Z', ?)""",
                     (self.thread, json.dumps({'text': 'review the requested change', 'createdBy': 'agent'})))
        self.assertEqual(self.inspect().latest_user_message_at, '2026-10-25T13:58:00Z')

    def test_bad_implicit_databases_warn_and_do_not_hide_a_valid_thread(self) -> None:
        invalid = Path(self.tmp.name) / 'invalid.sqlite'
        invalid.write_text('not a SQLite database')
        unsupported = Path(self.tmp.name) / 'unsupported.sqlite'
        sqlite3.connect(unsupported).close()
        candidates = [status.store.Candidate(p, 'implicit', 'test') for p in (invalid, unsupported)]
        with patch.object(status, 'resolve_candidates', return_value=(candidates + [self.candidate], self.thread)), \
             redirect_stdout(io.StringIO()) as stdout:
            result = status.main(['--thread', self.thread, '--json'])
        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload['database'], str(self.db))
        self.assertEqual(payload['state'], 'completed')
        self.assertIn(str(invalid), ' '.join(payload['warnings']))
        self.assertIn(str(unsupported), ' '.join(payload['warnings']))
        # If every candidate fails, the command still returns an error with the skipped-path diagnostics.
        with patch.object(status, 'resolve_candidates', return_value=(candidates, self.thread)), \
             redirect_stdout(io.StringIO()) as stdout:
            result = status.main(['--thread', self.thread, '--json'])
        self.assertEqual(result, 2)
        self.assertIn('Skipped database', json.loads(stdout.getvalue())['error'])

    def test_bad_explicit_database_still_fails(self) -> None:
        invalid = Path(self.tmp.name) / 'invalid.sqlite'
        invalid.write_text('not a SQLite database')
        candidate = status.store.Candidate(invalid, 'explicit', 'test')
        for selection in (['--db', str(invalid)], ['--base-dir', str(invalid.parent)]):
            with self.subTest(selection=selection), \
                 patch.object(status, 'resolve_candidates', return_value=([candidate, self.candidate], self.thread)), \
                 redirect_stdout(io.StringIO()) as stdout:
                result = status.main(['--thread', self.thread, '--json', *selection])
                self.assertEqual(result, 2)
                self.assertIn('SQLite status query failed', json.loads(stdout.getvalue())['error'])

    def test_missing_required_table_is_unsupported(self) -> None:
        self.execute('DROP TABLE orchestration_v2_projection_runtime_requests')
        with self.assertRaisesRegex(status.store.SearchError, 'unsupported T3 schema'):
            self.inspect()

    def test_missing_explicit_database_reports_the_path(self) -> None:
        missing = self.db.with_name('missing.sqlite')
        for selection in (['--db', str(missing)], ['--base-dir', str(self.db.parent / 'missing-home')]):
            with self.subTest(selection=selection), redirect_stdout(io.StringIO()) as stdout:
                result = status.main(['--thread', self.thread, '--json', *selection])
                self.assertEqual(result, 2)
                self.assertIn('Database does not exist', json.loads(stdout.getvalue())['error'])


if __name__ == "__main__":
    unittest.main()
