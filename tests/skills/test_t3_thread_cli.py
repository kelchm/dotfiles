"""Run the one shipped recovery entry point as a user invokes it."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from .t3_v2_fixture import ARCHIVED, DELETED, ENVIRONMENT, NATIVE_ID, fixture

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "home/dot_agents/skills/t3-thread-search/scripts/t3-thread-search"
)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "userdata/statev2.sqlite"
        fixture(self.db)

    def invoke(self, *argv):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--db", str(self.db), *argv],
            capture_output=True,
            text=True,
            cwd=self.root,
        )

    def test_json_and_text_recovery_results(self):
        for argv in (
            ["Spark BIOS"],
            ["--provider-id", NATIVE_ID],
            ["--include-deleted", "--thread", ENVIRONMENT + "/" + DELETED],
            ["--pr", "https://github.com/owner/home-lab/pull/123"],
            ["--list-dbs"],
        ):
            with self.subTest(argv=argv):
                result = self.invoke("--json", *argv)
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["databases"][0]["path"], str(self.db))
                text = self.invoke(*argv)
                self.assertEqual(text.returncode, 0, text.stderr)
                if "--list-dbs" not in argv:
                    self.assertIn(payload["results"][0]["scoped_id"], text.stdout)

    def test_usage_and_removed_modes(self):
        for argv in (
            [],
            ["--active-only", "needle"],
            ["--since", "7d", "needle"],
            ["--until", "2026-10-25", "needle"],
            ["--ssh", "host"],
            ["--remote-json", "file"],
            ["--endpoint", "https://example.invalid"],
            ["--watch-for", "10m"],
            ["--environment", ENVIRONMENT],
            ["--base-dir", "/unused"],
            ["--cwd", "/unused"],
            ["--provider-id", NATIVE_ID, "extra-query"],
            ["--limit", "0", "needle"],
            ["--limit", "101", "needle"],
            ["--thread", ARCHIVED],
        ):
            with self.subTest(argv=argv):
                result = self.invoke(*argv)
                self.assertEqual(result.returncode, 2)
                self.assertIn("error:", result.stderr)
        self.assertEqual(self.invoke("--help").returncode, 0)

    def test_missing_and_unsupported_database_errors(self):
        self.db.unlink()
        result = self.invoke("--json", "needle")
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not exist", json.loads(result.stdout)["error"])
        self.db.touch()
        result = self.invoke("--json", "needle")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unsupported T3 schema", json.loads(result.stdout)["error"])

    def test_standalone_command_has_no_code_or_database_writes(self):
        script = self.root / "standalone/t3-thread-search"
        script.parent.mkdir()
        shutil.copy2(SCRIPT, script)
        before = hashlib.sha256(self.db.read_bytes()).digest()
        result = subprocess.run(
            [sys.executable, str(script), "--json", "--db", str(self.db), "Spark BIOS"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["results"][0]["thread_id"], ARCHIVED)
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).digest())
        self.assertEqual(list(script.parent.iterdir()), [script])
        self.assertFalse(self.db.with_name(self.db.name + "-wal").exists())
        self.assertFalse(self.db.with_name(self.db.name + "-shm").exists())


if __name__ == "__main__":
    unittest.main()
