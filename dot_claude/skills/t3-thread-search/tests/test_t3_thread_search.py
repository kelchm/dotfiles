#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "t3-thread-search"
LOADER = importlib.machinery.SourceFileLoader("t3_thread_search", str(SCRIPT))
SPEC = importlib.util.spec_from_loader("t3_thread_search", LOADER)
assert SPEC is not None and SPEC.loader is not None
tts = importlib.util.module_from_spec(SPEC)
sys.modules["t3_thread_search"] = tts
SPEC.loader.exec_module(tts)


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


FULL_SCHEMA = """
CREATE TABLE projection_projects (
  project_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  workspace_root TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT
);
CREATE TABLE projection_threads (
  thread_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  title TEXT NOT NULL,
  branch TEXT,
  worktree_path TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT,
  archived_at TEXT
);
CREATE TABLE projection_thread_messages (
  message_id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  turn_id TEXT,
  role TEXT NOT NULL,
  text TEXT NOT NULL,
  is_streaming INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE projection_thread_sessions (
  thread_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  provider_name TEXT,
  provider_session_id TEXT,
  provider_thread_id TEXT,
  provider_instance_id TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE projection_turns (
  row_id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT NOT NULL,
  turn_id TEXT,
  assistant_message_id TEXT,
  state TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  checkpoint_files_json TEXT NOT NULL DEFAULT '[]'
);
"""

LEGACY_SCHEMA = """
CREATE TABLE projection_projects (
  project_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  workspace_root TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT
);
CREATE TABLE projection_threads (
  thread_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  title TEXT NOT NULL,
  branch TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT
);
CREATE TABLE projection_thread_messages (
  message_id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  role TEXT NOT NULL,
  text TEXT NOT NULL,
  is_streaming INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE projection_thread_sessions (
  thread_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  provider_name TEXT,
  provider_session_id TEXT,
  updated_at TEXT NOT NULL
);
"""

SEED = """
INSERT INTO projection_projects VALUES
  ('proj-active', 'T3 Code', '/repo/t3code', '2026-01-01T00:00:00.000Z', '2026-05-01T00:00:00.000Z', NULL),
  ('proj-deleted', 'Old App', '/repo/old', '2026-01-01T00:00:00.000Z', '2026-02-01T00:00:00.000Z', '2026-04-01T00:00:00.000Z');

INSERT INTO projection_threads VALUES
  ('thread-active', 'proj-active', 'Projection rebuild performance', 'feat/search', '/tmp/wt',
   '2026-05-01T00:00:00.000Z', '2026-05-02T00:00:00.000Z', NULL, NULL),
  ('thread-archived', 'proj-active', 'Archived relay notes', 'main', NULL,
   '2026-04-01T00:00:00.000Z', '2026-04-02T00:00:00.000Z', NULL, '2026-04-03T00:00:00.000Z'),
  ('thread-deleted', 'proj-active', 'Deleted secret thread', 'main', NULL,
   '2026-03-01T00:00:00.000Z', '2026-03-02T00:00:00.000Z', '2026-03-03T00:00:00.000Z', NULL),
  ('thread-percent-decoy', 'proj-active', 'Unrelated', 'main', NULL,
   '2026-05-01T00:00:00.000Z', '2026-05-01T00:00:00.000Z', NULL, NULL),
  ('thread-old-project', 'proj-deleted', 'Legacy workspace chat', 'main', NULL,
   '2026-02-01T00:00:00.000Z', '2026-02-02T00:00:00.000Z', NULL, NULL);

INSERT INTO projection_thread_messages VALUES
  ('message-user', 'thread-active', 'turn-active', 'user',
   'Please find this USER needle in an old prompt.', 0, '2026-05-01T00:00:12.000Z', '2026-05-01T00:00:12.000Z'),
  ('message-percent', 'thread-active', NULL, 'user',
   'Literal 100% fix in a prompt.', 0, '2026-05-01T00:00:11.000Z', '2026-05-01T00:00:11.000Z'),
  ('message-percent-decoy', 'thread-percent-decoy', NULL, 'user',
   'Literal 100x fix in a prompt.', 0, '2026-05-01T00:00:11.000Z', '2026-05-01T00:00:11.000Z'),
  ('message-final', 'thread-active', 'turn-active', 'assistant',
   'The canonical FINAL NEEDLE appears in this completed answer.', 0, '2026-05-01T00:00:13.000Z', '2026-05-01T00:00:13.000Z'),
  ('message-interim', 'thread-active', 'turn-active', 'assistant',
   'Interim needle must not be searchable in UI mode.', 0, '2026-05-01T00:00:14.000Z', '2026-05-01T00:00:14.000Z'),
  ('message-system', 'thread-active', NULL, 'system',
   'System needle must not be searchable.', 0, '2026-05-01T00:00:15.000Z', '2026-05-01T00:00:15.000Z'),
  ('message-hidden', 'thread-archived', NULL, 'user',
   'Hidden needle in archive.', 0, '2026-04-01T00:00:16.000Z', '2026-04-01T00:00:16.000Z'),
  ('message-deleted', 'thread-deleted', NULL, 'user',
   'Deleted needle should be opt-in.', 0, '2026-03-01T00:00:16.000Z', '2026-03-01T00:00:16.000Z'),
  ('message-quote', 'thread-active', NULL, 'user',
   'He said it''s a "quoted" _value_.', 0, '2026-05-01T00:00:10.000Z', '2026-05-01T00:00:10.000Z');

INSERT INTO projection_turns (thread_id, turn_id, assistant_message_id, state, requested_at)
VALUES ('thread-active', 'turn-active', 'message-final', 'completed', '2026-05-01T00:00:12.000Z');

INSERT INTO projection_thread_sessions VALUES
  ('thread-active', 'idle', 'claude', 'sess-123', 'prov-thread-xyz', 'claude-work', '2026-05-02T00:00:00.000Z');
"""


def full_fixture(path: Path) -> None:
    write_db(path, [FULL_SCHEMA, SEED])


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
        with self.assertRaises(tts.UsageError):
            tts.discover_candidates(
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
            full_fixture(nested / "state.sqlite")
            production = home / ".t3" / "userdata" / "state.sqlite"
            full_fixture(production)
            candidates = tts.discover_candidates(cwd=home, home=home, env={})
            paths = {candidate.path.resolve() for candidate in candidates if candidate.path.is_file()}
            self.assertIn(production.resolve(), paths)
            self.assertNotIn((nested / "state.sqlite").resolve(), paths)

    def test_linked_worktree_outRanks_ambient_env_as_a_listed_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            worktree = root / "worktree"
            gitdir = root / "main.git" / "worktrees" / "feature"
            gitdir.mkdir(parents=True)
            worktree.mkdir()
            (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
            wt_db = worktree / ".t3" / "userdata" / "state.sqlite"
            full_fixture(wt_db)
            env_base = root / "env-home"
            env_db = env_base / "userdata" / "state.sqlite"
            full_fixture(env_db)
            home = root / "home"
            home.mkdir()
            candidates = tts.discover_candidates(
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
            full_fixture(repo / ".t3" / "userdata" / "state.sqlite")
            self.assertIsNone(tts.is_linked_worktree(repo))

    def test_explicit_base_dir_uses_userdata_not_dev(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            userdata = base / "userdata" / "state.sqlite"
            dev = base / "dev" / "state.sqlite"
            full_fixture(userdata)
            full_fixture(dev)
            candidates = tts.discover_candidates(cwd=base, home=base, env={}, base_dir=str(base))
            self.assertEqual(candidates[0].path, userdata)


class SearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "state.sqlite"
        full_fixture(self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def ids(self, report, source=None) -> list[str]:
        rows = report.results
        if source:
            rows = [row for row in rows if source in row["sources"] or row["source"] == source]
        return [row["thread_id"] for row in rows]

    def test_title_match(self) -> None:
        report = search(self.db, "rebuild performance")
        self.assertIn("thread-active", self.ids(report))
        match = report.results[0]
        self.assertEqual(match["database"], str(self.db))
        self.assertIn(match["source"], {"title", "user", "thread_id"})

    def test_user_and_assistant_message_matches(self) -> None:
        user = search(self.db, "USER needle")
        self.assertEqual(user.results[0]["source"], "user")
        self.assertIn("USER needle", user.results[0]["snippet"])
        assistant = search(self.db, "FINAL NEEDLE")
        self.assertEqual(assistant.results[0]["thread_id"], "thread-active")
        self.assertEqual(assistant.results[0]["source"], "assistant")

    def test_archived_included_by_default_deleted_opt_in(self) -> None:
        archived = search(self.db, "Hidden needle")
        self.assertEqual(self.ids(archived), ["thread-archived"])
        self.assertTrue(archived.results[0]["archived"])
        self.assertIn("archived", archived.results[0]["status"])

        deleted = search(self.db, "Deleted needle")
        self.assertEqual(deleted.results, [])
        included = search(self.db, "Deleted needle", include_deleted=True)
        self.assertEqual(self.ids(included), ["thread-deleted"])
        self.assertTrue(included.results[0]["deleted"])
        self.assertIn("deleted", included.results[0]["status"].lower())

    def test_ui_mode_matches_t3_message_semantics(self) -> None:
        ui_user = search(self.db, "user needle", active_only=True)
        self.assertEqual(ui_user.results[0]["source"], "user")

        ui_final = search(self.db, "FINAL NEEDLE", active_only=True)
        self.assertEqual(ui_final.results[0]["source"], "assistant")

        self.assertEqual(search(self.db, "interim needle", active_only=True).results, [])
        self.assertEqual(search(self.db, "System needle", active_only=True).results, [])
        self.assertEqual(search(self.db, "Hidden needle", active_only=True).results, [])

        recovery_interim = search(self.db, "interim needle")
        self.assertEqual(self.ids(recovery_interim), ["thread-active"])

        deduped = search(self.db, "needle", active_only=True)
        active_rows = [row for row in deduped.results if row["thread_id"] == "thread-active"]
        self.assertEqual(len(active_rows), 1)
        self.assertEqual(active_rows[0]["source"], "user")

    def test_ui_mode_excludes_deleted_projects(self) -> None:
        self.assertEqual(search(self.db, "Legacy workspace", active_only=True).results, [])
        recovery = search(self.db, "Legacy workspace")
        self.assertIn("thread-old-project", self.ids(recovery))

    def test_provider_ids(self) -> None:
        report = search(self.db, "prov-thread-xyz")
        self.assertEqual(self.ids(report), ["thread-active"])
        self.assertEqual(report.results[0]["provider_thread_id"], "prov-thread-xyz")
        session = search(self.db, "sess-123")
        self.assertEqual(self.ids(session), ["thread-active"])

    def test_parameterized_special_characters(self) -> None:
        percent = search(self.db, "100%")
        self.assertEqual(self.ids(percent), ["thread-active"])
        self.assertNotIn("thread-percent-decoy", self.ids(percent))
        quoted = search(self.db, "it's a \"quoted\" _value_")
        self.assertEqual(self.ids(quoted), ["thread-active"])
        underscore = search(self.db, "_value_")
        self.assertEqual(self.ids(underscore), ["thread-active"])

    def test_project_and_since_filters(self) -> None:
        by_path = search(self.db, "needle", project="/repo/t3code")
        self.assertTrue(self.ids(by_path))
        self.assertTrue(all(row["workspace_root"] == "/repo/t3code" for row in by_path.results))
        recent = search(self.db, "thread", since="2026-05-01")
        self.assertIn("thread-active", self.ids(recent))
        self.assertNotIn("thread-archived", self.ids(recent))

    def test_thread_lookup_is_bounded(self) -> None:
        report = search(self.db, query=None, thread_id="thread-active")
        self.assertEqual(report.mode, "thread")
        self.assertEqual(report.results[0]["thread_id"], "thread-active")
        self.assertIn("quoted", report.results[0]["first_user_snippet"])
        self.assertIn("FINAL NEEDLE", report.results[0]["last_assistant_snippet"])
        self.assertNotIn("Interim needle", report.results[0]["last_assistant_snippet"])
        self.assertLessEqual(len(report.results[0]["first_user_snippet"]), 240)

    def test_cli_json_and_readonly_enforcement(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        before = sha256(self.db)
        stdout = StringIO()
        with redirect_stdout(stdout):
            payload = tts.main(["--db", str(self.db), "--json", "rebuild"])
        self.assertEqual(payload, 0)
        body = json.loads(stdout.getvalue())
        self.assertEqual(body["results"][0]["thread_id"], "thread-active")
        after = sha256(self.db)
        self.assertEqual(before, after)

        conn = tts.connect_readonly(self.db)
        try:
            pragma = conn.execute("PRAGMA query_only").fetchone()
            self.assertEqual(int(pragma[0]), 1)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("CREATE TABLE should_fail (id INTEGER)")
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("INSERT INTO projection_threads (thread_id, project_id, title, created_at, updated_at) VALUES ('x','y','z','t','t')")
        finally:
            conn.close()
        self.assertEqual(sha256(self.db), before)

    def test_missing_database(self) -> None:
        missing = Path(self.tmp.name) / "nope.sqlite"
        with self.assertRaises(tts.SearchError) as raised:
            search(missing, "needle")
        self.assertIn("does not exist", str(raised.exception))

    def test_schema_drift_missing_required_table(self) -> None:
        broken = Path(self.tmp.name) / "broken.sqlite"
        write_db(broken, ["CREATE TABLE unrelated (id INTEGER);"])
        with self.assertRaises(tts.SearchError) as raised:
            search(broken, "needle")
        self.assertIn("Missing required table", str(raised.exception))

    def test_cli_reports_selected_database(self) -> None:
        from io import StringIO
        from contextlib import redirect_stdout

        stdout = StringIO()
        with redirect_stdout(stdout):
            code = tts.main(["--db", str(self.db), "rebuild performance"])
        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn(str(self.db), output)
        self.assertIn("thread-active", output)


class LegacySchemaTests(unittest.TestCase):
    def test_older_schema_without_optional_columns(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            db = Path(raw) / "state.sqlite"
            write_db(
                db,
                [
                    LEGACY_SCHEMA,
                    """
                    INSERT INTO projection_projects VALUES
                      ('proj-active', 'T3 Code', '/repo/t3code', '2026-01-01T00:00:00.000Z', '2026-05-01T00:00:00.000Z', NULL);
                    INSERT INTO projection_threads VALUES
                      ('thread-active', 'proj-active', 'Legacy title search', 'main',
                       '2026-05-01T00:00:00.000Z', '2026-05-02T00:00:00.000Z', NULL);
                    INSERT INTO projection_thread_messages VALUES
                      ('message-user', 'thread-active', 'user', 'legacy user needle', 0, '2026-05-01T00:00:12.000Z');
                    INSERT INTO projection_thread_sessions VALUES
                      ('thread-active', 'idle', 'codex', 'sess-legacy', '2026-05-02T00:00:00.000Z');
                    """,
                ],
            )
            report = search(db, "legacy user needle")
            self.assertEqual(report.results[0]["thread_id"], "thread-active")
            self.assertFalse(report.results[0]["archived"])
            provider = search(db, "sess-legacy")
            self.assertEqual(provider.results[0]["provider_session_id"], "sess-legacy")
            title = search(db, "Legacy title")
            self.assertEqual(title.results[0]["source"], "title")


class LikeEscapeTests(unittest.TestCase):
    def test_escape_like_pattern(self) -> None:
        self.assertEqual(tts.escape_like_pattern("100%_!"), "100!%!_!!")


class MultipleDatabaseTests(unittest.TestCase):
    def test_list_dbs_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            production = home / ".t3" / "userdata" / "state.sqlite"
            development = home / ".t3" / "dev" / "state.sqlite"
            full_fixture(production)
            full_fixture(development)
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
            userdata = env_base / "userdata" / "state.sqlite"
            dev = env_base / "dev" / "state.sqlite"
            full_fixture(userdata)
            full_fixture(dev)
            candidates = tts.discover_candidates(
                cwd=home, home=home, env={"T3CODE_HOME": str(env_base)}
            )
            env_paths = [candidate.path for candidate in candidates if candidate.kind == "env"]
            self.assertEqual(env_paths, [userdata])

    def test_db_directory_prefers_userdata_over_sibling_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            decoy = base / "state.sqlite"
            userdata = base / "userdata" / "state.sqlite"
            write_db(decoy, ["CREATE TABLE unrelated (id INTEGER);"])
            full_fixture(userdata)
            candidates = tts.discover_candidates(cwd=base, home=base, env={}, db=str(base))
            self.assertEqual(candidates[0].path, userdata)

    def test_one_bad_database_does_not_abort_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            good = home / ".t3" / "userdata" / "state.sqlite"
            bad = home / ".t3" / "dev" / "state.sqlite"
            full_fixture(good)
            write_db(bad, ["CREATE TABLE unrelated (id INTEGER);"])
            report = tts.run_search(
                query="rebuild",
                cwd=home,
                home=home,
                env={},
            )
            self.assertTrue(report.results)
            self.assertTrue(any("Missing required table" in warning for warning in report.warnings))
            self.assertIn("thread-active", [row["thread_id"] for row in report.results])


class ReviewFixTests(unittest.TestCase):
    def test_recovery_limit_does_not_starve_other_threads(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            db = Path(raw) / "state.sqlite"
            statements = [FULL_SCHEMA]
            inserts = [
                """
                INSERT INTO projection_projects VALUES
                  ('proj-active', 'T3 Code', '/repo/t3code', '2026-01-01T00:00:00.000Z', '2026-05-01T00:00:00.000Z', NULL);
                INSERT INTO projection_threads VALUES
                  ('thread-chatty', 'proj-active', 'Chatty', 'main', NULL,
                   '2026-05-01T00:00:00.000Z', '2026-05-03T00:00:00.000Z', NULL, NULL),
                  ('thread-quiet-b', 'proj-active', 'Quiet B', 'main', NULL,
                   '2026-05-01T00:00:00.000Z', '2026-05-02T00:00:00.000Z', NULL, NULL),
                  ('thread-quiet-c', 'proj-active', 'Quiet C', 'main', NULL,
                   '2026-05-01T00:00:00.000Z', '2026-05-01T00:00:00.000Z', NULL, NULL);
                """
            ]
            messages = ["INSERT INTO projection_thread_messages VALUES"]
            rows = []
            for index in range(30):
                rows.append(
                    f"('msg-chatty-{index}', 'thread-chatty', NULL, 'user', 'shared needle {index}', 0, "
                    f"'2026-05-01T00:00:{index:02d}.000Z', '2026-05-01T00:00:{index:02d}.000Z')"
                )
            rows.append(
                "('msg-b', 'thread-quiet-b', NULL, 'user', 'shared needle b', 0, "
                "'2026-05-01T00:00:40.000Z', '2026-05-01T00:00:40.000Z')"
            )
            rows.append(
                "('msg-c', 'thread-quiet-c', NULL, 'user', 'shared needle c', 0, "
                "'2026-05-01T00:00:41.000Z', '2026-05-01T00:00:41.000Z')"
            )
            messages.append(",\n".join(rows) + ";")
            write_db(db, statements + inserts + ["\n".join(messages)])
            report = search(db, "shared needle", limit=5)
            ids = {row["thread_id"] for row in report.results}
            self.assertEqual(ids, {"thread-chatty", "thread-quiet-b", "thread-quiet-c"})

    def test_checkpointed_open_does_not_create_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            db = Path(raw) / "state.sqlite"
            full_fixture(db)
            wal = Path(str(db) + "-wal")
            shm = Path(str(db) + "-shm")
            self.assertFalse(wal.exists())
            self.assertFalse(shm.exists())
            conn = tts.connect_readonly(db)
            try:
                conn.execute("SELECT COUNT(*) FROM projection_threads").fetchone()
            finally:
                conn.close()
            self.assertFalse(wal.exists())
            self.assertFalse(shm.exists())

    def test_until_date_includes_that_day(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            db = Path(raw) / "state.sqlite"
            full_fixture(db)
            report = search(db, "rebuild", until="2026-05-02")
            self.assertIn("thread-active", [row["thread_id"] for row in report.results])

    def test_workspace_match_snippet_is_the_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            db = Path(raw) / "state.sqlite"
            full_fixture(db)
            report = search(db, "/repo/t3code")
            self.assertTrue(report.results)
            self.assertIn("/repo/t3code", report.results[0]["snippet"] or "")

    def test_sessions_table_without_thread_id_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            db = Path(raw) / "state.sqlite"
            write_db(
                db,
                [
                    """
                    CREATE TABLE projection_projects (
                      project_id TEXT PRIMARY KEY,
                      title TEXT NOT NULL,
                      workspace_root TEXT NOT NULL,
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL,
                      deleted_at TEXT
                    );
                    CREATE TABLE projection_threads (
                      thread_id TEXT PRIMARY KEY,
                      project_id TEXT NOT NULL,
                      title TEXT NOT NULL,
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL,
                      deleted_at TEXT
                    );
                    CREATE TABLE projection_thread_sessions (
                      status TEXT NOT NULL,
                      provider_name TEXT
                    );
                    INSERT INTO projection_projects VALUES
                      ('proj-active', 'T3 Code', '/repo/t3code', '2026-01-01T00:00:00.000Z', '2026-05-01T00:00:00.000Z', NULL);
                    INSERT INTO projection_threads VALUES
                      ('thread-active', 'proj-active', 'Legacy title search',
                       '2026-05-01T00:00:00.000Z', '2026-05-02T00:00:00.000Z', NULL);
                    """
                ],
            )
            report = search(db, "Legacy title")
            self.assertEqual(report.results[0]["thread_id"], "thread-active")


if __name__ == "__main__":
    unittest.main()
