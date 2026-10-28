#!/usr/bin/env python3
"""Read-only inventory of disposable Git fixtures."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'home/dot_agents/skills/repo-workspace/scripts/audit.py'


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='repo-audit-fixture-')
        self.root = Path(self.temporary.name).resolve()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, path, *args):
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                        '-c', 'commit.gpgsign=false', '-C', str(path), *args],
                       check=True, capture_output=True, env=self.env, timeout=30)

    def audit(self, *roots, env=None):
        args = [arg for root in roots for arg in ('--root', str(root))]
        result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                                text=True, env=env or self.env, timeout=60, check=True)
        return {entry['path']: entry for entry in json.loads(result.stdout)['checkouts']}

    def test_follows_external_worktrees_and_strips_credentials(self):
        scan = self.root / 'Development'
        repo = scan / 'owner' / 'repo'
        repo.mkdir(parents=True)
        self.git(repo, 'init', '-b', 'main')
        self.git(repo, 'commit', '--allow-empty', '-m', 'Initialize fixture')
        self.git(repo, 'remote', 'add', 'origin', 'https://user:secret-token@GitHub.com/me/repo.git')
        self.git(repo, 'remote', 'add', 'upstream', 'git@github.com:owner/repo.git')
        task = self.root / 'outside' / 'task'
        self.git(repo, 'worktree', 'add', '-b', 'task', str(task))

        checkouts = self.audit(scan, self.root / 'missing')
        self.assertEqual(checkouts[str(repo)]['kind'], 'primary')
        self.assertEqual(checkouts[str(task)]['kind'], 'linked')
        self.assertEqual(checkouts[str(task)]['common_dir'], str(repo / '.git'))
        self.assertEqual(checkouts[str(repo)]['remotes']['origin'], ['github.com/me/repo'])
        self.assertEqual(checkouts[str(repo)]['canonical_candidate'], 'github.com/owner/repo')
        self.assertNotIn('secret-token', json.dumps(checkouts))

    def test_ignores_inherited_git_repository_variables(self):
        scan = self.root / 'Development'
        repo, decoy = scan / 'owner' / 'repo', self.root / 'decoy'
        for path in (repo, decoy):
            path.mkdir(parents=True)
            self.git(path, 'init', '-b', 'main')
            self.git(path, 'commit', '--allow-empty', '-m', 'Initialize fixture')
        (repo / 'dirty').write_text('untracked')
        env = {**self.env, 'GIT_DIR': str(decoy / '.git'), 'GIT_WORK_TREE': str(decoy)}
        entry = self.audit(scan, env=env)[str(repo)]
        self.assertEqual(entry['common_dir'], str(repo / '.git'))
        self.assertEqual(entry['untracked'], ['dirty'])

    def test_reports_broken_worktree_link(self):
        broken = self.root / 'Development' / 'owner' / 'orphan'
        broken.mkdir(parents=True)
        (broken / '.git').write_text(f'gitdir: {self.root}/gone/.git/worktrees/orphan\n')
        entry = self.audit(self.root / 'Development')[str(broken)]
        self.assertFalse(entry['declared_git_dir_exists'])
        self.assertIn('error', entry)


if __name__ == '__main__':
    unittest.main()
