"""Exercise the shipped command and compatibility wrappers as users invoke them."""
from __future__ import annotations

import hashlib
import json
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .t3_v2_fixture import ENVIRONMENT, THREAD, fixture

SCRIPTS = Path(__file__).resolve().parents[2] / 'home/dot_agents/skills/t3-thread-search/scripts'
sys.path.insert(0, str(SCRIPTS))
from t3_thread import search


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.db = self.directory / 'store/userdata/statev2.sqlite'
        fixture(self.db)
        self.cwd = self.directory / 'unrelated-cwd'
        self.cwd.mkdir()

    def invoke(self, script: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                              cwd=self.cwd, capture_output=True, text=True)

    def test_search_and_status_match_compatibility_wrappers(self) -> None:
        for command, args in (
            ('search', ['--json', '--db', str(self.db), 'Spark BIOS']),
            ('search', ['--json', '--db', str(self.db), '--pr', '123']),
            ('search', ['--json', '--db', str(self.db), '--thread', THREAD]),
            ('search', ['--json', '--db', str(self.db), '--list-dbs']),
            ('status', ['--json', '--db', str(self.db), '--thread', ENVIRONMENT + '/' + THREAD]),
        ):
            with self.subTest(command=command, args=args):
                canonical = self.invoke('t3-thread', command, *args)
                legacy = self.invoke('t3-thread-' + command, *args)
                self.assertEqual(canonical.returncode, 0, canonical.stderr)
                self.assertEqual(legacy.returncode, canonical.returncode, legacy.stderr)
                actual, expected = json.loads(canonical.stdout), json.loads(legacy.stdout)
                for payload in (actual, expected):
                    if command == 'status':
                        payload.pop('activity_age_seconds')
                self.assertEqual(actual, expected)
                self.assertEqual(canonical.stderr, legacy.stderr)

    def test_help_and_usage_errors(self) -> None:
        for args, fragment in (
            (['--help'], '{search,status}'),
            (['search', '--help'], 'usage: t3-thread search'),
            (['status', '--help'], 'usage: t3-thread status'),
        ):
            result = self.invoke('t3-thread', *args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(fragment, result.stdout)
        for args in ([], ['unknown'], ['status'], ['search', '--watch-for', '10m']):
            result = self.invoke('t3-thread', *args)
            self.assertEqual(result.returncode, 2)
            self.assertIn('error:', result.stderr)
        for command in ('search', 'status'):
            args = ['--json', '--db', str(self.cwd / 'missing.sqlite'), '--thread', THREAD]
            canonical = self.invoke('t3-thread', command, *args)
            legacy = self.invoke('t3-thread-' + command, *args)
            self.assertEqual(canonical.returncode, legacy.returncode)
            self.assertNotEqual(canonical.returncode, 0)
            self.assertEqual(canonical.stdout, legacy.stdout)

    def test_removed_modes_are_rejected(self) -> None:
        for command, flags in (
            ('search', ['--remote-json', '/unused.json']),
            ('search', ['--endpoint', 'https://example.invalid']),
            ('status', ['--watch-for', '10m']),
            ('status', ['--interval', '15s']),
        ):
            with self.subTest(command=command, flags=flags):
                result = self.invoke('t3-thread', command, '--thread', THREAD, *flags)
                self.assertEqual(result.returncode, 2)
                self.assertIn('unrecognized arguments', result.stderr)

    def test_commands_do_not_create_bytecode_or_mutate_database(self) -> None:
        # Deploy only code into a fresh directory to catch imports creating pyc files.
        deployed = self.directory / 'scripts'
        shutil.copytree(SCRIPTS, deployed, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        before = hashlib.sha256(self.db.read_bytes()).digest()
        for name, command in (('t3-thread', ['search']), ('t3-thread', ['status']),
                              ('t3-thread-search', []), ('t3-thread-status', [])):
            result = subprocess.run([sys.executable, str(deployed / name), *command,
                                     '--json', '--db', str(self.db), '--thread', THREAD],
                                    cwd=self.cwd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).digest())
        self.assertFalse(list(deployed.rglob('__pycache__')))
        self.assertFalse(self.db.with_name(self.db.name + '-wal').exists())
        self.assertFalse(self.db.with_name(self.db.name + '-shm').exists())

    def test_ssh_program_runs_without_package_installation(self) -> None:
        before = hashlib.sha256(self.db.read_bytes()).digest()

        shadow = self.cwd / 'json.py'
        shadow.write_text("raise RuntimeError('remote cwd must not supply Python imports')\n")

        def execute_remote(argv, stdin):
            # Execute exactly the streamed program and remote arguments, isolated
            # from the local package and cwd, without opening an SSH connection.
            command = shlex.split(argv[-1])
            self.assertEqual(command[:3], ['python3', '-I', '-'])
            return subprocess.run([sys.executable, *command[1:]], input=stdin,
                                  cwd=self.cwd, capture_output=True)

        for args in (['Spark BIOS'], ['--thread', THREAD], ['--pr', '123']):
            with self.subTest(args=args):
                payload, error = search.run_ssh_search('test-host',
                    remote_argv=['--json', '--base-dir', str(self.db.parent.parent), *args],
                    ssh_exec=execute_remote)
                self.assertIsNone(error)
                self.assertIn(THREAD, [row['thread_id'] for row in payload['results']])
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).digest())
        self.assertEqual(list(self.cwd.iterdir()), [shadow])


if __name__ == '__main__':
    unittest.main()
