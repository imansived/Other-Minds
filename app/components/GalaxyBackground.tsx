/**
 * The sky behind the room.
 *
 * Three glows wandering past one another, three parallax star layers drifting
 * at their own speeds, and a vignette that lets the corners fall away. Star
 * positions come from a seeded PRNG so the server and client render
 * byte-identical markup (a random layout here would trip a hydration
 * mismatch).
 *
 * All motion is switched off under `prefers-reduced-motion` in globals.css —
 * the scene stays, it just stops moving.
 */
import type { CSSProperties } from "react";

// mulberry32 — tiny deterministic PRNG.
function seeded(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface LayerSpec {
  seed: number;
  count: number;
  /** Dot diameter in px. */
  size: number;
  /** Base opacity of the whole layer. */
  opacity: number;
  /** How many of the stars twinkle, as a fraction. */
  twinkle: number;
  /** How many wander a few pixels on their own, as a fraction. */
  float: number;
  /** Which drift keyframe this layer rides. */
  drift: "a" | "b" | "c";
}

// Far → near. The nearest layer is biggest, brightest and drifts fastest.
const LAYERS: LayerSpec[] = [
  { seed: 20260813, count: 78, size: 1.1, opacity: 0.42, twinkle: 0.34, float: 0.25, drift: "a" },
  { seed: 77712, count: 46, size: 1.7, opacity: 0.6, twinkle: 0.55, float: 0.5, drift: "b" },
  { seed: 4242, count: 26, size: 2.4, opacity: 0.82, twinkle: 0.78, float: 0.85, drift: "c" },
];

function Layer({ spec, index }: { spec: LayerSpec; index: number }) {
  const rand = seeded(spec.seed);
  const stars = Array.from({ length: spec.count }, () => {
    const top = rand() * 100;
    const left = rand() * 100;
    const twinkles = rand() < spec.twinkle;
    const floats = rand() < spec.float;
    const delay = rand() * 6;
    const dur = 2.4 + rand() * 3.6;
    const dim = 0.5 + rand() * 0.5;
    // Where this star wanders to at the halfway point, and how long it takes.
    const fx = (rand() * 2 - 1) * 10;
    const fy = (rand() * 2 - 1) * 10;
    const floatDur = 12 + rand() * 14;
    const floatDelay = rand() * 12;
    return { top, left, twinkles, floats, delay, dur, dim, fx, fy, floatDur, floatDelay };
  });

  return (
    <div className={`star-layer drift-${spec.drift}`} style={{ opacity: spec.opacity }}>
      {stars.map((s, i) => {
        // A star can carry the twinkle, the float, both, or neither — so the
        // animation shorthand parts are assembled per star.
        const names: string[] = [];
        const durations: string[] = [];
        const delays: string[] = [];
        if (s.twinkles) {
          names.push("twinkle");
          durations.push(`${s.dur}s`);
          delays.push(`${s.delay}s`);
        }
        if (s.floats) {
          names.push("star-float");
          durations.push(`${s.floatDur}s`);
          delays.push(`${s.floatDelay}s`);
        }

        const style: CSSProperties = {
          top: `${s.top}%`,
          left: `${s.left}%`,
          width: spec.size,
          height: spec.size,
          opacity: s.dim,
        };
        if (names.length) {
          style.animationName = names.join(", ");
          style.animationDuration = durations.join(", ");
          style.animationDelay = delays.join(", ");
        }
        if (s.floats) {
          (style as Record<string, string | number>)["--fx"] = `${s.fx}px`;
          (style as Record<string, string | number>)["--fy"] = `${s.fy}px`;
        }

        return <span key={`${index}-${i}`} className="star" style={style} />;
      })}
    </div>
  );
}

export default function GalaxyBackground() {
  return (
    <div className="galaxy" aria-hidden="true">
      <div className="nebula nebula-purple" />
      <div className="nebula nebula-indigo" />
      <div className="nebula nebula-amber" />

      {LAYERS.map((spec, i) => (
        <Layer key={i} spec={spec} index={i} />
      ))}

      <div className="vignette" />
    </div>
  );
}
