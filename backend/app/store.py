"""SQLite persistence.

Replaces the browser's localStorage as the home for conversation history, and
adds the thing localStorage could never give us: a queryable corpus of turns to
run the divergence analytics over.

Two independent write paths, deliberately not entangled:

  conversations + messages  the user's history. Mirrored from the client on
                            every change, full-replace, exactly as it was
                            mirrored into localStorage before.
  generations               append-only telemetry, written by /agent/turn.
                            Never rewritten, so it survives the full-replace
                            above and keeps an honest record of every call.

Messages are stored one row per turn rather than as a JSON blob, so pandas can
read the corpus directly with a plain SELECT.

Uses stdlib sqlite3: no ORM, because the schema is three flat tables and an
ORM's value here would be negative. pandas.read_sql works against these
connections as-is.
"""

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import settings
from app.schemas import ChatMessage

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT    PRIMARY KEY,
    title       TEXT    NOT NULL,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    conversation_id TEXT    NOT NULL
        REFERENCES conversations(id) ON DELETE CASCADE,
    turn_index      INTEGER NOT NULL,
    role            TEXT    NOT NULL,
    content         TEXT    NOT NULL,
    PRIMARY KEY (conversation_id, turn_index)
);

-- Telemetry for every generated turn. `conversation_id` is intentionally NOT a
-- foreign key: a turn can be generated without ever being saved (the user can
-- close the tab), and losing that record would bias the analytics toward
-- conversations people chose to keep.
CREATE TABLE IF NOT EXISTS generations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT,
    agent_id        TEXT    NOT NULL,
    model           TEXT    NOT NULL,
    latency_ms      INTEGER NOT NULL,
    char_count      INTEGER NOT NULL,
    word_count      INTEGER NOT NULL,
    transcript_len  INTEGER NOT NULL,
    created_at      INTEGER NOT NULL,
    -- The generated text itself. Duplicating it here is deliberate: `messages`
    -- is client-managed (full-replace on every save, deletable, re-indexed by a
    -- re-run), so joining a stored message back to the model that produced it is
    -- unreliable — measured at 76% before this column existed. `generations` is
    -- append-only and model-stamped, which makes it the honest corpus for
    -- analytics. Nullable because rows written before this column exist.
    text            TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conv_updated  ON conversations(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_gen_agent     ON generations(agent_id);
"""


def db_path() -> Path:
    p = Path(settings.db_path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / p
    return p


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """A connection per operation.

    FastAPI runs sync endpoints in a threadpool, and a sqlite3 connection is not
    safe to share across threads. Opening per call is cheap, and WAL mode (set
    once at init) keeps concurrent readers from blocking the writer.
    """
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    # Off by default in sqlite, and the messages cascade depends on it.
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        # Migration for databases created before `text` existed. Adding a
        # nullable column is cheap and keeps old rows readable.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(generations)")}
        if "text" not in cols:
            conn.execute("ALTER TABLE generations ADD COLUMN text TEXT")


def _now_ms() -> int:
    return int(time.time() * 1000)


# ── Conversations ───────────────────────────────────────────────────────────


def list_conversations(limit: int = 60) -> list[dict]:
    """Sidebar rows, newest first. Deliberately does not load transcripts."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.title, c.updated_at,
                   (SELECT COUNT(*) FROM messages m
                     WHERE m.conversation_id = c.id) AS message_count
              FROM conversations c
             ORDER BY c.updated_at DESC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_conversation(conversation_id: str) -> dict | None:
    with connect() as conn:
        conv = conn.execute(
            "SELECT id, title, updated_at FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if conv is None:
            return None
        msgs = conn.execute(
            """SELECT role, content FROM messages
                WHERE conversation_id = ? ORDER BY turn_index""",
            (conversation_id,),
        ).fetchall()
    return {**dict(conv), "transcript": [dict(m) for m in msgs]}


def save_conversation(
    conversation_id: str, title: str, transcript: list[ChatMessage]
) -> dict:
    """Upsert a conversation and replace its messages wholesale.

    Full-replace rather than append: it mirrors what the client already does on
    every change, and it makes the write idempotent, so a retry or an
    out-of-order save can't duplicate or interleave turns.
    """
    now = _now_ms()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO conversations (id, title, created_at, updated_at)
                 VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET title = excluded.title,
                                          updated_at = excluded.updated_at
            """,
            (conversation_id, title, now, now),
        )
        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
        )
        conn.executemany(
            """INSERT INTO messages (conversation_id, turn_index, role, content)
               VALUES (?, ?, ?, ?)""",
            [(conversation_id, i, m.role, m.content) for i, m in enumerate(transcript)],
        )
    return {"id": conversation_id, "title": title, "updatedAt": now}


def delete_conversation(conversation_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,)
        )
    return cur.rowcount > 0


# ── Telemetry ───────────────────────────────────────────────────────────────


def record_generation(
    *,
    conversation_id: str | None,
    agent_id: str,
    model: str,
    latency_ms: int,
    text: str,
    transcript_len: int,
) -> None:
    """Record one generated turn. Never raises into the request path."""
    with connect() as conn:
        conn.execute(
            """INSERT INTO generations (conversation_id, agent_id, model,
                   latency_ms, char_count, word_count, transcript_len,
                   created_at, text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                conversation_id,
                agent_id,
                model,
                latency_ms,
                len(text),
                len(text.split()),
                transcript_len,
                _now_ms(),
                text,
            ),
        )
