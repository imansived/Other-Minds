"""Generate a corpus of real agent turns to run the analytics over.

The divergence metrics measure whether the three agents actually think
differently. That question cannot be answered from a handful of turns, and it
must not be answered from invented text — fake transcripts would tell us
about the fixture, not about the prompts. So this drives the real agents,
through the real orchestrator, and stores the result in the real database.

Conversations are given deterministic `seed-NNNN` ids so a re-run replaces them
rather than piling up duplicates, and so seeded rows are easy to tell apart
from anything you produced by using the app.

    python backend/scripts/seed_corpus.py --turns 6
    python backend/scripts/seed_corpus.py --clear
"""

import argparse
import asyncio
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store  # noqa: E402
from app.agents.registry import get_agent  # noqa: E402
from app.config import settings  # noqa: E402
from app.llm import RateLimited, generate_turn  # noqa: E402
from app.orchestrator import last_agent_speaker, pick_next_speaker  # noqa: E402
from app.schemas import ChatMessage  # noqa: E402

# Ordinary dilemmas, deliberately varied: the agents' differences show up in
# what they reach for, so a corpus of all-career questions would understate how
# far apart they actually are.
QUESTIONS = [
    "I've been at my job six years and I think I want to leave, but I can't tell if I'm just tired.",
    "My mother is getting older and lives four hours away. Do I move back?",
    "I keep saying yes to things I don't want to do.",
    "I've been offered a promotion that means relocating away from my closest friends.",
    "My partner wants children and I'm not sure I do.",
    "I stopped painting three years ago and I miss it, but I never actually pick up a brush.",
    "Everyone says I should be grateful for this job. I'm not.",
    "I have enough money to stop working for a year. I don't know if I should.",
    "A friend of fifteen years said something cruel and hasn't apologised.",
    "I got into a graduate programme but it means four more years of being broke.",
    "I moved to a new city eight months ago and still haven't made friends.",
    "My father and I haven't spoken in two years and I don't know who should call.",
    "I'm good at my job and bored by it.",
    "I promised myself I'd run a marathon this year and I've trained twice.",
    "My sister keeps asking to borrow money and I keep lending it.",
]


class Pacer:
    """Keep under the API's requests-per-minute ceiling.

    The free tier allows 5 requests/minute for gemini-3.5-flash, so calls have
    to be spaced deliberately rather than fired off back to back.
    """

    def __init__(self, rpm: float):
        self.interval = 60.0 / rpm if rpm > 0 else 0.0
        self.last = 0.0

    async def wait(self) -> None:
        gap = time.monotonic() - self.last
        if gap < self.interval:
            await asyncio.sleep(self.interval - gap)
        self.last = time.monotonic()


class DailyQuotaExhausted(RuntimeError):
    """The per-day free-tier allowance is gone. Waiting will not help."""


def retry_delay_from(err: Exception, default: float) -> float:
    """Honour the server's own retry hint when it gives one."""
    match = re.search(r"[Pp]lease retry in ([\d.]+)s", str(err))
    return float(match.group(1)) + 1.0 if match else default


def classify_quota_error(err: Exception) -> str:
    """Per-minute or per-day? The difference decides whether retrying is sane.

    A per-minute limit clears on its own in under a minute. A per-day one does
    not clear until tomorrow, and retrying against it just burns time quietly —
    which looks exactly like slow progress.
    """
    quota_ids = re.findall(r"'quotaId': '([^']+)'", str(err))
    if any("PerDay" in q for q in quota_ids):
        return "day"
    if quota_ids:
        return "minute"
    return "minute" if "retry in" in str(err) else "unknown"


async def generate_with_retry(agent, transcript, pacer: Pacer, attempts: int = 5) -> str:
    """One turn, retried on rate limits.

    Retrying rather than skipping matters for the corpus: failures cluster in
    time, so dropping them would quietly bias which agents and which
    conversation positions are represented.
    """
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        await pacer.wait()
        try:
            return await generate_turn(agent, transcript)
        except RateLimited as err:
            # generate_turn now classifies this for us. Before it did, the
            # seeder sniffed the raw provider string — and when the exception
            # type changed, that sniffing silently stopped matching, so
            # rate-limited turns were SKIPPED rather than retried. Skipping
            # biases the corpus exactly where retrying was meant to protect it.
            last_error = err
            if err.per_day:
                raise DailyQuotaExhausted(str(err)) from err
            wait = 20.0 * attempt
        except Exception as err:  # noqa: BLE001 - anything else is not ours to retry
            last_error = err
            if "RESOURCE_EXHAUSTED" not in str(err) and "429" not in str(err):
                raise
            if classify_quota_error(err) == "day":
                limit = re.findall(r"'quotaValue': '([^']+)'", str(err))
                raise DailyQuotaExhausted(
                    f"the per-day free-tier quota for {settings.model} is used up"
                    + (f" (limit {limit[0]}/day)" if limit else "")
                ) from err
            wait = retry_delay_from(err, default=20.0 * attempt)
            print(f"    rate limited, waiting {wait:.0f}s (attempt {attempt}/{attempts})", flush=True)
            await asyncio.sleep(wait)
    raise RuntimeError(f"gave up after {attempts} attempts") from last_error


async def seed_one(index: int, question: str, turns: int, pacer: Pacer) -> int:
    """Run one conversation to `turns` agent messages. Returns turns stored."""
    conversation_id = f"seed-{index:04d}"
    transcript = [ChatMessage(role="user", content=question)]

    for _ in range(turns):
        agent_id = pick_next_speaker(last_agent_speaker(transcript))
        agent = get_agent(agent_id)
        started = time.perf_counter()
        try:
            text = await generate_with_retry(agent, transcript, pacer)
        except DailyQuotaExhausted:
            # Nothing to be gained by continuing: every later call fails too.
            raise
        except Exception as err:  # noqa: BLE001 - one bad turn must not end the run
            print(f"  ! {agent_id}: {type(err).__name__}: {str(err)[:120]}")
            continue
        transcript.append(ChatMessage(role=agent_id, content=text))
        store.record_generation(
            conversation_id=conversation_id,
            agent_id=agent_id,
            model=settings.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            text=text,
            transcript_len=len(transcript) - 1,
        )
        print(f"  {agent_id:13s} {len(text):5d} chars  {text[:64]!r}", flush=True)

    title = " ".join(question.split())
    store.save_conversation(
        conversation_id, title[:63] + "…" if len(title) > 64 else title, transcript
    )
    return len(transcript) - 1


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--turns", type=int, default=6, help="agent turns per conversation")
    ap.add_argument("--limit", type=int, default=len(QUESTIONS), help="how many questions")
    ap.add_argument("--rpm", type=float, default=4.5,
                    help="requests per minute; the free tier ceiling is 5")
    ap.add_argument("--thinking-budget", default=None,
                    help="'none' omits the parameter (required by -lite models, "
                         "which reject a budget of 0)")
    ap.add_argument("--model", default=None,
                    help="override the model, e.g. gemini-3.5-flash-lite. Free-tier "
                         "daily quotas differ sharply between models, and the model "
                         "used is recorded with every turn.")
    ap.add_argument("--clear", action="store_true", help="delete seeded conversations and exit")
    args = ap.parse_args()

    store.init_db()

    if args.thinking_budget is not None:
        settings.thinking_budget = (
            None if args.thinking_budget.lower() == "none" else int(args.thinking_budget)
        )

    if args.model and args.model != settings.model:
        # Both the call and the telemetry read settings.model, so overriding it
        # here keeps the stored `model` column honest about what produced each
        # turn. The chat model is cached, so the cache has to go with it.
        settings.model = args.model

    from app.llm import get_model

    get_model.cache_clear()

    if args.clear:
        removed = 0
        for row in store.list_conversations(limit=1000):
            if row["id"].startswith("seed-"):
                store.delete_conversation(row["id"])
                removed += 1
        print(f"removed {removed} seeded conversation(s)")
        return

    questions = QUESTIONS[: args.limit]
    calls = len(questions) * args.turns
    print(f"seeding {len(questions)} conversations x {args.turns} turns "
          f"= {calls} calls to {settings.model}")
    print(f"paced at {args.rpm}/min -> roughly {calls / args.rpm:.0f} minutes\n")

    pacer = Pacer(args.rpm)
    total = 0
    try:
        for i, question in enumerate(questions):
            print(f"[{i + 1}/{len(questions)}] {question}", flush=True)
            total += await seed_one(i, question, args.turns, pacer)
            print(flush=True)
    except DailyQuotaExhausted as err:
        print(f"\nstopped: {err}")
        print("  Waiting will not help until tomorrow. Options:")
        print("    - seed with another model:  npm run seed -- --model gemini-3.5-flash-lite")
        print("    - or come back tomorrow and re-run to top the corpus up")
        print(f"\n{total} agent turns stored before stopping")
        raise SystemExit(2)

    print(f"done: {total} agent turns stored")


if __name__ == "__main__":
    asyncio.run(main())
