# Other Minds

Three agents — **The Introspector**, **The Behaviorist**, and **The Gardener** —
respond to the same question from genuinely different worldviews. They aren't
trying to persuade each other or reach agreement; the point is the perspective
shift, not a resolution.

Agents speak one message at a time. After each reply you either respond or press
_hear another mind_ — nothing auto-advances, so you are never bombarded.

## Architecture

A Python backend does the thinking; a Next.js frontend does the presenting.

```
  browser ──► Next.js  (:3000) ─┐
              proxy route       ├─► FastAPI (:8000) ──► Gemini
  browser ──► Streamlit(:8501) ─┘   agents, prompts,
              direct HTTP           turn logic, LLM call, storage
```

Two frontends, one service. They share no code: the Streamlit app asks the API
for everything, including **who speaks next**. That rule lives in exactly one
place (`backend/app/orchestrator.py`), which is why a second frontend could be
added without it drifting out of step with the first.

The browser never talks to FastAPI directly. The Next.js route handlers under
[`app/api/agent/`](app/api/agent/) proxy to it server-side, so the backend needs
no CORS, no public exposure, and the API key stays out of the client bundle.

| | |
|---|---|
| [`backend/`](backend/) | agents, system prompts, turn logic, model call, storage — see [backend/README.md](backend/README.md) |
| [`app/`](app/) | the Next.js UI — history sidebar, sound, animation |
| [`ui/`](ui/) | the Streamlit UI — conversation + divergence pages |
| [`app/lib/agents.ts`](app/lib/agents.ts) | agent ids, display names, colours — **not** the prompts |

The system prompts live only in
[`backend/app/agents/prompts/`](backend/app/agents/prompts/).

Conversation history is stored by the service in SQLite
(`backend/data/other_minds.db`), not in the browser. That is what makes the
transcripts a queryable corpus rather than something trapped in one browser
profile.

## Running it with Docker

```bash
cp .env.local.example .env.local     # add your GEMINI_API_KEY
docker compose up --build
```

| | |
|---|---|
| http://localhost:3000 | the Next.js app |
| http://localhost:8501 | the Streamlit client |
| http://localhost:8000/docs | the API |

Three services from one key. Conversations and the analytics corpus live on a
named volume, so `docker compose down` keeps them — `down -v` is what deletes
them.

A few deliberate choices, in [docker/](docker/) and
[docker-compose.yml](docker-compose.yml):

- **Ports are published to `127.0.0.1` only.** Plain `3000:3000` would bind
  every interface and put an app that spends your API quota on the local
  network.
- **The key is never baked into an image.** It arrives via `env_file` at run
  time, and `.dockerignore` keeps `.env*` out of the build context entirely.
- **Services bind `0.0.0.0` inside containers** — the opposite of the local
  setup, and necessarily so: a container's loopback is its own, so binding it
  would make the service unreachable. The Streamlit image passes
  `--server.address` on the command line to override the loopback pinned in
  `.streamlit/config.toml`.
- **`web` waits for the API to be healthy**, not merely started, so the first
  page load does not race it.
- The web image uses Next's `output: "standalone"`, and copies `public/` and
  `.next/static` in by hand — standalone omits both, and without them pages
  render while portraits and stylesheets 404.

> **Not yet built.** These images were written and every part that could be
> checked without a Docker daemon was: compose parses, all `COPY` sources
> exist, `npm ci` matches the lockfile, the env vars map onto the settings, and
> the exact production command (`node server.js` with statics copied) was run
> locally and serves pages, portraits and the API proxy. The images themselves
> have not been built or run — there is no Docker on this machine.

## Setup (without Docker)

Needs Node and Python 3.12+.

```bash
npm install
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements-dev.txt   # Windows
# backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt     # macOS/Linux
```

`requirements-dev.txt` pulls in the service, the Streamlit UI, and the test
tools. To install only what serving needs, use `backend/requirements.txt`.

The app needs a Gemini API key. Get one free from
[Google AI Studio](https://aistudio.google.com/apikey):

```bash
cp .env.local.example .env.local
# edit .env.local and set GEMINI_API_KEY=your-key
```

Both processes read that one file.

## Running

```bash
npm run dev:all
```

Then open <http://localhost:3000>. The API's interactive docs are at
<http://127.0.0.1:8000/docs>.

| script | does |
|---|---|
| `npm run dev:all` | web + api together |
| `npm run dev` | web only (:3000) |
| `npm run dev:api` | api only (:8000), with reload |
| `npm run dev:ui` | the Streamlit UI (:8501) — needs the api running |
| `npm run dev:clean` | free ports 8000/3000 if a previous run left something behind |
| `npm run report` | divergence report — are the agents actually distinct? |
| `npm run seed` | generate a corpus of real agent turns to analyse |
| `npm test` | all tests (backend + UI) |
| `npm run test:api` | backend parity + storage tests |
| `npm run test:ui` | Streamlit UI tests (headless, API stubbed) |
| `npm run build` | production build of the frontend |

If the UI reports it can't reach the backend, the API process isn't running —
start it with `npm run dev:api`.

### Running on different ports

The frontend finds the backend via `OTHER_MINDS_API_URL` (default
`http://127.0.0.1:8000`). To move either process:

```bash
npx next dev --port 3010                                  # in one shell
OTHER_MINDS_API_URL=http://127.0.0.1:8010 npx next dev    # ...pointing at
node scripts/py.mjs -m uvicorn app.main:app --app-dir backend --port 8010
```

### Stale dev servers and stuck ports

Windows does not kill a process's descendants when the process dies, and — the
part that makes this genuinely nasty — **cleanup that runs inside the dying
process is not dependable either**. Ctrl+C delivers `CTRL_C_EVENT` to every
process attached to the console, so a `taskkill` spawned from a shutdown
handler is killed before it acts. The handler prints that it is stopping
things, kills nothing, and exits looking clean.

An orphaned server then keeps its port **and keeps serving the code it started
with**, which shows up as "my changes aren't taking effect" rather than as an
obvious stale process.

`npm run dev:all` uses [`scripts/dev.mjs`](scripts/dev.mjs), which defends four
ways:

1. **Fewer layers** — the venv python and next's own bin are launched directly,
   not through `npm`/`npx` wrappers.
2. **Detached tree kills** on shutdown, so the killer is in its own process
   group and the signal killing us cannot kill it too.
3. **A watchdog** ([`scripts/dev-reaper.mjs`](scripts/dev-reaper.mjs)) spawned
   detached and console-less, which outlives the supervisor and finishes the job
   if defence 2 does not run or does not finish. **This is what makes Ctrl+C
   reliable.** It guarantees *ports*, not just child pids, because a dying
   supervisor tends to orphan grandchildren that no longer belong to any tree.
4. **A preflight sweep** on start, which announces loudly that the previous
   session leaked — a leak quietly tidied away is how a broken shutdown goes
   unnoticed for days.

The port logic is shared by the supervisor and the watchdog via
[`scripts/proc.mjs`](scripts/proc.mjs), so the two cannot drift apart.

Nothing that isn't ours is ever killed: an unrelated program on port 3000
produces a refusal naming it.

```bash
npm run dev:clean          # just free the ports and exit
API_PORT=8010 WEB_PORT=3010 npm run dev:all
```

## The two frontends

They are not the same app twice, and the difference is deliberate.

**Next.js** is the product: the galaxy backdrop, the per-agent entrance
animations, the arrival sound timed to the bubble settling, the collapsing
history sidebar.

**Streamlit** ([`ui/streamlit_app.py`](ui/streamlit_app.py)) is the quick
surface — the one to reach for when the question is "what do the agents actually
say", not "how does it feel". It keeps what carries meaning: who is speaking,
one turn at a time, and the choice to answer or to hear another mind. It does
**not** reproduce the animation or the sound. Streamlit re-runs the whole script
on every interaction, so per-message animation state does not survive; imitating
it there would produce a worse version of something the React app already does
well.

## Does it actually work?

The whole app rests on one claim: that these three agents think differently. It
is an easy claim to believe from reading a few transcripts and an easy one to be
wrong about, because prompt edits drift and every agent slowly converges on the
same helpful voice.

So it is measured. `npm run report` trains a cross-validated classifier to guess
which agent wrote a turn, from the text alone:

- near **33%** (chance) — one voice in three costumes, whatever the transcripts
  feel like
- clearly above it — the prompts are doing real work, and the confusion matrix
  names which two agents blur together

The same report is served at `/analytics/divergence` and rendered on the
**Divergence** page of the Streamlit UI. Details, including why small corpora are
refused rather than fudged, are in [backend/README.md](backend/README.md).

### A note on free-tier quotas

`gemini-3.5-flash` allows **20 requests per day** on the free tier, which is
enough to use the app but not enough to seed a corpus. `npm run seed` therefore
takes `--model`, and the model used is recorded with every turn:

```bash
npm run seed -- --model gemini-3.5-flash-lite --thinking-budget none
```

`--thinking-budget none` is required for the `-lite` models: they reject a
budget of `0` outright, while `gemini-3.5-flash` needs it so thinking tokens do
not eat the output budget.

A corpus seeded with one model does not describe another, so re-seed before
comparing numbers across models.
