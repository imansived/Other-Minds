// The small sound a message makes when it lands.
//
// Synthesised rather than loaded: a short sine with a quick rise and a soft
// tail, run through a lowpass so there is no click on the attack. Keeping it
// in code means no asset request, and it stays quiet by construction — the
// gain ceiling here is the only volume it can ever reach.

const MUTE_KEY = "other-minds:muted:v1";

let ctx: AudioContext | null = null;

/** The reader's saved preference. Silent (false) until the client says otherwise. */
export function loadMuted(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(MUTE_KEY) === "1";
  } catch {
    return false;
  }
}

export function saveMuted(muted: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(MUTE_KEY, muted ? "1" : "0");
  } catch {
    // A blocked storage shouldn't cost the reader a working toggle.
  }
}

/** True when the reader has asked for stillness — the caller drops any delay. */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function audioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const AC: typeof AudioContext | undefined =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext;
  if (!AC) return null;
  // Built on first play, never at import: by then the reader has typed and
  // pressed something, so the context starts unblocked under the autoplay
  // policy. The resume below covers a tab that was backgrounded since.
  ctx ??= new AC();
  return ctx;
}

/** A soft, short pop — one note, about a fifth of a second, well under the voice. */
export function playPop(): void {
  const ac = audioContext();
  if (!ac) return;
  if (ac.state === "suspended") void ac.resume();

  const t = ac.currentTime;

  const osc = ac.createOscillator();
  osc.type = "sine";
  // A small upward bend is what reads as a "pop" rather than a beep.
  osc.frequency.setValueAtTime(430, t);
  osc.frequency.exponentialRampToValueAtTime(760, t + 0.055);

  // Takes the edge off the attack, so it arrives rather than snaps.
  const tone = ac.createBiquadFilter();
  tone.type = "lowpass";
  tone.frequency.setValueAtTime(2200, t);

  const gain = ac.createGain();
  gain.gain.setValueAtTime(0.0001, t);
  gain.gain.exponentialRampToValueAtTime(0.055, t + 0.014);
  gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);

  osc.connect(tone).connect(gain).connect(ac.destination);
  osc.start(t);
  osc.stop(t + 0.22);
}
