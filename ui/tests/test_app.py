"""Streamlit UI behaviour, driven headlessly through Streamlit's AppTest.

The API is stubbed throughout: these tests are about what the UI does with a
response, not about the model. Anything that would cost a real call is faked.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import api

APP = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")


@pytest.fixture
def fake_api(monkeypatch):
    """A stub service. `calls` records what the UI asked for."""
    state = {"conversations": [], "calls": [], "speaker": "gardener"}

    def next_speaker(transcript, allow_same_speaker=True):
        # The flag is recorded, not ignored: whether the UI asks for "someone
        # else" or "whoever the room hands it to" is the whole difference
        # between the button and a typed reply.
        state["calls"].append(("next_speaker", len(transcript), allow_same_speaker))
        return state["speaker"]

    def take_turn(transcript, agent_id, conversation_id):
        state["calls"].append(("take_turn", agent_id))
        return f"reply from {agent_id}"

    monkeypatch.setattr(api, "next_speaker", next_speaker)
    monkeypatch.setattr(api, "take_turn", take_turn)
    monkeypatch.setattr(api, "list_conversations", lambda: state["conversations"])
    monkeypatch.setattr(api, "save_conversation", lambda *a, **k: {})
    monkeypatch.setattr(api, "delete_conversation", lambda *a, **k: None)
    monkeypatch.setattr(
        api, "get_conversation",
        lambda cid: {"id": cid, "title": "t", "updatedAt": 0,
                     "transcript": [{"role": "user", "content": "restored"}]},
    )
    return state


def run(timeout=30) -> AppTest:
    return AppTest.from_file(APP, default_timeout=timeout).run()


def test_landing_introduces_the_three_minds(fake_api):
    at = run()
    assert not at.exception
    assert "Other Minds" in at.title[0].value
    body = " ".join(m.value for m in at.markdown)
    for name in ("The Introspector", "The Behaviorist", "The Gardener"):
        assert name in body


def test_asking_a_question_produces_one_agent_reply(fake_api):
    at = run()
    at.chat_input[0].set_value("should I stay?").run()

    roles = [m["role"] for m in at.session_state["transcript"]]
    assert roles == ["user", "gardener"], roles
    assert at.session_state["transcript"][1]["content"] == "reply from gardener"
    # It asked who speaks rather than deciding for itself — and a typed reply
    # leaves the double turn on the table.
    assert ("next_speaker", 1, True) in fake_api["calls"]


def test_hear_another_mind_asks_for_a_different_one(fake_api):
    """The button says "another mind". It has to ask for one.

    Without the flag the draw could hand the floor straight back to whoever
    just spoke, roughly one press in four — which is what a reader saw when
    The Introspector answered twice with the button in between.
    """
    at = run()
    at.chat_input[0].set_value("should I stay?").run()
    at.button[0].click().run()

    asks = [c for c in fake_api["calls"] if c[0] == "next_speaker"]
    assert asks[-1][2] is False, asks


def test_only_one_agent_speaks_per_turn(fake_api):
    """The whole shape of the app: one message, then it waits for the reader."""
    at = run()
    at.chat_input[0].set_value("hello").run()
    assert len(at.session_state["transcript"]) == 2
    assert at.session_state["pending"] is False


def test_hear_another_mind_advances_by_exactly_one(fake_api):
    at = run()
    at.chat_input[0].set_value("hello").run()
    fake_api["speaker"] = "introspector"

    advance = [b for b in at.button if "another mind" in b.label][0]
    advance.click().run()

    roles = [m["role"] for m in at.session_state["transcript"]]
    assert roles == ["user", "gardener", "introspector"], roles


def test_a_service_failure_is_shown_and_does_not_wedge_the_app(fake_api):
    def boom(*a, **k):
        raise api.BackendUnreachable("Can't reach the Other Minds service.")

    at = run()
    at.chat_input[0].set_value("hello").run()
    # Break the service, then ask for another turn.
    import api as api_mod
    api_mod.next_speaker = boom
    advance = [b for b in at.button if "another mind" in b.label][0]
    advance.click().run()

    assert at.error, "no error surfaced to the reader"
    assert "reach" in at.error[0].value
    # Crucially: not stuck pending, so the reader can try again.
    assert at.session_state["pending"] is False


def test_opening_a_stored_conversation_loads_its_transcript(fake_api):
    fake_api["conversations"] = [
        {"id": "abc", "title": "an older question", "updatedAt": 0, "messageCount": 2}
    ]
    at = run()
    opener = [b for b in at.sidebar.button if "older question" in b.label][0]
    opener.click().run()

    assert at.session_state["conversation_id"] == "abc"
    assert at.session_state["transcript"][0]["content"] == "restored"


def test_new_conversation_clears_the_room(fake_api):
    at = run()
    at.chat_input[0].set_value("hello").run()
    assert at.session_state["transcript"]

    new = [b for b in at.sidebar.button if "new conversation" in b.label][0]
    new.click().run()
    assert at.session_state["transcript"] == []
    assert at.session_state["conversation_id"] is None
