#!/usr/bin/env python3
"""Isolated Git fixtures; never reads or moves the user's repositories."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[2] / 'home/dot_agents/skills/repo-workspace/scripts/migrate.py'
SPEC = importlib.util.spec_from_file_location('migrate', MODULE)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='repo-migration-fixture-')
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / 'fixture-home'
        self.home.mkdir()
        self.environment = patch.dict(os.environ, {'HOME': str(self.home),
                                                   'XDG_CONFIG_HOME': str(self.home / '.config')})
        self.environment.start()
        self.source = self.root / 'old owner' / 'repo'
        self.dest = self.root / 'upstream owner' / 'repo'
        self.source.mkdir(parents=True)
        self.dest.parent.mkdir()
        self.journal = self.root / 'move.json'
        self.run_git(self.source, 'init', '-b', 'main')
        self.run_git(self.source, 'config', 'user.name', 'Migration fixture')
        self.run_git(self.source, 'config', 'user.email', 'fixture@example.invalid')
        self.run_git(self.source, 'config', 'commit.gpgsign', 'false')
        (self.source / 'tracked').write_text('preserve me\n')
        (self.source / '.gitignore').write_text('cache/\n')
        self.run_git(self.source, 'add', '.')
        self.run_git(self.source, 'commit', '-m', 'Initialize disposable fixture')
        self.process_guard = patch.object(m, 'check_processes')
        self.process_guard.start()

    def tearDown(self):
        self.process_guard.stop()
        self.environment.stop()
        self.temporary.cleanup()

    def run_git(self, path, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        # Isolate fixture commits and status from user hooks, signing, and ignores.
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
        result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(path), *args],
                                capture_output=True, env=env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return result.stdout

    def linked(self, name='task'):
        path = self.root / ('retained ' + name)
        self.run_git(self.source, 'worktree', 'add', '-b', name, str(path))
        return path

    def prepare(self):
        return m.prepare(self.source, self.dest, self.journal)

    def test_roundtrip_primary_with_ignored_material_and_refs(self):
        (self.source / 'cache').mkdir()
        (self.source / 'cache' / 'result').write_text('ignored but preserved')
        self.run_git(self.source, 'update-ref', 'refs/notes/fixture', 'HEAD')
        before_inode = self.source.stat().st_ino
        data = self.prepare()
        self.assertTrue(self.source.exists())
        self.assertFalse(self.dest.exists())
        if not m.WINDOWS:  # Windows reports access through ACLs, not mode bits.
            self.assertEqual(self.journal.stat().st_mode & 0o777, 0o600)
        m.apply(self.journal, data)
        self.assertFalse(self.source.exists())
        self.assertEqual(self.dest.stat().st_ino, before_inode)
        self.assertEqual((self.dest / 'cache/result').read_text(), 'ignored but preserved')
        m.verify_data(data, True)
        m.apply(self.journal, data)  # Safe retry after a lost success response.
        m.rollback(self.journal, data)
        m.verify_data(data, False)
        m.rollback(self.journal, data)  # Likewise for rollback.
        self.assertEqual(data['phase'], 'rolled_back')

    def test_multiple_worktrees_keep_paths_and_history(self):
        one, two = self.linked('one'), self.linked('two')
        (one / 'tracked').write_text('worktree branch content')
        self.run_git(one, 'commit', '-am', 'Disposable worktree change')
        heads = [self.run_git(p, 'rev-parse', 'HEAD') for p in (self.source, one, two)]
        data = self.prepare()
        m.apply(self.journal, data)
        for path, head in zip((self.dest, one, two), heads):
            self.assertEqual(self.run_git(path, 'rev-parse', 'HEAD'), head)
        self.assertIn((self.dest / '.git').as_posix(), (one / '.git').read_text())
        m.rollback(self.journal, data)
        self.assertIn((self.source / '.git').as_posix(), (one / '.git').read_text())

    def test_repair_failure_restores_base_and_pointers(self):
        wt = self.linked()
        data = self.prepare()
        real_repair = m.repair
        def fail_forward(base, journal):
            if base == self.dest:
                raise m.Refused('Injected repair failure')
            return real_repair(base, journal)
        with patch.object(m, 'repair', side_effect=fail_forward):
            with self.assertRaisesRegex(m.Refused, 'Injected'):
                m.apply(self.journal, data)
        self.assertEqual(m.load(self.journal)['phase'], 'rolled_back')
        self.assertTrue(self.source.exists())
        self.assertFalse(self.dest.exists())
        self.run_git(wt, 'status', '--porcelain')

    def test_path_conditional_config_refuses_and_restores_original_path(self):
        wt = self.linked()
        extra = self.home / 'canonical.gitconfig'
        extra.write_text('[user]\n\temail = changed@example.invalid\n')
        (self.home / '.gitconfig').write_text(
            f'[includeIf "gitdir:{self.dest.parent.as_posix()}/"]\n\tpath = {extra.as_posix()}\n')
        data = self.prepare()
        with self.assertRaisesRegex(m.Refused, 'effective_config'):
            m.apply(self.journal, data)
        self.assertEqual(data['phase'], 'rolled_back')
        self.assertTrue(self.source.exists())
        self.assertFalse(self.dest.exists())
        self.assertIn((self.source / '.git').as_posix(), (wt / '.git').read_text())
        m.verify_data(data, False)

    def test_automatic_undo_keeps_concurrent_changes_and_reports_them(self):
        data = self.prepare()
        real_repair = m.repair
        def introduce_change(base, journal):
            if base == self.dest:
                self.run_git(base, 'branch', 'concurrent-work')
                raise m.Refused('Injected forward failure with concurrent work')
            return real_repair(base, journal)
        with patch.object(m, 'repair', side_effect=introduce_change):
            with self.assertRaisesRegex(m.Refused, 'automatic recovery failed'):
                m.apply(self.journal, data)
        self.assertTrue(self.source.exists())
        self.assertFalse(self.dest.exists())
        self.assertEqual(data['phase'], 'recovery_required')
        self.run_git(self.source, 'rev-parse', '--verify', 'refs/heads/concurrent-work')

    def test_automatic_undo_does_not_move_an_unrelated_inode(self):
        data = self.prepare()
        m.record(self.journal, data, 'moving')
        self.dest.mkdir()
        with self.assertRaisesRegex(m.Refused, 'inode'):
            m.undo_failed_apply(self.journal, data)
        self.assertTrue((self.source / '.git').is_dir())

    def test_destination_race_leaves_prepared_journal_and_both_paths_intact(self):
        data = self.prepare()
        real_rename = m.rename_exclusive
        def create_competitor(source, destination):
            destination.mkdir()
            (destination / 'sentinel').write_text('another owner')
            real_rename(source, destination)
        with patch.object(m, 'rename_exclusive', side_effect=create_competitor):
            with self.assertRaises(FileExistsError):
                m.apply(self.journal, data)
        self.assertTrue((self.source / '.git').is_dir())
        self.assertEqual((self.dest / 'sentinel').read_text(), 'another owner')
        self.assertEqual(m.load(self.journal)['phase'], 'prepared')

    def test_untracked_cache_index_refresh_does_not_block_verification(self):
        wt = self.linked()
        self.run_git(self.source, 'config', 'core.untrackedCache', 'true')
        for path in (self.source, wt):
            self.run_git(path, 'update-index', '--untracked-cache')
            self.run_git(path, 'status')
        data = self.prepare()
        m.apply(self.journal, data)
        for path in (self.dest, wt):
            self.run_git(path, 'status')
        m.verify_data(data, True)
        m.rollback(self.journal, data)
        m.verify_data(data, False)

    def test_relative_path_preference_does_not_change_format_or_pointers(self):
        wt = self.linked()
        (self.home / '.gitconfig').write_text('[worktree]\n\tuseRelativePaths = true\n')
        data = self.prepare()
        m.apply(self.journal, data)
        self.assertEqual((wt / '.git').read_text(),
                         f"gitdir: {(self.dest / '.git' / data['before']['checkouts'][1]['admin']).as_posix()}\n")
        self.assertEqual(m.git(self.dest, 'config', '--local', '--get', 'extensions.relativeWorktrees', ok=(0, 1)), b'')
        m.rollback(self.journal, data)

    def test_absolute_path_config_is_refused_without_exposing_values(self):
        # Windows tools write either slash, mixed slashes, and any case; elsewhere these coincide.
        hooks = self.source / '.githooks'
        windows = [hooks.as_posix().upper(), str(hooks.parent) + '/.githooks'] if m.WINDOWS else []
        spellings = [str(hooks), hooks.as_posix(), *windows]
        for value in spellings:
            with self.subTest(value=value):
                self.run_git(self.source, 'config', 'core.hooksPath', value)
                with self.assertRaisesRegex(m.Refused, 'core.hookspath') as result:
                    self.prepare()
                self.assertNotIn('.githooks', str(result.exception))
                self.assertFalse(self.journal.exists())
                self.assertTrue(self.source.exists())

    def test_wrong_case_existing_destination_parent_is_refused(self):
        parent = self.root / 'CaseOwner'
        parent.mkdir()
        wrong_case = self.root / 'caseowner'
        if not wrong_case.exists():
            self.skipTest('Filesystem is case-sensitive')
        with self.assertRaisesRegex(m.Refused, 'spelling'):
            m.prepare(self.source, wrong_case / 'repo', self.journal)
        self.assertEqual(list(parent.iterdir()), [])

    def test_global_config_change_blocks_standalone_rollback(self):
        data = self.prepare()
        m.apply(self.journal, data)
        (self.home / '.gitconfig').write_text('[commit]\n\tgpgsign = true\n')
        with self.assertRaisesRegex(m.Refused, 'effective_config'):
            m.rollback(self.journal, data)
        self.assertTrue(self.dest.exists())

    def test_clean_in_progress_operation_is_refused(self):
        (self.source / '.git/BISECT_START').write_text('main\n')
        with self.assertRaisesRegex(m.Refused, 'in progress'):
            self.prepare()

    def test_cli_errors_report_phase_checkout_and_field(self):
        data = self.prepare()
        m.apply(self.journal, data)
        self.run_git(self.dest, 'branch', 'later-branch')
        result = subprocess.run([sys.executable, str(MODULE), 'verify', '--journal', str(self.journal)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        for expected in (str(self.dest), 'refs', 'journal phase: applied'):
            self.assertIn(expected, result.stderr)

    def test_finished_journal_requests_a_fresh_plan(self):
        data = self.prepare()
        m.apply(self.journal, data)
        m.rollback(self.journal, data)
        with self.assertRaisesRegex(m.Refused, 'finished after rollback'):
            m.apply(self.journal, data)

    def test_rollback_refuses_a_corrupted_pointer_prefix(self):
        wt = self.linked()
        data = self.prepare()
        m.apply(self.journal, data)
        marker = (wt / '.git').read_text()
        (wt / '.git').write_text(marker.replace('gitdir: ', 'GITDIR: ', 1))
        with self.assertRaises(m.Refused):
            m.rollback(self.journal, data)
        self.assertEqual(m.load(self.journal)['phase'], 'applied')
        self.assertTrue(self.dest.exists())

    def test_partial_repair_failure_restores_every_pointer(self):
        one, two = self.linked('one'), self.linked('two')
        data = self.prepare()
        real_repair = m.repair
        def partial(base, journal):
            if base == self.dest:
                m.git(base, 'worktree', 'repair', str(one))
                raise m.Refused('Injected partial repair')
            return real_repair(base, journal)
        with patch.object(m, 'repair', side_effect=partial):
            with self.assertRaises(m.Refused):
                m.apply(self.journal, data)
        self.assertEqual(data['phase'], 'rolled_back')
        for path in (one, two):
            self.assertIn((self.source / '.git').as_posix(), (path / '.git').read_text())

    def test_resume_rollback_after_crash_between_rename_and_repair(self):
        self.linked()
        data = self.prepare()
        m.record(self.journal, data, 'moving')
        m.rename_exclusive(self.source, self.dest)
        m.rollback(self.journal, m.load(self.journal))
        m.verify_data(data, False)

    def test_resume_rollback_after_crash_during_rollback(self):
        self.linked()
        data = self.prepare()
        m.apply(self.journal, data)
        m.record(self.journal, data, 'rolling_back')
        m.rename_exclusive(self.dest, self.source)
        m.rollback(self.journal, m.load(self.journal))
        m.verify_data(data, False)

    def test_dirty_tracked_and_untracked_are_refused(self):
        for path in ('tracked', 'untracked'):
            with self.subTest(path=path):
                original = (self.source / path).read_bytes() if path == 'tracked' else None
                (self.source / path).write_text('dirty')
                with self.assertRaisesRegex(m.Refused, 'Dirty'):
                    self.prepare()
                if original is None:
                    (self.source / path).unlink()
                else:
                    (self.source / path).write_bytes(original)
        self.assertFalse(self.journal.exists())

    def test_dirty_linked_checkout_is_refused(self):
        wt = self.linked()
        (wt / 'untracked').write_text('keep')
        with self.assertRaisesRegex(m.Refused, 'Dirty'):
            self.prepare()

    def test_stale_refs_are_refused_before_move(self):
        data = self.prepare()
        self.run_git(self.source, 'branch', 'new-local-branch')
        with self.assertRaisesRegex(m.Refused, 'refs'):
            m.apply(self.journal, data)
        self.assertTrue(self.source.exists())
        self.assertEqual(data['phase'], 'prepared')

    def test_new_worktree_after_prepare_is_refused(self):
        data = self.prepare()
        self.linked()
        with self.assertRaisesRegex(m.Refused, 'registrations'):
            m.apply(self.journal, data)

    def test_configuration_drift_is_refused(self):
        data = self.prepare()
        self.run_git(self.source, 'config', 'remote.pushDefault', 'changed')
        with self.assertRaises(m.Refused):
            m.apply(self.journal, data)
        self.assertFalse(self.dest.exists())

    def test_rollback_refuses_new_work(self):
        data = self.prepare()
        m.apply(self.journal, data)
        (self.dest / 'new-work').write_text('do not lose this')
        with self.assertRaisesRegex(m.Refused, 'Dirty'):
            m.rollback(self.journal, data)
        self.assertEqual((self.dest / 'new-work').read_text(), 'do not lose this')
        self.assertFalse(self.source.exists())

    def test_rollback_refuses_new_commits_and_refs(self):
        data = self.prepare()
        m.apply(self.journal, data)
        self.run_git(self.dest, 'branch', 'later-work')
        with self.assertRaisesRegex(m.Refused, 'refs'):
            m.rollback(self.journal, data)

    def test_destination_and_journal_collisions_are_preserved(self):
        self.dest.mkdir()
        (self.dest / 'sentinel').write_text('keep')
        with self.assertRaisesRegex(m.Refused, 'occupied'):
            self.prepare()
        self.assertEqual((self.dest / 'sentinel').read_text(), 'keep')
        (self.dest / 'sentinel').unlink()
        self.dest.rmdir()
        self.journal.write_text('existing record')
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(self.journal.read_text(), 'existing record')

    def test_atomic_rename_does_not_replace_even_empty_directory(self):
        self.dest.mkdir()
        with self.assertRaises(OSError):
            m.rename_exclusive(self.source, self.dest)
        self.assertTrue((self.source / '.git').is_dir())
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_symlink_paths_are_refused(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(m.Refused, 'symlink'):
            m.path_arg(alias)

    def test_journal_inside_checkout_is_refused(self):
        for journal in (self.source / 'move.json', self.dest / 'move.json'):
            with self.assertRaises(m.Refused):
                m.prepare(self.source, self.dest, journal)

    def test_ancestor_repo_is_refused(self):
        self.run_git(self.dest.parent, 'init', '-b', 'main')
        with self.assertRaisesRegex(m.Refused, 'Organizer'):
            self.prepare()

    def test_nested_worktree_is_refused(self):
        nested = self.source / 'cache' / 'nested'
        self.run_git(self.source, 'worktree', 'add', '-b', 'nested', str(nested))
        with self.assertRaisesRegex(m.Refused, 'Nested'):
            self.prepare()

    def test_nested_independent_repo_is_refused(self):
        nested = self.source / 'cache' / 'nested'
        nested.mkdir(parents=True)
        self.run_git(nested, 'init', '-b', 'main')
        with self.assertRaisesRegex(m.Refused, 'Nested'):
            self.prepare()

    def test_unreadable_directory_fails_nested_check_closed(self):
        hidden = self.source / 'cache' / 'hidden'
        hidden.mkdir(parents=True)
        hidden.chmod(0)
        try:
            if os.access(hidden, os.R_OK):
                self.skipTest('Running with privileges that bypass permissions')
            with self.assertRaisesRegex(m.Refused, 'Cannot inspect'):
                self.prepare()
        finally:
            hidden.chmod(0o700)

    def test_broken_worktree_is_refused(self):
        wt = self.linked()
        wt.rename(self.root / 'unregistered-location')
        with self.assertRaises(m.Refused):
            self.prepare()

    def test_submodule_configuration_is_refused(self):
        (self.source / '.gitmodules').write_text('')
        self.run_git(self.source, 'add', '.gitmodules')
        self.run_git(self.source, 'commit', '-m', 'Disposable submodule marker')
        with self.assertRaisesRegex(m.Refused, 'Submodules'):
            self.prepare()

    def test_hidden_index_flags_are_refused(self):
        self.run_git(self.source, 'update-index', '--assume-unchanged', 'tracked')
        with self.assertRaisesRegex(m.Refused, 'Index flags'):
            self.prepare()

    def test_git_lock_is_refused(self):
        (self.source / '.git/index.lock').write_text('owned by another operation')
        with self.assertRaisesRegex(m.Refused, 'lock'):
            self.prepare()

    def test_idle_gh_stack_locks_allow_move_rollback_and_undo(self):
        for name in ('gh-stack.lock', 'gh-stack-operation.lock'):
            (self.source / '.git' / name).touch()
        data = self.prepare()
        m.apply(self.journal, data)
        m.rollback(self.journal, data)
        self.journal.unlink()
        data = self.prepare()
        real_repair = m.repair
        def fail_forward(base, journal):
            if base == self.dest:
                raise m.Refused('Injected repair failure')
            return real_repair(base, journal)
        with patch.object(m, 'repair', side_effect=fail_forward):
            with self.assertRaisesRegex(m.Refused, 'Injected'):
                m.apply(self.journal, data)
        self.assertEqual(m.load(self.journal)['phase'], 'rolled_back')

    def test_busy_or_unfamiliar_locks_are_refused(self):
        common = self.source / '.git'
        for lock, content in ((common / 'gh-stack.lock', 'busy'), (common / 'other-tool.lock', ''),
                              (common / 'refs' / 'gh-stack.lock', '')):
            with self.subTest(lock=str(lock.relative_to(common))):
                lock.write_text(content)
                with self.assertRaisesRegex(m.Refused, 'lock'):
                    self.prepare()
                lock.unlink()
        if m.WINDOWS:
            return  # A held lock blocks the rename instead; see the in-use test.
        lock = common / 'gh-stack.lock'
        lock.touch()
        holder = subprocess.Popen([sys.executable, '-c', 'import sys, time; f = open(sys.argv[1]); time.sleep(30)', lock])
        try:
            self.wait_for_handle(lock)
            with self.assertRaisesRegex(m.Refused, 'lock'):
                self.prepare()
        finally:
            holder.terminate()
            holder.wait(timeout=10)

    def wait_for_handle(self, path):
        for _ in range(50):
            if subprocess.run(['lsof', '-t', '--', str(path)], capture_output=True).stdout.strip():
                return
            time.sleep(0.1)
        self.fail(f'No process opened {path}')

    def test_cross_device_refusal_without_mutation(self):
        # Patch only the device comparison, leaving the actual fixture intact.
        original = Path.stat
        destination_parent = self.dest.parent
        def fake_stat(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == destination_parent:
                fields = list(result)
                fields[2] += 1
                return os.stat_result(fields)
            return result
        with patch.object(Path, 'stat', fake_stat):
            with self.assertRaisesRegex(m.Refused, 'Cross-filesystem'):
                self.prepare()
        self.assertTrue(self.source.exists())
        self.assertFalse(self.dest.exists())

    def test_exclusive_journal_lock(self):
        with m.locked(self.journal):
            with self.assertRaises(FileExistsError):
                with m.locked(self.journal):
                    self.fail('Second lock acquired')
        self.assertFalse(self.journal.with_name(self.journal.name + '.lock').exists())

    @unittest.skipIf(m.WINDOWS, 'Windows has no lsof; the rename itself is the guard')
    def test_real_cwd_guard(self):
        self.process_guard.stop()
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], cwd=self.source)
        try:
            with self.assertRaisesRegex(m.Refused, 'Process [0-9]+ has a cwd'):
                m.check_processes([self.source])
            m.check_processes([self.dest])
        finally:
            process.terminate()
            process.wait(timeout=10)

    @unittest.skipUnless(m.WINDOWS, 'Windows drive letters')
    def test_lowercase_drive_letter_round_trips(self):
        self.linked()
        lower = lambda path: Path(str(path)[0].lower() + str(path)[1:])
        data = m.prepare(lower(self.source), lower(self.dest), self.journal)
        m.apply(self.journal, data)
        m.verify_data(data, True)
        m.rollback(self.journal, data)

    @unittest.skipUnless(m.WINDOWS, 'Windows-only guard')
    def test_windows_will_not_move_a_directory_in_use(self):
        data = self.prepare()
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], cwd=self.source)
        try:
            with self.assertRaises(OSError):
                m.apply(self.journal, data)
        finally:
            process.terminate()
            process.wait(timeout=10)
        with open(self.source / 'tracked'):
            with self.assertRaises(OSError):
                m.apply(self.journal, data)
        self.assertEqual(m.load(self.journal)['phase'], 'prepared')
        self.assertFalse(self.dest.exists())
        m.apply(self.journal, data)

    def checkpoint(self, path, ordinal, tree='HEAD^{tree}', parent='HEAD', ref=None, named=None):
        """Mimic T3: a commit of the clean HEAD tree, parented on HEAD, under a per-thread ref."""
        ref = ref or f'refs/t3/orchestration-v2/checkpoints/dGhyZWFk/ordinal/{ordinal}'
        tree = self.run_git(path, 'rev-parse', tree).decode().strip()
        parent = self.run_git(path, 'rev-parse', parent).decode().strip()
        message = f't3 checkpoint ref={named or ref}'
        oid = self.run_git(path, 'commit-tree', tree, '-p', parent, '-m', message).decode().strip()
        self.run_git(path, 'update-ref', ref, oid)
        return [ref, oid, str(path)]

    def moved_with_task_worktree(self):
        wt = self.linked()
        (wt / 'tracked').write_text('task branch content')
        self.run_git(wt, 'commit', '-am', 'Diverge the task worktree')
        self.run_git(self.source, 'update-ref', 'refs/notes/fixture', 'HEAD')
        data = self.prepare()
        m.apply(self.journal, data)
        return data, wt

    def assert_record_refused(self, data, claims, pattern):
        before = self.journal.read_bytes()
        with self.assertRaisesRegex(m.Refused, pattern):
            m.record_checkpoints(self.journal, data, claims)
        self.assertEqual(self.journal.read_bytes(), before)

    def test_continuation_checkpoints_are_recorded_without_rewriting_snapshot(self):
        data, wt = self.moved_with_task_worktree()
        saved = json.dumps(data['before'], sort_keys=True)
        claims = [self.checkpoint(self.dest, 0), self.checkpoint(wt, 49)]
        with self.assertRaisesRegex(m.Refused, 'refs'):
            m.verify_data(data, True)
        result = subprocess.run([sys.executable, str(MODULE), 'record-checkpoints', '--journal', str(self.journal),
                                 *[arg for claim in claims for arg in ('--checkpoint', *claim)]],
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['checkpoints'], 2)
        data = m.load(self.journal)
        self.assertEqual(json.dumps(data['before'], sort_keys=True), saved)
        self.assertEqual(data['phase'], 'applied')
        m.verify_data(data, True)
        m.apply(self.journal, data)  # A retried apply accepts recorded checkpoints too.
        later = self.checkpoint(self.dest, 1)
        with self.assertRaisesRegex(m.Refused, 'refs'):
            m.verify_data(data, True)
        m.record_checkpoints(self.journal, data, [later])
        self.assert_record_refused(data, [later], 'named twice')
        with self.assertRaisesRegex(m.Refused, 'reverse move'):
            m.rollback(self.journal, data)
        self.assertTrue(self.dest.exists())

    def test_checkpoint_recording_refuses_changed_or_deleted_old_refs(self):
        data, _ = self.moved_with_task_worktree()
        claim = self.checkpoint(self.dest, 3)
        original = self.run_git(self.dest, 'rev-parse', 'refs/notes/fixture').decode().strip()
        self.run_git(self.dest, 'update-ref', 'refs/notes/fixture', claim[1])
        self.assert_record_refused(data, [claim], 'refs')
        self.run_git(self.dest, 'update-ref', '-d', 'refs/notes/fixture')
        self.assert_record_refused(data, [claim], 'refs')
        self.run_git(self.dest, 'update-ref', 'refs/notes/fixture', original)
        m.record_checkpoints(self.journal, data, [claim])

    def test_checkpoint_recording_refuses_unexpected_refs(self):
        data, wt = self.moved_with_task_worktree()
        claim = self.checkpoint(self.dest, 3)
        undeclared = self.checkpoint(wt, 49)
        self.assert_record_refused(data, [claim], 'refs')
        self.run_git(self.dest, 'update-ref', '-d', undeclared[0])
        self.run_git(self.dest, 'branch', 'unrelated-work')
        self.assert_record_refused(data, [claim], 'refs')
        self.run_git(self.dest, 'branch', '-D', 'unrelated-work')
        padded = ('refs/t3/orchestration-v2/checkpoints/dGhyZWFk/ordinal/00',
                  'refs/t3/orchestration-v2/checkpoints/dGhyZWFk/ordinal/01')
        for ref in ('refs/heads/unrelated-work', 'refs/t3/other/thread',
                    'refs/t3/orchestration-v2/checkpoints/a/b/ordinal/1', *padded):
            with self.subTest(ref=ref):
                self.assert_record_refused(data, [[ref, claim[1], str(self.dest)]], 'Not a T3 checkpoint')
        m.record_checkpoints(self.journal, data, [claim])

    def test_checkpoint_recording_refuses_wrong_objects(self):
        data, wt = self.moved_with_task_worktree()
        empty_tree = self.run_git(self.dest, 'hash-object', '-t', 'tree', '-w', os.devnull).decode().strip()
        task_head = self.run_git(wt, 'rev-parse', 'HEAD').decode().strip()
        cases = {
            'tree differs': lambda: self.checkpoint(self.dest, 3, tree=empty_tree),
            'parent': lambda: self.checkpoint(self.dest, 3, parent=task_head),
            'missing or moved': lambda: [self.checkpoint(self.dest, 3)[0], '0' * 40, str(self.dest)],
            'not a commit': lambda: self.tree_ref(empty_tree),
            'name its own ref': lambda: self.checkpoint(
                self.dest, 3, named='refs/t3/orchestration-v2/checkpoints/b3RoZXI/ordinal/7'),
        }
        for pattern, make in cases.items():
            with self.subTest(pattern=pattern):
                claim = make()
                self.assert_record_refused(data, [claim], pattern)
                self.run_git(self.dest, 'update-ref', '-d', claim[0])
        claim = self.checkpoint(wt, 3)
        self.assert_record_refused(data, [[claim[0], claim[1], str(self.dest)]], 'parent')
        self.assert_record_refused(data, [[claim[0], claim[1][:12], str(wt)]], 'full object ID')
        self.assert_record_refused(data, [[claim[0], claim[1], str(self.root)]], 'Not a checkout')

    def tree_ref(self, tree):
        ref = 'refs/t3/orchestration-v2/checkpoints/dGhyZWFk/ordinal/3'
        self.run_git(self.dest, 'update-ref', ref, tree)
        return [ref, tree, str(self.dest)]

    def test_checkpoint_recording_refuses_unrelated_drift(self):
        data, _ = self.moved_with_task_worktree()
        claim = self.checkpoint(self.dest, 3)
        self.run_git(self.dest, 'config', 'remote.pushDefault', 'changed')
        self.assert_record_refused(data, [claim], 'config')
        self.run_git(self.dest, 'config', '--unset', 'remote.pushDefault')
        (self.dest / 'new-work').write_text('keep')
        self.assert_record_refused(data, [claim], 'Dirty')

    def test_checkpoints_require_an_applied_move(self):
        data = self.prepare()
        claim = self.checkpoint(self.source, 3)
        self.assert_record_refused(data, [claim], 'successful apply')

    def test_cli_prepare_apply_verify_rollback(self):
        for args in (
            ['prepare', '--source', str(self.source), '--destination', str(self.dest)],
            ['apply'], ['verify'], ['rollback'], ['verify']
        ):
            result = subprocess.run([sys.executable, str(MODULE), *args, '--journal', str(self.journal)],
                                    capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'], 'passed')


if __name__ == '__main__':
    unittest.main(verbosity=2)
