# Other Minds — backend

FastAPI service holding everything that isn't presentation: the three agents,
their system prompts, the model call, and the turn rule.

## Layout

```
backend/app/
  main.py             FastAPI app + routes
  config.py           settings (reads ../.env.local, then backend/.env)
  schemas.py          wire types; JSON stays camelCase, Python stays snake_case
  orchestrator.py     who speaks next
  llm.py              the single LLM call, via LangChain
  store.py            SQLite: conversation history + turn telemetry
  analytics.py        do the three agents actually diverge?
  agents/registry.py  agent definitions + transcript rendering
  agents/prompts/*.md THE SYSTEM PROMPTS — this is the product
```

`agents/prompts/*.md` is the **only** copy of the prompts. They used to also live
in `app/lib/agents.ts`, which shipped ~16KB of prompt text to every visitor and
gave the project two sources of truth. The frontend now keeps only what it
renders: ids, display names, and colours.

## Setup

```bash
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt   # Windows
# backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt     # macOS/Linux
```

The API key is read from the project-root `.env.local` — the same file the
Next.js app already uses, so there is one key on disk rather than two copies
drifting apart.

## Running

From the project root:

```bash
npm run dev:all     # web (:3000) + api (:8000) together
npm run dev:api     # api only
npm run test:api    # parity tests
```

## Endpoints

| Method | Path                  | Purpose |
|--------|-----------------------|---------|
| `GET`  | `/health`             | liveness, model name, whether a key is present |
| `POST` | `/agent/next-speaker` | who speaks next — **no model call**, returns immediately |
| `POST` | `/agent/turn`         | advance the conversation by exactly one agent message |
| `GET`  | `/conversations`      | sidebar rows, newest first (no transcripts) |
| `GET`  | `/conversations/{id}` | one conversation, transcript included |
| `PUT`  | `/conversations/{id}` | upsert — the client mirrors its transcript here |
| `DELETE` | `/conversations/{id}` | remove it; messages cascade |
| `GET`  | `/analytics/divergence` | are the agents actually distinct? |

A turn is deliberately two requests. The UI lights up the speaking agent's
portrait and name *while* the reply is being written, which means it has to know
who is speaking before the reply exists. `/agent/next-speaker` answers that
instantly; the client passes the id straight back to `/agent/turn`.

Omitting `agentId` from `/agent/turn` makes the server draw a speaker itself —
fine for scripts, but a client that does this after calling `/agent/next-speaker`
gets an independent second draw.

Interactive API docs run at <http://127.0.0.1:8000/docs>.

## Generation parameters

These mirror the original TypeScript implementation exactly, and the reasons are
in `config.py`:

- `max_output_tokens=300` — both a backstop and a real brake on length. At 500
  the ceiling never bit and instruction alone did not hold turns short; 300
  makes a rambling turn impossible while leaving room for an earned paragraph.
- `thinking_budget=0` — Gemini Flash thinks by default and thinking tokens count
  against the output budget. Disabled so the whole budget is reply.

## Swapping providers

`llm.py` builds the model through LangChain, so switching means adding the
integration to `requirements.txt` and changing the constructor — nothing else in
the app knows which provider is in use.

## Tests

`tests/test_parity.py` guards the two things the agents' behaviour actually
depends on: the prompt text and the envelope it is wrapped in. The prompts are
NOT pinned to a hash — they are meant to be edited — but the tests do check the
prompts load whole, that the display names still match the frontend, and that
the Introspector's and Behaviorist's safety carve-outs are intact. That last one
is the highest-consequence possible prompt regression, so it has its own test.

## Storage

SQLite at `backend/data/other_minds.db` (override with `DB_PATH`), created on
first boot. Three tables, and the split between them is deliberate:

| table | written by | shape |
|---|---|---|
| `conversations` | the client, on every change | upsert |
| `messages` | the client, on every change | full replace |
| `generations` | `/agent/turn` | append-only |

`messages` is full-replace because that mirrors what the client already does,
which makes the write idempotent — a retry or an out-of-order save can't
duplicate or interleave turns.

`generations` is separate and append-only for two reasons. It survives the
full-replace above, so the record of what was actually generated stays honest.
And it has **no foreign key** to `conversations`: a turn can be generated
without ever being saved, and dropping those would bias the corpus toward
conversations people chose to keep. Deleting a conversation therefore removes
its messages but leaves its telemetry.

Messages are stored one row per turn rather than as a JSON blob, so the
analytics phase can read the corpus with a plain `SELECT` via `pandas.read_sql`.

Storage failures never fail a turn: the reply is already generated by the time
telemetry is written, and losing a row must not take the answer away from the
reader.

## Divergence analytics

The premise of the app is that the three agents think differently. Until there
was a corpus there was no way to check that except by reading, which is exactly
the kind of judgement that drifts.

`analytics.py` reads the stored turns and reports:

| metric | question it answers |
|---|---|
| **separability** | can a classifier tell the agents apart from text alone? |
| lexical similarity | how much vocabulary do they share? |
| distinctive terms | which words make each agent recognisable? |
| length profile | do their turn lengths differ, or has everyone settled on one paragraph? |
| turn taking | does the observed repeat rate match `double_turn_chance`? |

**Separability is the one that matters.** A cross-validated classifier tries to
guess the author of each turn. Near chance (0.33) means the prompts are
producing one voice in three costumes, whatever the transcripts feel like when
you read a few. The confusion matrix is as useful as the score, because it names
*which* two agents blur together — that is the thing you would act on.

```bash
npm run report      # readable summary
curl localhost:8000/analytics/divergence
```

Two deliberate design points:

- **The classifier keeps stop words; the term list drops them.** Function words
  ("you", "would", "what") are strong authorship signal, so the classifier wants
  them. A human reading "most distinctive terms" does not — `to this` and
  `right now` are true and useless, and they crowd out the content words worth
  acting on. The two use different vectorisers on purpose.
- **Small corpora are refused, not fudged.** Separability needs
  `MIN_TURNS_PER_AGENT` turns per agent; the turn-taking check reports
  `sufficient_data: false` below `MIN_TRANSITIONS`, because under about 20
  transitions the confidence interval is wider than the effect being looked for
  and the check would pass simply because it cannot fail.

### Seeding a corpus

```bash
npm run seed -- --turns 5          # 15 questions, real agent turns
npm run seed -- --clear            # remove seeded conversations
```

Seeded conversations get `seed-NNNN` ids, so a re-run replaces them instead of
piling up, and they stay distinguishable from real use. The turns are genuinely
generated — inventing transcripts would measure the fixture rather than the
prompts. Pacing defaults to 4.5 requests/minute because the Gemini free tier
allows 5, and rate-limited turns are retried rather than skipped: failures
cluster in time, so dropping them would quietly bias which agents and which
conversation positions are represented.
