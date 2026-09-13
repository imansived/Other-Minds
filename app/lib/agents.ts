// Shared agent identity and chat types — the parts the UI needs.
//
// The system prompts are NOT here. They live in backend/app/agents/prompts/*.md
// and are loaded by backend/app/agents/registry.py, which is the only thing
// that needs them. Keeping a second copy in the client bundle meant ~16KB of
// prompt text shipped to every visitor and two sources of truth that could
// quietly drift apart.
//
// `name` IS still shared, and is load-bearing on both sides: the strings below
// must match AGENT_NAMES in the backend registry, because the prompts refer to
// the agents by these exact names.

export type AgentId = "introspector" | "behaviorist" | "gardener";

// Who "spoke" a given line in the visible transcript.
export type Speaker = "user" | AgentId;

export interface ChatMessage {
  role: Speaker;
  content: string;
}

export interface AgentConfig {
  id: AgentId;
  name: string;
}

export const AGENTS: Record<AgentId, AgentConfig> = {
  introspector: {
    id: "introspector",
    name: "The Introspector",
  },
  behaviorist: {
    id: "behaviorist",
    name: "The Behaviorist",
  },
  gardener: {
    id: "gardener",
    name: "The Gardener",
  },
};

/**
 * Turn order is the backend's business — this is only the reading order for the
 * three cards on the landing screen.
 *
 * Derived from AGENTS rather than written out again, so a fourth mind appears
 * on the landing by virtue of existing. The hand-kept copy this replaces sat in
 * page.tsx, where nothing connected it to the registry it was mirroring.
 */
export const AGENT_IDS = Object.keys(AGENTS) as AgentId[];
