# Other Minds — Technical Manual

**Scope:** the state of the project as of 25 September 2026, written for the person who
built it. It is not a tour of the file tree; the file tree is in the READMEs. This is
the reasoning: what each decision bought, what it cost, what was tried first and
failed, and what the measurements actually say.

This is a living document, not a snapshot taken once and left — §3.9, the `build`
column (§3.8), and the summoning rules (§3.3) were all added in this revision, after
being shipped in the code first. A manual that documents a build older than the one
running is worse than no manual, because it reads as authoritative while being wrong;
the appendix at the bottom exists to make that failure visible rather than silent.

**How to read it for interview prep.** Every section is written so the *why* survives
on its own. If you can restate the "why" of a section without looking at the code, you
can answer a question about it. The strongest interview material is §4 (bugs) and §5
(measurement), because those are the places where you were wrong first and can show
the correction.

---

## Table of contents

1. [Concept and architecture](#1-concept-and-architecture)
2. [The migration story](#2-the-migration-story)
3. [Engineering concepts from first principles](#3-engineering-concepts-from-first-principles)
4. [Real bugs and what they taught](#4-real-bugs-and-what-they-taught)
5. [The measurement approach](#5-the-measurement-approach)
6. [Glossary](#6-glossary)
7. [Questions you should be able to answer cold](#7-questions-you-should-be-able-to-answer-cold)

---

## 1. Concept and architecture

### 1.1 What the app does

A person types an ordinary hard question — *"I've been at my job six years and I think
I want to leave, but I can't tell if I'm just tired."* Three agents answer, **one
message at a time**, from three worldviews that do not agree:

| Agent | Stance | What it treats as evidence |
|---|---|---|
| **The Introspector** | A person is understood from the inside. | Your own reaction when you picture doing the thing. |
| **The Behaviorist** | What you repeatedly do tells you more than what you say you feel. | A change you made and what followed from it. |
| **The Gardener** | A life is lived among other people, not solved privately. | What has actually been said out loud to the people involved. |

Nothing auto-advances. After each reply the reader either responds or presses *hear
another mind*. That is a product decision with technical consequences: there is no
unattended multi-agent loop, so no runaway token spend, no "agents talking to each
other for forty turns", and every turn is exactly one HTTP request a human asked for.

The agents are explicitly **not** trying to reach agreement. There is no synthesis
step, no judge, no final answer. The output of the system is the perspective shift.

### 1.2 Why three agents and not one

This is the first question an interviewer will ask, and the naive answer ("more
perspectives is better") is weak. The real answer has three parts.

**(a) One model asked for three perspectives produces one perspective in three
costumes.** Prompt a single call with "give me three views" and the model writes all
three in one forward pass, conditioned on the same context, optimising one coherent
output. It balances them. It makes them complement each other. It usually closes with
a reconciling paragraph. That is the opposite of the product — the value here is
*unreconciled* disagreement.

**(b) Separate calls give separate conditioning.** Each turn is one call with one
agent's system prompt in the system slot and the shared transcript in the user slot.
The Behaviorist has never seen the Introspector's instructions. It sees only what the
Introspector *said out loud* — which is exactly the information a person in a group
conversation has. Divergence becomes structural rather than requested.

**(c) The claim is falsifiable, so it is tested.** "These three think differently" is
easy to believe from reading four transcripts and easy to be wrong about, because
prompts drift and every persona slowly converges on the same helpful-assistant voice.
So there is a classifier that tries to guess which agent wrote a turn from the text
alone (§5). It currently scores **75.3% against 33.3% chance**. That number is the
product spec, not a vanity metric.

The compact framing: *"Three agents isn't decoration — it's the only architecture
that produces the thing I'm selling, and I have a metric that would tell me if it
stopped working."*

### 1.3 The architecture as it stands

```
                  ┌───────────────────────── browser ─────────────────────────┐
                  │  React 19 UI: galaxy backdrop, per-agent entrance          │
 Next.js (:3000) ─┤  animation, arrival sound, history sidebar                 │
                  └──────────────┬────────────────────────────────────────────┘
                                 │ fetch('/api/agent')      same-origin only
                  ┌──────────────▼──────────────┐
                  │ Next route handlers          │  app/api/**  — thin server-side
                  │ (the proxy / BFF layer)      │  proxy. No agent logic at all.
                  └──────────────┬──────────────┘
                                 │ HTTP, server-to-server
 Streamlit (:8501) ──────────────┤ ui/api.py — direct HTTP, shares no code
                                 │
                  ┌──────────────▼───────────────────────────────────────────┐
                  │ FastAPI (:8000)                       backend/app/       │
                  │                                                          │
                  │  main.py          routes, error → HTTP status mapping     │
                  │  orchestrator.py  WHO SPEAKS NEXT  ← single source of     │
                  │                   truth for the turn rule                 │
                  │  agents/          registry + prompts/ (lens + _house.md)  │
                  │                   ← the product                           │
                  │  llm.py           envelope assembly + the one model call   │
                  │  store.py         SQLite: history + append-only telemetry  │
                  │  analytics.py     divergence + chat-feel metrics           │
                  └──────┬──────────────────────────────┬────────────────────┘
                         │ LangChain                    │ sqlite3
                 ┌───────▼────────┐            ┌────────▼───────────┐
                 │ Gemini         │            │ other_minds.db     │
                 │ (3.5-flash)    │            │ 3 tables           │
                 └────────────────┘            └────────────────────┘
```

`docker-compose.yml` runs those three services with one API key and one named volume.

### 1.4 Why each piece exists

Not *what it is* — what it does here that the alternative would not.

**FastAPI.** The job was to move agent logic out of the browser into somewhere it
could be tested, seeded and analysed. That somewhere had to be Python, because the
analytics need pandas and scikit-learn and there is no Node equivalent worth using.
Given Python, FastAPI buys three specific things: Pydantic models that validate the
wire format at the boundary (`schemas.py`); automatic OpenAPI docs at `/docs`, which
make the API explorable without writing a client; and a concurrency model where
`async def` handlers share one event loop for the network-bound model call while plain
`def` handlers are pushed to a threadpool. That split is used deliberately —
`/agent/turn` is `async def`, every `/conversations` route is plain `def`, because
`sqlite3` calls block and a blocking call on the event loop would stall every other
request.

**LangChain.** Used as a *thin adapter*, not a framework. No chains, no agent
executors, no memory objects, no retrievers. It provides two things. First, a uniform
constructor and `ainvoke` across providers, so swapping Gemini for Anthropic or OpenAI
means changing one class and one requirements line and nothing else in the app knows.
Second — the part that turned out to matter more — **provider-agnostic exception
types** (`ModelRateLimitError`, `ModelAuthenticationError`, `ModelNotFoundError`) in
`langchain_core`, which let the route layer map failures to HTTP status codes without
knowing which SDK is underneath. §4.6 is the bug that made that non-theoretical. The
honest cost: one more layer between you and the provider SDK, which is itself a place
for bugs to hide.

**Gemini (`gemini-3.5-flash`).** Free tier, good latency (median 7.4s per turn in the
recorded corpus), and a native separate system-instruction channel, which is what
makes "persona in the system slot, conversation in the user slot" clean rather than a
convention you have to enforce. The free tier is an active design constraint, not a
footnote: 20 requests/day on `flash` is enough to *use* the app and nowhere near
enough to *seed a corpus*, which is why `seed_corpus.py` takes `--model` and why every
stored turn is stamped with the model that produced it.

**SQLite.** The requirement was never "a database", it was "a queryable corpus".
`localStorage` could store history but could never be `SELECT`ed. SQLite is one file,
no server, no ops — and, critically, `pandas.read_sql_query` works directly against a
`sqlite3` connection, so `analytics.py` is a few SQL strings rather than an ETL
pipeline. No ORM: the schema is three flat tables and an ORM's value at that size is
negative.

**Next.js.** It was already there (the project began here) and it stays because it is
the *product* surface: the galaxy backdrop, the per-agent entrance animations, the
arrival sound, the collapsing history sidebar. Its route handlers act as a
Backend-For-Frontend proxy, which is load-bearing for three reasons: the browser only
ever talks to its own origin, so the backend needs no CORS; the API key never enters a
client bundle; and the backend never needs public exposure.

**Streamlit.** It exists to *prove the architecture*, and it earns its place by being
genuinely different rather than a second copy. It shares **zero** code with the React
app — everything it knows it asks the API for, including who speaks next. Had the turn
rule stayed in the browser, this app would have had to reimplement it and the two would
have drifted apart within a week. Streamlit also carries the Divergence page, which
suits it better than React: it is a data view, and `st.dataframe` plus `st.bar_chart`
is fifteen lines against a charting library's two hundred. What it deliberately does
*not* copy is the animation and sound — Streamlit re-runs the whole script on every
interaction, so per-message animation state cannot survive, and imitating it would
produce a worse version of something React already does well. Knowing what *not* to
port is the interesting half of this decision.

**Docker Compose.** Three processes, one shared key, one network, one persistent
volume is exactly the shape Compose is for. It also forced the
localhost-vs-container-loopback distinction into the open (§4.9), which is real
knowledge rather than boilerplate.

### 1.5 One turn, end to end

Worth memorising — this is the "walk me through a request" answer.

1. Reader presses **Continue**. `page.tsx` sets `turnInFlightRef` *synchronously* —
   not React state, because a second click can land before a re-render and state read
   from the render closure would still be stale.
2. `POST /api/agent/next-speaker` → proxy → `POST /agent/next-speaker`.
   `orchestrator.pick_next_speaker` returns an agent id. **No model call**, so it
   returns in milliseconds.
3. The UI lights that agent's portrait and shows a composing row — *before the reply
   exists*. This is the entire reason a turn is two requests instead of one.
4. `POST /api/agent` with `{agentId, transcript}` → proxy → `POST /agent/turn`.
5. `registry.get_agent` returns the cached prompt. `llm.build_messages` assembles the
   envelope: `SystemMessage(persona)` + `HumanMessage(rendered transcript + situation
   note + two-sided length permission + "Say what you would actually say next.")`.
6. `await model.ainvoke(...)` — one Gemini call, `max_output_tokens=300`,
   `thinking_budget=0`.
7. Provider errors are translated into this module's own exception types and mapped to
   status codes: 429 rate limit, 401 auth, 502 upstream refused, 500 backstop.
   **Nothing escapes** — an unhandled exception returns the plain-text string
   "Internal Server Error", and every client here calls `res.json()` on the body.
8. The turn is appended to `generations`. A storage failure is caught and logged but
   never fails the request: the answer already exists, and losing a telemetry row must
   not take it away from the reader.
9. The client renders the bubble with a per-agent entrance animation and fires the
   arrival sound at `LANDING_MS[agent]` — the instant the bubble *settles*: 440ms for
   the Behaviorist, 870ms for the Introspector. A sound at message-start reads as
   unrelated to the message.
10. A `useEffect` mirrors the whole transcript to `PUT /conversations/{id}` — upsert,
    full replace, idempotent.

---

## 2. The migration story

This is a narrative of pressures, not a changelog. Each step happened because
something became impossible, not because a newer stack was more fashionable.

### 2.1 Where it started: everything in Next.js

The first working version was a single Next.js app. `app/lib/agents.ts` held the agent
ids, display names, colours **and the three system prompts**. `app/api/agent/route.ts`
called Gemini directly. `app/page.tsx` decided who spoke next. History lived in
`localStorage`.

It worked. It demoed well. Three separate pressures made it a dead end.

### 2.2 Pressure one: the prompts were in the client bundle

The prompts are the product — roughly 16KB of carefully tuned text at the time
(~26KB today, since they have grown). In
`app/lib/agents.ts` they were imported by a `"use client"` component, which means they
were shipped to **every visitor**, in a file anyone could read, on every page load.
That is two problems at once: bundle weight nobody benefits from, and the fact that
the most valuable artefact in the project was published to the public.

Worse was the structural problem. Once anything else needed the prompts — a seed
script, a test, a second frontend — there would be two copies, and prompt text is the
kind of thing that drifts silently. You do not get an error; you get a slightly
different agent.

The fix: prompts move to `backend/app/agents/prompts/*.md`, extracted byte-for-byte
and verified as exact substrings of the original. The frontend keeps only what it
renders — ids, names, colours. `test_parity.py::test_frontend_no_longer_carries_the_prompts`
asserts `systemPrompt` never reappears in `agents.ts`, so the regression cannot come
back quietly.

### 2.3 Pressure two: history in localStorage could not be analysed

The central claim of the app — the three agents diverge — was, at this point,
unmeasured. Checking it meant reading transcripts, which is exactly the judgement that
drifts: you read four good ones and conclude it works.

Measuring it requires a corpus, and `localStorage` is a corpus dead end. It is trapped
in one browser profile, it is a JSON blob rather than rows, and nothing outside the
browser can read it. That single requirement — *"I want to run a classifier over
every turn these agents have ever produced"* — is what forced a real database, and a
real database means a server process, and Python is where the classifier lives.

The shape that came out of it is worth defending in an interview:

| table | written by | write pattern | why |
|---|---|---|---|
| `conversations` | the client, on every change | upsert | mirrors what the client already does |
| `messages` | the client, on every change | **full replace** | idempotent: a retry or out-of-order save cannot duplicate or interleave turns |
| `generations` | `/agent/turn` | **append-only** | survives the full replace above, so the record of what was actually generated stays honest |

`generations` deliberately has **no foreign key** to `conversations`. A turn can be
generated and never saved — the reader closes the tab — and dropping those rows would
bias the corpus toward conversations people chose to keep. Deleting a conversation
removes its messages and leaves its telemetry.

Messages are stored one row per turn rather than as a JSON blob for exactly one
reason: `pandas.read_sql_query` can then read the corpus with a plain `SELECT`.

### 2.4 Pressure three, and the decision that unlocked everything: turn logic moves server-side

This is "step 2's decision", and it is the one to lead with, because it looks small
and is not.

In the original app, `page.tsx` decided who spoke next: semi-random rotation, ~25%
chance the same agent speaks twice in a row. It was maybe fifteen lines of React. It
looked like view logic. It is not view logic — it is a rule about how the conversation
behaves, and it was living in the view.

Moving it to `backend/app/orchestrator.py` unlocked four things that were previously
impossible:

**(1) A second frontend becomes cheap and safe.** The Streamlit app asks
`POST /agent/next-speaker` and gets an answer. It does not reimplement the rule; it
cannot drift from the rule. Without this move, the Streamlit app would need its own
copy of the rotation logic, and the day you changed `double_turn_chance` you would
have changed it in one place and quietly not in the other. *The general principle: the
number of frontends you can afford is determined by how much behaviour lives in them.*

**(2) The turn rule becomes testable without a browser.** `pick_next_speaker` takes an
injectable `rng`, so `test_parity.py` runs it 20,000 times and asserts the repeat rate
sits between 0.23 and 0.27, and separately that non-repeat turns split evenly between
the other two agents (ratio under 1.06). You cannot write that test against a React
component in any pleasant way.

**(3) The seed script can drive the *real* system.** `seed_corpus.py` imports
`pick_next_speaker` and `generate_turn` — the same functions the API route uses. The
corpus is therefore produced by the real orchestrator, the real prompts and the real
model. Had turn order stayed in the browser, the seeder would have had to fake it, and
the analytics would have been measuring the fixture instead of the product.

**(4) The turn rule becomes something analytics can audit.** `analytics.turn_taking`
reads the stored corpus, computes the observed repeat rate, and compares it to
`settings.double_turn_chance` with a standard-error band. Observed right now: **0.23
against a configured 0.25 over 61 transitions** — within two standard errors. That check
only means anything because there is exactly one place the rule could have come from.

The cost of the move was real and worth naming: a turn became **two HTTP requests**.
That is not free — it adds a round trip and a window where no one is composing yet. It
was accepted because the UI needs to name the speaker *while* the reply is being
written, and the alternative (one request that returns speaker and text together)
would leave the composing row anonymous for the full 7 seconds of generation. The
second-order cost showed up in state management: `busy` now has to cover the gap
between the two requests, which is why `resolvingSpeaker` exists alongside
`composingAgent`.

There is also a sharp edge documented in `backend/README.md`: omitting `agentId` from
`/agent/turn` makes the server draw a speaker itself. That is fine for scripts, but a
client that calls `/agent/next-speaker` and *then* omits `agentId` gets an
**independent second draw** — the portrait lights for one agent and a different one
replies. The API is honest about this rather than defending against it, because the
alternative (server-side session state remembering the draw) would introduce state the
API otherwise does not have.

### 2.5 What was deliberately kept identical

A migration that changes behaviour while changing structure is one you cannot debug,
because every difference has two possible causes. So the port was made **byte-exact**
where behaviour was concerned, and `test_parity.py` exists to pin it:

- prompts extracted verbatim and verified as substrings of the original;
- `render_transcript` reproduces the TypeScript `renderTranscript` exactly —
  `"Speaker: content"` with a blank line between, because the prompts assume that
  layout;
- generation parameters mirrored exactly;
- display names asserted to match `app/lib/agents.ts`, because the prompts instruct the
  agents to refer to each other by those exact strings. If the two sides drift, the
  agents start naming someone who does not exist.

One thing was deliberately *not* ported: the flat-transcript-in-one-human-message
shape was kept rather than "improved" into alternating `AIMessage`/`HumanMessage`
objects. Mapping the speaking agent's own turns to `AIMessage` would change model
behaviour, and that is a separate change to evaluate on its own evidence — not a
freebie to smuggle into a port.

### 2.6 What the migration cost

Being able to state the downsides is what makes the story credible:

- **Two processes instead of one.** "It just hangs" became a real failure mode, which
  is why `app/lib/backend.ts` catches connection errors and returns the literal advice
  *"Can't reach the Python backend… Start it with: npm run dev:api"*.
- **Two error vocabularies.** FastAPI's validation errors are `{detail: ...}`; the app
  speaks `{error: ...}`. The proxy normalises that one case so every failure reaches
  the client in one shape.
- **A dev-loop problem that consumed real days.** Two servers, on Windows, with a
  reload watcher — that is §4.1 and §4.2, and it is the most interview-ready part of
  this whole project.
- **Deployment went from "one Vercel app" to "three containers".** Hence
  `docker-compose.yml`.

---

## 3. Engineering concepts from first principles

### 3.1 System prompt vs. envelope

Two different things occupy two different slots in every call, and conflating them is
a common mistake.

The **system prompt** is the persona: who this agent is, what it notices first, what
it counts as evidence, what vocabulary it must avoid, what moves it may make in a
turn. It is identical on every call and goes into Gemini's `systemInstruction`
channel (`SystemMessage` in LangChain terms).

It is assembled from two files, and the split is load-bearing:

| file | holds | length |
| --- | --- | --- |
| `prompts/<agent>.md` | the **lens** — worldview, what this mind notices, what it accepts as evidence, what it values, its blind spot, what it may never assume, its own voice | ~3.5KB each |
| `prompts/_house.md` | the **house style** — hypothesis vs fact, turn shape, questions, challenging another mind, safety, banned phrasings | ~7KB, one copy |

`registry.compose_prompt` joins them, lens first, and substitutes `__ALL_NAMES__`
from `AGENT_NAMES` so the roster sentence cannot go stale when a mind is added.

This used to be one self-contained file per agent, which had two costs. The house
rules existed in triplicate, so every edit had to be made three times or silently
drift. And each prompt was long enough that the model began dropping rules —
measured repeatedly: sharpening one behaviour would quietly break another that had
been holding, because instructions were competing for the same finite attention.
One shared copy is both the maintenance fix and what keeps each mind's own section
short enough to carry weight. Adding a fourth mind is now a lens file plus an entry
in `AGENT_NAMES`.

The **envelope** is everything wrapped around the conversation in the *user* slot, and
it is rebuilt on every single turn:

```
Here is the conversation so far:

User: I've been at my job six years…

The Gardener: who else is affected by this?

You are The Behaviorist. You have just heard all of this.

<rhythm note — one line, chosen from the transcript state>

A single sentence is a complete turn. So is a question, or agreeing in four
words. Take a full paragraph only when you have a case nobody here has made
yet — and then make it properly.

Say what you would actually say next.
```

**The code that assembles it** — `backend/app/llm.py` and `backend/app/agents/registry.py`
(docstrings elided; the inline comments are the originals):

```python
def build_messages(
    agent: AgentConfig, transcript: list[ChatMessage]
) -> list[SystemMessage | HumanMessage]:
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


def render_transcript(transcript: list[ChatMessage]) -> str:
    """Render the visible transcript as plain-text conversation history."""
    lines = []
    for m in transcript:
        speaker = "User" if m.role == "user" else AGENT_NAMES[m.role]
        lines.append(f"{speaker}: {m.content}")
    return "\n\n".join(lines)
```

Three things to notice in that assembly. The persona goes in a `SystemMessage` and
everything situational goes in the `HumanMessage` — the split from the paragraphs
above, made concrete. The whole conversation is rendered as **flat text inside one
message**, not as a list of alternating message objects (§2.5 explains why that was
kept rather than "improved"). And `rhythm_note(...)` is interpolated *between* the
transcript and the fixed two-sided permission, so the only part that varies turn to
turn sits in one clearly bounded place.

Why the split matters: the persona is *stable identity*, the envelope is *current
situation*. Anything that varies turn to turn belongs in the envelope, and anything
constant belongs in the system prompt. Putting situational instructions in the system
prompt is how you end up with a prompt that says "vary your length" — which, as §4.3
shows, produces uniformity at a new average rather than variation.

The envelope is **pinned by a test** (`test_prompt_envelope_is_pinned`) that asserts
the exact assembled string, character for character. That is unusual and deliberate:
the envelope measurably changes model behaviour, two earlier versions were measured
and both failed, so an undeliberate edit needs to fail loudly. The prompts themselves
are explicitly *not* hash-pinned — they are meant to be edited — but the tests check
they load whole, start with the right line, and still contain their safety carve-outs.

### 3.2 What LangChain is actually doing here

Worth being precise, because "we used LangChain" invites a follow-up.

**What it does:**
- `ChatGoogleGenerativeAI(...)` wraps the Google SDK behind a constructor whose
  parameters (`model`, `max_output_tokens`, `timeout`, `max_retries`) have the same
  names across providers.
- `await model.ainvoke([SystemMessage, HumanMessage])` — one async call, returning an
  object with `.text`.
- Raises **provider-agnostic exception classes** from `langchain_core`, which are the
  same classes the Anthropic and OpenAI integrations raise.

**What it is not doing:** no chains, no LCEL pipelines, no `AgentExecutor`, no tools,
no memory abstraction, no retrieval, no callbacks, no tracing. The transcript is
rendered by our own function; conversation state is our own SQLite table; turn order
is our own orchestrator.

**Versus raw API calls.** The raw `google-genai` SDK would be roughly the same number
of lines for the happy path. The difference is entirely in the swap story and in the
error surface. `llm.py` catches `ModelRateLimitError` rather than a Gemini-specific
class, so the day the model changes, `main.py` — which maps that to HTTP 429 — does not
change at all. That is the whole value proposition, and it is worth stating as a
narrow, defensible claim rather than as "we use LangChain for orchestration", which
would be false here.

The failure mode that justified it retroactively is §4.6.

### 3.3 Turn orchestration

"Orchestration" in multi-agent systems usually means one of three things:

1. **Model-chosen** — a router model decides who speaks next.
2. **Strict rotation** — A, B, C, A, B, C.
3. **Rule-based with randomness** — what this app does.

Option 1 was rejected because it costs a model call per turn (latency and quota) and
because a router would introduce a fourth opinion into a product whose entire premise
is three fixed ones. Option 2 was rejected because strict rotation reads as
mechanical; real group conversations have someone jumping back in.

The weighted-random draw, `pick_next_speaker` — this is the core of
`backend/app/orchestrator.py`, module docstring elided:

```python
def pick_next_speaker(
    last: AgentId | None,
    *,
    allow_same: bool = True,
    rng: random.Random | None = None,
) -> AgentId:
    """Who speaks next, given who spoke last (None when no agent has yet)."""
    r = rng or random
    others = [a for a in AGENT_IDS if a != last]
    if last is None:
        return r.choice(AGENT_IDS)
    if allow_same and r.random() < settings.double_turn_chance:
        return last
    return r.choice(others or [last])
```

The `double_turn_chance` is read from settings rather than hardcoded, which is what
lets `analytics.turn_taking` compare the observed rate against the configured one
rather than against a magic number. `last_agent_speaker` skipping user messages is why
a person can interject without resetting the rotation.

Here is the test that the `rng` parameter exists to make possible
(`backend/tests/test_parity.py`):

```python
def test_double_turn_rate_is_about_one_in_four():
    rng = random.Random(1234)
    n = 20_000
    repeats = sum(pick_next_speaker("gardener", rng=rng) == "gardener" for _ in range(n))
    assert 0.23 < repeats / n < 0.27


def test_non_repeat_turns_are_split_evenly_between_the_other_two():
    rng = random.Random(99)
    counts = {"introspector": 0, "behaviorist": 0}
    for _ in range(20_000):
        pick = pick_next_speaker("gardener", rng=rng)
        if pick != "gardener":
            counts[pick] += 1
    lo, hi = sorted(counts.values())
    assert hi / lo < 1.06, f"uneven split: {counts}"
```

Three properties fall out and all three are tested: any agent can open; the repeat
rate is ~25%; and when it does not repeat, the other two split evenly. `rng` is
injectable so the tests are deterministic — a small design detail with a large payoff,
because "test a random function" otherwise means either flakiness or monkeypatching
the global module.

**`allow_same` — two different requests that happen to run the same code.** When the
person replies with text, the room carries on, and whoever is mid-thought may well
keep it — that is the wanted double turn. When the person presses *hear another mind*,
they have asked for someone else in those words, and letting the draw return the same
agent one time in four breaks the only promise the button makes. This was a real
observed bug: The Introspector answered, was asked for another mind, and answered
again, with nothing in the UI explaining why. `allow_same=False` is what the button
passes; an ordinary reply passes `True`.

**Summoning — asking for a mind by name.** Reported from testing: *"when I want a
particular opinion of one agent I even call them explicitly, but randomly anyone was
coming."* The draw was ignoring the one thing the person had said unambiguously.
`summoned()` checks the person's own most recent message for a name (`"Introspector"`,
`"the gardener"`, either case, either form) and `choose_speaker()` is the entry point
every client should call — the summons wins outright, otherwise it falls through to
the ordinary weighted draw:

```python
def summoned(transcript: list[ChatMessage]) -> AgentId | None:
    """The mind the person asked for by name, or None if they asked for no one."""
    if not transcript:
        return None
    last = transcript[-1]
    if last.role != "user":
        return None
    named = [a for a, pattern in _SUMMONS.items() if pattern.search(last.content)]
    return named[0] if len(named) == 1 else None


def choose_speaker(
    transcript: list[ChatMessage], *, allow_same: bool = True, rng=None,
) -> AgentId:
    return summoned(transcript) or pick_next_speaker(
        last_agent_speaker(transcript), allow_same=allow_same, rng=rng
    )
```

Four rules, each closing a specific failure mode rather than being a general
guess:

- **Only the last message, and only if the person sent it.** Once the named mind
  answers, the summons is served. If an *older* mention still counted, *hear another
  mind* would re-elect the same mind forever, because the name never leaves the
  transcript.
- **Only the person can summon.** The agents refer to each other by name constantly —
  the house style requires it — so reading a summons out of an agent's own turn would
  hand the floor to whoever it mentioned last and collapse the whole draw into
  ping-pong.
- **Naming two minds is a topic, not a request.** *"The Gardener and the Behaviorist
  are both missing something"* falls through to the ordinary draw; picking one of the
  two named minds arbitrarily would look deliberate and be wrong.
- **A summons on the mind that just spoke beats `allow_same=False`.** Naming the mind
  that just answered is a request for more from it, not the mistake `allow_same=False`
  exists to correct.

`choose_speaker` is what both HTTP routes call (`/agent/next-speaker` and
`/agent/turn`), so both UIs get summoning for free without either one knowing the rule
exists — the same "single source of truth, multiple callers" shape §2.4 already
established. One asymmetry worth knowing: `seed_corpus.py` calls `pick_next_speaker`
directly rather than `choose_speaker`, because the corpus it generates has no person
typing a name into it — summoning is a UI-facing feature with nothing to attach to in
a script that writes both sides of the conversation.

The important architectural point is not the algorithm. It is that `choose_speaker`
(built on `pick_next_speaker`) is the **single source of truth** for who speaks next,
consumed by every real caller — the Next.js app via the proxy, the Streamlit app via
HTTP — and audited independently by `analytics.turn_taking`.

### 3.4 The rhythm note: state-conditioned prompting

`llm.rhythm_note()` is the most conceptually interesting function in the codebase, and
it exists because of a measured failure (§4.3 and §5.4).

The problem: a fixed instruction produces a fixed length, whichever length it names.
The insight: **a conversation is not uniform, so the prompt cannot be uniform either.**
Rather than naming a length, name the *situation* and let length follow from it.

Four situations, checked in order:

| Situation | The line inserted |
|---|---|
| You spoke last, nobody has answered | "Do not restate it… silence is better than padding." |
| Your own last turn ran > 60 words | "Your last turn ran to about 94 words — you have already made that case." |
| Another agent just spoke | "The Gardener just spoke. You can answer them directly — a line is enough, and disagreeing in four words is a real turn." |
| The person just spoke (or it's the opening) | "You can answer with a single question if that is what you actually have." |

**The code** (`backend/app/llm.py`, docstring elided — it is quoted in §4.3 and §5.4;
the inline comments are the originals):

```python
# A turn longer than this counts as "you have already made your case", and the
# next turn by the same agent is nudged toward a reaction instead.
MADE_THE_CASE_WORDS = 60


def rhythm_note(agent: AgentConfig, transcript: list[ChatMessage]) -> str:
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
```

Read the branch order as a priority list, because that is what it is: holding the floor
is checked *before* "your last turn was long", so an agent speaking twice in a row gets
the do-not-restate line rather than the shorten line. Note also that the second branch
interpolates the **actual measured word count** — `f"about {spoken} words"` — rather
than saying "your last turn was long". Naming the real number is what makes the nudge
concrete enough for the model to act on, and it is the only place in the envelope where
a computed value from the transcript reaches the prompt.

Two design properties to be able to defend:

**It is deterministic on purpose.** Randomising the note would produce spread without
meaning — variance uncorrelated with the conversation. The goal is *responsive*
variance: the note differs because the situation differs, so the lengths differ for a
reason a reader can feel.

**The two-sided permission is separate from the note and appears in every envelope.**
"A single sentence is a complete turn… Take a full paragraph only when you have a case
nobody here has made yet." Naming only one end of the range is what produced a hard
ceiling in every earlier version — say "be brief" and you get uniform brevity; say
nothing and you get uniform essays. `test_envelope_legitimises_both_ends` asserts both
sentences survive in all four situations.

This is a transferable idea worth naming in an interview: **condition the prompt on
observable state rather than instructing a rate.** Models average a stated frequency
across every generation, because each generation is independent and has no memory of
the others; they cannot "do this 40% of the time" — but they can respond to a fact
about the input.

### 3.5 What a divergence / classifier analysis is, and why cross-validation matters

The premise "these three agents are distinct" is an empirical claim about text. The way
to test it is to ask whether the authorship is *recoverable*: if a model can read a
turn with the labels hidden and reliably name the author, the voices carry real signal.
If it cannot do better than guessing, they do not — regardless of how they read.

The pipeline is deliberately simple, and simplicity is a feature:

1. **TF-IDF vectoriser**, unigrams and bigrams, `min_df=2`, `sublinear_tf=True`.
   Turns text into a sparse numeric vector where each dimension is a term, weighted up
   for being frequent in this turn and down for being common across all turns.
2. **Logistic regression**, `class_weight="balanced"`. A linear model — chosen so the
   result is interpretable and so it cannot memorise a small corpus the way a deep
   model would.
3. **`StratifiedKFold` + `cross_val_predict`**, 5 folds (auto-reduced for small
   corpora).

**The code** (`backend/app/analytics.py`, docstrings elided, comments original):

```python
# Below this, the numbers are noise dressed up as findings.
MIN_TURNS_PER_AGENT = 8
MAX_FOLDS = 5


def _vectorizer() -> TfidfVectorizer:
    # Stop words are deliberately KEPT. Function words ("you", "what", "would")
    # are among the strongest authorship signals there are, and the agents'
    # differences are as much in how they address someone as in what they name.
    return TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),
        min_df=2,
        sublinear_tf=True,
    )


def separability(turns: pd.DataFrame) -> dict:
    counts = turns["agent"].value_counts()
    if len(counts) < 2 or counts.min() < MIN_TURNS_PER_AGENT:
        return {
            "available": False,
            "reason": (
                f"needs at least {MIN_TURNS_PER_AGENT} turns per agent; "
                f"smallest class has {int(counts.min()) if len(counts) else 0}"
            ),
        }

    X = turns["content"].tolist()
    y = turns["agent"].to_numpy()
    folds = int(min(MAX_FOLDS, counts.min()))

    model = make_pipeline(
        _vectorizer(),
        LogisticRegression(max_iter=2000, class_weight="balanced"),
    )
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=0)
    predicted = cross_val_predict(model, X, y, cv=cv)

    labels = sorted(counts.index)
    cm = confusion_matrix(y, predicted, labels=labels)
    accuracy = float((predicted == y).mean())
    chance = 1.0 / len(labels)

    # Which pair blurs together most — the actionable part.
    worst_pair, worst_count = None, 0
    for i, a in enumerate(labels):
        for j, b in enumerate(labels):
            if i != j and cm[i][j] > worst_count:
                worst_count, worst_pair = cm[i][j], f"{a} mistaken for {b}"

    return {
        "available": True,
        "accuracy": round(accuracy, 3),
        "chance": round(chance, 3),
        "lift_over_chance": round(accuracy - chance, 3),
        "confusion_matrix": cm.tolist(),
        "most_confused": worst_pair,
        "verdict": (
            "distinct" if accuracy >= chance + 0.30
            else "weak" if accuracy >= chance + 0.15
            else "not distinguishable"
        ),
    }
```

Four details worth being able to point at. `make_pipeline` puts the vectoriser
**inside** the cross-validated estimator, which is not cosmetic: fitting TF-IDF on the
whole corpus before splitting would leak information from the test fold into the
training vocabulary and inflate the score. `folds = min(MAX_FOLDS, counts.min())`
degrades gracefully rather than crashing on a small corpus. `chance` is computed from
the number of labels rather than hardcoded to 0.33, so the metric still means something
if a fourth agent is ever added. And the verdict thresholds are explicit constants in
the return value — the report never makes the reader decide whether +0.42 is good.

**Why cross-validation is the load-bearing part.** If you train on all 77 turns and
score on those same 77 turns, you measure memorisation, not distinctiveness. A model
with enough capacity scores 100% on any labelled set including randomly labelled
noise. Cross-validation splits the data into k folds, trains on k−1 and predicts the
held-out one, rotating until every turn has been predicted by a model that never saw
it. The score is therefore a claim about *unseen* turns, which is the claim you
actually want. "Stratified" means each fold keeps the same class proportions, so no
fold accidentally contains almost no Gardener turns.

**Why the confusion matrix matters as much as the number.** Accuracy is one number for
three agents; the matrix is the 3×3 grid of "who actually spoke" against "who the
classifier guessed". The diagonal is correct predictions; off-diagonal cells name
*which pair blurs together*. Currently the largest off-diagonal is **behaviorist
mistaken for introspector, 5 times** — which is directly actionable: if the two need
separating, that is the pair whose prompts to edit.

**Name masking is an ablation.** The prompts tell agents to refer to each other by
name, which hands the classifier a shortcut — "mentions The Introspector" is decent
evidence the speaker is *not* the Introspector. That would inflate the score without
the voices being any more distinct. So the report runs the same analysis twice, once
with `\b(the\s+)?(introspector|behaviorist|gardener)\b` replaced by "someone". If
accuracy survives, recognition is coming from *how they speak*. Currently: **0.753
intact, 0.740 masked — a drop of 0.013.** The voices are not propped up by
name-dropping. That is an ablation study, and calling it that is worth doing.

The masking itself is four lines, and the report simply runs the metric twice:

```python
def mask_agent_names(turns: pd.DataFrame) -> pd.DataFrame:
    masked = turns.copy()
    masked["content"] = masked["content"].str.replace(
        r"\b(the\s+)?(introspector|behaviorist|gardener)\b",
        "someone",
        regex=True,
        case=False,
    )
    return masked

# ...in divergence_report():
"separability": separability(known),
# The same check with every agent name removed, so the score cannot be
# propped up by who the speaker name-drops.
"separability_names_masked": separability(mask_agent_names(known)),
```

### 3.6 Coefficient of variation

Standard deviation answers "how spread out are these numbers?" but its units are the
same as the data, which makes it incomparable across sets with different means. A
standard deviation of 20 words is enormous for turns averaging 22 words and modest for
turns averaging 96.

**Coefficient of variation = standard deviation ÷ mean.** Unitless. Comparable across
corpora of different average length. That is exactly what was needed here, because the
whole point was comparing a corpus of essays against a corpus of one-liners.

Why it mattered for the rhythm problem: the failure mode was never "turns are too
long" or "turns are too short" — it was **"turns are all the same length"**. Two sets
of turns can share a mean and feel nothing alike:

- `61, 66, 67, 67, 65, 64` → cv ≈ 0.04. Six identical paragraphs.
- `4, 130, 8, 150, 5, 90` → cv ≈ 1.04. A conversation.

Both average ~65 words. Any metric based on the mean says they are the same. The cv
says they are opposites. Both of those cases are pinned as tests
(`test_uniform_turns_show_low_variation`, `test_varied_turns_show_high_variation_at_the_same_mean`),
which is what stops the metric from silently stopping working.

The rule of thumb encoded in `analytics.py`: below about 0.4, the turns are one length
wearing different words. The measured history is in §5.4.

**The code** — `chat_feel()` in `backend/app/analytics.py`, trimmed to the length
statistics (the engagement fields from §4.5 are cut here and shown there):

```python
# Under this, a turn is a reaction rather than a statement.
SHORT_TURN_WORDS = 15
# Over this, it is an essay.
LONG_TURN_WORDS = 100


def chat_feel(turns: pd.DataFrame) -> dict:
    if turns.empty:
        return {"available": False, "reason": "no generated turns with recorded text"}

    words = turns["word_count"].to_numpy(dtype=float)
    n = len(words)
    mean = float(words.mean())
    std = float(words.std(ddof=1)) if n > 1 else 0.0

    return {
        "available": True,
        "turns": int(n),
        "mean_words": round(mean, 1),
        "median_words": float(np.median(words)),
        "std_words": round(std, 1),
        # The uniformity number. Spread relative to size, so it is comparable
        # across corpora with different average lengths. Below ~0.4 the turns
        # are essentially one length wearing different words.
        "coefficient_of_variation": round(std / mean, 2) if mean else None,
        "min_words": int(words.min()),
        "max_words": int(words.max()),
        "short_turns": int((words < SHORT_TURN_WORDS).sum()),
        "short_share": round(float((words < SHORT_TURN_WORDS).mean()), 3),
        "long_turns": int((words > LONG_TURN_WORDS).sum()),
        "long_share": round(float((words > LONG_TURN_WORDS).mean()), 3),
        "thresholds": {"short_under": SHORT_TURN_WORDS, "long_over": LONG_TURN_WORDS},
    }
```

`ddof=1` is the sample standard deviation rather than the population one — the corpus
is a sample of what the agents *would* say, not the entire population of their possible
turns. `if mean else None` guards a division by zero that cannot currently happen but
would return `inf` into a JSON response if it ever did. And `short_share` / `long_share`
are reported next to the cv on purpose: the cv says *how much* spread there is, and the
two shares say *where* it sits, which is the difference between "varied" and "bimodal".

Here are the two tests that pin it — they are the 61/66/67 and 4/130/8 cases from above,
turned into a regression guard:

```python
def test_uniform_turns_show_low_variation():
    """The 61/66/67/67 case: same mean as a varied set, completely different feel."""
    for i, n in enumerate([61, 66, 67, 67, 65, 64]):
        gen("behaviorist", words(n), conversation=f"c{i}")
    r = analytics.chat_feel(analytics.generated_turns())
    assert r["coefficient_of_variation"] < 0.1, r
    assert r["short_share"] == 0.0
    assert r["long_share"] == 0.0


def test_varied_turns_show_high_variation_at_the_same_mean():
    """Same average as above, but swinging — the metric must separate them."""
    for i, n in enumerate([4, 130, 8, 150, 5, 90]):
        gen("behaviorist", words(n), conversation=f"c{i}")
    r = analytics.chat_feel(analytics.generated_turns())
    assert r["coefficient_of_variation"] > 0.7, r
    assert r["short_share"] > 0.4
    assert r["long_share"] > 0.3
```

### 3.7 Standard error, and refusing to answer

`turn_taking` compares the observed repeat rate against the configured 0.25. The
standard error of a proportion is `sqrt(p(1−p)/n)` — how much a sample proportion
would bounce around by chance alone at that sample size. With n=61 that is about
0.055, so an observed 0.23 sits comfortably within two standard errors of 0.25.

The more interesting part is the refusal. Below `MIN_TRANSITIONS = 20`, the report
sets `sufficient_data: false`. With, say, 11 transitions the interval around 25% is
wider than 25%, so even a corpus with **zero** repeats sits "within 2 SE" — the check
passes because it *cannot fail*, not because the rule is being followed. A test pins
exactly that case. The same instinct governs separability, which refuses outright
below `MIN_TURNS_PER_AGENT = 8`.

**The general lesson: a metric that cannot fail is worse than no metric, because it
produces confidence.** Being able to say that sentence is worth more in an interview
than the formula.

### 3.8 Idempotency, append-only, and WAL

Three storage ideas worth being able to explain:

**Idempotent writes.** The client mirrors its entire transcript on every change, so
`PUT /conversations/{id}` is called constantly. It deletes all messages for that
conversation and re-inserts them. That looks wasteful and is: the payoff is that a
retry, a duplicate, or an out-of-order save produces the *same* end state. An append
API would need de-duplication and ordering logic; full replace needs neither.

**Append-only telemetry.** `generations` is never rewritten, so it survives the
full-replace above. It stamps the **model** on every row, and — since this was found
to be insufficient on its own — the **build** too: a short fingerprint of the source
that produced the turn (`app/build.py`, §4.3 and §4.4). Model alone cannot say which
revision of the *prompts* a row came from, and the prompts are the product; without
`build`, every prompt edit ever shipped pools into one number and "did the change
work" cannot be answered from stored data — it has to be answered by spending fresh
API quota on a new run, every single time. `build` is nullable and migrated the same
way `text` was: a row written before the column existed keeps `NULL` rather than being
guessed into a bucket it cannot be shown to belong to.

**WAL mode.** Write-Ahead Logging, set once at init. In the default journal mode a
writer blocks readers. In WAL, readers read the main file while the writer appends to a
log — so hitting `/analytics/divergence` (which scans every turn) does not block a turn
being recorded. A connection is opened per operation rather than shared, because FastAPI
runs sync endpoints in a threadpool and a `sqlite3` connection is not thread-safe.
`PRAGMA foreign_keys = ON` is set per connection, because SQLite defaults it *off* and
the messages cascade depends on it.

### 3.9 Behavioural detectors: testing reasoning, not vocabulary

Two prompt rules needed a way to say whether the model was actually obeying them —
"an abstract question is a real question" (don't secretly convert it into a question
about the person) and "a lens, not an instruction" (don't let a suggestion harden into
an order). Neither is a phrase to ban. Both are a *stance toward a claim*, and the same
words can be on either side of it:

```
"You already know you want to leave."                          — asserted
"I wonder if you already know you want to leave."               — proposed
```

Banning "you already know" would have caught neither correctly: it fires on the second
line just as hard as the first, when the second is the one the prompt is *asking for*.
`backend/app/epistemics.py` looks for the CLAIM pattern, then checks whether an
EPISTEMIC MARKER governs it — "I wonder", "might", "one reading is", a trailing
question mark. Flagged only when the claim appears with no marker attached.

This generalises past mind-reading. `personalises_the_question` catches a mind
substituting an invented personal question for the abstract one actually asked
("when people ask that, they're usually…") unless it is offered as an explicit branch
("if you're asking because…"). `prescribes` catches a suggestion that hardened into an
order ("tell them no, that's the only way") unless it is offered as an experiment
("you could try declining, and see what happens") or the sentence is *quoting* a claim
in order to challenge it.

**Every regression test in this file is a matched pair on the same words** — a bad
line and a good line built from the same underlying claim — so a test cannot be
satisfied by deleting a phrase from the prompt; it has to be satisfied by the model
actually distinguishing assertion from proposal. `test_this_is_not_a_phrase_ban`
enforces the pairing mechanically: every "banned-sounding" phrase is asserted to also
appear on the *passing* side of some pair.

**Three bugs found by reading transcripts, not by the tests passing:**

1. **Gemini writes curly apostrophes (`’`); the patterns were written with straight
   ones (`'`).** `You're afraid that…` matched; `You’re afraid that…` did not — silently
   clearing exactly the sentences the detector existed to catch. The metric read 0%
   while the failure was sitting in the transcript. Fixed by normalising apostrophes
   before matching, and pinned with a test built from the literal offending sentence.
2. **A banned word swapped for a synonym slipped through.** The prompt bans "he
   deserves"; a live turn wrote "he has a right to know" — same entitlement claim,
   different words, and the metric improved while nothing had changed. There is no
   general fix for this class of bug; the fix is to keep reading transcripts and keep
   adding the synonym when it shows up, which is why the test file's bad examples are
   pulled from real output rather than invented.
3. **Attribution-order laundering.** "The claim that you need to tell him, rather than
   *assuming* the marriage is felt the same way…" contains the word "assuming"
   *after* the claim it was supposed to excuse, and a position-blind check cleared it.
   `_earliest()` now requires the attribution word to appear *before* what it governs,
   or the claim still counts.

The general lesson, stated once so it does not have to be relearned: **a detector that
reports a clean number is not evidence of correctness until someone has tried to read
past it.** Every one of the three bugs above shipped with tests that passed. What
caught them was reading the actual generated transcript and noticing a sentence the
number said should not be there.

---

## 4. Real bugs and what they taught

Each entry: what broke, why it broke, and the general lesson. These are the strongest
interview stories in the project because each one has a mechanism, not just a symptom.

### 4.1 The zombie uvicorn process

**What broke.** After stopping the dev servers, port 8000 stayed occupied. Worse than
occupied: something was still *answering* on it — and answering with the code it had
started with. The symptom presented as **"my changes aren't taking effect"**, which is
the worst possible symptom because it sends you to look at your code instead of at
your process table.

**Why.** Three mechanisms stacked:

1. **Windows does not kill descendants.** Killing a process leaves its children
   running, reparented to nothing. Every wrapper layer (`npm` → `npx` → `next`) is a
   place a server can be orphaned behind.
2. **uvicorn `--reload` runs the app in a child process.** Its command line is
   `python -c "from multiprocessing.spawn import spawn_main..."` — which is why
   searching the process list for "uvicorn" finds nothing.
3. **The socket handle is inherited.** Windows keeps the LISTENING entry under the PID
   that *created* the socket even after that process dies, when a child inherited the
   handle. So `Get-NetTCPConnection` names a PID that no longer exists. Killing it does
   nothing; there is nothing there.

**The fix** is `scripts/proc.mjs`, and the shape of it is the interesting part. It does
not ask "which process is uvicorn". It asks two questions:

- *What is holding this port, and is that owner still alive?* A **dead** owner is not
  "unknown, leave it alone" — it is the clearest possible evidence of an orphan.
- *Which live processes matching our patterns have a parent that no longer exists?*
  That is `orphans()`, and it is what actually finds the `spawn_main` child holding the
  inherited handle.

Two more details worth mentioning: `freePorts` loops up to six times, because Windows
lets several processes bind the same port when none requested exclusive use — killing
one reveals the next, so a single pass can report success while the port is still
taken. And an `OURS` regex guards everything: an unrelated program on port 3000
produces a refusal that names it, never a kill.

**The code** — `scripts/proc.mjs`, the loop that ties all of that together:

```js
// Only processes matching this are ever killed automatically. Something else
// listening on port 3000 is the user's business, not ours.
export const OURS = /next|uvicorn|spawn_main|streamlit|multiprocessing|py\.mjs|dev\.mjs/i;

export function freePorts(ports, { onKill, onForeign, passes = 6 } = {}) {
  for (let attempt = 1; attempt <= passes; attempt++) {
    const found = listeners(ports);
    if (found.length === 0) return true;

    // Only a LIVE owner can be judged foreign. A dead one is an orphan.
    const foreign = found.filter((f) => f.alive && !OURS.test(f.cmd));
    if (foreign.length) {
      if (onForeign) onForeign(foreign);
      return false;
    }

    for (const f of found.filter((x) => x.alive)) {
      onKill?.({ kind: "listener", pid: f.pid, port: f.port, cmd: f.cmd, attempt });
      killTree(f.pid);
    }

    // A dead owner means a surviving child holds the inherited handle, so the
    // PID on the row cannot be killed — find the child instead.
    if (found.some((f) => !f.alive)) {
      for (const s of orphans()) {
        onKill?.({ kind: "orphan", pid: s.pid, cmd: s.cmd, attempt });
        killTree(s.pid);
      }
    }

    sleepSync(500);
  }
  return listeners(ports).length === 0;
}
```

The whole three-mechanism story above is visible in that one function: `f.alive` is
mechanism 3, the `orphans()` branch is mechanism 2, and the retry loop is the
several-processes-one-port behaviour. `onKill` / `onForeign` are callbacks rather than
`console.log` calls because the supervisor and the watchdog want different behaviour on
a foreign process — the supervisor refuses to start and says why, the watchdog runs
unattended and simply leaves it alone.

`listeners()` is where "is the owner alive?" is actually answered — it shells out to
PowerShell and builds the rows the loop above consumes:

```js
  const script = [
    `$ports = @(${ports.join(",")})`,
    `Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |`,
    `  Where-Object { $ports -contains $_.LocalPort } |`,
    `  ForEach-Object {`,
    `    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)" -ErrorAction SilentlyContinue`,
    `    [PSCustomObject]@{`,
    `      port  = $_.LocalPort`,
    `      owner = $_.OwningProcess`,
    `      alive = [bool]$proc`,
    `      cmd   = if ($proc) { "$($proc.Name) $($proc.CommandLine)" } else { "" }`,
    `    }`,
    `  } | ConvertTo-Json -Compress`,
  ].join("\n");
```

`alive = [bool]$proc` is the whole trick: `Get-NetTCPConnection` gives the owning PID,
and a second lookup asks whether a process with that PID still exists. When it does not,
the socket is held by a child that inherited the handle — mechanism 3 from above, turned
into a boolean.

And `orphans()` searches for the process the LISTENING row cannot name — matching on
the command line, not the executable, because the culprit is `python.exe` running
`multiprocessing.spawn`:

```js
  const script = [
    `$all = Get-CimInstance Win32_Process`,
    `$live = @{}`,
    `foreach ($p in $all) { $live[[int]$p.ProcessId] = $true }`,
    `$all | Where-Object {`,
    `  $_.CommandLine -and`,
    `  $_.CommandLine -match 'uvicorn|spawn_main|multiprocessing|next|streamlit' -and`,
    `  -not $live.ContainsKey([int]$_.ParentProcessId)`,
    `} | ForEach-Object {`,
    `  [PSCustomObject]@{ opid = $_.ProcessId; cmd = "$($_.Name) $($_.CommandLine)" }`,
    `} | ConvertTo-Json -Compress`,
  ].join("\n");
```

The `$live` hashtable is built once and then used as a set — "is my parent still in the
process table?" — which is how a parentless process is identified without a race against
PIDs being recycled mid-scan.

**General lesson.** *When a stale process serves stale code, the bug looks like a code
bug.* Debug the running system, not the source. And when you clean something up
automatically, **say so loudly** — `dev.mjs` prints *"the previous session did not shut
down cleanly"* precisely because a leak quietly tidied away on the next start is how a
broken shutdown goes unnoticed for days.

### 4.2 The Ctrl+C signal-inheritance bug

**What broke.** The shutdown handler ran. It printed "stopping both processes". It
killed nothing. It exited looking clean.

**Why.** On Windows, Ctrl+C delivers `CTRL_C_EVENT` to **every process attached to the
console**. The supervisor's SIGINT handler spawns `taskkill` — and `taskkill`, being a
child attached to the same console, receives `CTRL_C_EVENT` too, and dies before it
does anything. The killer is killed by the same signal that triggered it.

This is the subtle part and the reason this is a good story: **cleanup that runs inside
the dying process is not dependable.** The usual mental model — "I'll clean up in my
signal handler" — has an assumption in it (that the handler's own children survive long
enough to act) that is false on Windows.

**The fix** is two-layered:

1. `killTree` spawns `taskkill` with `detached: true`, putting it in its own process
   group, out of reach of the console event.
2. `scripts/dev-reaper.mjs` — a watchdog spawned **detached and console-less** at
   startup, which polls `process.kill(parent, 0)` every 400ms. When the supervisor
   disappears — Ctrl+C, force-kill, closed terminal, crash — the reaper cleans up. It
   ignores SIGINT/SIGTERM/SIGHUP explicitly, because dying alongside the thing it
   exists to outlive would defeat the point.

**The code, layer 1** — `killTree` in `scripts/proc.mjs`. The comment is the bug report:

```js
/**
 * `detached` is load-bearing on Windows, not tidiness. Ctrl+C delivers
 * CTRL_C_EVENT to every process attached to the console, so a `taskkill`
 * spawned normally from a SIGINT handler receives it too and dies before it
 * kills anything. Detaching puts it in its own process group, out of reach of
 * the event that is killing us.
 */
export function killTree(pid, { quiet = false } = {}) {
  if (!pid) return true;
  try {
    if (IS_WIN) {
      const r = spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], {
        detached: true,
        windowsHide: true,
        encoding: "utf8",
      });
      if (r.error) throw r.error;
      // 128 = "no such process": already gone, which is the outcome we wanted.
      if (r.status !== 0 && r.status !== 128 && !quiet) {
        const why = (r.stderr || r.stdout || "").trim();
        if (why && !/not found|could not be found/i.test(why)) {
          console.error(`  ! taskkill ${pid}: ${why.split(/\r?\n/)[0]}`);
        }
      }
    } else {
      try {
        process.kill(-pid, "SIGKILL");
      } catch {
        process.kill(pid, "SIGKILL");
      }
    }
  } catch (err) {
    if (!quiet) console.error(`  ! could not kill ${pid}: ${err.message}`);
    return false;
  }
  return true;
}
```

`/T` is the tree kill and `/F` is force; `detached: true` is the actual fix. On POSIX
the equivalent is `process.kill(-pid, ...)` — the negative pid signals the whole process
*group*, which is why `dev.mjs` spawns children with `detached: !IS_WIN` there.

**The code, layer 2** — `scripts/dev-reaper.mjs`, the whole watchdog loop:

```js
function alive(pid) {
  try {
    // Signal 0 tests for existence without touching the process.
    process.kill(pid, 0);
    return true;
  } catch (err) {
    // EPERM means it exists but belongs to someone else — still alive.
    return err.code === "EPERM";
  }
}

function reap() {
  // Direct children first: the cheap case, and it takes their trees with them.
  for (const pid of children) killTree(pid, { quiet: true });
  // Then make the ports actually free, whatever is holding them now. Foreign
  // processes are left alone — this runs unattended, so it never guesses.
  if (ports.length) freePorts(ports, { passes: 8 });
}

const timer = setInterval(() => {
  if (!alive(parent)) {
    reap();
    clearInterval(timer);
    process.exit(0);
  }
  if (Date.now() - startedAt > MAX_MS) {
    clearInterval(timer);
    process.exit(0);
  }
}, POLL_MS);

// The supervisor kills this process on a clean shutdown; ignoring console
// signals keeps it from dying alongside the thing it exists to outlive.
process.on("SIGINT", () => {});
process.on("SIGTERM", () => {});
process.on("SIGHUP", () => {});
```

`process.kill(pid, 0)` is the idiom to know: signal 0 performs the permission-and-
existence check without delivering anything. The three no-op signal handlers at the
bottom are the other half of the fix — a watchdog that dies on Ctrl+C is not a watchdog.

And the spawn side, in `scripts/dev.mjs`:

```js
reaper = spawn(
  process.execPath,
  [
    join(ROOT, "scripts", "dev-reaper.mjs"),
    "--parent",
    String(process.pid),
    "--children",
    children.map((ch) => ch.pid).filter(Boolean).join(","),
    "--ports",
    PORTS.join(","),
  ],
  { detached: true, stdio: "ignore", windowsHide: true },
);
// Never hold the event loop open on its account.
reaper.unref();
```

`stdio: "ignore"` plus `detached` is what gives it no console to receive `CTRL_C_EVENT`
on, and `unref()` stops it keeping the supervisor's event loop alive.

Note what the reaper guarantees: **ports, not pids**. A dying supervisor orphans
grandchildren that no longer belong to any tree you could walk, so killing recorded
child pids can reach nothing while a grandchild still holds the socket. The ports are
the thing that actually needs to end up free — which is exactly why `reap()` above calls
`killTree` on the recorded children *and then* `freePorts` on the ports regardless.

The port logic lives in `proc.mjs`, shared by supervisor and watchdog, so the two
cannot drift apart — the same single-source-of-truth argument as the orchestrator, at a
smaller scale.

**General lesson.** *Cleanup code must survive the event that triggers it.* Ask, for
any teardown path: "what kills this, and does that same thing kill my cleanup?"

### 4.3 Prompt-length and rule saturation

**What broke.** Every turn was an essay. Measured: **95.7 mean words, 48% of turns over
100 words, 1.3% under 15.** The transcripts were individually good and collectively
unreadable — nothing in them read like people talking.

**Why the obvious fixes failed.** Three separate attempts to instruct length —
`"2-4 sentences"`, `"length varies naturally"`, `"at least half should be short"` —
each produced **uniform output at whatever the new target was**. The mechanism: each
generation is independent. The model has no memory of its other turns, so it cannot
implement a *rate*; asked to be short half the time, every individual turn resolves the
instruction the same way. Asking for variation across generations from inside a single
generation is asking for something the architecture cannot deliver.

Then the correction overshot. Replacing the envelope with *"say the one thing you would
say next"* produced **21.9 mean words, 0% over 40 words, 81% inside a single 15–40 word
band** — and its coefficient of variation was *lower* than the essay version (0.39 vs
0.53). Both versions were uniform. The second was simply uniform somewhere else.

**The related failure is rule saturation.** These prompts carry a lot of rules — a
turn repertoire, vocabulary bans, an anti-aphorism rule, an anti-point-counterpoint
rule, an address-the-person rule. Adding more rules to fix a behaviour has diminishing
and then *negative* returns: past some density the model satisfies the most recent or
most concrete constraints and lets earlier ones slip. The essay problem was not
fixable by adding a length rule to a prompt that already had thirty rules.

**The fix** was to move the length signal out of the persona and into the
per-turn envelope (§3.4): stop instructing a rate, start describing a situation.
Result: cv from 0.39 → **0.65**, range from 3–34 words → 6–84 words, 20% short turns
and 15% over 40 words, with essays still eliminated. `test_prompt_rules.py` now guards
this — `FREQUENCY_PHRASES` is a list of banned phrasings, so putting `"at least half"`
back into a prompt fails the suite with an explanation of why.

**General lesson.** *An instruction that specifies a frequency will be applied at that
frequency to every individual sample — which means uniformly.* If you want variation
across generations, the variation must come from something that varies in the input.

### 4.4 The essay-length regression from a stale working tree

**What broke.** The length work was done, measured and confirmed. Then the essays came
back — same symptom as before the fix, on a codebase that (as far as the editor was
concerned) contained the fix.

**Why.** The code being executed was not the code on screen. A stale working tree meant
the prompt files on disk were an older revision than the ones that had been measured.
The measurement was real; the artefact under measurement had changed underneath it.

**A second, verified mechanism in the same family** — worth knowing because it is live
in this repo right now, and it is the mechanism most likely to bite next:

> `npm run dev:api` runs uvicorn with `--reload --reload-dir backend/app`. uvicorn's
> reloader filters watched files by `default_includes = ["*.py"]`. The system prompts
> are **`.md` files inside that directory** — so editing a prompt does **not** trigger
> a reload. Compounding it, `registry.agents()` is decorated `@lru_cache(maxsize=1)`,
> so prompts are read from disk exactly once per process. **An edited prompt is not in
> effect until the API process is restarted.** Nothing warns you; the server keeps
> answering, with the old persona.

(That is a fixable gap — `--reload-include '*.md'` on the `dev:api` script would close
it — and it is the single highest-value follow-up in this document.)

**General lesson, and it generalises past this project:** *a correct file on disk is
not evidence that the running process has it.* Before concluding that a change did not
work, verify that the change is loaded — restart, check a health endpoint, echo the
value, diff what is actually running. This is the same failure family as §4.1: the
zombie server serving old code, the reloader ignoring the file type, the stale
checkout. All three present as "my change had no effect", and all three are invisible
from inside the source.

### 4.5 The engagement metric was measuring the wrong thing

**What broke.** Nothing crashed. That is what makes it a good story. A metric reported
that the agents almost never engaged with each other — around **2%** of turns — and
the number was wrong.

**Why.** `addresses_another_agent_share` detects engagement by regex: does the turn name
one of the other two agents? That is literal and reliable, and it undercounts badly.
The observed exchange that exposed it:

> **Introspector:** "…the first thing you feel on a Tuesday morning…"
> **Gardener:** "Tuesday mornings happen to the people in the next cubicle too."

Unmistakable engagement. Zero names. Scores nothing. And the bias is systematic rather
than random: **short turns reference by content, long turns reference by name**, so
judging a terse conversation by name-callouts alone reads as silence — exactly at the
moment the rhythm work had made turns terse. The metric got *more* wrong precisely as
the product got better.

**The fix** is `_echo_share`: does a turn reuse a **distinctive** word from the previous
*different* agent's turn? Two design decisions inside it are the interesting part:

- **Distinctiveness is measured by document frequency in this corpus, not by a
  hand-written stopword list.** A list is guesswork that fails quietly — "matter" is
  six letters and unremarkable, and it counted as engagement until a test caught it.
  Document frequency has no such blind spot: whatever is common *here* is common, and
  is ignored, without anyone having to anticipate it in advance.
- **Only cross-agent pairs count**, so an agent repeating its own vocabulary never
  registers as engagement.

The measured difference: **2% by name against 48% by content** on the same corpus (60%
on the current one). Both numbers are still reported, and the code says explicitly that
the name-based one is *"a floor on engagement, not a measure of it"* — because whether
a turn responds without naming or echoing is not detectable this way at all. Naming a
metric's blind spot in the metric itself is the honest move.

**General lesson.** *A metric that is easy to compute is not the same as a metric that
measures the thing.* When a number contradicts what you can see in the data, the number
is a hypothesis too. And when you fix it, keep the old one alongside — the gap between
the two is itself information.

### 4.6 The rate limit that escaped as a JSON parse error

**What broke.** Hitting the free-tier quota produced, in the browser, this:
`Unexpected token 'I' ... is not valid JSON`.

**Why.** A four-layer chain:

1. `llm.py` caught `google.genai.errors.APIError`.
2. `langchain-google-genai` wraps provider errors in its *own* classes
   (`GoogleRateLimitError` and friends) which do **not** inherit from `APIError`.
3. So the rate limit escaped the handler, and FastAPI answers an unhandled exception
   with the plain-text body `"Internal Server Error"`.
4. Every client here parses errors with `res.json()`. `JSON.parse("Internal Server
   Error")` fails on the capital I.

The reader is told about a JSON parsing problem when the actual fact is "you are out of
quota for today".

**The fix, at three layers, deliberately redundant:**

- `llm.py` now catches LangChain's **provider-agnostic** `langchain_core` classes,
  which is both the correct fix and the one that keeps the swap-the-provider promise
  honest — those same classes are raised by the Anthropic and OpenAI integrations.
- `main.py` has a bare `except Exception` backstop with the comment *"Nothing may
  escape this handler"*, returning `{error: ...}` JSON with the traceback going to the
  log.
- `app/lib/backend.ts` parses the upstream body and, if it is not JSON, synthesises a
  JSON error — so the client's contract holds even if the backend breaks its own.

Rate limiting is now **429**, not 500, because it is temporary and the reader can act
on it.

**Layer 1** — `backend/app/llm.py`. Every provider failure is translated into a local
exception type, so nothing above this line knows which SDK is underneath:

```python
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


async def generate_turn(agent: AgentConfig, transcript: list[ChatMessage]) -> str:
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
```

The imports are the point of the whole fix: `ModelRateLimitError` and friends come from
`langchain_core.exceptions`, **not** from `langchain_google_genai` and not from
`google.genai`. `ClientError` and `APIError` are still caught underneath as a belt-and-
braces layer, because the raw SDK can surface directly through the wrapper. Note the
error *messages* are written for the reader, not for the log — "wait a moment, or try a
different model" is what actually reaches the browser.

**Layer 2** — `backend/app/main.py`. Local exception types map onto HTTP status codes,
and the final `except Exception` is the one that matters:

```python
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
```

A blanket `except Exception` is normally a smell. Here it is deliberate and the comment
says why: the cost of an escape is not a 500, it is a *misleading* 500 that destroys the
error message on the way out. The traceback is preserved via `log.exception`, so nothing
is actually swallowed.

**Layer 3** — `app/lib/backend.ts`. The proxy guarantees the client always receives
JSON, even if the backend breaks its own contract:

```ts
  const text = await upstream.text();

  // Everything past this point exists to guarantee ONE thing: the client always
  // receives JSON. It parses every response with res.json(), so a non-JSON body
  // reaches the reader as "Unexpected token 'I' ... is not valid JSON" and
  // hides whatever actually went wrong.
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    // Not JSON at all. FastAPI answers an unhandled exception with the plain
    // text "Internal Server Error"; a proxy or a crash can produce HTML.
    return Response.json(
      {
        error:
          upstream.status >= 500
            ? `The backend failed (HTTP ${upstream.status}). Check the api log for the traceback.`
            : text.slice(0, 300) || `Unexpected response (HTTP ${upstream.status})`,
      },
      { status: upstream.status },
    );
  }

  // The backend speaks { error } on failure, which is what the client already
  // expects — but FastAPI's own request validation answers with { detail }.
  // Normalise that one case so every error reaches the client the same shape.
  if (!upstream.ok) {
    const body = parsed as { error?: unknown; detail?: unknown } | null;
    if (body?.error === undefined && body?.detail !== undefined) {
      const detail = body.detail;
      const message =
        typeof detail === "string"
          ? detail
          : ((detail as { msg?: string }[] | undefined)?.[0]?.msg ?? "Invalid request");
      return Response.json({ error: message }, { status: upstream.status });
    }
  }

  // Valid JSON — pass status and body through untouched.
  return new Response(text, {
    status: upstream.status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
```

Read `.text()` first and parse manually, rather than calling `.json()` and catching —
that is what makes the raw body available to put *into* the synthesised error. The
`{detail}` → `{error}` normalisation handles FastAPI's own Pydantic validation failures,
which never pass through the handler in layer 2 at all: they are generated by the
framework before the route body runs, which is exactly why a second normalisation layer
is needed rather than being redundant with the first.

There is a fourth layer in `page.tsx` doing the same defensive parse — the comment there
calls it "the last line of defence and costs nothing". Four layers for one error shape
is defensible precisely because each one covers a case the others structurally cannot:
layer 1 the SDK's class hierarchy, layer 2 the route's own bugs, layer 3 the framework's
pre-route errors and transport failures, layer 4 anything that reaches the browser
regardless.

**General lesson.** *An error path that can produce a different content-type than the
success path will eventually be parsed as the success path.* Guarantee the shape at the
boundary. And: **catching a base class is only safe if you have verified the library
actually inherits from it.**

### 4.7 The 76% join, and refusing to guess

**What broke.** `generations` originally stored word counts but not the text. Reuniting
a stored message with the model that produced it meant joining `generations` to
`messages` on `(conversation_id, transcript_len == turn_index)`. That join agreed with
reality only **~76%** of the time, because `messages` is client-managed: full-replace
on every save, deletable, re-indexed by a re-run.

**The fix** was a nullable `text` column on `generations` plus a migration in
`init_db()` (`ALTER TABLE` if the column is absent — cheap, and old rows stay
readable). The backfill script is where the judgement is: it fills a row **only** when
the joined message matches on *both* agent id and exact word count, and leaves
everything else `NULL` rather than guessing. It prints the four counts — missing,
joinable, verified, left NULL — and is a dry run unless you pass `--apply`.

**General lesson.** *A corpus with silently wrong attributions is worse than a smaller
correct one.* When recovering data, prefer a verified subset over a plausible whole,
and make the discard visible.

### 4.8 `thinking_budget=0` is rejected by the model it was added for

**What broke.** Seeding the corpus with `gemini-3.5-flash-lite` — necessary, because
`flash` allows 20 requests/day and a corpus needs hundreds — failed immediately with
`INVALID_ARGUMENT`.

**Why.** Gemini Flash thinks by default, and thinking tokens count against
`max_output_tokens`, so `thinking_budget=0` was set to keep the whole budget for the
reply. The `-lite` variants reject a budget of `0` outright rather than treating it as
"do not think".

**The fix.** `thinking_budget: int | None = 0`, where `None` **omits the parameter
entirely**. `seed_corpus.py` takes `--thinking-budget none`. The distinction between
"set this to zero" and "do not send this key" is a real one that a typed config makes
expressible.

**General lesson.** *Provider parameters are not uniform across a provider's own model
family.* Absent and zero are different values.

### 4.9 Container loopback is not your loopback

**What broke** (caught before it shipped, by reading rather than by failure): the local
setup deliberately binds `127.0.0.1` everywhere — the FastAPI service, and
`.streamlit/config.toml` — so that a dev run is not exposed to the local network and
does not print an "External URL" that lets anyone nearby spend your API quota.

Inside a container, that same setting makes the service **unreachable**: the loopback
interface belongs to the container, and nothing outside it can connect.

**The fix.** Containers bind `0.0.0.0`, and exposure is controlled by *which ports
Compose publishes* — every port is published to `127.0.0.1:` explicitly, because plain
`3000:3000` binds every interface and puts an app that spends your API quota on the
local network. The Streamlit image passes `--server.address=0.0.0.0` on the command
line, because a CLI flag overrides the config file's pinned loopback.

**General lesson.** *"Bind loopback for safety" and "bind all interfaces to be
reachable" are both correct — in different network namespaces.* The security boundary
in Compose is the published port, not the bind address.

### 4.10 The standalone build that renders without its stylesheets

Next's `output: "standalone"` emits a minimal `server.js` plus only the `node_modules`
actually reached at runtime — which is what lets the web image ship without running an
install at all. It does **not** copy `public/` or `.next/static`, so the Dockerfile
copies both in by hand.

Miss them and the failure is nasty: pages render, and portraits and stylesheets 404.
The app is *up*, it just looks broken — a failure mode that healthchecks pass and
smoke tests miss.

**General lesson.** *A build optimisation that removes files changes what "working"
means.* Verify the exact production command, not an approximation of it. (The README is
honest that the images have not been built — there is no Docker daemon on this machine
— and lists precisely what *was* verified: compose parses, all `COPY` sources exist,
`npm ci` matches the lockfile, env vars map onto the settings, and `node server.js` was
run locally with the statics copied in and serves pages, portraits and the API proxy.
Being explicit about the boundary between verified and assumed is worth more than a
confident claim.)

### 4.11 The double-click race

**What broke.** A second click landing before React re-rendered could start a second
turn.

**Why.** `busy` is derived from state read out of the render closure. Between the click
handler firing and React re-rendering, `busy` is still `false`. Two clicks in that
window both pass the guard.

**The fix.** `turnInFlightRef` — a ref, checked and set in the same synchronous step,
which a second call cannot slip past. Related: `resolvingSpeaker` is cleared in the
same synchronous block that sets `composingAgent`, so the two state updates batch and
`busy` never dips false in the gap between the two requests of a turn.

**General lesson.** *State is for rendering; refs are for guarding.* If a check must be
atomic with respect to user input, it cannot read from a value that updates
asynchronously.

---

## 5. The measurement approach

### 5.1 Why measure at all

The app rests on one claim: these three agents think differently. Before the analytics
existed, the only way to check was to read transcripts — and reading is exactly the
judgement that drifts. You read four good ones and conclude it works. You cannot notice
gradual convergence by reading, because each transcript is compared against your memory
of the last one rather than against the original.

So the claim was made falsifiable. `npm run report`, `/analytics/divergence`, and the
Streamlit Divergence page all render the same computation.

### 5.2 Why the synthetic corpus came first

This is the methodological point most people miss, and it is worth leading with.

`test_analytics.py` builds a fake corpus of three hand-written vocabularies with no
overlap beyond glue words. It is deliberately not real agent output. The purpose is not
to test the agents — it is to test **the metric**.

The load-bearing test is `test_identical_voices_are_reported_as_not_distinguishable`:
all three agents draw from one shared pool, so there is genuinely nothing to learn, and
the check must report "not distinguishable". **A divergence check that always says
"distinct" is worse than no check at all** — it manufactures confidence. So it is shown
failing when it should fail, before it is trusted when it passes.

That is a **negative control**, the same idea as a placebo arm. The companion positive
control (`test_distinct_voices_are_detected`) asserts three genuinely different
vocabularies come back above chance + 0.30, and that *every* agent has recall > 0.5 —
so one agent carrying the average cannot hide two that blur.

The same discipline runs through the rest of the suite: `test_masking_agent_names_removes_the_shortcut`
constructs text that is *nothing but* agent name-drops, so masking must collapse the
score — if it did not, masking would not be masking.

**The general principle: validate the instrument on data whose answer you already know,
before you point it at data whose answer you want.**

### 5.3 Why the real corpus had to be genuinely generated

`seed_corpus.py` drives the real agents, through the real orchestrator, into the real
database. Inventing transcripts would measure the fixture rather than the prompts.

Details that matter:

- **15 deliberately varied questions.** A corpus of all-career questions would
  understate how far apart the agents actually are, because the differences show up in
  what each reaches for.
- **Paced at 4.5 requests/minute**, because the free tier allows 5.
- **Rate-limited turns are retried, not skipped.** Failures cluster in time, so
  dropping them would quietly bias which agents and which conversation positions are
  represented. That is a sampling-bias argument, and it is the reason the retry loop
  exists.
- **Per-minute vs per-day quota errors are distinguished** (`classify_quota_error`),
  because retrying against a daily limit burns hours and looks exactly like slow
  progress.
- **Seeded conversations get `seed-NNNN` ids**, so a re-run replaces rather than piles
  up, and seeded rows stay distinguishable from real use.
- **The model is recorded on every row.** A corpus seeded with one model does not
  describe another.

### 5.4 The methodology failure: measuring distinctiveness without checking length

This is the best measurement story in the project, and it is a story about being wrong.

The divergence metrics came back excellent — separability around 90%, distinctive terms
clean, lexical similarity trending down. That was reported as success.

It was not success. **Every turn was a 150-word essay.** The metrics were all green
while nothing in the transcript read like people talking.

The error was not in any calculation. It was in the **question**. "Are these three
different from each other?" and "does this read like a group chat?" are different
questions, and the first can be answered perfectly while the second fails completely.
Three agents can be perfectly distinguishable *and all be writing essays* — in fact
long turns make separability *easier*, because there is more text per sample. The
metric was, if anything, rewarded by the defect.

The correction was a second metric family (`chat_feel`) reading from `generations`, and
the design principle stated in its docstring: **averages hide the thing that matters.**
A set of turns that are all 65 words and a set swinging between 5 and 150 have the same
mean and feel nothing alike, so the *spread* is reported as prominently as the centre —
which is where the coefficient of variation (§3.6) comes in.

The measured history, recovered by segmenting the corpus at the two boundary markers in
`backend/data/`:

| era | n | mean words | cv | under 15w | over 100w | 15–40w band |
|---|---|---|---|---|---|---|
| **A** — original envelope ("Respond as X with your next message") | 75 | 95.7 | 0.53 | 1% | **48%** | 17% |
| **B** — "say the one thing you would say next" | 32 | 21.9 | **0.39** | 19% | 0% | **81%** |
| **C** — situational rhythm note + two-sided permission | 40 | 27.0 | **0.65** | 20% | 0% | 65% |

Read it as: A was uniformly long. B fixed the length and was *more* uniform than A —
81% of turns inside one 25-word band, nothing over 40 words. Only C produced actual
variation, and it is the only one where a turn can be six words or eighty-four
depending on what the conversation set up.

Notice what would have happened without the cv column: B looks like a triumph. Mean
down 77%, essays eliminated. Every headline number improved. The cv is the only number
that says B replaced one uniformity with another.

### 5.5 What the numbers say right now

Live output of `npm run report`, current as of this writing — 87 stored agent turns
across 17 conversations (behaviorist 34, gardener 28, introspector 25):

```
separability   accuracy 0.759  vs chance 0.333  (+0.425)   ->  DISTINCT
per-agent recall   behaviorist 0.794 · gardener 0.750 · introspector 0.720
most confused      gardener mistaken for behaviorist (5x)
names masked       0.713 (+0.046) -> voice, not name-dropping
turn taking        same speaker again 0.229  (configured 0.25, n=70)  ok
lexical similarity mean 0.708  (gardener vs introspector 0.616 · behaviorist vs introspector 0.756)
latency            median 7541ms over 250 generations
```

Distinctive terms — the qualitative check that the prompts are still biting:

- **introspector** — feel, fact, grateful, picture, chest, want, body
- **behaviorist** — did, times, year, look, haven, spend, months, hours
- **gardener** — people, talked, shared, person, mentioned, depends, friend

Read those as evidence about the *bans*, not just the personas: the Gardener's list
contains no gardening imagery and the Introspector's contains no spiritual vocabulary,
which is what those prompt rules exist to prevent. If gardening words reappear in that
list, the "no nature metaphors" rule has stopped working.

Chat-feel, `gemini-3.5-flash` only (59 generations with recorded text): mean 57.7
words, median 56, cv 0.41, range 20–120, 0% short turns, 5% long, 5% end on a
quotable verdict, 5% unmarked mind-reading, **0% personalise an abstract question,
5% let a lens harden into an order** (the last two are the newest metrics — see §3.9
— and this is the first time either has a number attached to it from the real
corpus rather than a one-off scenario run), 30% open by restating another mind,
echo rate 0.73.

Every row above predates the `build` column (§3.8) and reads as `unknown` in
`npm run report -- --builds` — this corpus cannot be split into before/after any
specific prompt edit. The next real prompt change is the first one `--build current`
will actually be able to isolate.

### 5.6 Known limits of these numbers

Being able to state these is what separates a measured claim from a marketing one:

- **87 turns is small.** Above the refusal threshold, well below comfortable. The
  confidence interval on 0.759 is wide.
- **The corpus mixes prompt revisions with no way to separate them.** Every row
  predates the `build` column, so a change in these numbers over the app's history
  cannot be attributed to a specific edit — only future rows can be. See §3.8 and §3.9.
- **The chat-feel slice and the divergence slice are different tables.** Divergence
  turns come from `messages` (the full-replace conversation history); chat-feel reads
  `generations` (append-only telemetry) filtered to the shipped model. They will not
  agree on a turn count, and that is by design, not a bug — see §2.3 and §2.5 for why
  the split exists.
- **Lexical similarity is a blunt instrument.** Three agents discussing the same
  questions will always share a lot of words; treat it as a trend across prompt edits,
  not an absolute score.
- **Echo rate is a proxy.** Reusing a rare word is evidence of engagement, not a
  definition of it, and a turn can engage without echoing anything.
- **Separability measures distinguishability, not quality.** Three agents could be
  perfectly separable and all be bad. That is precisely the trap §5.4 fell into once
  already.
- **The behavioural detectors (§3.9) are regex, not a model judging the transcript.**
  Read a metric of 0% or 5% as "the patterns tried did not fire," not as proof the
  behaviour never occurs — three bugs were already found in these specific detectors
  by reading past a clean-looking number, and a fourth is simply unknown until found.
- **`test_routes.py`'s docstring used to claim `/agent/turn` was "deliberately not
  exercised here" — corrected while writing this section.** It had gone quietly
  stale: several tests in that file (including `test_agent_turn_stamps_the_running_
  build`, added alongside the `build` column) already posted to `/agent/turn`
  through `TestClient` successfully, by patching `main.generate_turn` directly so
  the request never reaches the real client. What genuinely still is not, and
  cannot be, exercised there is a real model call through the cached client, which
  does not survive `TestClient`'s per-request event loop — that path stays covered
  end to end against a real server instead. The lesson isn't the specific bullet;
  it's that a docstring explaining what a test file does NOT cover is itself
  untested and will drift the moment a new test quietly covers the gap it describes.

---

## 6. Glossary

Plain-English definitions of every term this project uses.

**Ablation study** — removing one input to see how much the result depends on it. Here:
masking agent names to check the classifier is not just spotting name-drops.

**Append-only** — a table that is only ever inserted into, never updated or deleted.
Makes it a trustworthy record: nothing can be rewritten after the fact.

**Backend-For-Frontend (BFF)** — a server layer that exists purely to serve one
frontend. The Next.js route handlers here: they add no logic, they just let the browser
talk to its own origin while the real API stays private.

**Bigram** — a two-word sequence ("right now"). The vectoriser uses unigrams and
bigrams, so word *combinations* can be signal too.

**Chance level** — what a classifier scores by guessing. With three balanced classes,
1/3 ≈ 0.333. Accuracy is meaningless without it.

**Classifier** — a model that assigns a label to an input. Here: read a turn, name the
agent that wrote it.

**Coefficient of variation (cv)** — standard deviation ÷ mean. A unitless measure of
spread, comparable across datasets with different averages. Below ~0.4 here means the
turns are one length wearing different words. (§3.6)

**Confusion matrix** — a grid of "actual" against "predicted". The diagonal is correct
answers; off-diagonal cells name which pairs get mistaken for each other.

**CORS (Cross-Origin Resource Sharing)** — the browser rule that a page on one origin
cannot freely call another. Sidestepped here: the browser only ever calls its own
origin, and the proxy makes the cross-origin call server-side, where CORS does not
apply.

**Cosine similarity** — the angle between two vectors, 0 (unrelated) to 1 (identical
direction). Used to compare the agents' pooled vocabularies.

**Cross-validation** — splitting data into k folds, training on k−1 and testing on the
held-out one, rotating until every sample has been predicted by a model that never saw
it. Prevents scoring memorisation as skill. (§3.5)

**Detached process** — a child process placed in its own process group, so signals sent
to the parent's group do not reach it. The mechanism that makes the Ctrl+C fix work.

**Document frequency** — the share of documents (turns) a word appears in. Used instead
of a hand-written stopword list to decide what is too common to be meaningful. (§4.5)

**Envelope** — everything wrapped around the transcript in the *user* message of a
call: the rendered conversation, the situational rhythm note, the two-sided length
permission, the closing instruction. Rebuilt every turn. Distinct from the system
prompt, which never changes. (§3.1)

**FastAPI** — a Python web framework built on type hints. Validates requests via
Pydantic, generates OpenAPI docs automatically, and supports both async and sync
handlers (running the latter in a threadpool).

**Idempotent** — an operation with the same result whether applied once or many times.
`PUT /conversations/{id}` is idempotent because it replaces rather than appends.

**LangChain** — a library providing a uniform interface across LLM providers. Used here
narrowly: model construction, `ainvoke`, and provider-agnostic exception classes.
Explicitly *not* used for chains, agents, memory or retrieval. (§3.2)

**Lift over chance** — accuracy minus chance. The honest headline: 0.753 − 0.333 =
+0.42.

**Logistic regression** — a linear classifier that outputs class probabilities. Chosen
for interpretability and because it cannot memorise a small corpus the way a deep model
could.

**`lru_cache`** — a Python decorator that caches a function's return value. Used on
`agents()` and `get_model()`. Cheap, and a trap when the underlying file changes at
runtime (§4.4).

**Orchestrator** — the component deciding who acts next in a multi-agent system. Here it
is 20 lines of weighted random choice, held server-side as the single source of truth.
(§3.3)

**Orphan process** — a process whose parent has died. On Windows it keeps running and
keeps its resources — including listening sockets. (§4.1)

**Proxy route** — a server-side handler that forwards a request elsewhere. Keeps the
API key server-side and the backend unexposed.

**Pydantic** — Python data validation via type annotations. `schemas.py` uses it with
field aliases so JSON stays camelCase while Python stays snake_case.

**Rate limit / quota** — the provider's cap on requests. Gemini's free tier has both
per-minute and per-day limits, and the difference decides whether retrying is sane.

**Recall (per class)** — of the turns an agent actually wrote, the share the classifier
got right. Reported per agent so one strong agent cannot mask two weak ones.

**Rhythm note** — the one line in the envelope describing what just happened in the
conversation, chosen deterministically from transcript state. The mechanism that makes
turn length vary. (§3.4)

**Rule saturation** — the point past which adding prompt rules degrades adherence to
existing ones. (§4.3)

**Separability** — the headline metric: can a classifier tell the agents apart from
text alone?

**Signal inheritance** — on Windows, `CTRL_C_EVENT` reaching every process attached to
the console, including children spawned by a shutdown handler. (§4.2)

**Standalone build** — Next's `output: "standalone"`, emitting a minimal `server.js`
plus only the `node_modules` reached at runtime. Excludes `public/` and `.next/static`,
which must be copied in. (§4.10)

**Standard error of a proportion** — `sqrt(p(1−p)/n)`. How much a sample proportion
bounces around by chance at that sample size. Used to judge whether the observed repeat
rate meaningfully differs from the configured one. (§3.7)

**Stop words** — very common words ("the", "you", "would"). Deliberately **kept** for
the classifier, because function words are strong authorship signal, and **dropped**
for the human-readable term list, where they are true but useless. Two vectorisers, on
purpose.

**Stratified k-fold** — cross-validation where each fold preserves the class
proportions, so no fold ends up with almost no examples of one agent.

**System prompt** — the persona instructions sent in a call's system slot. Constant per
agent. The product. (§3.1)

**TF-IDF** — Term Frequency × Inverse Document Frequency. Weights a word up for being
frequent in this document and down for being common across all documents, turning text
into a numeric vector.

**Threadpool (FastAPI)** — where FastAPI runs plain `def` handlers, so blocking calls
(like `sqlite3`) do not stall the event loop shared by `async def` handlers.

**Turn** — one agent message. The unit of everything here: one API request, one row in
`generations`, one sample in the corpus.

**Upsert** — insert, or update if the key already exists. SQLite's
`ON CONFLICT(id) DO UPDATE`.

**uvicorn** — the ASGI server running FastAPI. `--reload` runs the app in a child
process and watches `*.py` files only.

**WAL (Write-Ahead Log)** — a SQLite journal mode where readers read the main file while
the writer appends to a log, so reads do not block writes. (§3.8)

**Watchdog / reaper** — a detached process that outlives its parent and cleans up after
it. `scripts/dev-reaper.mjs`. (§4.2)

---

## 7. Questions you should be able to answer cold

Short answers to the questions this project invites. If one of these feels shaky, the
section reference is where to go.

**"Why three agents instead of one prompt asking for three perspectives?"**
One call optimises one coherent output — it balances the three views and reconciles
them, which is the opposite of the product. Three calls with three system prompts give
structurally separate conditioning; each agent sees only what the others said out loud.
And the claim is tested: a cross-validated classifier scores 75% against 33% chance.
(§1.2, §3.5)

**"Why move from Next.js to a Python backend?"**
Three pressures. The prompts were shipping to every browser and were about to have two
copies. Turn logic in the browser meant a second frontend would have to reimplement it.
And `localStorage` could store history but could never be `SELECT`ed — and I wanted to
run a classifier over every turn the agents had ever produced. That last one forced a
database, which forced a server process, and the classifier lives in Python.
(§2.2–§2.4)

**"What did moving turn logic server-side actually buy you?"**
Four things that were impossible before: a second frontend that cannot drift from the
rule; a testable rule (20,000 injectable-rng draws asserting a 23–27% repeat rate); a
seed script that drives the *real* orchestrator, so the corpus measures the product and
not a fixture; and an analytics check that audits the observed repeat rate against the
configured one. Cost: a turn is now two HTTP requests. (§2.4)

**"Why LangChain if you're not using chains?"**
I'm using it as a thin adapter for two things — a uniform constructor and `ainvoke`
across providers, and provider-agnostic exception classes. The second turned out to
matter: `langchain-google-genai` wraps rate limits in classes that don't inherit from
the Google SDK's base error, so catching the SDK class let a 429 escape and surface to
users as a JSON parse error. Catching `langchain_core`'s `ModelRateLimitError` is both
the correct fix and the one that keeps the swap-the-provider promise honest. (§3.2,
§4.6)

**"Tell me about a bug that taught you something."**
Lead with Ctrl+C (§4.2) — it has a genuinely surprising mechanism: the killer spawned
by the shutdown handler is killed by the same console event that triggered the handler,
so the handler prints that it stopped everything and stops nothing. The fix is a
detached watchdog that guarantees *ports*, not pids, because a dying supervisor orphans
grandchildren no tree walk can reach. The general lesson is one sentence: cleanup code
has to survive the event that triggers it.

**"Tell me about a time you were wrong."**
The engagement metric (§4.5) or the length methodology failure (§5.4). The second is
stronger: I had green divergence metrics and reported success while every turn was a
150-word essay. Nothing was miscalculated — I was answering the wrong question. "Are
these three different from each other?" can be answered perfectly while "does this read
like a group chat?" fails completely; long turns actually make separability *easier*.
The fix was a second metric family that reports spread as prominently as centre, and
the number that exposed it was the coefficient of variation.

**"Why coefficient of variation and not standard deviation?"**
Because I was comparing a corpus averaging 96 words against one averaging 22. Standard
deviation carries the units of the data, so it isn't comparable across those. Dividing
by the mean makes it comparable — and it's what showed that my "fix" for essays had
actually made the output *more* uniform, not less: cv 0.53 → 0.39, with 81% of turns
inside a single 25-word band.

**"How do you know your metric is right?"**
I validated it on data whose answer I already knew, before pointing it at data whose
answer I wanted. The load-bearing test gives all three agents one shared vocabulary and
asserts the report says "not distinguishable" — a divergence check that always says
"distinct" is worse than no check, because it manufactures confidence. There's a
matching positive control, and separate thresholds below which the report refuses to
answer rather than producing a number that can't fail. (§5.2, §3.7)

**"What would you do next?"**
Four things, in order. Add `--reload-include '*.md'` to the `dev:api` script, because
right now editing a prompt doesn't reload the server and the symptom looks like a
prompt that didn't work (§4.4). Build and actually run the Docker images — they're
written and statically verified but have never been built. Grow the corpus past a few
hundred turns per agent on a single model, so the separability interval tightens. And
act on the confusion matrix: behaviorist-mistaken-for-introspector is the pair that
blurs, so that's the pair whose prompts to separate.

---

### Appendix — documentation drift found while writing this

Two inconsistencies were flagged here in an earlier revision and — worth noting
plainly — sat unfixed for a while after being flagged, which is itself the lesson: an
appendix that *describes* drift instead of *fixing* it just becomes a second place for
the same fact to go stale. Both are now corrected in the source, not just noted here:

- `backend/README.md` stated `max_output_tokens=500`; `config.py` had already moved to
  **300**. Fixed in the README, with the same reasoning the config comment gives: at
  500 the ceiling never bit, so it was lowered to make a rambling turn impossible while
  leaving room for an earned paragraph.
- `backend/requirements.txt` referred to a `config.PROVIDER` setting for swapping
  providers. No such setting exists — the swap is done by changing the constructor in
  `llm.py`. Fixed in the requirements.txt comment to match what `backend/README.md`
  already correctly described.

Drift found and fixed in *this* revision (see §3.3, §3.8, §3.9, §5.5, §5.6 above for
the full context on each):

- `test_routes.py`'s own docstring claimed `/agent/turn` was "deliberately not
  exercised here." Several tests in that file already contradicted it. Corrected.
- §3.3's orchestrator listing was the pre-summoning version of the file — missing
  `allow_same`, `summoned`, and `choose_speaker` entirely. Replaced with the current
  code and the reasoning behind each of the four summoning rules.
- §5.5's numbers were nearly two months stale (77 turns / 147 generations vs. the
  actual 87 turns / 250 generations at time of writing) and described a chat-feel
  corpus on `gemini-3.5-flash-lite` when the app has shipped on `gemini-3.5-flash`
  since. Replaced with a live `npm run report` run, and both newly-wired reasoning
  metrics (§3.9) are now included in what §5.5 reports.
