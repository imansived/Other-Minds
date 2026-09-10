"""HTTP client for the Other Minds service.

Deliberately thin, and deliberately ignorant of the backend's internals: this is
a separate process talking over HTTP, not an import of `backend.app`. In
particular it does NOT decide who speaks next — it asks. That rule lives in one
place (backend/app/orchestrator.py) precisely so a second frontend cannot drift
out of step with the first.
"""

import os

import httpx

BASE_URL = os.environ.get("OTHER_MINDS_API_URL", "http://127.0.0.1:8000")
TIMEOUT = 90.0


class ApiError(RuntimeError):
    pass


class BackendUnreachable(ApiError):
    pass


def _request(method: str, path: str, **kw):
    try:
        r = httpx.request(method, f"{BASE_URL}{path}", timeout=TIMEOUT, **kw)
    except httpx.RequestError as err:
        raise BackendUnreachable(
            f"Can't reach the Other Minds service at {BASE_URL}.\n\n"
            f"Start it with `npm run dev:api`, or set OTHER_MINDS_API_URL."
        ) from err
    if r.status_code >= 400:
        try:
            payload = r.json()
            message = payload.get("error") or payload.get("detail") or r.text
        except Exception:
            message = r.text
        if isinstance(message, list) and message:
            message = message[0].get("msg", str(message))
        raise ApiError(str(message))
    return r.json()


def health() -> dict:
    return _request("GET", "/health")


def next_speaker(transcript: list[dict], allow_same_speaker: bool = True) -> str:
    """Who speaks next. No model call — returns immediately.

    Pass allow_same_speaker=False when the reader asked for a DIFFERENT mind;
    otherwise the draw may hand the floor straight back to whoever just spoke.
    """
    return _request(
        "POST",
        "/agent/next-speaker",
        json={"transcript": transcript, "allowSameSpeaker": allow_same_speaker},
    )["agentId"]


def take_turn(transcript: list[dict], agent_id: str, conversation_id: str | None) -> str:
    return _request(
        "POST",
        "/agent/turn",
        json={
            "transcript": transcript,
            "agentId": agent_id,
            "conversationId": conversation_id,
        },
    )["text"]


def list_conversations() -> list[dict]:
    return _request("GET", "/conversations")


def get_conversation(conversation_id: str) -> dict:
    return _request("GET", f"/conversations/{conversation_id}")


def save_conversation(conversation_id: str, title: str, transcript: list[dict]) -> dict:
    return _request(
        "PUT",
        f"/conversations/{conversation_id}",
        json={"title": title, "transcript": transcript},
    )


def delete_conversation(conversation_id: str) -> None:
    _request("DELETE", f"/conversations/{conversation_id}")


def divergence() -> dict:
    """The divergence report. Computed on demand by the service."""
    return _request("GET", "/analytics/divergence")
