"use client";

import { useRef } from "react";
import { AGENTS, type AgentId } from "@/app/lib/agents";
import { agentVars } from "./agent-theme";
import Avatar from "./Avatar";

// How far a drag has to travel to count as "reply", and the furthest the
// message will follow the finger. Past the threshold it resists, the way a
// message on a phone does.
const THRESHOLD = 56;
const RESIST = 0.28;
const MAX_PULL = 92;

/**
 * One message from a mind — and the ways to reply to it.
 *
 * Swipe right (touch or pen) and the message slides out of the way to show a
 * reply arrow; let go past the threshold and you are replying to THAT mind. A
 * mouse gets a reply button on hover instead, because a mouse drag is how text
 * gets selected and the two must not fight. The button is in the tab order for
 * everyone else who cannot swipe.
 *
 * The row is the same single element it always was — a wrapper here would break
 * the sibling selectors that space a run of messages (`.row + .row`).
 */
export default function AgentRow({
  mind,
  carriesOn,
  enter,
  onReply,
  children,
}: {
  mind: AgentId;
  carriesOn: boolean;
  /** The entrance animation class for this mind. */
  enter: string;
  onReply: () => void;
  children: React.ReactNode;
}) {
  const rowRef = useRef<HTMLDivElement>(null);
  // Held in a ref and written straight to the element: a drag fires dozens of
  // events a second, and re-rendering the whole thread for each would stutter.
  const drag = useRef<{
    id: number;
    x: number;
    y: number;
    axis: "h" | "v" | null;
    armed: boolean;
  } | null>(null);

  function pull(px: number) {
    const el = rowRef.current;
    if (!el) return;
    el.style.setProperty("--swipe", `${px}px`);
    el.style.setProperty("--swipe-p", String(Math.min(1, px / THRESHOLD)));
  }

  function release() {
    const el = rowRef.current;
    drag.current = null;
    if (!el) return;
    el.classList.remove("swiping");
    pull(0);
  }

  function onPointerDown(e: React.PointerEvent) {
    if (e.pointerType === "mouse" || !e.isPrimary) return;
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, axis: null, armed: false };
  }

  function onPointerMove(e: React.PointerEvent) {
    const d = drag.current;
    if (!d || e.pointerId !== d.id) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;

    // Decide once, early, whether this is a swipe or a scroll. Reading it as a
    // swipe only when it is clearly sideways is what stops reading down the
    // page from nudging messages around.
    if (d.axis === null) {
      if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
      d.axis = dx > 0 && Math.abs(dx) > Math.abs(dy) * 1.3 ? "h" : "v";
      if (d.axis === "h") rowRef.current?.classList.add("swiping");
    }
    if (d.axis !== "h") return;

    const x = Math.max(0, dx);
    const pulled =
      x <= THRESHOLD ? x : Math.min(MAX_PULL, THRESHOLD + (x - THRESHOLD) * RESIST);
    pull(pulled);

    // A tick the moment it will take, so you feel the threshold without looking.
    if (!d.armed && x >= THRESHOLD) {
      d.armed = true;
      navigator.vibrate?.(9);
    } else if (d.armed && x < THRESHOLD) {
      d.armed = false;
    }
  }

  function onPointerUp(e: React.PointerEvent) {
    const d = drag.current;
    if (!d || e.pointerId !== d.id) return;
    const reply = d.axis === "h" && e.clientX - d.x >= THRESHOLD;
    release();
    if (reply) onReply();
  }

  const name = AGENTS[mind].name;
  return (
    <div
      ref={rowRef}
      className={`row agent ${enter}${carriesOn ? " carries-on" : ""}`}
      style={agentVars(mind)}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={release}
    >
      {children}

      {/* Where the message was, uncovered as it slides: the arrow. */}
      <span className="swipe-hint" aria-hidden="true">
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M9 14 4 9l5-5" />
          <path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5v0a5.5 5.5 0 0 1-5.5 5.5H11" />
        </svg>
      </span>

      <button
        type="button"
        className="reply-btn"
        onClick={onReply}
        aria-label={`Reply to ${name}`}
        title={`Reply to ${name}`}
      >
        <svg
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M9 14 4 9l5-5" />
          <path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5v0a5.5 5.5 0 0 1-5.5 5.5H11" />
        </svg>
      </button>
    </div>
  );
}
