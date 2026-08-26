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
  // Tailwind classes used to visually distinguish this agent in the UI.
  bubbleClass: string;
  nameClass: string;
}

export const AGENTS: Record<AgentId, AgentConfig> = {
  introspector: {
    id: "introspector",
    name: "The Introspector",
    bubbleClass:
      "bg-indigo-50 border border-indigo-200 dark:bg-indigo-950/40 dark:border-indigo-900",
    nameClass: "text-indigo-700 dark:text-indigo-300",
  },
  behaviorist: {
    id: "behaviorist",
    name: "The Behaviorist",
    bubbleClass:
      "bg-amber-50 border border-amber-200 dark:bg-amber-950/40 dark:border-amber-900",
    nameClass: "text-amber-700 dark:text-amber-300",
  },
  gardener: {
    id: "gardener",
    name: "The Gardener",
    bubbleClass:
      "bg-emerald-50 border border-emerald-200 dark:bg-emerald-950/40 dark:border-emerald-900",
    nameClass: "text-emerald-700 dark:text-emerald-300",
  },
};
