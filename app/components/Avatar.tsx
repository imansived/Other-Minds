import type { AgentId } from "@/app/lib/agents";
import { AGENT_PORTRAIT, AGENT_PORTRAIT_FRAME, agentVars } from "./agent-theme";

/**
 * A strictly circular avatar. Width and height are locked in inline styles and
 * `flex: none` is set in CSS, so no flex or grid parent can ever squash it into
 * an oval.
 *
 * The person-silhouette placeholder is always rendered. When the agent has a
 * portrait, it is painted over the top as a background image — which means a
 * missing or misnamed file simply falls back to the silhouette instead of
 * leaving a broken-image glyph in the circle.
 */
export default function Avatar({
  agent,
  size,
  active = false,
  className = "",
}: {
  agent: AgentId;
  size: number;
  active?: boolean;
  className?: string;
}) {
  const portrait = AGENT_PORTRAIT[agent];
  const frame = AGENT_PORTRAIT_FRAME[agent];

  return (
    <span
      className={`avatar${active ? " active" : ""}${className ? ` ${className}` : ""}`}
      style={{ ...agentVars(agent), width: size, height: size }}
      aria-hidden="true"
    >
      <svg viewBox="0 0 24 24" fill="currentColor" focusable="false">
        <circle cx="12" cy="8.6" r="3.7" />
        <path d="M12 13.6c-3.7 0-6.8 2.3-7.6 5.4-.2.7.3 1.3 1 1.3h13.2c.7 0 1.2-.6 1-1.3-.8-3.1-3.9-5.4-7.6-5.4Z" />
      </svg>

      {portrait && (
        <span
          className="avatar-photo"
          style={{
            backgroundImage: `url(${portrait})`,
            backgroundSize: frame?.size ?? "cover",
            backgroundPosition: frame?.position ?? "50% 50%",
            backgroundColor: frame?.fill,
          }}
        />
      )}
    </span>
  );
}
