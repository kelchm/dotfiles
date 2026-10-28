"""Verify only the recovery cases that native T3 cannot provide."""

from __future__ import annotations
import hashlib
import json
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

from .t3_v2_fixture import (
    ARCHIVED,
    DELETED,
    DELEGATED_ID,
    ENVIRONMENT,
    NATIVE_ID,
    THREAD,
    add_message,
    fixture,
)

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "home/dot_agents/skills/t3-thread-search/scripts/t3-thread-search"
)
spec = spec_from_loader("t3_recovery_search", SourceFileLoader("t3_recovery_search", str(SCRIPT)))
recovery = module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.db = self.root / "userdata/statev2.sqlite"
        fixture(self.db)

    def search(self, *argv):
        args = recovery.build_parser().parse_args(argv)
        conn = recovery.connect_readonly(self.db)
        try:
            return recovery.search(conn, recovery.database_info(self.db), args)
        finally:
            conn.close()

    def execute(self, sql, params=()):
        conn = sqlite3.connect(self.db)
        conn.execute(sql, params)
        conn.commit()
        conn.close()

    def test_text_and_metadata_are_recovery_only(self):
        for query in (
            "Spark BIOS",
            "Archived Spark",
            "fix/spark",
            "100% fix",
            '"quoted" _value_',
            "don't",
        ):
            with self.subTest(query=query):
                found, _, _ = self.search(query)
                self.assertIn(ARCHIVED, [r["thread_id"] for r in found])
                self.assertNotIn(THREAD, [r["thread_id"] for r in found])
        self.assertFalse(self.search("Active Spark")[0])
        self.assertFalse(
            self.search("home-lab")[0]
        )  # Project titles are filters, not match sources.

    def test_deleted_records_are_opt_in_and_can_have_no_provider(self):
        self.assertFalse(self.search("deleted residual")[0])
        found, _, _ = self.search("--include-deleted", "deleted residual")
        self.assertEqual([r["thread_id"] for r in found], [DELETED])
        self.assertEqual(found[0]["status"], "deleted")
        self.assertIsNone(found[0]["provider"])
        self.assertEqual(
            self.search("--include-deleted", "--thread", DELETED)[0][0]["thread_id"], DELETED
        )

    def test_provider_ids_map_active_and_archived_but_not_provider_names(self):
        for value in (NATIVE_ID, "session-" + THREAD, "provider-" + THREAD):
            with self.subTest(value=value):
                found, _, _ = self.search("--provider-id", value)
                self.assertEqual([r["thread_id"] for r in found], [THREAD])
                self.assertEqual(found[0]["status"], "active")
        self.assertEqual(
            self.search("--provider-id", "native-" + ARCHIVED)[0][0]["thread_id"], ARCHIVED
        )
        for value in ("claudeAgent", "2826bc79", "codex"):
            self.assertFalse(self.search("--provider-id", value)[0])

    def test_provider_mapping_checks_historical_sessions_and_deduplicates(self):
        self.execute(
            "INSERT INTO orchestration_v2_projection_provider_threads VALUES (?,?,?,?,?,?,?)",
            ("historical", THREAD, "claudeAgent", "older-session", "idle", "2026-10-01", "{}"),
        )
        found, _, _ = self.search("--provider-id", "older-session")
        self.assertEqual(found[0]["provider_thread_id"], "historical")
        self.execute(
            "UPDATE orchestration_v2_projection_provider_threads SET provider_session_id=? WHERE thread_id=?",
            ("shared-session", THREAD),
        )
        self.assertEqual(len(self.search("--provider-id", "shared-session")[0]), 1)

    def test_deleted_provider_ids_require_opt_in(self):
        self.execute(
            "INSERT INTO orchestration_v2_projection_provider_threads VALUES (?,?,?,?,?,?,?)",
            (
                "provider-" + DELETED,
                DELETED,
                "claudeAgent",
                "deleted-session",
                "idle",
                "2026-10-25",
                '{"nativeThreadRef":{"nativeId":"deleted-native"}}',
            ),
        )
        for value in ("provider-" + DELETED, "deleted-session", "deleted-native"):
            self.assertFalse(self.search("--provider-id", value)[0])
            found, _, _ = self.search("--include-deleted", "--provider-id", value)
            self.assertEqual([item["thread_id"] for item in found], [DELETED])
            self.assertEqual(found[0]["status"], "deleted")

    def test_record_lookup_is_compact_and_does_not_read_active_threads(self):
        for ref in (
            DELETED,
            ENVIRONMENT + "/" + DELETED,
            "https://app.t3.codes/" + ENVIRONMENT + "/" + DELETED,
        ):
            found, _, _ = self.search("--include-deleted", "--thread", ref)
            self.assertEqual(found[0]["scoped_id"], ENVIRONMENT + "/" + DELETED)
            self.assertNotIn("message_counts", found[0])
            self.assertNotIn("first_user_snippet", found[0])
        self.assertFalse(self.search("--thread", THREAD)[0])
        self.assertFalse(self.search("--include-deleted", "--thread", ARCHIVED)[0])
        with self.assertRaisesRegex(recovery.SearchError, "environment"):
            self.search("--thread", "00000000-0000-0000-0000-000000000000/" + ARCHIVED)

    def test_opaque_thread_link_round_trip(self):
        opaque = DELEGATED_ID + "-deleted"
        self.execute(
            "UPDATE orchestration_v2_projection_threads SET thread_id=? WHERE thread_id=?",
            (opaque, DELETED),
        )
        for ref in (
            opaque,
            ENVIRONMENT + "/" + opaque,
            "t3-thread://v1/" + opaque,
            "t3-thread://v1/" + quote(opaque, safe=""),
        ):
            self.assertEqual(
                self.search("--include-deleted", "--thread", ref)[0][0]["thread_id"], opaque
            )

    def test_unknown_environment_is_reported_without_a_false_mismatch(self):
        (self.db.parent / "environment-id").unlink()
        with self.assertRaisesRegex(recovery.SearchError, "no environment-id"):
            self.search("--include-deleted", "--thread", ENVIRONMENT + "/" + DELETED)
        self.assertEqual(
            self.search("--include-deleted", "--thread", DELETED)[0][0]["thread_id"], DELETED
        )

    def test_pr_lookup_is_recovery_only(self):
        found, _, _ = self.search("--pr", "https://github.com/owner/home-lab/pull/123")
        self.assertEqual({r["thread_id"] for r in found}, {ARCHIVED, DELEGATED_ID})
        self.assertIn(
            DELETED,
            {
                r["thread_id"]
                for r in self.search(
                    "--include-deleted", "--pr", "https://github.com/owner/home-lab/pull/123"
                )[0]
            },
        )
        self.assertIn(
            "attribution thread:",
            " ".join(self.search("--pr", "https://github.com/another/repo/pull/123")[1]),
        )
        for value in ("123", "0", "https://github.com/owner/home-lab/issues/123"):
            with self.assertRaises(recovery.SearchError):
                self.search("--pr", value)

    def test_pr_lookup_covers_recorded_link_shapes_and_reports_the_matching_fields(self):
        link = {
            "projectId": "p",
            "repository": "owner/home-lab",
            "number": 717,
            "url": "https://github.com/owner/home-lab/pull/717",
        }
        payload = {
            "pullRequests": [dict(link, host="github.com")],
            "branchPullRequest": link,
            "linkedPullRequest": link,
        }
        for field in payload:
            with self.subTest(field=field):
                self.execute(
                    "UPDATE orchestration_v2_projection_threads SET payload_json=? WHERE thread_id IN (?,?,?)",
                    (json.dumps({field: payload[field]}), THREAD, ARCHIVED, DELETED),
                )
                found, _, _ = self.search("--pr", link["url"])
                self.assertEqual([item["thread_id"] for item in found], [ARCHIVED])
                self.assertEqual(found[0]["pr_sources"], [field])
                found, _, _ = self.search("--include-deleted", "--pr", link["url"])
                self.assertEqual({item["thread_id"] for item in found}, {ARCHIVED, DELETED})
                self.assertFalse(
                    self.search("--pr", "https://another.example/owner/home-lab/pull/717")[0]
                )
        self.execute(
            "UPDATE orchestration_v2_projection_threads SET payload_json=? WHERE thread_id=?",
            (json.dumps(payload), ARCHIVED),
        )
        found, _, _ = self.search("--pr", link["url"])
        self.assertEqual(len(found), 1)
        self.assertEqual(set(found[0]["pr_sources"]), set(payload))
        self.assertEqual(
            self.search("--pr", "https://github.com/Owner/Home-Lab/pull/717")[0][0]["thread_id"],
            ARCHIVED,
        )

    def test_project_filter_applies_before_messages_and_provider_mapping(self):
        for argv in (
            ["Spark BIOS"],
            ["--provider-id", NATIVE_ID],
            ["--pr", "https://github.com/owner/home-lab/pull/123"],
        ):
            self.assertTrue(self.search("--project", "/repo/home-lab", *argv)[0])
            self.assertFalse(self.search("--project", "another", *argv)[0])

    def test_literal_search_and_index_coverage(self):
        for query in (
            "streaming needle",
            "agent-authored opening prompt",
            "subagent transcript needle",
            "100x fix",
            '" OR "',
            "' OR 1=1 --",
        ):
            with self.subTest(query=query):
                self.assertFalse(self.search(query)[0])
        self.assertEqual(self.search("Archived delegate")[0][0]["thread_id"], DELEGATED_ID)

    def test_short_query_never_reads_messages(self):
        args = recovery.build_parser().parse_args(["BI"])
        conn = recovery.connect_readonly(self.db)
        statements = []
        conn.set_trace_callback(statements.append)
        try:
            found, warnings, _ = recovery.search(conn, recovery.database_info(self.db), args)
        finally:
            conn.close()
        self.assertTrue(found)
        self.assertIn("metadata only", " ".join(warnings))
        self.assertFalse(any("projection_messages" in statement for statement in statements))

    def test_newer_active_hits_do_not_hide_old_archived_hits(self):
        conn = sqlite3.connect(self.db)
        for index in range(5):
            add_message(conn, f"new-active-{index}", THREAD, "Spark BIOS")
        conn.commit()
        conn.close()
        with patch.object(recovery, "MESSAGE_HIT_LIMIT", 2):
            found, warnings, truncated = self.search("Spark BIOS")
        self.assertEqual([r["thread_id"] for r in found], [ARCHIVED])
        self.assertFalse(truncated)
        self.assertFalse(any("reached" in warning for warning in warnings))

    def test_hit_budget_is_explicit_and_project_filter_precedes_budget(self):
        conn = sqlite3.connect(self.db)
        for index in range(4):
            add_message(conn, f"archive-hit-{index}", ARCHIVED, "budget needle")
        conn.commit()
        conn.close()
        with patch.object(recovery, "MESSAGE_HIT_LIMIT", 2):
            found, warnings, truncated = self.search("budget needle")
        self.assertTrue(found)
        self.assertTrue(truncated)
        self.assertIn("older matches may be omitted", " ".join(warnings))
        self.assertFalse(self.search("--project", "other", "budget needle")[0])

    def test_other_projects_do_not_consume_the_message_budget(self):
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO projection_projects VALUES ('other','other','/repo/other',NULL)")
        conn.execute(
            """INSERT INTO orchestration_v2_projection_threads
            SELECT 'other-archive','other','Other archive',created_at,updated_at,archived_at,
                deleted_at,payload_json,NULL FROM orchestration_v2_projection_threads WHERE thread_id=?""",
            (ARCHIVED,),
        )
        for index in range(3):
            add_message(conn, f"other-project-{index}", "other-archive", "Spark BIOS")
        conn.commit()
        conn.close()
        with patch.object(recovery, "MESSAGE_HIT_LIMIT", 1):
            found, warnings, truncated = self.search("--project", "home-lab", "Spark BIOS")
        self.assertEqual([item["thread_id"] for item in found], [ARCHIVED])
        self.assertFalse(truncated)
        self.assertFalse(any("reached" in warning for warning in warnings))

    def test_result_limit_and_per_thread_deduplication(self):
        found, _, truncated = self.search("--limit", "1", "fix/spark")
        self.assertEqual(len(found), 1)
        self.assertTrue(truncated)
        found, _, _ = self.search("Spark BIOS")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["source"], "title")
        self.assertIn("user", found[0]["sources"])
        self.assertEqual(found[0]["snippet"], "Please update the Spark BIOS safely.")

    def test_equal_time_results_keep_the_same_order_at_every_limit(self):
        for thread in ("aaa", "bbb", "ccc"):
            self.execute(
                """INSERT INTO orchestration_v2_projection_threads
                SELECT ?,project_id,'ordering probe',created_at,updated_at,archived_at,
                    deleted_at,payload_json,NULL FROM orchestration_v2_projection_threads WHERE thread_id=?""",
                (thread, ARCHIVED),
            )
        full, _, _ = self.search("--limit", "100", "ordering probe")
        self.assertEqual([item["thread_id"] for item in full], ["aaa", "bbb", "ccc"])
        for limit in (1, 2, 3):
            found, _, truncated = self.search("--limit", str(limit), "ordering probe")
            self.assertEqual(found, full[:limit])
            self.assertEqual(truncated, limit < len(full))

    def test_long_normalized_matches_show_the_matching_original_text(self):
        text = "unrelated " * 80 + "don’t lose this match" + " trailing" * 80
        with sqlite3.connect(self.db) as writer:
            add_message(writer, "long-apostrophe", ARCHIVED, text)
        found, _, _ = self.search("don't lose this match")
        self.assertIn("don’t lose this match", found[0]["snippet"])
        self.assertLessEqual(len(found[0]["snippet"]), 240)

    def test_fts_query_plan_and_readonly_safety(self):
        before = hashlib.sha256(self.db.read_bytes()).digest()
        conn = recovery.connect_readonly(self.db)
        statements = []
        conn.set_trace_callback(statements.append)
        try:
            recovery.search(
                conn,
                recovery.database_info(self.db),
                recovery.build_parser().parse_args(["Spark BIOS"]),
            )
            sql = next(statement for statement in statements if "WITH hits" in statement)
            plan = "\n".join(row["detail"] for row in conn.execute("EXPLAIN QUERY PLAN " + sql))
            self.assertIn("VIRTUAL TABLE INDEX", plan)
            self.assertIn("INTEGER PRIMARY KEY", plan)
            self.assertNotIn("SCAN m", plan)
            self.assertEqual(conn.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM orchestration_v2_projection_threads")
        finally:
            conn.close()
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).digest())
        self.assertFalse(self.db.with_name(self.db.name + "-wal").exists())
        self.assertFalse(self.db.with_name(self.db.name + "-shm").exists())

    def test_live_wal_and_symlink_are_visible(self):
        alias = self.root / "alias.sqlite"
        alias.symlink_to(self.db)
        writer = sqlite3.connect(self.db)
        try:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute(
                "UPDATE orchestration_v2_projection_threads SET title=? WHERE thread_id=?",
                ("Fresh archive title", ARCHIVED),
            )
            writer.commit()
            self.assertNotIn("immutable=1", recovery.sqlite_uri(alias))
            conn = recovery.connect_readonly(alias)
            try:
                found, _, _ = recovery.search(
                    conn,
                    recovery.database_info(self.db),
                    recovery.build_parser().parse_args(["Fresh archive title"]),
                )
                self.assertEqual(found[0]["thread_id"], ARCHIVED)
            finally:
                conn.close()
        finally:
            writer.close()

    def test_rollback_journal_uses_normal_readonly_locking(self):
        writer = sqlite3.connect(self.db)
        try:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute(
                "UPDATE orchestration_v2_projection_threads SET title=? WHERE thread_id=?",
                ("Uncommitted", ARCHIVED),
            )
            self.assertNotIn("immutable=1", recovery.sqlite_uri(self.db))
            self.assertEqual(
                self.search("Archived Spark BIOS")[0][0]["title"], "Archived Spark BIOS"
            )
        finally:
            writer.rollback()
            writer.close()

    def test_reader_opened_before_a_writer_never_returns_uncommitted_pages(self):
        with sqlite3.connect(self.db) as setup:
            for index in range(200):
                setup.execute(
                    """INSERT INTO orchestration_v2_projection_threads
                    SELECT ?,project_id,?,created_at,updated_at,archived_at,deleted_at,'{}',NULL
                    FROM orchestration_v2_projection_threads WHERE thread_id=?""",
                    (f"probe-{index}", f"committed-{index}-" + "x" * 2000, ARCHIVED),
                )
        self.assertFalse(self.db.with_name(self.db.name + "-journal").exists())
        reader = recovery.connect_readonly(self.db)
        reader.execute("PRAGMA busy_timeout=20")
        writer = sqlite3.connect(self.db)
        try:
            writer.execute("PRAGMA cache_size=5")
            writer.execute("BEGIN EXCLUSIVE")
            writer.execute(
                "UPDATE orchestration_v2_projection_threads SET title='UNCOMMITTED-' || title WHERE thread_id LIKE 'probe-%'"
            )
            args = recovery.build_parser().parse_args(["UNCOMMITTED"])
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                recovery.search(reader, recovery.database_info(self.db), args)
            writer.rollback()
            self.assertFalse(recovery.search(reader, recovery.database_info(self.db), args)[0])
        finally:
            writer.rollback()
            writer.close()
            reader.close()

    def test_schema_is_required_without_scan_fallback(self):
        self.execute("DROP TABLE orchestration_v2_message_search")
        with self.assertRaisesRegex(recovery.SearchError, "Unsupported T3 schema"):
            recovery.connect_readonly(self.db)

    def test_default_store_and_stale_reporting(self):
        import os

        self.db.with_name("state.sqlite").touch()
        with patch.dict(os.environ, {"T3CODE_HOME": str(self.root)}):
            paths = recovery.database_paths(None)
        self.assertEqual(paths, [self.db, self.db.with_name("state.sqlite")])
        self.assertIn("legacy/stale", recovery.database_info(paths[1])["role"])
        self.assertEqual(recovery.database_paths(str(self.db)), paths)

    def test_live_tokenizer_matches_accents(self):
        from .t3_v2_fixture import LIVE_FTS_SCHEMA

        probe = sqlite3.connect(":memory:")
        try:
            try:
                probe.executescript(LIVE_FTS_SCHEMA)
            except sqlite3.OperationalError as error:
                self.skipTest(str(error))
        finally:
            probe.close()
        self.db = self.root / "live/statev2.sqlite"
        fixture(self.db, live_tokenizer=True)
        conn = sqlite3.connect(self.db)
        add_message(conn, "accent", ARCHIVED, "Inspect the café résumé")
        conn.commit()
        conn.close()
        self.assertEqual(self.search("cafe resume")[0][0]["thread_id"], ARCHIVED)
        for index, (query, original) in enumerate(
            (
                ("cafe resume one", "café résumé one"),
                ("cafe resume two", "cafe\u0301 re\u0301sume\u0301 two"),
            )
        ):
            with self.subTest(original=original):
                # Decomposed accents and a case expansion before the match must
                # not shift the snippet's offset in the original text.
                with sqlite3.connect(self.db) as writer:
                    add_message(
                        writer,
                        f"long-accent-{index}",
                        ARCHIVED,
                        "Cafe\u0301 İ " * 100 + original + " trailing" * 80,
                    )
                found, _, _ = self.search(query)
                self.assertIn(original, found[0]["snippet"])
                self.assertLessEqual(len(found[0]["snippet"]), 240)


if __name__ == "__main__":
    unittest.main()
