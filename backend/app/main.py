"""FastAPI app — the Other Minds backend.

Serves one endpoint that matters: POST /agent/turn, which advances the
conversation by exactly one agent message.
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.genai.errors import APIError

from app.agents.registry import agents, get_agent
from app.build import BUILD, STARTED_AT
from app.config import settings
from app.llm import (
    AuthFailed,
    MissingApiKey,
    RateLimited,
    UpstreamFailed,
    UpstreamRefused,
    generate_turn,
)
from app.orchestrator import choose_speaker
from app import store
from app.schemas import (
    ConversationDetail,
    ConversationSummary,
    ErrorResponse,
    NextSpeakerRequest,
    NextSpeakerResponse,
    SaveConversationRequest,
    TurnRequest,
    TurnResponse,
)

log = logging.getLogger("other_minds")

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Creating the schema is idempotent, so this is safe on every boot.
    store.init_db()
    yield


app = FastAPI(
    title="Other Minds API",
    description="Three minds respond to the same question from different worldviews.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
async def health() -> dict:
    """Liveness, plus the things that actually go wrong.

    `build` is the fingerprint of the source this process LOADED, not of the
    source on disk — see app/build.py. Compare it against a fresh
    `fingerprint()` (npm run check) to find out whether the server is serving
    the code you are looking at. It is reported here rather than logged because
    the question "is my edit live?" is asked from outside the process.
    """
    return {
        "ok": True,
        "model": settings.model,
        "has_api_key": bool(settings.gemini_api_key),
        "agents": sorted(agents().keys()),
        "build": BUILD,
        "started_at": STARTED_AT,
    }


@app.post("/agent/next-speaker", response_model=NextSpeakerResponse)
async def next_speaker(body: NextSpeakerRequest) -> JSONResponse:
    """Who speaks next — decided here, with no model call.

    Exists so the UI can light up the right portrait and name *while* the reply
    is still being written, without the client owning the turn rule. Clients
    should pass the returned id straight back to /agent/turn as `agentId`; a
    client that skips this and omits `agentId` just gets an independent draw.

    Naming a mind in the message elects that mind — see orchestrator.summoned.
    """
    picked = choose_speaker(body.transcript, allow_same=body.allow_same_speaker)
    return JSONResponse({"agentId": picked})


@app.post(
    "/agent/turn",
    response_model=TurnResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse},
               500: {"model": ErrorResponse}},
)
async def agent_turn(body: TurnRequest) -> JSONResponse:
    """Advance the conversation by exactly one agent message.

    With `agentId` omitted the server picks the next speaker, so the client no
    longer controls turn order.
    """
    agent_id = body.agent_id or choose_speaker(
        body.transcript, allow_same=body.allow_same_speaker
    )
    agent = get_agent(agent_id)
    if agent is None:
        return JSONResponse({"error": f"Unknown agent: {agent_id}"}, status_code=400)

    started = time.perf_counter()
    try:
        text = await generate_turn(agent, body.transcript)
    except MissingApiKey as err:
        return JSONResponse({"error": str(err)}, status_code=500)
    except AuthFailed as err:
        return JSONResponse({"error": str(err)}, status_code=401)
    except RateLimited as err:
        # 429, not 500: this is temporary and the reader can act on it.
        return JSONResponse({"error": str(err)}, status_code=429)
    except UpstreamRefused as err:
        log.exception("The provider rejected the request")
        return JSONResponse({"error": str(err)}, status_code=502)
    except UpstreamFailed as err:
        log.exception("The model call failed")
        return JSONResponse({"error": str(err) or "Error calling the model"}, status_code=502)
    except APIError as err:
        log.exception("Gemini call failed")
        return JSONResponse(
            {"error": getattr(err, "message", None) or "Error calling Gemini"},
            status_code=500,
        )
    except Exception:  # noqa: BLE001 - deliberate backstop, see below
        # Nothing may escape this handler. An unhandled exception is answered by
        # FastAPI with the PLAIN TEXT "Internal Server Error", and every client
        # here parses errors as JSON — so an escape surfaces to the reader as
        # "Unexpected token 'I' ... is not valid JSON" instead of anything they
        # could act on. The traceback still goes to the log.
        log.exception("Unhandled error while generating a turn")
        return JSONResponse(
            {"error": "Something went wrong generating that turn."}, status_code=500
        )

    # Telemetry is a side effect of answering, never a reason to fail. The turn
    # already succeeded by this point; a storage problem must not take it away
    # from the reader.
    try:
        store.record_generation(
            conversation_id=body.conversation_id,
            agent_id=agent.id,
            model=settings.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            text=text,
            transcript_len=len(body.transcript),
            # So a stored turn can be attributed to the prompt revision that
            # produced it — see app/build.py and the `build` column comment
            # in store.py. Without this every prompt version pools into one
            # number and "did the change work" needs fresh API calls to answer.
            build=BUILD,
        )
    except Exception:
        log.exception("Failed to record generation telemetry")

    return JSONResponse({"agentId": agent.id, "text": text})


# ── Conversation history ────────────────────────────────────────────────────
# Replaces the browser's localStorage. Endpoints are sync `def`, so FastAPI runs
# them in its threadpool — the right shape for blocking sqlite3 calls.


@app.get("/conversations", response_model=list[ConversationSummary])
def list_conversations() -> list[dict]:
    return store.list_conversations()


@app.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str) -> JSONResponse:
    conv = store.get_conversation(conversation_id)
    if conv is None:
        return JSONResponse({"error": "No such conversation"}, status_code=404)
    return JSONResponse(
        {
            "id": conv["id"],
            "title": conv["title"],
            "updatedAt": conv["updated_at"],
            "transcript": conv["transcript"],
        }
    )


@app.put("/conversations/{conversation_id}")
def save_conversation(
    conversation_id: str, body: SaveConversationRequest
) -> JSONResponse:
    """Upsert. The client mirrors its live transcript here on every change, so
    this is called often and must stay idempotent."""
    saved = store.save_conversation(conversation_id, body.title, body.transcript)
    return JSONResponse(saved)


@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> JSONResponse:
    # Deleting something already gone is a success, not an error — the caller
    # wanted it absent, and it is.
    store.delete_conversation(conversation_id)
    return JSONResponse({"ok": True})


# ── Analytics ───────────────────────────────────────────────────────────────


@app.get("/analytics/divergence")
def analytics_divergence() -> JSONResponse:
    """Do the three agents actually think differently?

    Read-only, computed on demand from the stored corpus. Imported lazily so a
    deployment that only serves conversations does not pay for pandas and
    scikit-learn at startup — they are in requirements-analytics.txt, not
    requirements.txt.
    """
    try:
        from app.analytics import divergence_report
    except ImportError:
        return JSONResponse(
            {"error": "Analytics dependencies are not installed "
                      "(pip install -r backend/requirements-analytics.txt)"},
            status_code=501,
        )
    return JSONResponse(divergence_report())
