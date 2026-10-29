#!/usr/bin/env python3
"""Journaled, same-filesystem relocation of a clean primary Git checkout.

Linked worktrees stay in place. T3 coordination belongs to the calling workflow.
No fetch, checkout, pruning, copying, deletion, remote changes, or database writes.
"""

import argparse
from contextlib import contextmanager
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


class Refused(RuntimeError):
    pass


# T3 records a checkpoint commit per provider turn, even a read-only one.
CHECKPOINT_REF = re.compile(r'refs/t3/orchestration-v2/checkpoints/[A-Za-z0-9_-]+=*/ordinal/(?:0|[1-9][0-9]*)')
OBJECT_ID = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')


def require(condition, message):
    if not condition:
        raise Refused(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def path_arg(value):
    path = Path(os.path.abspath(os.path.expanduser(str(value))))
    require('\n' not in str(path) and '\r' not in str(path), 'Checkout paths must not contain line breaks')
    require(path == path.resolve(), f"Use a real path without symlink components: {path}")
    parent = Path(path.anchor)
    for part in path.parts[1:]:
        current = parent / part
        if not os.path.lexists(current):
            break
        names = os.listdir(parent)
        require(part in names, f"Path spelling differs from disk at {current}; use the exact existing name")
        parent = current
    return path


def inside(path, parent):
    return path == parent or parent in path.parents


def git(path, *args, admin=None, ok=(0,)):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0')
    command = ['git', '--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', str(path)]
    if admin is not None:
        command += [f'--git-dir={admin}', f'--work-tree={path}']
    result = subprocess.run(command + list(args), capture_output=True, timeout=30, env=env)
    require(result.returncode in ok, f"Git {args[0]} failed at {path} (exit {result.returncode})")
    return result.stdout


def digest(value):
    return hashlib.sha256(value).hexdigest()


def file_hash(path):
    return digest(path.read_bytes()) if path.exists() else None


def worktrees(base):
    entries = []
    for block in git(base, 'worktree', 'list', '--porcelain', '-z').split(b'\0\0'):
        fields = [x for x in block.split(b'\0') if x]
        if not fields:
            continue
        require(fields[0].startswith(b'worktree '), 'Unexpected worktree listing')
        require(not any(x.startswith((b'prunable', b'locked', b'bare')) for x in fields),
                'Locked, missing, or bare worktrees need separate recovery')
        entries.append(path_arg(os.fsdecode(fields[0][9:])))
    return entries


def unreadable(error):
    raise Refused(f"Cannot inspect {error.filename} for nested checkouts")


def no_nested_repo(path):
    for directory, dirs, files in os.walk(path, onerror=unreadable, followlinks=False):
        if Path(directory) == path:
            dirs[:] = [d for d in dirs if d != '.git']
        else:
            require('.git' not in dirs and '.git' not in files,
                    f"Nested checkout requires a separate plan: {directory}")


def check_processes(paths):
    """Best-effort visibility is limited to the current user's cwd handles."""
    # Suppress warnings about unrelated unmounted/network volumes. Errors still
    # fail the command; this remains a best-effort guard, not a process lock.
    result = subprocess.run(['lsof', '-nP', '-w', '-a', '-u', str(os.getuid()), '-d', 'cwd', '-Fpn'],
                            capture_output=True, text=True, timeout=30)
    require(result.returncode == 0 and not result.stderr.strip() and result.stdout.startswith('p'),
            'Could not inspect cwd handles; resolve lsof errors before moving')
    process = '?'
    for line in result.stdout.splitlines():
        if line.startswith('p'):
            process = line[1:]
        elif line.startswith('n'):
            cwd = Path(line[1:]).resolve()
            require(not any(inside(cwd, p) for p in paths),
                    f"Process {process} has a cwd in an affected checkout")


def idle_gh_stack_lock(lock, common):
    """gh stack leaves its empty lock files behind between commands; only a held one is in use."""
    if lock.parent != common or lock.name not in ('gh-stack.lock', 'gh-stack-operation.lock') or lock.stat().st_size:
        return False
    result = subprocess.run(['lsof', '-nP', '-w', '-t', '--', str(lock)], capture_output=True, text=True, timeout=30)
    require(result.returncode in (0, 1) and not result.stderr.strip(), f"Could not inspect handles on {lock}")
    return not result.stdout.strip()


def busy_locks(base):
    common = base / '.git'
    return [lock for lock in common.rglob('*.lock') if not idle_gh_stack_lock(lock, common)]


def check_layout(source, destination, journal):
    for path in (source, destination, journal):
        path_arg(path)
    require(source.is_dir() and (source / '.git').is_dir(), 'Source must be a primary checkout')
    require(not (source / '.git').is_symlink(), 'Git directory must not be a symlink')
    require(git(source, 'rev-parse', '--show-toplevel').rstrip(b'\n') == os.fsencode(source),
            'Source must equal the Git top-level path')
    require(Path(os.fsdecode(git(source, 'rev-parse', '--absolute-git-dir').strip())) == source / '.git',
            'Separate Git directories are outside this helper scope')
    require(not inside(destination, source) and not inside(source, destination),
            'Source and destination must not overlap')
    require(destination.parent.is_dir(), 'Create and inspect the destination parent first')
    require(not os.path.lexists(destination), 'Destination is already occupied')
    require(source.stat().st_dev == destination.parent.stat().st_dev,
            'Cross-filesystem moves are outside this helper scope')
    for parent in (source.parent, destination.parent):
        require(not any(os.path.lexists(p / '.git') for p in (parent, *parent.parents)),
                f"Organizer directory is inside another checkout: {parent}")
    require(journal.parent.is_dir(), 'Journal parent must already exist')
    paths = worktrees(source)
    require(paths and paths[0] == source, 'Unexpected primary worktree registration')
    for i, path in enumerate(paths):
        require(path.is_dir(), f"Missing worktree: {path}")
        require(not inside(journal, path) and not inside(journal, destination),
                'Journal must be outside every affected checkout and destination')
        require(not inside(destination, path) and not inside(path, destination),
                'Destination overlaps a worktree')
        for other in paths[i + 1:]:
            require(not inside(path, other) and not inside(other, path), 'Nested worktrees are unsupported')
        no_nested_repo(path)
    require(not (source / '.git/objects/info/alternates').exists(), 'Object alternates need a separate plan')
    require(not busy_locks(source), 'Git lock file exists; investigate the owning operation')
    check_processes(paths)
    return paths


def check_path_config(source, paths):
    for path in paths:
        entries = git(path, 'config', '--null', '--list', '--includes').split(b'\0')
        keys = sorted({os.fsdecode(entry.partition(b'\n')[0]) for entry in entries
                       if os.fsencode(source) in entry.partition(b'\n')[2]})
        require(not keys, f"Config refers to the old checkout path at {path}: {', '.join(keys)}; "
                'resolve those path consumers before preparing a move (values withheld)')


def capture(base, specs=None, check_links=True, checkpoints=()):
    common = base / '.git'
    paths = worktrees(base)
    if specs is None:
        specs = []
        for path in paths:
            admin = Path(os.fsdecode(git(path, 'rev-parse', '--absolute-git-dir').strip()))
            require(admin == common or admin.parent == common / 'worktrees',
                    'Worktree uses an unexpected Git directory')
            specs.append({'path': str(path), 'admin': str(admin.relative_to(common))})
    require(paths == [Path(s['path']) for s in specs], 'Worktree registrations changed')
    states = []
    for spec in specs:
        path = Path(spec['path'])
        require(path_arg(path).is_dir(), f"Missing checkout: {path}")
        admin = common / spec['admin']
        require(not any((admin / name).exists() for name in
                        ('rebase-merge', 'rebase-apply', 'MERGE_HEAD', 'CHERRY_PICK_HEAD',
                         'REVERT_HEAD', 'sequencer', 'BISECT_START')),
                f"Git operation is in progress at {path}")
        def run(*args, **kw):
            return git(path, *args, admin=admin, **kw)
        if check_links:
            require(git(path, 'rev-parse', '--show-toplevel').rstrip(b'\n') == os.fsencode(path),
                    f"Incorrect Git top-level path: {path}")
            require(Path(os.fsdecode(git(path, 'rev-parse', '--path-format=absolute', '--git-common-dir').strip())) == common,
                    f"Incorrect Git common directory: {path}")
        require(not run('status', '--porcelain=v1', '--untracked-files=all'), f"Dirty checkout: {path}")
        require(not (path / '.gitmodules').exists() and not run('submodule', 'status'),
                'Submodules need a separate migration plan')
        require(all(item.startswith(b'H ') for item in run('ls-files', '-v', '-z').split(b'\0') if item),
                'Index flags can hide changes; resolve them before moving')
        require(not run('config', '--get', 'core.worktree', ok=(0, 1)), 'Explicit core.worktree needs a separate plan')
        st = path.stat()
        state = {**spec, 'device': st.st_dev, 'inode': st.st_ino,
                 'head': run('rev-parse', '--verify', 'HEAD').decode().strip(),
                 'branch': run('symbolic-ref', '-q', 'HEAD', ok=(0, 1)).decode().strip(),
                 'index_entries': digest(run('ls-files', '--stage', '-z')),
                 'config_worktree': file_hash(admin / 'config.worktree'),
                 'effective_config': digest(run('config', '--null', '--list', '--includes'))}
        if spec['admin'] != '.':
            marker = (path / '.git').read_text()
            if check_links:
                require(marker == f'gitdir: {admin}\n', 'Only absolute, canonical worktree pointers are supported')
            state.update(marker=marker, backlink=(admin / 'gitdir').read_text(),
                         commondir=(admin / 'commondir').read_text())
            require(Path(state['backlink'].strip()) == path / '.git', 'Incorrect worktree backlink')
        states.append(state)
    refs = git(base, 'for-each-ref', '--format=%(refname) %(objectname)').splitlines(keepends=True)
    for checkpoint in checkpoints:
        # Set aside only an exact recorded name and object; anything else stays in the fingerprint.
        line = f"{checkpoint['ref']} {checkpoint['oid']}\n".encode()
        require(line in refs, f"Recorded checkpoint is missing or moved: {checkpoint['ref']}")
        refs.remove(line)
    return {'checkouts': states, 'refs': digest(b''.join(refs)),
            'config': file_hash(common / 'config'), 'worktrees': git(base, 'worktree', 'list', '--porcelain', '-z').hex()}


def expected(data, moved):
    result = json.loads(json.dumps(data['before']))
    if not moved:
        return result
    old, new = data['source'], data['destination']
    result['checkouts'][0]['path'] = new
    for state in result['checkouts'][1:]:
        state['marker'] = state['marker'].replace(f'gitdir: {old}/.git/', f'gitdir: {new}/.git/', 1)
    listing = bytes.fromhex(result['worktrees'])
    result['worktrees'] = listing.replace(b'worktree ' + os.fsencode(old) + b'\0',
                                        b'worktree ' + os.fsencode(new) + b'\0', 1).hex()
    return result


def verify_data(data, moved, check_links=True):
    base = Path(data['destination'] if moved else data['source'])
    other = Path(data['source'] if moved else data['destination'])
    require(not os.path.lexists(other), f"Opposite checkout path is occupied: {other}")
    want = expected(data, moved)
    got = capture(base, want['checkouts'], check_links=check_links,
                  checkpoints=data.get('checkpoints', []) if moved else ())
    if not check_links:
        for i, (actual, desired) in enumerate(zip(got['checkouts'], want['checkouts'])):
            if 'marker' in actual:
                # Git repair may have stopped partway through this list.
                original = data['before']['checkouts'][i]['marker']
                allowed = {original, original.replace(data['source'] + '/.git/', data['destination'] + '/.git/', 1)}
                require(actual['marker'] in allowed, 'Worktree pointer changed outside this migration')
                actual['marker'] = desired['marker']
    for key in want:
        if key == 'checkouts':
            for actual, desired in zip(got[key], want[key]):
                for field in desired:
                    require(actual[field] == desired[field],
                            f"Preserved Git state changed at {desired['path']}: {field}")
        else:
            require(got[key] == want[key], f"Preserved Git state changed at {base}: {key}")
    return got


def write_json(path, data, exclusive=False):
    payload = json.dumps(data, indent=2) + '\n'
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return
    require(path.is_file() and not path.is_symlink(), 'Journal disappeared or became a symlink')
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked(journal):
    lock = journal.with_name(journal.name + '.lock')
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(str(os.getpid()) + '\n')
        yield
    finally:
        lock.unlink()


def record(journal, data, phase):
    data['phase'] = phase
    data['updated_at'] = now()
    write_json(journal, data)


def rename_exclusive(source, destination):
    """Atomic no-overwrite rename. Refuse platforms without an exclusive API."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        function = libc.renamex_np
        function.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        args = (os.fsencode(source), os.fsencode(destination), 4)  # RENAME_EXCL
    elif sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        function = libc.renameat2
        function.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        args = (-100, os.fsencode(source), -100, os.fsencode(destination), 1)  # RENAME_NOREPLACE
    else:
        raise Refused('This platform has no supported atomic, exclusive rename API')
    function.restype = ctypes.c_int
    if function(*args) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def repair(base, data):
    linked = [state['path'] for state in data['before']['checkouts'][1:]]
    if linked:
        git(base, '-c', 'worktree.useRelativePaths=false', 'worktree', 'repair', *linked)


def prepare(source, destination, journal):
    paths = check_layout(source, destination, journal)
    check_path_config(source, paths)
    before = capture(source)
    data = {'version': 2, 'source': str(source), 'destination': str(destination),
            'created_at': now(), 'phase': 'prepared', 'before': before}
    write_json(journal, data, exclusive=True)
    return data


def load(journal):
    require(journal.is_file() and not journal.is_symlink(), 'Expected a regular migration journal')
    data = json.loads(journal.read_text())
    require(data.get('version') == 2 and data.get('phase') in
            {'prepared', 'moving', 'applied', 'rolling_back', 'rolled_back', 'recovery_required'},
            'Unsupported migration journal')
    for key in ('source', 'destination'):
        require(str(path_arg(data[key])) == data[key], 'Journal paths must be canonical')
    return data


def rollback(journal, data):
    source, destination = Path(data['source']), Path(data['destination'])
    require(data['phase'] != 'prepared', 'Nothing has been moved')
    require(not data.get('checkpoints'), 'Provider work resumed after this move; plan a new reverse move instead')
    moved = not source.exists() and destination.exists()
    base = destination if moved else source
    # Ignore only the pointers that this operation is responsible for repairing.
    verify_data(data, moved, check_links=False)
    check_processes([Path(s['path']) for s in expected(data, moved)['checkouts']])
    require(not busy_locks(base), 'Git lock file exists')
    record(journal, data, 'rolling_back')
    if moved:
        rename_exclusive(destination, source)
    repair(source, data)
    verify_data(data, False)
    record(journal, data, 'rolled_back')
    return data


def apply(journal, data):
    if data['phase'] == 'applied':
        verify_data(data, True)
        return data
    require(data['phase'] != 'rolled_back', 'This journal is finished after rollback; prepare a new journal')
    require(data['phase'] == 'prepared', 'Interrupted operation: inspect paths, then use verify or rollback')
    source, destination = Path(data['source']), Path(data['destination'])
    paths = check_layout(source, destination, journal)
    check_path_config(source, paths)
    verify_data(data, False)
    # Run while affected T3 threads and other tools are idle. Cwd inspection is
    # a guard, not a substitute for the caller's live orchestration checks.
    record(journal, data, 'moving')
    try:
        rename_exclusive(source, destination)
    except Exception:
        # An exclusive rename failure has not moved our inode. A competing
        # destination is somebody else's material, not a failed rollback.
        record(journal, data, 'prepared' if same_checkout(source, data) else 'recovery_required')
        raise
    try:
        repair(destination, data)
        verify_data(data, True)
        record(journal, data, 'applied')
    except Exception as original_error:
        try:
            undo_failed_apply(journal, data)
        except Exception as recovery_error:
            record(journal, data, 'recovery_required')
            raise Refused(f'{original_error}; automatic recovery failed: {recovery_error}') from original_error
        raise
    return data


def record_checkpoints(journal, data, claims):
    """Accept exactly the named checkpoint commits that a verified continuation added.

    The saved snapshot is never rewritten. Every other ref and Git field must
    still match, and each checkpoint must snapshot its unchanged, clean HEAD.
    """
    require(data['phase'] == 'applied', 'Record checkpoints only after a successful apply')
    checkouts = {state['path']: state for state in expected(data, True)['checkouts']}
    known = {checkpoint['ref'] for checkpoint in data.get('checkpoints', [])}
    added = []
    for ref, oid, checkout in claims:
        require(CHECKPOINT_REF.fullmatch(ref), f'Not a T3 checkpoint ref: {ref}')
        require(ref not in known, f'Checkpoint named twice: {ref}')
        known.add(ref)
        require(OBJECT_ID.fullmatch(oid), f'Use the full object ID for {ref}')
        state = checkouts.get(str(path_arg(checkout)))
        require(state is not None, f'Not a checkout in this move: {checkout}')
        added.append({'ref': ref, 'oid': oid, 'checkout': state['path']})
    candidate = {**data, 'checkpoints': data.get('checkpoints', []) + added}
    verify_data(candidate, True)
    base = Path(data['destination'])
    for checkpoint in added:
        head = checkouts[checkpoint['checkout']]['head']
        oid = checkpoint['oid']
        require(git(base, 'cat-file', '-t', oid).strip() == b'commit', f"Checkpoint is not a commit: {checkpoint['ref']}")
        message = git(base, 'show', '-s', '--format=%B', oid).decode(errors='replace').strip()
        require(message == f"t3 checkpoint ref={checkpoint['ref']}",
                f"Checkpoint commit does not name its own ref: {checkpoint['ref']}")
        require(git(base, 'rev-list', '--parents', '-n', '1', oid).split()[1:] == [head.encode()],
                f"Checkpoint parent is not its checkout's HEAD: {checkpoint['ref']}")
        tree = git(base, 'rev-parse', oid + '^{tree}').strip()
        require(tree == git(base, 'rev-parse', head + '^{tree}').strip(),
                f"Checkpoint tree differs from its clean checkout: {checkpoint['ref']}")
        checkpoint.update(tree=tree.decode(), recorded_at=now())
    data['checkpoints'] = candidate['checkpoints']
    record(journal, data, 'applied')
    return data


def same_checkout(path, data):
    if not path.is_dir() or path.is_symlink():
        return False
    stat = path.stat()
    original = data['before']['checkouts'][0]
    return stat.st_dev == original['device'] and stat.st_ino == original['inode']


def undo_failed_apply(journal, data):
    """Undo this call's own rename; don't let a path-induced mismatch block it.

    No refs/content/config are reset. Any concurrent changes move back intact and
    cause the final verification to fail, leaving recovery_required for review.
    This is deliberately unavailable as a force flag on standalone rollback.
    """
    source, destination = Path(data['source']), Path(data['destination'])
    require(same_checkout(destination, data), 'Destination is no longer the inode this call moved')
    require(not os.path.lexists(source), 'Original path became occupied; cannot undo the move')
    check_processes([Path(s['path']) for s in expected(data, True)['checkouts']])
    require(not busy_locks(destination), 'Git lock file appeared during the move')
    record(journal, data, 'rolling_back')
    rename_exclusive(destination, source)
    repair(source, data)
    verify_data(data, False)
    record(journal, data, 'rolled_back')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare', help='Check and snapshot one move without relocating it')
    p.add_argument('--source', required=True)
    p.add_argument('--destination', required=True)
    for name in ('apply', 'verify', 'rollback'):
        sub.add_parser(name, help={'apply': 'Revalidate, move, repair, and verify',
                                  'verify': 'Check the preserved state at its current location',
                                  'rollback': 'Restore the original path if preserved state still matches'}[name])
    p = sub.add_parser('record-checkpoints', help='Accept exactly the checkpoint refs a verified continuation added')
    p.add_argument('--checkpoint', nargs=3, action='append', required=True, metavar=('REF', 'OID', 'CHECKOUT'))
    for p in sub.choices.values():
        p.add_argument('--journal', required=True, help='Private JSON record outside all affected checkouts')
    args = parser.parse_args()
    data = None
    try:
        journal = path_arg(args.journal)
        with locked(journal):
            if args.command == 'prepare':
                data = prepare(path_arg(args.source), path_arg(args.destination), journal)
            else:
                data = load(journal)
                if args.command == 'apply':
                    data = apply(journal, data)
                elif args.command == 'rollback':
                    data = rollback(journal, data)
                elif args.command == 'record-checkpoints':
                    data = record_checkpoints(journal, data, args.checkpoint)
                else:
                    moved = not Path(data['source']).exists() and Path(data['destination']).exists()
                    verify_data(data, moved)
        print(json.dumps({'status': 'passed', 'command': args.command, 'phase': data['phase'],
                          'source': data['source'], 'destination': data['destination'],
                          'retained_worktrees': len(data['before']['checkouts']) - 1,
                          'checkpoints': len(data.get('checkpoints', [])), 'journal': str(journal)}))
    except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
        phase = f"; journal phase: {data['phase']}" if data else ''
        print(f'Refused: {error}{phase}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
