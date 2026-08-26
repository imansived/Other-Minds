"""Storage behaviour.

Each test gets its own database file, so nothing here touches the real one.
"""

import pytest

from app import store
from app.config import settings
from app.schemas import ChatMessage


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    store.init_db()
    yield


def msgs(*pairs) -> list[ChatMessage]:
    return [ChatMessage(role=r, content=c) for r, c in pairs]


def test_round_trip():
    t = msgs(("user", "should I move?"), ("gardener", "who else is affected?"))
    store.save_conversation("c1", "should I move?", t)

    got = store.get_conversation("c1")
    assert got["title"] == "should I move?"
    assert [m["role"] for m in got["transcript"]] == ["user", "gardener"]
    assert got["transcript"][1]["content"] == "who else is affected?"


def test_missing_conversation_is_none():
    assert store.get_conversation("nope") is None


def test_save_is_idempotent_and_replaces_rather_than_appends():
    """The client mirrors on every change, so the same conversation is saved
    over and over. Saving twice must not double the transcript."""
    t = msgs(("user", "a"), ("behaviorist", "b"))
    store.save_conversation("c1", "a", t)
    store.save_conversation("c1", "a", t)
    assert len(store.get_conversation("c1")["transcript"]) == 2

    grown = t + msgs(("user", "c"))
    store.save_conversation("c1", "a", grown)
    assert len(store.get_conversation("c1")["transcript"]) == 3


def test_transcript_order_survives_a_reload():
    t = msgs(*[("user" if i % 2 == 0 else "gardener", f"line {i}") for i in range(12)])
    store.save_conversation("c1", "ordering", t)
    got = store.get_conversation("c1")["transcript"]
    assert [m["content"] for m in got] == [f"line {i}" for i in range(12)]


def test_list_is_newest_first_and_counts_messages():
    store.save_conversation("old", "older one", msgs(("user", "x")))
    store.save_conversation("new", "newer one", msgs(("user", "y"), ("gardener", "z")))
    rows = store.list_conversations()
    assert [r["id"] for r in rows] == ["new", "old"]
    assert rows[0]["message_count"] == 2
    assert rows[1]["message_count"] == 1


def test_delete_cascades_to_messages():
    store.save_conversation("c1", "t", msgs(("user", "a"), ("gardener", "b")))
    assert store.delete_conversation("c1") is True
    assert store.get_conversation("c1") is None
    with store.connect() as conn:
        left = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = 'c1'"
        ).fetchone()[0]
    assert left == 0, "messages outlived their conversation"


def test_deleting_something_absent_is_not_an_error():
    assert store.delete_conversation("never-existed") is False


def test_generation_telemetry_is_recorded():
    store.record_generation(
        conversation_id="c1", agent_id="gardener", model="gemini-3.5-flash",
        latency_ms=1234, text="two words", transcript_len=3,
    )
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM generations").fetchone()
    assert row["agent_id"] == "gardener"
    assert row["latency_ms"] == 1234
    assert row["char_count"] == len("two words")
    assert row["word_count"] == 2


def test_telemetry_survives_a_conversation_being_replaced():
    """Generations are append-only. A full-replace save of the conversation
    must not erase the record of turns already generated."""
    store.save_conversation("c1", "t", msgs(("user", "a")))
    for i in range(3):
        store.record_generation(
            conversation_id="c1", agent_id="gardener", model="m",
            latency_ms=100 + i, text="hello", transcript_len=i,
        )
    store.save_conversation("c1", "t", msgs(("user", "a"), ("gardener", "b")))
    with store.connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM generations WHERE conversation_id='c1'"
        ).fetchone()[0]
    assert n == 3


def test_telemetry_can_be_unattributed():
    """A turn taken before anything is saved still has to be recorded, or the
    corpus over-represents conversations people chose to keep."""
    store.record_generation(
        conversation_id=None, agent_id="introspector", model="m",
        latency_ms=10, text="x", transcript_len=1,
    )
    with store.connect() as conn:
        row = conn.execute("SELECT conversation_id FROM generations").fetchone()
    assert row["conversation_id"] is None
