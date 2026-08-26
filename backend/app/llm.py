"""The single LLM call behind one agent turn.

Provider access goes through LangChain so the model is swappable by config
without the rest of the app knowing. Generation parameters mirror
app/api/agent/route.ts exactly — see config.py for why each one is set.
"""

from functools import lru_cache

from google.genai.errors import APIError, ClientError
from langchain_core.exceptions import (
    ModelAuthenticationError,
    ModelError,
    ModelInvalidRequestError,
    ModelNotFoundError,
    ModelPermissionDeniedError,
    ModelRateLimitError,
)
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.agents.registry import AgentConfig, render_transcript
from app.config import settings
from app.schemas import ChatMessage


class MissingApiKey(RuntimeError):
    pass


class AuthFailed(RuntimeError):
    pass


class RateLimited(RuntimeError):
    """The provider refused the call for quota reasons."""


class UpstreamRefused(RuntimeError):
    """The provider rejected the request itself — bad model name, bad argument."""


class UpstreamFailed(RuntimeError):
    """Anything else the provider raised."""


@lru_cache(maxsize=1)
def get_model() -> ChatGoogleGenerativeAI:
    """Build the chat model once and reuse it across requests."""
    if not settings.gemini_api_key:
        raise MissingApiKey("Missing GEMINI_API_KEY — set it in .env.local.")
    kwargs = dict(
        model=settings.model,
        google_api_key=settings.gemini_api_key,
        max_output_tokens=settings.max_output_tokens,
        timeout=settings.request_timeout_s,
        max_retries=settings.max_retries,
    )
    # Not every model accepts this. gemini-3.5-flash-lite rejects
    # thinking_budget=0 outright with INVALID_ARGUMENT, while gemini-3.5-flash
    # requires it to stop thinking tokens eating the output budget. Setting it
    # to None omits the parameter, which is what a model that will not take a
    # zero needs.
    if settings.thinking_budget is not None:
        kwargs["thinking_budget"] = settings.thinking_budget
    return ChatGoogleGenerativeAI(**kwargs)


# A turn longer than this counts as "you have already made your case", and the
# next turn by the same agent is nudged toward a reaction instead.
MADE_THE_CASE_WORDS = 60


def rhythm_note(agent: AgentConfig, transcript: list[ChatMessage]) -> str:
    """One line describing what just happened, in this agent's terms.

    This exists because of a measured failure. A fixed instruction produces a
    fixed length, whichever length it names: "Respond as X with your next
    message" gave 48% of turns over 100 words and 1% under 15, while "say the
    one thing you would say next" gave 0% over 40 words and 81% inside a single
    15-40 word band. Both are uniform — the second is simply uniform somewhere
    else, and its variation was actually LOWER (cv 0.39 vs 0.53).

    A conversation is not uniform, so the prompt cannot be either. Rather than
    naming a length, this names the *situation* — you just spoke, or your last
    turn ran long, or someone else has the floor — and lets length follow from
    it. The situation differs turn to turn, so the lengths should too.

    Deterministic on purpose: this is responsive variance, not random variance.
    Rolling dice would produce spread without meaning.
    """
    others = [m for m in transcript if m.role not in ("user", agent.id)]
    mine = [m for m in transcript if m.role == agent.id]
    last = transcript[-1] if transcript else None

    # This agent held the floor and nobody has answered — the one case where
    # saying less is almost always right.
    if last is not None and last.role == agent.id:
        return (
            "You spoke last and no one has answered yet. Do not restate it. "
            "Either add one genuinely new specific, or say a single line — "
            "silence is better than padding."
        )

    # Its own previous turn was substantial, so the case is already on the table.
    if mine:
        spoken = len(mine[-1].content.split())
        if spoken > MADE_THE_CASE_WORDS:
            return (
                f"Your last turn ran to about {spoken} words — you have already "
                "made that case. This one almost certainly does not need to be "
                "that long."
            )

    # Someone else just spoke: react to them, briefly, or go elsewhere.
    if last is not None and last.role != "user" and others:
        from app.agents.registry import AGENT_NAMES

        return (
            f"{AGENT_NAMES[last.role]} just spoke. You can answer them directly "
            "— a line is enough, and disagreeing in four words is a real turn — "
            "or take it somewhere they have not."
        )

    # Opening the conversation, or replying straight after the person.
    return (
        "The person has just spoken. You can answer with a single question if "
        "that is what you actually have."
    )


def build_messages(
    agent: AgentConfig, transcript: list[ChatMessage]
) -> list[SystemMessage | HumanMessage]:
    """Assemble the prompt for one agent turn.

    Deliberately a flat text rendering of the conversation inside a single human
    message, NOT a list of alternating message objects. That is what the
    TypeScript version sent, and the prompts were tuned against it; mapping the
    speaker's own turns to AIMessage would change model behaviour and is a
    separate change to evaluate on its own.

    The closing lines are load-bearing, and both halves earn their place:
    `rhythm_note` supplies the situation, and the two sentences after it make
    the short end and the long end legitimate at the same time. Naming only one
    of them is what produced a hard ceiling in every version measured so far.
    """
    user_content = (
        "Here is the conversation so far:\n\n"
        f"{render_transcript(transcript)}\n\n"
        f"You are {agent.name}. You have just heard all of this.\n\n"
        f"{rhythm_note(agent, transcript)}\n\n"
        "A single sentence is a complete turn. So is a question, or agreeing in "
        "four words. Take a full paragraph only when you have a case nobody here "
        "has made yet — and then make it properly.\n\n"
        "Say what you would actually say next."
    )
    # Gemini's systemInstruction — the persona prompt.
    return [SystemMessage(content=agent.system_prompt), HumanMessage(content=user_content)]


async def generate_turn(agent: AgentConfig, transcript: list[ChatMessage]) -> str:
    """Ask one agent for its next line.

    Every provider failure is translated into one of this module's own
    exceptions, so the route layer never has to know which SDK is underneath.

    The classes caught here are LangChain's PROVIDER-AGNOSTIC ones from
    langchain_core. That matters twice over. It keeps the swap-the-provider
    promise honest — these same classes are raised by the Anthropic and OpenAI
    integrations. And it fixes a real hole: langchain-google-genai wraps errors
    in GoogleRateLimitError and friends, which do NOT inherit from the google
    SDK's APIError. Catching only APIError let a rate limit escape as an
    unhandled exception, which FastAPI answers with the plain text "Internal
    Server Error" — so the browser's `res.json()` failed on it and the reader
    saw a JSON parse error instead of "you are out of quota".
    """
    model = get_model()
    try:
        reply = await model.ainvoke(build_messages(agent, transcript))
    except ModelRateLimitError as err:
        raise RateLimited(
            "The model provider is rate limiting us. On the Gemini free tier "
            f"{settings.model} allows only a small number of requests per day — "
            "wait a moment, or try a different model."
        ) from err
    except (ModelAuthenticationError, ModelPermissionDeniedError) as err:
        raise AuthFailed("Authentication failed — check GEMINI_API_KEY.") from err
    except (ModelInvalidRequestError, ModelNotFoundError) as err:
        raise UpstreamRefused(
            f"The provider rejected the request for {settings.model}: {err}"
        ) from err
    except ClientError as err:
        # The raw google SDK can still surface directly. 400/403 usually means a
        # missing, invalid, or unauthorized key.
        if err.code in (400, 403):
            raise AuthFailed("Authentication failed — check GEMINI_API_KEY.") from err
        raise UpstreamFailed(str(err)) from err
    except (ModelError, APIError) as err:
        raise UpstreamFailed(str(err)) from err
    return reply.text.strip()
