"""Other Minds — Streamlit client.

A second frontend for the same service the Next.js app uses. It shares no code
with it; everything it knows, it asks the API for.

What this UI deliberately does NOT try to reproduce from the React app: the
galaxy backdrop, the per-agent entrance animations, and the arrival sound timed
to the bubble settling. Streamlit re-runs the whole script on every interaction,
so per-message animation state does not survive — chasing it here would produce
a worse imitation rather than a second good UI. What it does keep is the part
that carries meaning: who is speaking, one turn at a time, and the choice to
answer or to hear another mind.
"""

import uuid
from pathlib import Path

import streamlit as st

import api

ROOT = Path(__file__).resolve().parent.parent
PORTRAITS = ROOT / "public" / "minds"

AGENTS = {
    "introspector": ("The Introspector", "#6366f1"),
    "behaviorist": ("The Behaviorist", "#d97706"),
    "gardener": ("The Gardener", "#059669"),
}


def portrait(agent_id: str) -> str | None:
    p = PORTRAITS / f"{agent_id}.jpg"
    return str(p) if p.is_file() else None


def title_for(transcript: list[dict]) -> str:
    first = next((m for m in transcript if m["role"] == "user"), transcript[0])
    text = " ".join(first["content"].split())
    return f"{text[:63]}…" if len(text) > 64 else text


# ── State ───────────────────────────────────────────────────────────────────

# Set here when this file is run on its own (and by the tests). Under
# ui/main.py the entry point has already configured the page, and calling it
# twice raises — hence the guard rather than a bare call.
try:
    st.set_page_config(page_title="Other Minds", page_icon="🌀", layout="centered")
except Exception:  # noqa: BLE001 - already configured by the entry point
    pass

ss = st.session_state
ss.setdefault("transcript", [])
ss.setdefault("conversation_id", None)
# Set when a turn has been asked for but not yet taken. The actual call happens
# further down, after the transcript has been drawn, so the reader sees the
# conversation-so-far while the next line is being written.
ss.setdefault("pending", False)
ss.setdefault("error", None)


def start_new() -> None:
    ss.transcript = []
    ss.conversation_id = None
    ss.pending = False
    ss.error = None


def open_conversation(conversation_id: str) -> None:
    try:
        full = api.get_conversation(conversation_id)
    except api.ApiError as err:
        ss.error = str(err)
        return
    ss.transcript = full["transcript"]
    ss.conversation_id = conversation_id
    ss.pending = False
    ss.error = None


def persist() -> None:
    """Mirror the live transcript to the service. A failure here is not worth
    interrupting the conversation over — history is a convenience."""
    if not ss.transcript:
        return
    if ss.conversation_id is None:
        ss.conversation_id = str(uuid.uuid4())
    try:
        api.save_conversation(
            ss.conversation_id, title_for(ss.transcript), ss.transcript
        )
    except api.ApiError:
        pass


# ── Sidebar: history ────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### conversations")
    if st.button("＋ new conversation", width="stretch"):
        start_new()
        st.rerun()

    try:
        rows = api.list_conversations()
    except api.ApiError:
        rows = []
        st.caption("history unavailable")

    if not rows:
        st.caption("no conversations yet — ask something to begin.")
    for row in rows:
        open_col, del_col = st.columns([6, 1], vertical_alignment="center")
        label = row["title"] if len(row["title"]) <= 34 else row["title"][:33] + "…"
        current = row["id"] == ss.conversation_id
        if open_col.button(
            f"{'▸ ' if current else ''}{label}",
            key=f"open-{row['id']}",
            width="stretch",
            help=row["title"],
        ):
            open_conversation(row["id"])
            st.rerun()
        if del_col.button("✕", key=f"del-{row['id']}", help="Delete"):
            try:
                api.delete_conversation(row["id"])
            except api.ApiError as err:
                ss.error = str(err)
            if row["id"] == ss.conversation_id:
                start_new()
            st.rerun()


# ── Main ────────────────────────────────────────────────────────────────────

if not ss.transcript:
    st.title("Other Minds")
    st.markdown(
        "Three minds respond to the same question from genuinely different "
        "worldviews. They aren't trying to persuade each other or reach "
        "agreement — the point is the perspective shift, not a resolution."
    )
    cols = st.columns(3)
    for col, (agent_id, (name, colour)) in zip(cols, AGENTS.items()):
        with col:
            if p := portrait(agent_id):
                st.image(p, width="stretch")
            st.markdown(
                f"<div style='text-align:center;color:{colour};font-weight:600'>"
                f"{name}</div>",
                unsafe_allow_html=True,
            )

for message in ss.transcript:
    if message["role"] == "user":
        with st.chat_message("user"):
            st.markdown(message["content"])
    else:
        name, colour = AGENTS[message["role"]]
        with st.chat_message(name, avatar=portrait(message["role"])):
            st.markdown(
                f"<span style='color:{colour};font-weight:600'>{name}</span>",
                unsafe_allow_html=True,
            )
            st.markdown(message["content"])

if ss.error:
    st.error(ss.error)

# The turn itself. Drawn after the transcript so the composing row appears at
# the foot of the conversation, where the next line will actually land.
if ss.pending:
    try:
        agent_id = api.next_speaker(ss.transcript)
        name, colour = AGENTS[agent_id]
        with st.chat_message(name, avatar=portrait(agent_id)):
            st.markdown(
                f"<span style='color:{colour};font-weight:600'>{name}</span>",
                unsafe_allow_html=True,
            )
            with st.spinner(f"{name} is composing…"):
                text = api.take_turn(ss.transcript, agent_id, ss.conversation_id)
        ss.transcript.append({"role": agent_id, "content": text})
        ss.error = None
        persist()
    except api.ApiError as err:
        ss.error = str(err)
    finally:
        ss.pending = False
    st.rerun()

# One message at a time: after each reply the reader chooses to respond, or to
# invite the next mind in. Nothing auto-advances.
if ss.transcript and not ss.pending:
    if st.button("hear another mind  →"):
        ss.pending = True
        st.rerun()

if prompt := st.chat_input("say what you're thinking…"):
    ss.transcript.append({"role": "user", "content": prompt})
    persist()
    ss.pending = True
    st.rerun()
