#!/usr/bin/env python3
"""Read-only before/after evidence for T3 projects around a checkout move.

`save` records each named project and every thread in it, archived and deleted
ones included: bindings, lineage, state, and the ordered message IDs (never
message text). `compare` reads the same projects again and reports what changed.
Each saved message list must survive as a prefix of the current one, since a
continuation only appends. Project roots, titles, archive state, and tracked
folders are reported, not refused, because a move changes them deliberately.

The store is opened with mode=ro and query_only, as the t3-thread-search skill
does. Native T3 tools stay authoritative; this covers what they don't list.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

THREAD_FIELDS = ('project_id', 'title', 'provider', 'branch', 'worktree_path', 'parent_thread_id',
                 'relationship', 'archived_at', 'deleted_at', 'settled_at')
# A move must not change these; the others are reported for review.
BINDING_FIELDS = ('project_id', 'provider', 'branch', 'worktree_path', 'parent_thread_id', 'relationship')


def database(explicit):
    if explicit:
        return Path(explicit).expanduser().resolve()
    base = Path(os.environ.get('T3CODE_HOME') or Path.home() / '.t3').expanduser()
    return (base / 'userdata/statev2.sqlite').resolve()


def connect(path):
    if not path.is_file():
        sys.exit(f'T3 store not found: {path}; pass --db')
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    return conn


def snapshot(conn, project_ids):
    projects, threads = {}, {}
    for project_id in project_ids:
        row = conn.execute('SELECT * FROM projection_projects WHERE project_id=?', (project_id,)).fetchone()
        if row is None:
            sys.exit(f'No such project: {project_id}')
        row = dict(row)
        projects[project_id] = {
            'title': row['title'], 'root': row['workspace_root'], 'scripts': json.loads(row['scripts_json'] or '[]'),
            'archived_at': row.get('archived_at'), 'deleted_at': row['deleted_at'],
            'tracked_folders': sorted(f['path'] for f in json.loads(row.get('tracked_folders_json') or '[]'))}
        for t in conn.execute('SELECT * FROM orchestration_v2_projection_threads WHERE project_id=? '
                              'ORDER BY created_at, thread_id', (project_id,)):
            payload = json.loads(t['payload_json'])
            lineage = payload.get('lineage') or {}
            messages = [r[0] for r in conn.execute(
                'SELECT message_id FROM orchestration_v2_projection_messages WHERE thread_id=? '
                'ORDER BY created_at, rowid', (t['thread_id'],))]
            threads[t['thread_id']] = {
                'project_id': project_id, 'title': t['title'],
                'provider': dict(t).get('provider_instance_id') or t['default_provider'],
                'branch': payload.get('branch'), 'worktree_path': payload.get('worktreePath'),
                'parent_thread_id': lineage.get('parentThreadId'),
                'relationship': lineage.get('relationshipToParent'),
                'archived_at': t['archived_at'], 'deleted_at': t['deleted_at'],
                'settled_at': payload.get('settledAt'), 'messages': messages}
    return {'database': None, 'projects': projects, 'threads': threads}


def compare(before, after):
    """Return (problems, notes). Problems mean lost or rebound history."""
    problems, notes = [], []
    for project_id, old in before['projects'].items():
        new = after['projects'][project_id]
        for key in old:
            if old[key] != new[key]:
                (problems if key == 'deleted_at' else notes).append(
                    f'project {project_id} {key}: {old[key]!r} -> {new[key]!r}')
    appended = 0
    for thread_id, old in before['threads'].items():
        new = after['threads'].get(thread_id)
        if new is None:
            problems.append(f'thread {thread_id} ({old["title"]}) is missing')
            continue
        for key in THREAD_FIELDS:
            if old[key] != new[key]:
                (problems if key in BINDING_FIELDS or key == 'deleted_at' else notes).append(
                    f'thread {thread_id} {key}: {old[key]!r} -> {new[key]!r}')
        kept = new['messages'][:len(old['messages'])] == old['messages']
        if not kept:
            problems.append(f'thread {thread_id} ({old["title"]}) lost or reordered saved messages')
        elif len(new['messages']) > len(old['messages']):
            appended += 1
            notes.append(f'thread {thread_id} ({old["title"]}) gained '
                         f'{len(new["messages"]) - len(old["messages"])} message(s)')
    for thread_id in after['threads'].keys() - before['threads'].keys():
        notes.append(f'thread {thread_id} ({after["threads"][thread_id]["title"]}) is new')
    return problems, notes


def summary(data):
    threads = data['threads'].values()
    return {'projects': len(data['projects']), 'threads': len(threads),
            'archived': sum(1 for t in threads if t['archived_at']),
            'deleted': sum(1 for t in threads if t['deleted_at']),
            'worktree_bound': sum(1 for t in threads if t['worktree_path']),
            'messages': sum(len(t['messages']) for t in threads),
            'messages_sha256': hashlib.sha256('\n'.join(
                m for t in threads for m in t['messages']).encode()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    save = sub.add_parser('save', help='Write a new snapshot of the named projects')
    save.add_argument('--out', required=True, help='New file outside every affected checkout')
    check = sub.add_parser('compare', help='Compare a saved snapshot with the store now')
    check.add_argument('--before', required=True)
    for p in (save, check):
        p.add_argument('--db', help='Exact statev2.sqlite (default: $T3CODE_HOME or ~/.t3, then userdata/)')
    save.add_argument('--project', action='append', required=True, help='Project ID; repeat for several')
    args = parser.parse_args()
    path = database(args.db)
    with connect(path) as conn:
        if args.command == 'save':
            data = snapshot(conn, args.project)
            data['database'] = str(path)
            out = Path(args.out)
            with open(out, 'x', encoding='utf-8') as stream:  # Never overwrite earlier evidence.
                json.dump(data, stream, indent=1)
            print(json.dumps({'status': 'saved', 'out': str(out), **summary(data)}))
            return 0
        before = json.loads(Path(args.before).read_text(encoding='utf-8'))
        after = snapshot(conn, list(before['projects']))
    problems, notes = compare(before, after)
    print(json.dumps({'status': 'failed' if problems else 'passed', 'problems': problems, 'notes': notes,
                      'before': summary(before), 'now': summary(after)}, indent=1))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
