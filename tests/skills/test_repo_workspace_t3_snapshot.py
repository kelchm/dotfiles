#!/usr/bin/env python3
"""Disposable T3 store fixtures; never opens a user's database."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'home/dot_agents/skills/repo-workspace/scripts/t3_snapshot.py'
SCHEMA = """
CREATE TABLE projection_projects (project_id TEXT PRIMARY KEY, title TEXT, workspace_root TEXT, scripts_json TEXT,
 deleted_at TEXT, archived_at TEXT, tracked_folders_json TEXT NOT NULL DEFAULT '[]');
CREATE TABLE orchestration_v2_projection_threads (thread_id TEXT PRIMARY KEY, project_id TEXT, title TEXT,
 default_provider TEXT, created_at TEXT, archived_at TEXT, deleted_at TEXT, payload_json TEXT,
 provider_instance_id TEXT);
CREATE TABLE orchestration_v2_projection_messages (message_id TEXT PRIMARY KEY, thread_id TEXT,
 created_at TEXT, payload_json TEXT);
"""


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='t3-snapshot-fixture-')
        self.root = Path(self.temporary.name)
        self.db = self.root / 'statev2.sqlite'
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute("INSERT INTO projection_projects VALUES ('p', 'lab', '/dev/lab', '[]', NULL, NULL, '[]')")
            for thread, worktree, archived in (('root', None, None), ('task', '/wt/task', '2026-11-01')):
                payload = {'branch': 'main', 'worktreePath': worktree, 'lineage': {'parentThreadId': None}}
                conn.execute('INSERT INTO orchestration_v2_projection_threads VALUES (?,?,?,?,?,?,?,?,?)',
                             (thread, 'p', thread.title(), 'claudeAgent', '2026-11-01', archived, None,
                              json.dumps(payload), 'claudeAgent'))
                # Inserted out of time order, as imported history is.
                for message, created in (('m2', '02'), ('m1', '01')):
                    self.message(conn, f'{thread}-{message}', thread, created)
        self.before = self.root / 'before.json'
        self.save()

    def tearDown(self):
        self.temporary.cleanup()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db)
        try:
            with conn:  # Commits; closing frees the file for cleanup on Windows.
                yield conn
        finally:
            conn.close()

    def message(self, conn, message_id, thread, created):
        conn.execute('INSERT INTO orchestration_v2_projection_messages VALUES (?,?,?,?)',
                     (message_id, thread, f'2026-11-01T00:00:{created}Z', '{}'))

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args, '--db', str(self.db)],
                              capture_output=True, text=True, timeout=30)

    def save(self):
        result = self.run_script('save', '--project', 'p', '--out', str(self.before))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def compare(self):
        result = self.run_script('compare', '--before', str(self.before))
        return result.returncode, json.loads(result.stdout)

    def test_snapshot_keeps_ids_in_time_order_and_includes_archived_threads(self):
        data = json.loads(self.before.read_text())
        self.assertEqual(data['threads']['root']['messages'], ['root-m1', 'root-m2'])
        self.assertEqual(data['threads']['task']['worktree_path'], '/wt/task')
        code, report = self.compare()
        self.assertEqual((code, report['problems'], report['notes']), (0, [], []))

    def test_existing_snapshot_is_never_overwritten(self):
        result = self.run_script('save', '--project', 'p', '--out', str(self.before))
        self.assertNotEqual(result.returncode, 0)

    def test_root_change_and_appended_messages_are_notes(self):
        with self.connect() as conn:
            conn.execute("UPDATE projection_projects SET workspace_root='/dev/ws/lab', archived_at='x', "
                         "tracked_folders_json='[{\"path\": \"/dev/ws/lab\"}]'")
            self.message(conn, 'root-m3', 'root', '03')
        code, report = self.compare()
        self.assertEqual(code, 0, report)
        self.assertEqual(len(report['notes']), 4)

    def test_lost_message_rebinding_and_deletion_are_problems(self):
        with self.connect() as conn:
            conn.execute("DELETE FROM orchestration_v2_projection_messages WHERE message_id='root-m1'")
            conn.execute("UPDATE orchestration_v2_projection_threads SET payload_json=? WHERE thread_id='task'",
                         (json.dumps({'branch': 'main', 'worktreePath': '/elsewhere'}),))
        code, report = self.compare()
        self.assertEqual(code, 1)
        self.assertEqual(len(report['problems']), 2, report)
        with self.connect() as conn:
            conn.execute("DELETE FROM orchestration_v2_projection_threads WHERE thread_id='task'")
        code, report = self.compare()
        self.assertTrue(any('missing' in problem for problem in report['problems']))


if __name__ == '__main__':
    unittest.main()
