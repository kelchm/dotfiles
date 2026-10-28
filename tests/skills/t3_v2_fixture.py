"""Small recovery fixture; never opens or copies a user's T3 database."""

import json
from pathlib import Path
import sqlite3

THREAD = (
    "b4a329e2-6d07-495b-891b-4747334642af"  # Active; only provider-ID mapping should return it.
)
ARCHIVED = "7a87230b-e7b0-43db-849f-a6764d78dd70"
DELETED = "thread-deleted"
ENVIRONMENT = "085bbae7-4da9-4bfa-86ed-ac1a17ad3763"
NATIVE_ID = "2826bc79-f2cb-4db6-b9d7-da1cf3a44d2d"
DELEGATED_ID = "thread:delegated-task:command%3Afixture:delegate-task%3Achild"
TIME = "2026-10-25T13:40:31Z"
LIVE_FTS_SCHEMA = "CREATE VIRTUAL TABLE orchestration_v2_message_search USING fts5(text, content='', contentless_delete=1, tokenize='trigram remove_diacritics 1');"
SCHEMA = """
CREATE TABLE projection_projects (project_id TEXT PRIMARY KEY,title TEXT,workspace_root TEXT,deleted_at TEXT);
CREATE TABLE orchestration_v2_projection_threads (
 thread_id TEXT PRIMARY KEY,project_id TEXT,title TEXT,created_at TEXT,updated_at TEXT,
 archived_at TEXT,deleted_at TEXT,payload_json TEXT,active_provider_thread_id TEXT);
CREATE TABLE orchestration_v2_projection_provider_threads (
 provider_thread_id TEXT PRIMARY KEY,thread_id TEXT,provider TEXT,provider_session_id TEXT,
 status TEXT,updated_at TEXT,payload_json TEXT);
CREATE INDEX provider_thread_idx ON orchestration_v2_projection_provider_threads(thread_id);
CREATE TABLE orchestration_v2_projection_messages (
 message_id TEXT PRIMARY KEY,thread_id TEXT,role TEXT,streaming INTEGER,created_at TEXT,payload_json TEXT);
CREATE INDEX messages_thread_idx ON orchestration_v2_projection_messages(thread_id,created_at);
CREATE VIRTUAL TABLE orchestration_v2_message_search USING fts5(text, content='', tokenize='trigram');
CREATE TRIGGER message_search_insert AFTER INSERT ON orchestration_v2_projection_messages
WHEN new.streaming=0 AND (new.role='assistant' OR
 (new.role='user' AND COALESCE(json_extract(new.payload_json,'$.createdBy'),'user')='user'))
 AND NOT EXISTS (SELECT 1 FROM orchestration_v2_projection_threads t WHERE t.thread_id=new.thread_id
  AND json_extract(t.payload_json,'$.lineage.relationshipToParent')='subagent')
BEGIN
 INSERT INTO orchestration_v2_message_search(rowid,text)
 SELECT new.rowid,replace(replace(json_extract(new.payload_json,'$.text'),'’',''''), '‘','''')
 WHERE json_extract(new.payload_json,'$.text') IS NOT NULL;
END;
"""


def add_message(conn, message_id, thread, text, *, role="user", created_by="user", streaming=0):
    conn.execute(
        "INSERT INTO orchestration_v2_projection_messages VALUES (?,?,?,?,?,?)",
        (
            message_id,
            thread,
            role,
            streaming,
            TIME,
            json.dumps({"text": text, "createdBy": created_by}),
        ),
    )


def fixture(path: Path, *, live_tokenizer=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    schema = (
        SCHEMA.replace(
            "CREATE VIRTUAL TABLE orchestration_v2_message_search USING fts5(text, content='', tokenize='trigram');",
            LIVE_FTS_SCHEMA,
        )
        if live_tokenizer
        else SCHEMA
    )
    conn.executescript(schema)
    conn.execute(
        "INSERT INTO projection_projects VALUES (?,?,?,NULL)", ("p", "home-lab", "/repo/home-lab")
    )
    for thread, title, archived, deleted in (
        (THREAD, "Active Spark BIOS", None, None),
        (ARCHIVED, "Archived Spark BIOS", TIME, None),
        (DELETED, "Deleted residual work", None, TIME),
        (DELEGATED_ID, "Archived delegate", TIME, None),
    ):
        payload = {
            "branch": "fix/spark",
            "worktreePath": "/tmp/spark",
            "pullRequests": [
                {
                    "host": "github.com",
                    "repository": "owner/home-lab",
                    "number": 123,
                    "url": "https://github.com/owner/home-lab/pull/123",
                }
            ],
        }
        if thread == DELEGATED_ID:
            payload["lineage"] = {"relationshipToParent": "subagent"}
        conn.execute(
            "INSERT INTO orchestration_v2_projection_threads VALUES (?,?,?,?,?,?,?,?,?)",
            (
                thread,
                "p",
                title,
                TIME,
                TIME,
                archived,
                deleted,
                json.dumps(payload),
                "provider-" + thread,
            ),
        )
        if not deleted:
            conn.execute(
                "INSERT INTO orchestration_v2_projection_provider_threads VALUES (?,?,?,?,?,?,?)",
                (
                    "provider-" + thread,
                    thread,
                    "claudeAgent",
                    "session-" + thread,
                    "idle",
                    TIME,
                    json.dumps(
                        {
                            "nativeThreadRef": {
                                "nativeId": NATIVE_ID if thread == THREAD else "native-" + thread
                            }
                        }
                    ),
                ),
            )
    add_message(conn, "active", THREAD, "Please update the Spark BIOS safely.")
    add_message(conn, "archived", ARCHIVED, "Please update the Spark BIOS safely.")
    add_message(
        conn,
        "assistant",
        ARCHIVED,
        'A literal 100% fix with "quoted" _value_ and a curly apostrophe: don’t.',
        role="assistant",
    )
    add_message(conn, "streaming", ARCHIVED, "streaming needle", role="assistant", streaming=1)
    add_message(conn, "agent", ARCHIVED, "agent-authored opening prompt", created_by="agent")
    add_message(conn, "subagent", DELEGATED_ID, "subagent transcript needle", role="assistant")
    add_message(conn, "deleted", DELETED, "deleted residual needle")
    conn.commit()
    conn.close()
    (path.parent / "environment-id").write_text(ENVIRONMENT + "\n")
