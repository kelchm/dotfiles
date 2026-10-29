#!/usr/bin/env python3
"""Read-only checkout/worktree inventory. No fetches, project changes, or cleanup.

T3 bindings are not read here: use native T3 tools, plus the t3-thread-search
skill's --path lookup for archived and deleted threads.
"""

import argparse
import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit


SKIP = {'.git', 'node_modules', '.venv', 'venv', 'vendor', 'target', 'dist',
        'build', '__pycache__', '.next', '.cache', '.pnpm-store', '.bun',
        'logs', 'provider-sessions', 'sessions', 'secrets'}


def git(path, *args):
    # Inherited GIT_DIR/GIT_WORK_TREE would override -C and describe the caller's repository.
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0')
    try:
        result = subprocess.run(
            ['git', '--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', str(path), *args],
            text=True, errors='surrogateescape', capture_output=True, timeout=25, env=env)
        output = result.stdout if result.returncode == 0 else result.stderr
        return result.returncode, output.rstrip('\n')
    except (OSError, subprocess.TimeoutExpired) as error:
        return -1, type(error).__name__


def identity(url):
    """Normalize a remote without retaining credentials or query parameters."""
    if '://' in url:
        try:
            parsed = urlsplit(url)
            host, path = parsed.hostname, parsed.path.strip('/')
        except ValueError:
            return None
    else:
        match = re.match(r'^(?:[^@/]+@)?([^/:]+):(.+)$', url)
        if not match:
            return None
        host, path = match.group(1), match.group(2).strip('/')
    if not host:
        return None
    if path.endswith('.git'):
        path = path[:-4]
    return host.lower() + '/' + path


def discover(root, max_depth):
    found = set()
    if not root.is_dir():
        return found
    for directory, dirs, files in os.walk(root, followlinks=False):
        path = Path(directory)
        depth = len(path.relative_to(root).parts)
        if '.git' in dirs or '.git' in files:
            found.add(str(path.resolve()))
        dirs[:] = [name for name in dirs if name not in SKIP and depth < max_depth]
    return found


def worktrees(path):
    code, output = git(path, 'worktree', 'list', '--porcelain', '-z')
    if code:
        return [], output
    entries, current = [], {}
    for token in output.split('\0'):
        if token.startswith('worktree '):
            if current:
                entries.append(current)
            current = {'path': token[9:]}
        elif token.startswith('HEAD '):
            current['head'] = token[5:]
        elif token.startswith('branch '):
            current['branch'] = token[7:]
        elif token == 'detached':
            current['detached'] = True
        elif token.startswith(('locked', 'prunable')):
            key, _, value = token.partition(' ')
            current[key] = value or True
    if current:
        entries.append(current)
    return entries, None


def inspect(path):
    root = Path(path)
    code, common = git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    if code:
        broken = {'path': path, 'error': common}
        marker = root / '.git'
        if marker.is_file():
            try:
                with marker.open(errors='replace') as stream:
                    line = stream.readline(8192).strip()
                if line.startswith('gitdir: '):
                    target = (root / line[8:]).resolve()
                    broken.update(declared_git_dir=str(target),
                                  declared_git_dir_exists=target.is_dir())
            except OSError as error:
                broken['git_marker_read_error'] = type(error).__name__
        return broken
    _, top = git(root, 'rev-parse', '--show-toplevel')
    _, marker = git(root, 'rev-parse', '--absolute-git-dir')
    _, raw_remotes = git(root, 'config', '--get-regexp', r'^remote\..*\.(url|pushurl)$')
    remotes, push_urls = {}, {}
    for line in raw_remotes.splitlines():
        key, _, value = line.partition(' ')
        match = re.match(r'remote\.(.+)\.(url|pushurl)$', key)
        if match:
            target = push_urls if match.group(2) == 'pushurl' else remotes
            target.setdefault(match.group(1), []).append(identity(value))
    branch_code, branch = git(root, 'symbolic-ref', '--short', '-q', 'HEAD')
    head_code, head = git(root, 'rev-parse', '--verify', 'HEAD')
    upstream_code, upstream = git(root, 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}')
    status_code, status = git(root, 'status', '--porcelain=v1', '--untracked-files=normal')
    _, refs = git(root, 'for-each-ref', '--format=%(refname:short)\t%(upstream:short)\t%(upstream:track)', 'refs/heads')
    commit_code, last_commit = git(root, 'log', '-1', '--format=%cI')
    _, push_default = git(root, 'config', '--get', 'remote.pushDefault')
    _, default_base = git(root, 'symbolic-ref', '--short', '-q', 'refs/remotes/origin/HEAD')
    entries, worktree_error = worktrees(root)
    _, superproject = git(root, 'rev-parse', '--show-superproject-working-tree')
    lines = status.splitlines() if status_code == 0 else []
    return {
        'path': path, 'top_level': top, 'git_dir': marker, 'common_dir': common,
        'kind': ('submodule' if superproject else
                 'primary' if Path(common) == Path(marker) else 'linked'),
        'superproject': superproject or None,
        'remotes': remotes, 'push_urls': push_urls,
        'canonical_candidate': (remotes.get('upstream') or remotes.get('origin') or [None])[0],
        'canonical_source': 'local-remote-config-unverified',
        'branch': branch if branch_code == 0 else None, 'head': head if head_code == 0 else None,
        'upstream_ref': upstream if upstream_code == 0 else None, 'origin_default_ref': default_base or None,
        'push_default': push_default or None, 'last_commit_at': last_commit if commit_code == 0 else None,
        'status_error': status if status_code else None,
        'tracked_changes': [line for line in lines if not line.startswith('??')],
        'untracked': [line[3:] for line in lines if line.startswith('??')],
        'branches': [line.split('\t') for line in refs.splitlines()],
        'worktrees': entries, 'worktree_error': worktree_error,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', action='append', required=True, type=Path)
    parser.add_argument('--depth', type=int, default=4)
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    roots = [p.expanduser().resolve() for p in args.root]
    paths = set()
    for root in roots:
        paths.update(discover(root, args.depth))
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        initial = list(pool.map(inspect, sorted(paths)))
        additional = {str(Path(w['path']).resolve()) for repo in initial
                      for w in repo.get('worktrees', [])
                      if Path(w['path']).is_dir() and '.git' not in Path(w['path']).parts} - paths
        checkouts = initial + list(pool.map(inspect, sorted(additional)))
    checkouts.sort(key=lambda entry: entry['path'])
    result = {
        'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'roots': list(map(str, roots)), 'discovery_max_depth': args.depth,
        'missing_scan_roots': [str(root) for root in roots if not root.is_dir()],
        'scan_exclusions': sorted(SKIP),
        'limitations': ['No network fetches or GitHub fork verification.',
                        'Remote refs can be stale; clean status does not prove safe removal.',
                        'Ignored files, running processes, and other machines were not inventoried.'],
        'checkouts': checkouts,
    }
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == '__main__':
    main()
