"use client";

import { AGENTS, type AgentId } from "@/app/lib/agents";
import { AGENT_BLURB, agentVars } from "./agent-theme";
import Avatar from "./Avatar";
import Composer from "./Composer";

// Each card enters with its agent's own signature motion, so the personalities
// are legible before a single word is spoken.
const ENTRANCE: Record<AgentId, string> = {
  introspector: "enter-introspector",
  behaviorist: "enter-behaviorist",
  gardener: "enter-gardener",
};

export default function Landing({
  agentIds,
  input,
  onInputChange,
  onSubmit,
  busy,
}: {
  agentIds: AgentId[];
  input: string;
  onInputChange: (v: string) => void;
  onSubmit: () => void;
  busy: boolean;
}) {
  return (
    <div className="landing">
      <div className="landing-inner">
        {/* Three tiers, in the order they should be read: the name of the
            place, the idea behind it, then what to expect once you're in. */}
        <header className="landing-head">
          <h1>Other Minds</h1>
          {/* Each sentence is its own inline-block, so when the line has to
              break it breaks between them — never mid-thought. */}
          <p className="landing-idea">
            <span>One question.</span> <span>Three ways of seeing it.</span>
          </p>
          <p className="landing-sub">
            They won&apos;t agree — and each will take the conversation
            somewhere the others wouldn&apos;t.
          </p>
        </header>

        <div className="minds">
          {agentIds.map((id) => (
            <article
              key={id}
              className={`mind-card ${ENTRANCE[id]}`}
              style={agentVars(id)}
            >
              <Avatar agent={id} size={84} active />
              <div className="mind-copy">
                <h2>{AGENTS[id].name}</h2>
                <p>{AGENT_BLURB[id]}</p>
              </div>
            </article>
          ))}
        </div>

        <div className="landing-composer">
          <Composer
            value={input}
            onChange={onInputChange}
            onSubmit={onSubmit}
            disabled={busy}
            placeholder="say what you're thinking…"
            autoFocus
          />
          <p className="landing-hint">
            they speak one at a time — press <span aria-hidden="true">↑</span> to
            let another mind speak
          </p>
        </div>
      </div>
    </div>
  );
}
