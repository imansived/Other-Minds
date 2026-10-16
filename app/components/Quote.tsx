import { AGENTS, type AgentId } from "@/app/lib/agents";
import { parseReply } from "@/app/lib/reply";
import { agentVars } from "./agent-theme";

/**
 * What the person said — and, when it was a reply, the line it was answering,
 * set into the top of the bubble the way a quoted message is on a phone.
 * Everything else renders exactly as before.
 */
export function UserMessage({ content }: { content: string }) {
  const { quote, text } = parseReply(content);
  if (!quote) return <>{content}</>;
  return (
    <>
      <span className="quote" style={agentVars(quote.mind)}>
        <span className="quote-name">{AGENTS[quote.mind].name}</span>
        <span className="quote-text">{quote.excerpt}</span>
      </span>
      {text}
    </>
  );
}

/**
 * The strip above the box while a reply is being written: who it is going to,
 * and the line it answers. Cancelling it sends the next message to the room as
 * usual.
 */
export function ReplyChip({
  mind,
  excerpt,
  onCancel,
}: {
  mind: AgentId;
  excerpt: string;
  onCancel: () => void;
}) {
  return (
    <div className="reply-chip" style={agentVars(mind)} role="group" aria-label="Replying">
      <span className="quote">
        <span className="quote-name">Replying to {AGENTS[mind].name}</span>
        <span className="quote-text">{excerpt}</span>
      </span>
      <button
        type="button"
        className="reply-chip-x"
        onClick={onCancel}
        aria-label={`Stop replying to ${AGENTS[mind].name}`}
        title="Cancel (Esc)"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M6 6l12 12M18 6 6 18" />
        </svg>
      </button>
    </div>
  );
}
