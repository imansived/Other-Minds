"""Runtime configuration.

The API key is read from the SAME `.env.local` the Next.js app already uses, so
there is one key on disk rather than two copies drifting apart. `backend/.env`
overrides it when present.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Later files win, so a backend-local .env overrides the shared one.
        env_file=(PROJECT_ROOT / ".env.local", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str = ""

    # ── Generation parameters — these mirror app/api/agent/route.ts exactly. ──
    # gemini-3.5-flash: verified present in ListModels against the live key.
    model: str = "gemini-3.5-flash"
    # Both a backstop and a real brake on length. At 500 the ceiling never bit,
    # and instruction alone did not hold the agents to short turns. 300 leaves
    # room for the occasional earned paragraph while making a rambling turn
    # impossible.
    max_output_tokens: int = 300
    # Gemini Flash thinks by default and thinking tokens count against
    # max_output_tokens. Disable it so the whole budget is reply.
    #
    # None omits the parameter entirely, which some models require: the -lite
    # variants reject a budget of 0 with INVALID_ARGUMENT rather than treating
    # it as "do not think".
    thinking_budget: int | None = 0
    request_timeout_s: float = 60.0
    max_retries: int = 2

    # Conversation history + turn telemetry. Relative paths resolve against
    # backend/, so the default lands at backend/data/other_minds.db.
    db_path: str = "data/other_minds.db"

    # ── Turn logic (ported from app/page.tsx) ────────────────────────────────
    double_turn_chance: float = 0.25

    # Origins allowed to call this API directly. The Next.js proxy route does
    # not need CORS (it is server-to-server); this is for the Streamlit UI and
    # any future direct browser client.
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://localhost:8501")


settings = Settings()
