#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import shlex
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[2] / "home/dot_agents/skills/t3-thread-search"
sys.path.insert(0, str(ROOT / "scripts"))
from t3_thread import search as tts, store
from .t3_v2_fixture import fixture, THREAD, ENVIRONMENT


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def write_db(path: Path, statements: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        for statement in statements:
            conn.executescript(statement)
        conn.commit()
    finally:
        conn.close()


def legacy_fixture(path: Path) -> None:
    write_db(path, ["CREATE TABLE projection_threads (thread_id TEXT PRIMARY KEY, title TEXT);"
                    "INSERT INTO projection_threads VALUES ('legacy-only', 'rebuild performance');"])


def search(db: Path, query: str, **kwargs):
    return tts.run_search(
        query=query,
        cwd=db.parent,
        home=db.parent,
        env={},
        db=str(db),
        **kwargs,
    )


class DiscoveryTests(unittest.TestCase):
    def test_explicit_db_and_base_dir_are_mutually_exclusive(self) -> None:
        with self.assertRaises(store.UsageError):
            store.discover_candidates(
                cwd=Path("/tmp"),
                home=Path("/tmp"),
                env={},
                db="a.sqlite",
                base_dir="/tmp/base",
            )

    def test_does_not_scan_home_for_nested_t3_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            nested = home / "deep" / "secret" / ".t3" / "userdata"
            fixture(nested / "statev2.sqlite")
            production = home / ".t3" / "userdata" / "statev2.sqlite"
            fixture(production)
            candidates = store.discover_candidates(cwd=home, home=home, env={})
            paths = {candidate.path.resolve() for candidate in candidates if candidate.path.is_file()}
            self.assertIn(production.resolve(), paths)
            self.assertNotIn((nested / "statev2.sqlite").resolve(), paths)

    def test_linked_worktree_outRanks_ambient_env_as_a_listed_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            worktree = root / "worktree"
            gitdir = root / "main.git" / "worktrees" / "feature"
            gitdir.mkdir(parents=True)
            worktree.mkdir()
            (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
            wt_db = worktree / ".t3" / "userdata" / "statev2.sqlite"
            fixture(wt_db)
            env_base = root / "env-home"
            env_db = env_base / "userdata" / "statev2.sqlite"
            fixture(env_db)
            home = root / "home"
            home.mkdir()
            candidates = store.discover_candidates(
                cwd=worktree,
                home=home,
                env={"T3CODE_HOME": str(env_base)},
            )
            kinds = [candidate.kind for candidate in candidates]
            self.assertEqual(kinds[0], "worktree")
            self.assertIn("env", kinds)

    def test_main_checkout_git_directory_is_not_a_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            (repo / ".git").mkdir()
            (repo / ".t3" / "userdata").mkdir(parents=True)
            fixture(repo / ".t3" / "userdata" / "statev2.sqlite")
            self.assertIsNone(store.is_linked_worktree(repo))

    def test_explicit_base_dir_uses_userdata_not_dev(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            userdata = base / "userdata" / "statev2.sqlite"
            dev = base / "dev" / "statev2.sqlite"
            fixture(userdata)
            fixture(dev)
            candidates = store.discover_candidates(cwd=base, home=base, env={}, base_dir=str(base))
            self.assertEqual(candidates[0].path, userdata)


class LikeEscapeTests(unittest.TestCase):
    def test_escape_like_pattern(self) -> None:
        self.assertEqual(tts.escape_like_pattern("100%_!"), "100!%!_!!")


class MultipleDatabaseTests(unittest.TestCase):
    def test_list_dbs_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            production = home / ".t3" / "userdata" / "statev2.sqlite"
            development = home / ".t3" / "dev" / "statev2.sqlite"
            fixture(production)
            fixture(development)
            report = tts.run_search(
                query=None,
                cwd=home,
                home=home,
                env={},
                list_dbs=True,
            )
            kinds = {item["kind"] for item in report.databases if item["exists"]}
            self.assertEqual(kinds, {"production", "development"})
            payload = json.loads(json.dumps(tts.asdict(report)))
            self.assertEqual(payload["mode"], "list-dbs")

    def test_t3code_home_uses_userdata_not_dev(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            env_base = home / "custom"
            userdata = env_base / "userdata" / "statev2.sqlite"
            dev = env_base / "dev" / "statev2.sqlite"
            fixture(userdata)
            fixture(dev)
            candidates = store.discover_candidates(
                cwd=home, home=home, env={"T3CODE_HOME": str(env_base)}
            )
            env_paths = [candidate.path for candidate in candidates if candidate.kind == "env"]
            self.assertEqual(env_paths, [userdata])

    def test_db_directory_prefers_userdata_over_sibling_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            decoy = base / "statev2.sqlite"
            userdata = base / "userdata" / "statev2.sqlite"
            write_db(decoy, ["CREATE TABLE unrelated (id INTEGER);"])
            fixture(userdata)
            candidates = store.discover_candidates(cwd=base, home=base, env={}, db=str(base))
            self.assertEqual(candidates[0].path, userdata)

    def test_one_bad_database_does_not_abort_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            good = home / ".t3" / "userdata" / "statev2.sqlite"
            bad = home / ".t3" / "dev" / "statev2.sqlite"
            fixture(good)
            write_db(bad, ["CREATE TABLE unrelated (id INTEGER);"])
            report = tts.run_search(
                query="Spark BIOS",
                cwd=home,
                home=home,
                env={},
            )
            self.assertTrue(report.results)
            self.assertTrue(any("unsupported T3 schema" in warning for warning in report.warnings))
            self.assertIn(THREAD, [row["thread_id"] for row in report.results])


class V2SearchTests(unittest.TestCase):
    def setUp(self) -> None:
        from .t3_v2_fixture import fixture, THREAD
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / '.t3/userdata/statev2.sqlite'
        fixture(self.db)
        self.thread = THREAD

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_discovery_prefers_v2_and_lists_superseded_legacy(self) -> None:
        old = self.db.with_name('state.sqlite')
        legacy_fixture(old)
        home = Path(self.tmp.name)
        report = tts.run_search(query=None, cwd=home, home=home, env={}, list_dbs=True)
        live, legacy = [item for item in report.databases if item['exists']]
        self.assertEqual(live['role'], 'live')
        self.assertTrue(live['searchable'])
        self.assertIn('legacy/stale', legacy['role'])
        self.assertFalse(legacy['searchable'])
        report = tts.run_search(query='rebuild performance', cwd=home, home=home, env={})
        self.assertEqual(report.results, [])  # Only in the superseded database.
        for flag in ('db', 'base_dir'):
            candidate = store.discover_candidates(cwd=home, home=home, env={}, **{flag: str(self.db.parent if flag == 'db' else self.db.parent.parent)})
            self.assertEqual(candidate[0].path, self.db)
        with self.assertRaisesRegex(store.SearchError, 'unsupported T3 schema'):
            search(old, 'rebuild performance')

    def test_exact_identity_forms_and_fresh_title(self) -> None:
        from .t3_v2_fixture import ENVIRONMENT
        for ref in (self.thread, f'{ENVIRONMENT}/{self.thread}',
                    f'https://app.t3.codes/{ENVIRONMENT}/{self.thread}',
                    f't3-thread://v1/{self.thread}'):
            with self.subTest(ref=ref):
                report = search(self.db, None, thread_id=ref)
                self.assertEqual(report.results[0]['title'], 'Update Spark OS and Check BIOS')
                self.assertEqual(report.results[0]['scoped_id'], f'{ENVIRONMENT}/{self.thread}')
                self.assertEqual(report.results[0]['message_counts'], {'user': 2, 'assistant': 2})
        with self.assertRaises(store.UsageError):
            search(self.db, None, thread_id=f'{ENVIRONMENT}/{self.thread}', environment_id='wrong')

    def test_metadata_provider_and_message_search(self) -> None:
        for query in ('Update Spark OS', 'home-lab', '/repo/home-lab', 'fix/spark',
                      'provider-' + self.thread, 'session-' + self.thread, 'claude-work',
                      'update the Spark BIOS', '100% fix', '"quoted" _value_'):
            with self.subTest(query=query):
                self.assertIn(self.thread, [r['thread_id'] for r in search(self.db, query).results])
        for query in ('streaming needle', 'generated notification needle', '100x fix', '" OR "', "' OR 1=1 --"):
            with self.subTest(query=query):
                self.assertEqual(search(self.db, query).results, [])

    def test_message_filters(self) -> None:
        self.assertTrue(search(self.db, 'archived message').results)
        self.assertFalse(search(self.db, 'archived message', active_only=True).results)
        self.assertFalse(search(self.db, 'deleted message').results)
        self.assertTrue(search(self.db, 'deleted message', include_deleted=True).results)
        self.assertFalse(search(self.db, 'Spark BIOS', project='other').results)
        self.assertFalse(search(self.db, 'Spark BIOS', since='2026-10-26').results)
        self.assertTrue(search(self.db, 'Spark BIOS', project='/repo/home-lab', until='2026-10-25').results)
        conn = sqlite3.connect(self.db)
        conn.execute('UPDATE projection_projects SET deleted_at=?', ('2026-10-26',))
        conn.commit()
        conn.close()
        self.assertFalse(search(self.db, 'Spark BIOS', active_only=True).results)

    def test_fts_query_plan_and_readonly_safety(self) -> None:
        conn = store.connect_readonly(self.db)
        before = sha256(self.db)
        store.require_projection_schema(conn, self.db)
        statements = []
        conn.set_trace_callback(statements.append)
        matches, _ = tts.search_v2(conn, store.Candidate(self.db, 'test', 'test'), 'Spark BIOS',
            active_only=False, include_deleted=False, project=None, since=None, until=None, thread_id=None, limit=20)
        self.assertTrue(matches)
        query = next(sql for sql in statements if ' MATCH ' in sql)
        plan = conn.execute('EXPLAIN QUERY PLAN ' + query).fetchall()
        details = '\n'.join(row['detail'] for row in plan)
        self.assertIn('VIRTUAL TABLE INDEX', details)
        self.assertIn('INTEGER PRIMARY KEY', details)
        self.assertNotIn('SCAN m', details)
        with self.assertRaises(sqlite3.OperationalError):
            conn.execute("DELETE FROM orchestration_v2_projection_threads")
        conn.close()
        self.assertEqual(before, sha256(self.db))
        self.assertFalse(self.db.with_name(self.db.name + '-wal').exists())
        self.assertFalse(self.db.with_name(self.db.name + '-shm').exists())

    def test_short_query_and_missing_fts_do_not_scan_messages(self) -> None:
        short = search(self.db, 'OS')
        self.assertTrue(short.results)
        self.assertIn('metadata only', ' '.join(short.warnings))
        conn = sqlite3.connect(self.db)
        conn.execute('DROP TABLE orchestration_v2_message_search')
        conn.commit()
        conn.close()
        with self.assertRaisesRegex(store.SearchError, 'unsupported T3 schema.*orchestration_v2_message_search'):
            search(self.db, 'Spark BIOS')

    def test_pr_number_url_and_attribution_fallback(self) -> None:
        number = search(self.db, None, pr='123')
        self.assertEqual(len(number.results), 2)
        url = search(self.db, None, pr='https://github.com/owner/home-lab/pull/123')
        self.assertEqual([r['thread_id'] for r in url.results], [self.thread])
        self.assertEqual(url.results[0]['source'], 'pr')
        self.assertEqual(len(search(self.db, None, pr='123', active_only=True).results), 1)
        self.assertEqual(search(self.db, None, pr='999').results, [])
        missing = search(self.db, None, pr='1046')
        self.assertIn('attribution thread:', ' '.join(missing.warnings))
        for invalid in ('0', '-2', "123 OR 1=1", 'https://github.com/owner/home-lab/issues/123'):
            with self.subTest(invalid=invalid), self.assertRaises(store.UsageError):
                search(self.db, None, pr=invalid)

    def test_live_wal_is_visible(self) -> None:
        writer = sqlite3.connect(self.db)
        try:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('UPDATE orchestration_v2_projection_threads SET title=? WHERE thread_id=?',
                           ('Fresh uncheckpointed title', self.thread))
            writer.commit()
            result = search(self.db, 'Fresh uncheckpointed title')
            self.assertEqual(result.results[0]['thread_id'], self.thread)
            self.assertNotIn('immutable=1', store.sqlite_uri(self.db))
        finally:
            writer.close()

    def test_uuid_is_searched_as_both_native_and_app_id(self) -> None:
        from .t3_v2_fixture import NATIVE_ID
        for query in (NATIVE_ID, self.thread):
            report = search(self.db, query)
            self.assertIn(self.thread, [row['thread_id'] for row in report.results])
        self.assertEqual(search(self.db, None, thread_id=NATIVE_ID).results, [])

    def test_delegated_and_opaque_ids_round_trip(self) -> None:
        from .t3_v2_fixture import DELEGATED_ID, ENVIRONMENT
        for ref in (DELEGATED_ID, f'{ENVIRONMENT}/{DELEGATED_ID}',
                    f't3-thread://v1/{quote(DELEGATED_ID, safe="")}',
                    f'https://app.t3.codes/{ENVIRONMENT}/{DELEGATED_ID}'):
            with self.subTest(ref=ref):
                report = search(self.db, None, thread_id=ref)
                self.assertEqual(report.results[0]['thread_id'], DELEGATED_ID)
        self.assertTrue(search(self.db, 't3-thread://v1/' + DELEGATED_ID).results)
        conn = sqlite3.connect(self.db)
        conn.execute('UPDATE orchestration_v2_projection_threads SET thread_id=? WHERE thread_id=?',
                     ('opaque/id/with/slashes', DELEGATED_ID))
        conn.commit()
        conn.close()
        for ref in ('opaque/id/with/slashes', ENVIRONMENT + '/opaque/id/with/slashes'):
            self.assertEqual(search(self.db, None, thread_id=ref).results[0]['thread_id'], 'opaque/id/with/slashes')


    def test_live_wal_is_visible_through_symlink(self) -> None:
        alias = self.db.parent / 'alias.sqlite'
        alias.symlink_to(self.db)
        writer = sqlite3.connect(self.db)
        try:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('UPDATE orchestration_v2_projection_threads SET title=? WHERE thread_id=?',
                           ('Visible through alias', self.thread))
            writer.commit()
            self.assertNotIn('immutable=1', store.sqlite_uri(alias))
            self.assertEqual(search(alias, 'Visible through alias').results[0]['thread_id'], self.thread)
        finally:
            writer.close()

    def test_rollback_journal_uses_normal_readonly_locking(self) -> None:
        writer = sqlite3.connect(self.db)
        try:
            writer.execute('BEGIN IMMEDIATE')
            writer.execute('UPDATE orchestration_v2_projection_threads SET title=? WHERE thread_id=?',
                           ('Uncommitted title', self.thread))
            self.assertTrue(self.db.with_name(self.db.name + '-journal').is_file())
            self.assertNotIn('immutable=1', store.sqlite_uri(self.db))
            result = search(self.db, None, thread_id=self.thread)
            self.assertEqual(result.results[0]['title'], 'Update Spark OS and Check BIOS')
        finally:
            writer.rollback()
            writer.close()

    def test_live_fts_tokenizer_matches_accents(self) -> None:
        from .t3_v2_fixture import fixture, LIVE_FTS_SCHEMA
        probe = sqlite3.connect(':memory:')
        try:
            try:
                probe.executescript(LIVE_FTS_SCHEMA)
            except sqlite3.OperationalError as error:
                self.skipTest(f'live FTS tokenizer requires a newer SQLite runtime: {error}')
        finally:
            probe.close()
        live_db = self.db.with_name('live-tokenizer.sqlite')
        fixture(live_db, live_tokenizer=True)
        writer = sqlite3.connect(live_db)
        writer.execute('INSERT INTO orchestration_v2_projection_messages VALUES (?,?,?,?,?,?,?,?,?)',
                       ('accent', self.thread, 'run-1', 'node-1', 'user', 0,
                        '2026-10-25T13:40:32Z', '2026-10-25T13:40:32Z',
                        json.dumps({'text': 'Inspect the café résumé', 'createdBy': 'user'})))
        writer.commit()
        writer.close()
        report = search(live_db, 'cafe resume')
        self.assertEqual(report.results[0]['thread_id'], self.thread)
        self.assertEqual(report.results[0]['source'], 'user')
        self.assertIn('café résumé', report.results[0]['snippet'])

    def test_missing_required_v2_table_is_unsupported(self) -> None:
        writer = sqlite3.connect(self.db)
        writer.execute('DROP TABLE orchestration_v2_projection_provider_threads')
        writer.commit()
        writer.close()
        for kwargs in ({'query': 'Update Spark OS'}, {'query': None, 'thread_id': self.thread}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(store.SearchError, 'unsupported T3 schema'):
                search(self.db, **kwargs)

    def test_legacy_only_store_is_listed_but_not_searched(self) -> None:
        self.db.unlink()
        old = self.db.with_name('state.sqlite')
        legacy_fixture(old)
        home = Path(self.tmp.name)
        report = tts.run_search(query=None, cwd=home, home=home, env={}, list_dbs=True)
        self.assertFalse(next(item for item in report.databases if item['exists'])['searchable'])
        with self.assertRaisesRegex(store.SearchError, 'Only legacy'):
            tts.run_search(query='rebuild performance', cwd=home, home=home, env={})

    def test_missing_explicit_database(self) -> None:
        with self.assertRaisesRegex(store.SearchError, 'No T3 v2 SQLite database found'):
            search(self.db.with_name('missing.sqlite'), 'Spark')

    def test_env_scope_does_not_search_another_environment(self) -> None:
        with self.assertRaisesRegex(store.UsageError, 'no local database matched the requested environment'):
            search(self.db, None, thread_id=self.thread, environment_id='another-environment')

    def test_positional_pr_url_uses_pr_lookup(self) -> None:
        url = 'https://github.com/owner/home-lab/pull/123'
        explicit = search(self.db, None, pr=url)
        positional = search(self.db, url)
        self.assertEqual(positional.results, explicit.results)
        self.assertEqual([item['thread_id'] for item in positional.results], [self.thread])

    def test_many_matching_messages_do_not_starve_other_threads(self) -> None:
        writer = sqlite3.connect(self.db)
        for i in range(30):
            writer.execute('INSERT INTO orchestration_v2_projection_messages VALUES (?,?,?,?,?,?,?,?,?)',
                           (f'extra-{i}', self.thread, 'run-1', 'node-1', 'user', 0,
                            '2026-10-25T13:40:31Z', '2026-10-25T13:40:31Z',
                            json.dumps({'text': 'archived message needle'})))
        writer.commit()
        writer.close()
        report = search(self.db, 'archived message needle', limit=2)
        self.assertEqual({item['thread_id'] for item in report.results}, {self.thread, 'thread-archived'})

    def test_short_query_only_reads_metadata(self) -> None:
        conn = store.connect_readonly(self.db)
        statements = []
        conn.set_trace_callback(statements.append)
        try:
            tts.search_v2(conn, store.Candidate(self.db, 'test', 'test'), 'OS',
                          active_only=False, include_deleted=False, project=None, since=None,
                          until=None, thread_id=None, limit=20)
        finally:
            conn.close()
        self.assertFalse(any('orchestration_v2_projection_messages' in sql for sql in statements))


class DateFilterTests(unittest.TestCase):
    def test_equivalent_offset_bounds_preserve_equality_and_milliseconds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'statev2.sqlite'
            fixture(db)
            for fraction in ('', '.123'):
                timestamp = '2026-10-25T13:40:31' + fraction + 'Z'
                writer = sqlite3.connect(db)
                writer.execute('UPDATE orchestration_v2_projection_threads SET updated_at=? WHERE thread_id=?',
                               (timestamp, THREAD))
                writer.commit()
                writer.close()
                for bound in (timestamp, '2026-10-25T15:40:31' + fraction + '+02:00',
                              '2026-10-25T11:40:31' + fraction + '-02:00'):
                    report = search(db, 'Spark BIOS', since=bound, until=bound)
                    self.assertIn(THREAD, [r['thread_id'] for r in report.results], bound)
                self.assertFalse(search(db, 'Spark BIOS', since='2026-10-25T15:40:31.124+02:00').results)
                self.assertFalse(search(db, 'Spark BIOS', until='2026-10-25T11:40:30.999-02:00').results)
            now = datetime(2026, 10, 25, 16, 40, 31, tzinfo=timezone(timedelta(hours=2)))
            self.assertTrue(search(db, 'Spark BIOS', since='1h', now=now).results)

    def test_empty_search_is_rejected_before_database_discovery(self) -> None:
        for query in (None, '', '   '):
            with self.subTest(query=query), patch.object(tts, 'discover_candidates') as discover:
                with self.assertRaises(store.UsageError):
                    tts.run_search(query=query, cwd=Path('/unused'), home=Path('/unused'), env={})
                discover.assert_not_called()


class SshTests(unittest.TestCase):
    def test_remote_shell_arguments_are_quoted_and_filters_forwarded(self) -> None:
        from types import SimpleNamespace
        captured = {}
        def capture_ssh(argv, stdin):
            captured['argv'] = argv
            return SimpleNamespace(returncode=0, stdout=json.dumps({
                'databases': [{'path': '/remote/statev2.sqlite', 'kind': 'explicit-base',
                               'source': '--base-dir', 'exists': True, 'searched': True}],
                'results': [], 'warnings': [], 'truncated': False,
            }), stderr='')
        query = 'foo; $(id); "quoted"'
        report = tts.run_search(query=query, cwd=Path('/unused'), home=Path('/unused'), env={},
            ssh='user@remote', ssh_base_dir='/some path', ssh_exec=capture_ssh,
            project='home lab', since='2026-10-25', limit=3)
        argv = captured['argv']
        self.assertEqual(argv[:-2], ['ssh', '-o', 'BatchMode=yes', '--'])
        self.assertEqual(argv[-2], 'user@remote')
        self.assertEqual(shlex.split(argv[-1]), ['python3', '-I', '-', '--json', '--limit', '3',
            '--base-dir', '/some path', '--project', 'home lab', '--since', '2026-10-25T00:00:00', '--', query])
        self.assertEqual(report.databases[-1]['provenance'], 'ssh')

    def test_remote_failure_is_reported(self) -> None:
        from types import SimpleNamespace
        with self.assertRaisesRegex(store.SearchError, 'SSH search.*denied'):
            tts.run_search(query='Spark', cwd=Path('/unused'), home=Path('/unused'), env={},
                ssh='remote', ssh_exec=lambda argv, stdin: SimpleNamespace(returncode=255, stderr=b'denied'))


if __name__ == "__main__":
    unittest.main()
