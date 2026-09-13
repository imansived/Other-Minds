/**
 * The sky behind the room.
 *
 * Three glows wandering past one another, three parallax star layers drifting
 * at their own speeds, and a vignette that lets the corners fall away. Star
 * positions come from a seeded PRNG so the server and client render
 * byte-identical markup (a random layout here would trip a hydration
 * mismatch).
 *
 * ── Why the sky is described rather than decided here ──────────────────────
 * The same field that reads as atmosphere on a wide screen reads as a busy
 * one on a phone: the stars aren't closer together, but the viewport is
 * smaller, so more of them land near what you are trying to read.
 *
 * The fix can't be "generate fewer stars when narrow" — the markup is rendered
 * on the server, which has no viewport, and branching on window width here
 * would mean a hydration mismatch or a field that pops after first paint.
 *
 * So this file only ever *describes* each star, and CSS decides what to do
 * with the description. Every star carries its brightness and its animation
 * timings as custom properties rather than as finished values, plus three
 * facts about itself:
 *
 *   star-thin  every third star, so a media query can thin the field
 *   star-mid   sits behind the column where the text lives
 *   star-keep  one of the bright few, and not behind the text
 *
 * Desktop reads none of those classes and multiplies every timing by 1, so
 * what it renders is byte-identical to before. The phone rules live in one
 * block in globals.css.
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

/**
 * Where the reading column falls, in a star layer's own coordinates.
 *
 * A layer is oversized and offset — top/left -12%, 124% square — so its drift
 * never shows an edge. That means a star at layer position L sits at viewport
 * position `-12 + 1.24 * L`. Inverting that for the viewport box the text
 * occupies on a phone (x 4→96%, y 10→88%) gives the numbers below. Stars
 * inside it are the ones a phone dims; the brighter few are chosen from what's
 * left, so nothing bright ever sits behind a line of type.
 */
const READING_BAND = { x0: 12.9, x1: 87.1, y0: 17.7, y1: 80.6 };

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

        const vars = (style: CSSProperties) =>
          style as Record<string, string | number>;

        const style: CSSProperties = {
          top: `${s.top}%`,
          left: `${s.left}%`,
          width: spec.size,
          height: spec.size,
        };
        // Brightness and durations are handed over as raw ingredients — CSS
        // scales them by one factor per viewport. On desktop that factor is 1.
        vars(style)["--star-o"] = s.dim;
        if (names.length) {
          style.animationName = names.join(", ");
          style.animationDelay = delays.join(", ");
          vars(style)["--a1"] = durations[0];
          if (durations[1]) vars(style)["--a2"] = durations[1];
        }
        if (s.floats) {
          vars(style)["--fx"] = `${s.fx}px`;
          vars(style)["--fy"] = `${s.fy}px`;
        }

        // Behind the text, and bright enough to notice, are the two things a
        // narrow screen has to care about. Both are read off values already
        // drawn — no extra calls into the PRNG, so the field itself is
        // unchanged.
        const mid =
          s.left > READING_BAND.x0 &&
          s.left < READING_BAND.x1 &&
          s.top > READING_BAND.y0 &&
          s.top < READING_BAND.y1;
        // Drawn from the two nearest layers, which are the ones carrying enough
        // layer opacity to read as bright at all. A star only counts as one of
        // the bright few if it is also clear of the text — and on a phone the
        // text covers roughly seven tenths of the screen, so the thresholds
        // have to be generous or the handful comes out as one or two. `dim` is
        // doing duty as the lottery here rather than as a brightness: a phone
        // lights these from --sky-star-o, not from the value they drew.
        const bright =
          (spec.drift === "c" && s.dim > 0.62) ||
          (spec.drift === "b" && s.dim > 0.82);
        const keep = bright && !mid;

        const marks = [
          // Thinning skips the bright few — otherwise the handful meant to
          // survive is exactly the handful at risk of being deleted.
          i % 3 === 0 && !keep ? "star-thin" : "",
          mid ? "star-mid" : "",
          keep ? "star-keep" : "",
        ].filter(Boolean);

        return (
          <span
            key={`${index}-${i}`}
            className={["star", ...marks].join(" ")}
            style={style}
          />
        );
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
