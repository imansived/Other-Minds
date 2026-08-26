"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * The one pill-shaped input bar, shared by the landing and chat screens.
 * It owns no behaviour beyond its own height: text and submit are handed down
 * from the page, which keeps the send-vs-advance decision exactly where it
 * already lived.
 *
 * The field is a textarea rather than a single line, because the question this
 * app is for is rarely one line. A single line scrolls what you wrote off to
 * the left as you type, so the opening of your own paragraph is gone by the
 * time you finish it — you end up writing blind. This grows downward instead,
 * up to a ceiling, and only then scrolls.
 */

// About seven lines. Past that the room above matters more than the box.
const MAX_HEIGHT = 168;

export default function Composer({
  value,
  onChange,
  onSubmit,
  disabled = false,
  placeholder,
  autoFocus = false,
  muted,
  onToggleMute,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
  placeholder: string;
  autoFocus?: boolean;
  /** Sound state. Both are omitted on the landing screen, where nothing arrives yet. */
  muted?: boolean;
  onToggleMute?: () => void;
}) {
  const areaRef = useRef<HTMLTextAreaElement>(null);
  // Past one line the pill stops being a pill: a 999px radius on a tall box
  // bows the sides in and eats the corners of the text.
  const [grown, setGrown] = useState(false);

  const resize = useCallback(() => {
    const el = areaRef.current;
    if (!el) return;
    // Collapse first, or scrollHeight only ever reports the height it already
    // has and the box can never shrink back after a deletion.
    el.style.height = "auto";
    const full = el.scrollHeight;
    const next = Math.min(full, MAX_HEIGHT);
    el.style.height = `${next}px`;
    el.style.overflowY = full > MAX_HEIGHT ? "auto" : "hidden";

    // Measured rather than guessed at, so a font or padding change can't
    // silently strand the pill in the wrong shape.
    const cs = getComputedStyle(el);
    const oneLine =
      parseFloat(cs.lineHeight) +
      parseFloat(cs.paddingTop) +
      parseFloat(cs.paddingBottom);
    setGrown(next > oneLine + 2);
  }, []);

  // Every keystroke, and every width change — a narrower window re-wraps the
  // same text onto more lines.
  useEffect(resize, [value, resize]);
  useEffect(() => {
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [resize]);

  return (
    <form
      className={`composer${grown ? " grown" : ""}`}
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <textarea
        ref={areaRef}
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          // Enter sends, shift-Enter breaks the line. The composition guard is
          // for IME input, where Enter is how a candidate is accepted and must
          // not also fire the message.
          if (
            e.key === "Enter" &&
            !e.shiftKey &&
            !e.nativeEvent.isComposing
          ) {
            e.preventDefault();
            onSubmit();
          }
        }}
        placeholder={placeholder}
        aria-label={placeholder}
        autoFocus={autoFocus}
      />
      {/* Sits inside the pill, left of send: near enough to the words to be
          found when the sound is what you want to stop, quiet enough to
          ignore otherwise. */}
      {onToggleMute && (
        <button
          type="button"
          className="mute-btn"
          onClick={onToggleMute}
          title={muted ? "unmute arrivals" : "mute arrivals"}
          aria-pressed={muted}
          aria-label={
            muted
              ? "Unmute the sound played when a mind speaks"
              : "Mute the sound played when a mind speaks"
          }
        >
          {/* lucide-style Volume2 / VolumeX */}
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M11 5 6 9H2v6h4l5 4V5z" />
            {muted ? (
              <>
                <path d="m22 9-6 6" />
                <path d="m16 9 6 6" />
              </>
            ) : (
              <>
                <path d="M15.5 8.5a5 5 0 0 1 0 7" />
                <path d="M19 5a10 10 0 0 1 0 14" />
              </>
            )}
          </svg>
        </button>
      )}

      <button
        type="submit"
        className="send"
        disabled={disabled}
        title={value.trim() ? "say it" : "let another mind speak"}
        aria-label={value.trim() ? "Send your message" : "Let another mind speak"}
      >
        {/* lucide-style ArrowUp */}
        <svg
          width="19"
          height="19"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m5 12 7-7 7 7" />
          <path d="M12 19V5" />
        </svg>
      </button>
    </form>
  );
}
