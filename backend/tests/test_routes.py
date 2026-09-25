"""HTTP contract for the conversation endpoints.

These use FastAPI's TestClient and make no model calls — the conversation routes
are sync `def` handlers over sqlite. (The /agent/turn route is deliberately not
exercised here: it is async and TestClient gives each request its own event
loop, which the cached LLM client does not survive. It is covered end to end
against a real server instead.)

The 404 shape matters more than it looks: the UI distinguishes "this
conversation is gone" from "the service is unreachable" by status code, and
drops a stale sidebar row only on a 404.
"""

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app import store
from app.config import settings
from app.main import app


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "routes.db"))
    store.init_db()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def save(client, cid, title="a question"):
    return client.put(
        f"/conversations/{cid}",
        json={
            "title": title,
            "transcript": [
                {"role": "user", "content": "should I go?"},
                {"role": "gardener", "content": "who else is in this?"},
            ],
        },
    )


def test_empty_history_lists_nothing(client):
    r = client.get("/conversations")
    assert r.status_code == 200
    assert r.json() == []


def test_save_then_list_then_open(client):
    assert save(client, "abc").status_code == 200

    rows = client.get("/conversations").json()
    assert len(rows) == 1
    # camelCase on the wire — the client reads updatedAt/messageCount.
    assert rows[0]["id"] == "abc"
    assert rows[0]["messageCount"] == 2
    assert "updatedAt" in rows[0]

    # Opening uses the exact id the list handed out.
    detail = client.get(f"/conversations/{rows[0]['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["title"] == "a question"
    assert [m["role"] for m in body["transcript"]] == ["user", "gardener"]


def test_unknown_conversation_is_404_with_an_error_field(client):
    """The UI drops a stale sidebar row on exactly this response."""
    r = client.get("/conversations/never-existed")
    assert r.status_code == 404
    assert r.json() == {"error": "No such conversation"}


def test_ids_are_matched_exactly(client):
    """No normalising: a differently-cased id is a different conversation."""
    save(client, "AbC")
    assert client.get("/conversations/AbC").status_code == 200
    assert client.get("/conversations/abc").status_code == 404


def test_ids_are_opaque_within_one_path_segment(client):
    """The service does not parse ids — but it does address them by path.

    Anything that survives as a single path segment round-trips. Both clients
    mint ids with `crypto.randomUUID()` / `uuid4()`, so this is comfortably
    satisfied in practice.
    """
    for cid in ["3ce822b8-b029-44b3-bab2-07c051a5afba", "with space", "plus+sign"]:
        save(client, quote(cid, safe=""))
        assert client.get(f"/conversations/{quote(cid, safe='')}").status_code == 200


def test_an_id_containing_a_slash_is_not_addressable(client):
    """A known and accepted limitation, recorded rather than worked around.

    A `/` inside an id splits the path however it is encoded, so such a
    conversation could never be fetched back. Neither client can produce one —
    both generate UUIDs — so the fix would be machinery for a case that does not
    arise. This test exists so the limitation is a decision, not a surprise.
    """
    r = client.put(
        f"/conversations/{quote('a/b', safe='')}",
        json={"title": "t", "transcript": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 404
    assert client.get("/conversations").json() == []


def test_delete_then_open_is_404(client):
    save(client, "abc")
    assert client.delete("/conversations/abc").status_code == 200
    assert client.get("/conversations/abc").status_code == 404
    assert client.get("/conversations").json() == []


def test_deleting_twice_is_still_fine(client):
    save(client, "abc")
    assert client.delete("/conversations/abc").status_code == 200
    assert client.delete("/conversations/abc").status_code == 200


def test_next_speaker_needs_a_non_empty_transcript(client):
    assert client.post("/agent/next-speaker", json={"transcript": []}).status_code == 422


def test_naming_a_mind_elects_it_over_the_route(client):
    """The unit test covers the rule; this covers the contract both UIs call.

    The endpoint is where a client actually asks, so a regression that only
    showed up after serialisation would be invisible to the orchestrator tests.
    """
    for text, expected in [
        ("Introspector, what do you think?", "introspector"),
        ("gardener what about the kids", "gardener"),
        ("I want the Behaviorist take on this", "behaviorist"),
    ]:
        picked = set()
        for _ in range(20):
            res = client.post(
                "/agent/next-speaker",
                json={"transcript": [{"role": "user", "content": text}]},
            )
            assert res.status_code == 200
            picked.add(res.json()["agentId"])
        assert picked == {expected}, f"{text!r} elected {picked}"


def test_an_unnamed_question_still_draws_from_all_three(client):
    picked = set()
    for _ in range(60):
        res = client.post(
            "/agent/next-speaker",
            json={"transcript": [{"role": "user", "content": "What is freedom?"}]},
        )
        picked.add(res.json()["agentId"])
    assert picked == {"introspector", "behaviorist", "gardener"}


# ── Provider failures must never escape as plain text ───────────────────────
#
# FastAPI answers an unhandled exception with the PLAIN TEXT "Internal Server
# Error". Every client here parses errors as JSON, so an escape reaches the
# reader as "Unexpected token 'I' ... is not valid JSON" and hides the real
# cause. That happened for real: langchain-google-genai raises
# GoogleRateLimitError, which does NOT inherit from the google SDK's APIError,
# so hitting the daily quota escaped the handler entirely.


def turn_body():
    return {"agentId": "gardener",
            "transcript": [{"role": "user", "content": "should I go?"}]}


@pytest.mark.parametrize(
    "exc_name, expected_status, expect_in_message",
    [
        ("ModelRateLimitError", 429, "rate limit"),
        ("ModelAuthenticationError", 401, "GEMINI_API_KEY"),
        ("ModelPermissionDeniedError", 401, "GEMINI_API_KEY"),
        ("ModelInvalidRequestError", 502, "rejected"),
        ("ModelNotFoundError", 502, "rejected"),
    ],
)
def test_provider_errors_become_json(
    client, monkeypatch, exc_name, expected_status, expect_in_message
):
    """Each provider failure maps to a status, and always to a JSON body.

    The chat model is replaced with one whose ainvoke raises, so the real
    translation in llm.generate_turn and the real mapping in main.agent_turn
    both run.
    """
    import langchain_core.exceptions as exceptions

    from app import llm

    exc = getattr(exceptions, exc_name)

    class Failing:
        async def ainvoke(self, _messages):
            raise exc("upstream said no")

    monkeypatch.setattr(llm, "get_model", lambda: Failing())

    r = client.post("/agent/turn", json=turn_body())
    assert r.status_code == expected_status
    body = r.json()  # must not raise — the whole point of the fix
    assert expect_in_message.lower() in body["error"].lower()


def test_an_unexpected_exception_still_returns_json(client, monkeypatch):
    """The backstop. Anything at all, and the reader still gets { error }."""
    import app.main as main

    async def boom(agent, transcript):
        raise ValueError("something nobody predicted")

    monkeypatch.setattr(main, "generate_turn", boom)

    r = client.post("/agent/turn", json=turn_body())
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["error"] == "Something went wrong generating that turn."


def test_rate_limit_distinguishes_per_day_from_per_minute():
    """The seeder retries one and gives up on the other, so the flag must be right.

    This regressed once already: llm.generate_turn started raising its own
    RateLimited, the seeder was still sniffing the raw provider string, and
    rate-limited turns were silently SKIPPED instead of retried — biasing the
    corpus in exactly the way retrying exists to prevent.
    """
    import langchain_core.exceptions as exceptions

    from app import llm

    for raw, expected in [
        ("429 RESOURCE_EXHAUSTED 'quotaId': "
         "'GenerateRequestsPerDayPerProjectPerModel-FreeTier'", True),
        ("429 RESOURCE_EXHAUSTED 'quotaId': "
         "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'", False),
    ]:
        class Failing:
            async def ainvoke(self, _m):
                raise exceptions.ModelRateLimitError(raw)

        import asyncio

        from app.agents.registry import get_agent
        from app.schemas import ChatMessage

        orig = llm.get_model
        llm.get_model = lambda: Failing()
        try:
            try:
                asyncio.run(llm.generate_turn(
                    get_agent("gardener"),
                    [ChatMessage(role="user", content="hi")]))
                raise AssertionError("expected RateLimited")
            except llm.RateLimited as err:
                assert err.per_day is expected, f"{raw[:40]} -> per_day={err.per_day}"
        finally:
            llm.get_model = orig
