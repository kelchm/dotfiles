"""Small projection fixture; never opens or copies a user's T3 database."""
import json
import sqlite3
from pathlib import Path

THREAD = 'b4a329e2-6d07-495b-891b-4747334642af'
ENVIRONMENT = '085bbae7-4da9-4bfa-86ed-ac1a17ad3763'
TIME = '2026-10-25T13:40:31Z'
NATIVE_ID = '2826bc79-f2cb-4db6-b9d7-da1cf3a44d2d'
DELEGATED_ID = 'thread:delegated-task:command%3Afixture:delegate-task%3Achild'
LIVE_FTS_SCHEMA = """
CREATE VIRTUAL TABLE orchestration_v2_message_search USING fts5(
    text, content='', contentless_delete=1, tokenize='trigram remove_diacritics 1'
);
"""

SCHEMA = """
CREATE TABLE projection_projects (
    project_id TEXT PRIMARY KEY, title TEXT, workspace_root TEXT, deleted_at TEXT
);
CREATE TABLE orchestration_v2_projection_threads (
    thread_id TEXT PRIMARY KEY, project_id TEXT, title TEXT, created_at TEXT, updated_at TEXT,
    archived_at TEXT, deleted_at TEXT, payload_json TEXT, active_provider_thread_id TEXT,
    provider_instance_id TEXT
);
CREATE TABLE orchestration_v2_projection_provider_threads (
    provider_thread_id TEXT PRIMARY KEY, thread_id TEXT, provider TEXT,
    provider_session_id TEXT, status TEXT, updated_at TEXT, payload_json TEXT, provider_instance_id TEXT
);
CREATE INDEX provider_thread_idx ON orchestration_v2_projection_provider_threads(thread_id);
CREATE TABLE orchestration_v2_projection_messages (
    message_id TEXT PRIMARY KEY, thread_id TEXT, run_id TEXT, node_id TEXT, role TEXT,
    streaming INTEGER, created_at TEXT, updated_at TEXT, payload_json TEXT
);
CREATE INDEX messages_thread_idx ON orchestration_v2_projection_messages(thread_id, created_at);
CREATE INDEX messages_run_idx ON orchestration_v2_projection_messages(run_id);
CREATE VIRTUAL TABLE orchestration_v2_message_search USING fts5(text, content='', tokenize='trigram');
CREATE TRIGGER message_search_insert AFTER INSERT ON orchestration_v2_projection_messages
WHEN new.streaming = 0 AND (new.role = 'assistant' OR
    (new.role = 'user' AND COALESCE(json_extract(new.payload_json, '$.createdBy'), 'user') = 'user'))
BEGIN
    INSERT INTO orchestration_v2_message_search(rowid, text)
    VALUES (new.rowid, json_extract(new.payload_json, '$.text'));
END;
CREATE TABLE orchestration_v2_projection_runs (
    run_id TEXT PRIMARY KEY, thread_id TEXT, ordinal INTEGER, provider TEXT,
    provider_thread_id TEXT, status TEXT, requested_at TEXT, completed_at TEXT, payload_json TEXT
);
CREATE UNIQUE INDEX runs_thread_idx ON orchestration_v2_projection_runs(thread_id, ordinal);
CREATE TABLE orchestration_v2_projection_turn_items (
    turn_item_id TEXT PRIMARY KEY, thread_id TEXT, run_id TEXT, ordinal INTEGER,
    type TEXT, status TEXT, updated_at TEXT, payload_json TEXT
);
CREATE INDEX items_run_idx ON orchestration_v2_projection_turn_items(thread_id, run_id);
CREATE TABLE orchestration_v2_projection_nodes (node_id TEXT PRIMARY KEY, thread_id TEXT, run_id TEXT);
CREATE TABLE orchestration_v2_projection_runtime_requests (
    runtime_request_id TEXT PRIMARY KEY, thread_id TEXT, node_id TEXT,
    kind TEXT, status TEXT, created_at TEXT, resolved_at TEXT, payload_json TEXT
);
CREATE TABLE projection_thread_pull_requests (
    thread_id TEXT, host TEXT, repository TEXT, number INTEGER, url TEXT, source TEXT, linked_at TEXT,
    PRIMARY KEY(thread_id, host, repository, number)
);
-- Stale legacy projections coexist in the real store. Never select their threads on v2.
CREATE TABLE projection_threads (thread_id TEXT PRIMARY KEY, project_id TEXT, title TEXT);
CREATE TABLE projection_thread_sessions (thread_id TEXT, status TEXT);
CREATE TABLE projection_thread_messages (message_id TEXT, thread_id TEXT, role TEXT, text TEXT);
"""


def fixture(path: Path, *, live_tokenizer: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    schema = SCHEMA
    if live_tokenizer:
        schema = schema.replace(
            "CREATE VIRTUAL TABLE orchestration_v2_message_search USING fts5(text, content='', tokenize='trigram');",
            LIVE_FTS_SCHEMA,
        )
    conn.executescript(schema)
    conn.execute('INSERT INTO projection_projects VALUES (?,?,?,NULL)', ('p', 'home-lab', '/repo/home-lab'))
    for thread, title, archived, deleted in (
        (THREAD, 'Update Spark OS and Check BIOS', None, None),
        ('thread-archived', 'Archive', TIME, None),
        ('thread-deleted', 'Deleted', None, TIME),
    ):
        conn.execute('INSERT INTO orchestration_v2_projection_threads VALUES (?,?,?,?,?,?,?,?,?,?)',
                     (thread, 'p', title, TIME, TIME, archived, deleted,
                      json.dumps({'branch': 'fix/spark', 'worktreePath': '/tmp/spark',
                                  'pullRequests': [] if deleted else [{'host': 'github.com',
                                      'repository': 'owner/home-lab' if thread == THREAD else 'owner/another',
                                      'number': 123, 'url': 'https://github.com/' +
                                      ('owner/home-lab' if thread == THREAD else 'owner/another') + '/pull/123'}]}), 'provider-' + thread, 'claudeAgent'))
        conn.execute('INSERT INTO orchestration_v2_projection_provider_threads VALUES (?,?,?,?,?,?,?,?)',
                     ('provider-' + thread, thread, 'claudeAgent', 'session-' + thread, 'idle', TIME,
                      json.dumps({'nativeThreadRef': {'nativeId': NATIVE_ID if thread == THREAD else 'native-' + thread}}), 'claude-work'))
    conn.execute('INSERT INTO projection_threads VALUES (?,?,?)', (THREAD, 'p', 'Stale title'))
    messages = [
        ('user', THREAD, 'user', 'Please update the Spark BIOS safely.', 0, 'user'),
        ('assistant', THREAD, 'assistant', 'Completed a literal 100% fix with "quoted" _value_.', 0, 'agent'),
        ('streaming', THREAD, 'assistant', 'streaming needle', 1, 'agent'),
        ('generated', THREAD, 'user', 'generated notification needle', 0, 'agent'),
        ('archive', 'thread-archived', 'user', 'archived message needle', 0, 'user'),
        ('deleted', 'thread-deleted', 'user', 'deleted message needle', 0, 'user'),
    ]
    for mid, thread, role, text, streaming, created_by in messages:
        payload = {'text': text, 'createdBy': created_by}
        if mid == 'generated':
            payload['notification'] = {'source': {'kind': 'command'},
                                       'outcome': 'completed', 'summary': 'background command completed'}
        conn.execute('INSERT INTO orchestration_v2_projection_messages VALUES (?,?,?,?,?,?,?,?,?)',
                     (mid, thread, 'run-1', 'node-1', role, streaming, TIME, TIME,
                      json.dumps(payload)))
    conn.execute('INSERT INTO orchestration_v2_projection_runs VALUES (?,?,?,?,?,?,?,?,?)',
                 ('run-1', THREAD, 1, 'claudeAgent', 'provider-' + THREAD, 'completed', TIME, TIME,
                  json.dumps({'startedAt': TIME})))
    conn.execute('INSERT INTO orchestration_v2_projection_nodes VALUES (?,?,?)', ('node-1', THREAD, 'run-1'))
    conn.execute('INSERT INTO orchestration_v2_projection_turn_items VALUES (?,?,?,?,?,?,?,?)',
                 ('item-1', THREAD, 'run-1', 1, 'command_execution', 'completed', TIME,
                  json.dumps({'title': 'safe title token=do-not-leak'})))
    # The legacy link table is stale, even when present alongside v2.
    conn.execute('INSERT INTO projection_thread_pull_requests VALUES (?,?,?,?,?,?,?)',
                 (THREAD, 'github.com', 'owner/home-lab', 999,
                  'https://github.com/owner/home-lab/pull/999', 'agent', '2026-10-02T00:00:00Z'))
    conn.execute("""INSERT INTO orchestration_v2_projection_threads
        SELECT ?, project_id, 'Delegated fixture', created_at, updated_at, NULL, NULL, '{}', NULL, NULL
        FROM orchestration_v2_projection_threads WHERE thread_id = ?""", (DELEGATED_ID, THREAD))
    conn.commit()
    conn.close()
    (path.parent / 'environment-id').write_text(ENVIRONMENT + '\n')
