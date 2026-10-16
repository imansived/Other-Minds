// Replying to one mind's message, WhatsApp-style.
//
// A reply is an ordinary user message with one line on top saying what it is
// answering:
//
//     ↪ replying to The Gardener — “Who else is in this?”
//
//     I don't think that's the question.
//
// It is kept in the message text, not in a new field, on purpose. The text is
// what is saved, what comes back when an old conversation is reopened, and what
// the mind being answered actually reads — a reply to something said six turns
// ago means nothing to it without the line it is replying to. Putting it in the
// text gives all three for free, with no schema change anywhere.
//
// Which mind answers is NOT decided from this text. The browser sends the chosen
// mind explicitly (`addressTo`), so a quote that happens to mention two minds
// can never make the choice ambiguous.

import { AGENTS, type AgentId } from "@/app/lib/agents";

const MARK = "↪ replying to";
const MAX_EXCERPT = 110;

/** One line of what was said: whitespace collapsed, cut at a word, quote-safe. */
export function excerptOf(text: string): string {
  // The closing quote is what the parser keys on, so it can't appear inside.
  const flat = text.replace(/\s+/g, " ").replace(/[“”]/g, '"').trim();
  if (flat.length <= MAX_EXCERPT) return flat;
  const cut = flat.slice(0, MAX_EXCERPT);
  const at = cut.lastIndexOf(" ");
  return `${(at > MAX_EXCERPT * 0.6 ? cut.slice(0, at) : cut).trimEnd()}…`;
}

export function formatReply(mind: AgentId, excerpt: string, text: string): string {
  return `${MARK} ${AGENTS[mind].name} — “${excerpt}”\n\n${text}`;
}

export interface ParsedMessage {
  quote: { mind: AgentId; excerpt: string } | null;
  text: string;
}

// The names are matched against the registry rather than a fixed pattern, so a
// fourth mind needs no change here.
const NAMES = Object.fromEntries(
  (Object.keys(AGENTS) as AgentId[]).map((id) => [AGENTS[id].name, id]),
) as Record<string, AgentId>;

export function parseReply(content: string): ParsedMessage {
  if (!content.startsWith(MARK)) return { quote: null, text: content };
  const m = /^↪ replying to (.+?) — “([^”]*)”\n\n([\s\S]*)$/.exec(content);
  const mind = m ? NAMES[m[1]] : undefined;
  if (!m || !mind) return { quote: null, text: content };
  return { quote: { mind, excerpt: m[2] }, text: m[3] };
}
