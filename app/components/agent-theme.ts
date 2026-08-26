// Presentation-only agent theming. No behaviour lives here — just the CSS
// custom-property values each agent's UI is painted with.
import type { AgentId } from "@/app/lib/agents";

// Per-agent identity color, for driving the `--agent` CSS variable inline.
export const AGENT_COLOR: Record<AgentId, string> = {
  introspector: "var(--introspector)",
  behaviorist: "var(--behaviorist)",
  gardener: "var(--gardener)",
};

// The dimmer companion shade, used for bubble borders and idle states.
export const AGENT_DIM: Record<AgentId, string> = {
  introspector: "var(--introspector-dim)",
  behaviorist: "var(--behaviorist-dim)",
  gardener: "var(--gardener-dim)",
};

/**
 * Optional portrait per agent. Drop the file into `public/minds/` and name it
 * here and it takes over the avatar; with no entry, the silhouette stays.
 */
export const AGENT_PORTRAIT: Partial<Record<AgentId, string>> = {
  introspector: "/minds/introspector.jpg",
  behaviorist: "/minds/behaviorist.jpg",
  gardener: "/minds/gardener.jpg",
};

export interface PortraitFrame {
  /** `background-size`. Default `cover` fills the disc and crops the long edge. */
  size?: string;
  /** `background-position` — slides the crop window over the subject. */
  position?: string;
  /** Painted behind the image, for portraits that don't reach the disc edge. */
  fill?: string;
}

/**
 * How each portrait is fitted into its circle. Every number below came from
 * measuring the file — see public/minds/README.md for the method and for the
 * formula that turns a chosen crop into these two values.
 */
export const AGENT_PORTRAIT_FRAME: Partial<Record<AgentId, PortraitFrame>> = {
  // 1254×1254. A figure in silhouette against a lit wall — measured on a
  // luminance threshold of 35, which is what separates her (10-25) from the
  // wall she is lit against (50-62). Head and raised hand sit at x 313→702,
  // y 419→759; the shoulder line reaches full width at y 779; the dark window
  // frame starts at x 853 and the crop stops short of it. The disc takes a
  // 720px square centred at (480, 600) — head across 45% of the width, which
  // leaves the sunlit wall and the shadow line falling across it in frame
  // behind her, and her shoulder along the foot. Past 100% the image covers
  // the disc outright, so no fill.
  introspector: { size: "174%", position: "22% 45%" },
  // 1254×1254. Someone walking away down a lit street, backlit — the whole
  // point of the picture is the walking, so this is framed on the figure in
  // the street rather than cropped to a head. His right-hand profile is the
  // clean edge to measure against: hair from y 300, widest at x 622 by y 360,
  // pinching to 598 at the neck (y 420), shoulders opening again from y 435;
  // body and pack at their widest run x 405→694 around y 615. His left side
  // is not measurable — it merges into the dark doorway behind him, which is
  // also why he needs the lit path to read at all: he sits at luminance 15
  // against a path at 150, and that gap is what survives being 32px wide. The
  // disc takes a 900px square centred at (700, 600) — offset well right of him
  // on purpose, so he sits in the left third of the circle and the lit street
  // he is walking down occupies the rest of it. Centring him would have made
  // it a portrait of a man; this keeps it a picture of someone out in the
  // world, walking. Over 100%, so no fill.
  behaviorist: { size: "139%", position: "71% 42%" },
  // 1195×896 — the only one of the three that isn't square, hence the explicit
  // `auto` height. Someone tending a pot at a window, and too green for a
  // plain luminance threshold to find him: leaves and shirt sit in the same
  // band. What separates them is greenness, G - max(R, B), which the foliage
  // runs positive on and his hair and shirt do not. Masked that way the head
  // measures x 500→735, y 130→380; his lit hands on the pot are the brightest
  // thing low in the frame, at (797, 629). The disc takes a 780px square
  // centred at (695, 460), which holds head, hands and pot together with him
  // at 40% across — the plants and the window take the rest. Over 100%, so no
  // fill.
  gardener: { size: "153% auto", position: "73% 60%" },
};

// One-line stance blurbs — landing-screen copy only.
export const AGENT_BLURB: Record<AgentId, string> = {
  introspector: "The mind is known from the inside. What you feel is data.",
  behaviorist: "What you repeatedly do says more than what you say you feel.",
  gardener: "A life is lived in relationship — not solved alone in your head.",
};

// Inline style object carrying both color variables for a given agent.
export function agentVars(id: AgentId): React.CSSProperties {
  return {
    ["--agent" as string]: AGENT_COLOR[id],
    ["--agent-dim" as string]: AGENT_DIM[id],
  } as React.CSSProperties;
}
