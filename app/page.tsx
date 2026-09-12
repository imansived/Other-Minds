"use client";

import { useEffect, useRef, useState } from "react";
import { AGENTS, type AgentId, type ChatMessage } from "@/app/lib/agents";
import { agentVars } from "@/app/components/agent-theme";
import Avatar from "@/app/components/Avatar";
import Composer from "@/app/components/Composer";
import GalaxyBackground from "@/app/components/GalaxyBackground";
import Landing from "@/app/components/Landing";
import Sidebar from "@/app/components/Sidebar";
import {
  fetchConversation,
  HttpError,
  listConversations,
  makeId,
  removeConversation,
  saveConversation,
  titleFor,
  type Conversation,
} from "@/app/lib/history";
import {
  loadMuted,
  playPop,
  prefersReducedMotion,
  saveMuted,
} from "@/app/lib/sound";

// ── Turn logic ──────────────────────────────────────────────────────────────
// Who speaks next is decided by the backend now (see
// backend/app/orchestrator.py), not here — the rule is the same weighted-random
// one, but it is app logic rather than view logic, and keeping it in one place
// stops a second frontend from drifting out of step with this one.
//
// Agents still speak ONE message at a time: after each reply the user reads it
// and chooses to either respond, or press Continue to hear the next agent.
// Nothing is auto-advanced, so the user is never bombarded.
const AGENT_IDS: AgentId[] = ["introspector", "behaviorist", "gardener"];

// The composing indicator stays up for at least this long even if the API
// returns instantly — a brief deliberate pause reads better than a text dump.
const MIN_COMPOSE_MS = 1200;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// Per-agent entrance animation class — personality expressed as motion.
const ENTRANCE: Record<AgentId, string> = {
  introspector: "enter-introspector",
  behaviorist: "enter-behaviorist",
  gardener: "enter-gardener",
};

// How long each agent's entrance takes to reach the point where the bubble
// settles. The pop belongs to that instant, not to the instant the message
// starts fading in — the two are the better part of a second apart for the
// slowest arrival, and a sound that early reads as unrelated to the message.
// Kept in step with the `.enter-* .bubble` animation-delays in globals.css.
const LANDING_MS: Record<AgentId, number> = {
  introspector: 870,
  behaviorist: 440,
  gardener: 650,
};

export default function Home() {
  const [transcript, setTranscript] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  // The agent currently composing a reply (drives the composing row + ring).
  const [composingAgent, setComposingAgent] = useState<AgentId | null>(null);
  const [error, setError] = useState<string | null>(null);

  const conversationRef = useRef<HTMLDivElement>(null);
  const anchorRef = useRef<HTMLDivElement>(null);

  // ── Sound ─────────────────────────────────────────────────────────────────
  // Starts silent for the server render and the first paint, then takes the
  // saved preference on the client, so the icon never flips after hydration.
  // The ref is what the turn actually reads: a turn spans an await, and by the
  // time it lands the reader may have hit mute.
  const [muted, setMuted] = useState(false);
  const mutedRef = useRef(false);

  function toggleMute() {
    setMuted((v) => {
      const next = !v;
      mutedRef.current = next;
      saveMuted(next);
      return next;
    });
  }

  // ── Presentation state: history sidebar ───────────────────────────────────
  const [history, setHistory] = useState<Conversation[]>([]);
  // Distinct from `error`: an empty sidebar and an unreachable service look
  // identical otherwise, which makes a broken backend read as "no history yet".
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [collapsed, setCollapsed] = useState(false); // ≥720px: in-place collapse
  const [mobileOpen, setMobileOpen] = useState(false); // <720px: overlay
  const currentIdRef = useRef<string | null>(null);
  const [currentId, setCurrentId] = useState<string | null>(null);
  // Whether the reader was already at the foot of the conversation when the
  // last message landed. Tracked on scroll rather than measured afterwards,
  // because by the time the effect runs the new message has already grown the
  // scroll height.
  const atFootRef = useRef(true);

  // A turn is now two requests — ask who speaks, then ask them to speak. The
  // gap between them is a moment where no one is composing yet, so `busy` has
  // to cover it too or the composer would accept a second send.
  const [resolvingSpeaker, setResolvingSpeaker] = useState(false);
  const turnInFlightRef = useRef(false);
  const busy = composingAgent !== null || resolvingSpeaker;

  function trackScrollPosition() {
    const el = conversationRef.current;
    if (!el) return;
    atFootRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 140;
  }

  // Follow the conversation down only if the reader is already down there.
  // Someone re-reading an earlier exchange is left where they are.
  useEffect(() => {
    if (!atFootRef.current) return;
    anchorRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [transcript, composingAgent]);

  // Read saved conversations — and whether the room is meant to be silent —
  // once, on the client.
  useEffect(() => {
    const saved = loadMuted();
    mutedRef.current = saved;
    setMuted(saved);
    setHydrated(true);
    // History is a convenience — if the service is down the room still works.
    // But say so in the sidebar rather than showing an empty list, which would
    // claim there is no history when the truth is that we could not ask.
    void listConversations()
      .then((rows) => {
        setHistory(rows);
        setHistoryError(null);
      })
      .catch(() => setHistoryError("history unavailable — is the service running?"));
  }, []);

  // Mirror the live transcript to the service as it grows. The sidebar is
  // updated optimistically so the row moves the instant a message lands,
  // without waiting on the round trip.
  useEffect(() => {
    if (!hydrated || transcript.length === 0) return;
    const id = ensureConversationId();
    const title = titleFor(transcript);
    setHistory((prev) => [
      { id, title, updatedAt: Date.now(), messageCount: transcript.length },
      ...prev.filter((c) => c.id !== id),
    ]);
    void saveConversation(id, title, transcript).catch(() => {});
  }, [transcript, hydrated]);

  // Read a response as JSON without assuming it IS JSON.
  //
  // A bare res.json() on a non-JSON body throws "Unexpected token 'I' ... is
  // not valid JSON" — the reader sees a parser complaint instead of the actual
  // failure. The proxy now guarantees JSON, but this is the last line of
  // defence and costs nothing.
  async function readReply(res: Response): Promise<Record<string, unknown>> {
    const raw = await res.text();
    try {
      return JSON.parse(raw) as Record<string, unknown>;
    } catch {
      throw new Error(
        res.ok
          ? "The server sent something unreadable."
          : `Request failed (HTTP ${res.status}).`,
      );
    }
  }

  // Ask the backend who speaks next. No model call — it returns immediately,
  // which is what lets the composing row name the agent before the reply lands.
  async function askNextSpeaker(
    history: ChatMessage[],
    allowSameSpeaker: boolean,
  ): Promise<AgentId> {
    const res = await fetch("/api/agent/next-speaker", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript: history, allowSameSpeaker }),
    });
    const data = await readReply(res);
    if (!res.ok) throw new Error((data.error as string) ?? "Request failed");
    return data.agentId as AgentId;
  }

  // The conversation a turn belongs to.
  //
  // Assigned here rather than left to the mirroring effect below, because a
  // turn is generated BEFORE that effect runs — so on the opening message the
  // id would still be null. Every turn taken that way was stored unattributed,
  // and an unattributed turn can never be joined back to what was said around
  // it. That is what made the stored corpus unusable: 16 of the turns actually
  // served to a reader carry no conversation at all, and no backfill can
  // recover them.
  function ensureConversationId(): string {
    if (!currentIdRef.current) {
      currentIdRef.current = makeId();
      setCurrentId(currentIdRef.current);
    }
    return currentIdRef.current;
  }

  // Ask one agent for its next line, given the transcript-so-far.
  async function askAgent(
    agentId: AgentId,
    history: ChatMessage[],
  ): Promise<string> {
    const res = await fetch("/api/agent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agentId,
        transcript: history,
        conversationId: ensureConversationId(),
      }),
    });
    const data = await readReply(res);
    if (!res.ok) throw new Error((data.error as string) ?? "Request failed");
    return data.text as string;
  }

  // Run one full agent turn: show the composing state (for at least
  // MIN_COMPOSE_MS), fetch the real reply, reveal it, and return the new
  // transcript (or null if the turn failed).
  async function runAgentTurn(
    agentId: AgentId,
    history: ChatMessage[],
  ): Promise<ChatMessage[] | null> {
    setError(null);
    setComposingAgent(agentId);
    const started = Date.now();
    try {
      const text = await askAgent(agentId, history);
      const elapsed = Date.now() - started;
      if (elapsed < MIN_COMPOSE_MS) await sleep(MIN_COMPOSE_MS - elapsed);
      const updated: ChatMessage[] = [...history, { role: agentId, content: text }];
      setTranscript(updated);
      // Sounded on arrival only — never when an old conversation is reopened.
      // Checked again when it fires, so a mute during the entrance still lands.
      if (!mutedRef.current) {
        const delay = prefersReducedMotion() ? 0 : LANDING_MS[agentId];
        window.setTimeout(() => {
          if (!mutedRef.current) playPop();
        }, delay);
      }
      return updated;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      return null;
    } finally {
      setComposingAgent(null);
    }
  }

  // One full turn, end to end: ask the backend who speaks next, then ask them
  // to speak. Split in two so the composing row can name the agent and light
  // its portrait while the reply is still being written.
  // `allowSameSpeaker` is false when the person pressed "hear another mind".
  // The draw is made once, here, and the chosen agent is then pinned for the
  // generate call — so the two requests cannot disagree about who is speaking.
  async function runTurn(history: ChatMessage[], allowSameSpeaker = true) {
    // `busy` comes from the render closure, so it can still be stale for a
    // click that lands before React re-renders. The ref is checked and set in
    // the same synchronous step, which a second call cannot slip past.
    if (turnInFlightRef.current) return;
    turnInFlightRef.current = true;
    setError(null);
    setResolvingSpeaker(true);

    let agentId: AgentId;
    try {
      agentId = await askNextSpeaker(history, allowSameSpeaker);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setResolvingSpeaker(false);
      turnInFlightRef.current = false;
      return;
    }

    // Cleared in the same synchronous block that sets the composing agent, so
    // the two state updates batch and `busy` never dips false between them.
    setResolvingSpeaker(false);
    try {
      await runAgentTurn(agentId, history);
    } finally {
      turnInFlightRef.current = false;
    }
  }

  // Advance the conversation by exactly ONE agent message, then wait for the
  // user again (the Continue button, or an empty-box send, both call this).
  // The button says "hear another mind", so it must produce another mind. The
  // ~1-in-4 double turn belongs to the case where the person REPLIES and the
  // room carries on by itself, not to the case where they asked for someone
  // else in as many words.
  function advance() {
    if (busy || transcript.length === 0) return;
    void runTurn(transcript, false);
  }

  // Input-bar send: with text, drop the user's message in and let ONE agent
  // reply to it; with an empty box, just advance to the next agent.
  function handleSend() {
    if (busy) return;
    const content = input.trim();
    if (content) {
      setInput("");
      const base: ChatMessage[] = [...transcript, { role: "user", content }];
      setTranscript(base);
      void runTurn(base);
    } else {
      advance();
    }
  }

  // ── History actions (presentation only) ───────────────────────────────────
  function toggleNav() {
    setCollapsed((v) => !v);
    setMobileOpen((v) => !v);
  }

  function startNew() {
    if (busy) return;
    currentIdRef.current = null;
    setCurrentId(null);
    setTranscript([]);
    setInput("");
    setError(null);
    setMobileOpen(false);
    atFootRef.current = true;
  }

  // The sidebar row carries no transcript, so opening one fetches it.
  async function openConversation(c: Conversation) {
    if (busy) return;
    try {
      const full = await fetchConversation(c.id);
      currentIdRef.current = c.id;
      setCurrentId(c.id);
      setTranscript(full.transcript);
      setError(null);
      setMobileOpen(false);
      atFootRef.current = true;
    } catch (err) {
      if (err instanceof HttpError && err.status === 404) {
        // A stale row: the conversation is gone from the service, but this tab
        // still lists it. Drop it so the sidebar stops offering something that
        // cannot be opened.
        setHistory((prev) => prev.filter((h) => h.id !== c.id));
        setError("That conversation is no longer stored.");
      } else {
        setError("Couldn't open that conversation.");
      }
    }
  }

  function deleteConversation(id: string) {
    setHistory((prev) => prev.filter((c) => c.id !== id));
    void removeConversation(id).catch(() => {});
    if (currentIdRef.current === id) {
      currentIdRef.current = null;
      setCurrentId(null);
      setTranscript([]);
    }
  }

  // Who is speaking is said by the messages themselves, so the chrome carries
  // no agent state at all.
  const onLanding = transcript.length === 0;

  return (
    <div className="app">
      <GalaxyBackground />

      <Sidebar
        conversations={history}
        error={historyError}
        currentId={currentId}
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onSelect={openConversation}
        onDelete={deleteConversation}
        onNew={startNew}
      />
      {mobileOpen && (
        <button
          type="button"
          className="scrim"
          aria-label="Close conversation history"
          onClick={toggleNav}
        />
      )}

      <main className="main">
        {/* Chrome: history toggle and a way back to a blank room. Nothing about
            who is speaking — the conversation says that itself. */}
        <header className="topbar">
          <button
            type="button"
            className="icon-btn"
            onClick={toggleNav}
            aria-label="Toggle conversation history"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>

          <button
            type="button"
            className="icon-btn"
            onClick={startNew}
            aria-label="Start a new conversation"
            disabled={busy || onLanding}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
        </header>

        {onLanding ? (
          <Landing
            agentIds={AGENT_IDS}
            input={input}
            onInputChange={setInput}
            onSubmit={handleSend}
            busy={busy}
          />
        ) : (
          <>
            {/* Conversation. */}
            <div
              className="conversation"
              ref={conversationRef}
              onScroll={trackScrollPosition}
            >
              <div className="thread">
                {transcript.map((m, i) => {
                  // A mind may hold the floor for several turns running. When it
                  // does, the run closes up and only the first of them carries a
                  // portrait, so it reads as one person still thinking rather
                  // than as three separate arrivals.
                  const carriesOn = i > 0 && transcript[i - 1].role === m.role;

                  if (m.role === "user") {
                    return (
                      <div
                        key={i}
                        className={`row user enter-user${carriesOn ? " carries-on" : ""}`}
                      >
                        <div className="bubble user">{m.content}</div>
                      </div>
                    );
                  }

                  const agent = AGENTS[m.role];
                  return (
                    <div
                      key={i}
                      className={`row agent ${ENTRANCE[m.role]}${
                        carriesOn ? " carries-on" : ""
                      }`}
                      style={agentVars(m.role)}
                    >
                      <div className="gutter">
                        {!carriesOn && (
                          <Avatar agent={m.role} size={38} active className="row-avatar" />
                        )}
                      </div>
                      <div className="msg-col">
                        {/* The name lives inside the bubble, so the speaker and
                            what they said arrive as one object rather than a
                            label with a card under it. */}
                        <div className="bubble agent">
                          {!carriesOn && (
                            <span className="bubble-name">{agent.name}</span>
                          )}
                          {m.content}
                        </div>
                      </div>
                    </div>
                  );
                })}

                {/* About to speak — a lit portrait, a name, three dots. */}
                {composingAgent && (
                  <div
                    className="composing"
                    style={agentVars(composingAgent)}
                    aria-label={`${AGENTS[composingAgent].name} is about to speak`}
                  >
                    <Avatar agent={composingAgent} size={28} active />
                    <span className="composing-name">
                      {AGENTS[composingAgent].name}
                    </span>
                    <span className="dots" aria-hidden="true">
                      <span />
                      <span />
                      <span />
                    </span>
                  </div>
                )}

                {error && <div className="error">{error}</div>}

                {/* Invite the next mind in — one message at a time. */}
                {transcript.length > 0 && !busy && (
                  <button type="button" className="continue" onClick={advance}>
                    {error ? "try again" : "hear another mind"}
                    {!error && (
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                      >
                        <path d="M5 12h14" />
                        <path d="m12 5 7 7-7 7" />
                      </svg>
                    )}
                  </button>
                )}

                <div ref={anchorRef} />
              </div>
            </div>

            {/* Single unified input / control bar. */}
            <div className="composer-dock">
              <Composer
                value={input}
                onChange={setInput}
                onSubmit={handleSend}
                disabled={busy}
                placeholder="say what you're thinking…"
                muted={muted}
                onToggleMute={toggleMute}
              />
              {/* With nothing typed, the arrow isn't "send" — it's the room
                  carrying on without you. Say so, quietly. */}
              {!input.trim() && !busy && (
                <p className="composer-hint">
                  or use the arrow to invite another mind
                </p>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
