# Mind portraits

Drop an agent's portrait here and it replaces the silhouette placeholder in
every avatar — the header cluster, each message, the composing row and the
landing card — at every size.

| file               | agent            | wired up |
| ------------------ | ---------------- | -------- |
| `introspector.jpg` | The Introspector | yes      |
| `behaviorist.jpg`  | The Behaviorist  | yes      |
| `gardener.jpg`     | The Gardener     | yes      |

To wire up another one, add it to `AGENT_PORTRAIT` in
`app/components/agent-theme.ts`.

## Framing

With no entry in `AGENT_PORTRAIT_FRAME` (same file), an image is scaled to
**cover** the circle: any aspect ratio works, the long edge gets cropped, and
a subject near the centre needs nothing further.

For a subject that sits off-centre, or one that would otherwise be cropped by
the disc, give it a frame:

- `size` — `background-size`. Below `100%` the image no longer reaches the
  disc edge, so pair it with `fill`.
- `position` — `background-position`. Slides the crop window; second number is
  vertical, `0%` showing the top of the image and `100%` the bottom.
- `fill` — painted behind the image, covering whatever `size` left bare.

The three in place:

- **Introspector** — 1254×1254, a figure in silhouette against a sunlit wall.
  Head and raised hand at x 313→702, y 419→759; shoulders reach full width at
  y 779; the dark window frame starts at x 853. A 720px square centred on
  (480, 600) lands at `174%` / `22% 45%`, putting her head across 45% of the
  disc, with the sunlit wall and the shadow line across it left in frame
  behind her. Over 100%, so no fill.
- **Behaviorist** — 1254×1254, someone walking away down a lit street. Framed
  on the figure in the street, not cropped to a head — the walking is the
  picture. Measured down his right-hand profile: hair from y 300, widest at
  x 622 by y 360, neck pinching to 598 at y 420, shoulders from y 435; body
  and pack widest at x 405→694 around y 615. A 900px square centred on
  (700, 600) — offset right of him deliberately — lands at `139%` / `71% 42%`,
  putting him in the left third with the lit street filling the rest. Over
  100%, so no fill.
- **Gardener** — 1195×896, someone tending a pot at a window. The only
  non-square source, hence the explicit `auto`. Too green for a luminance
  threshold — leaves and shirt land in the same band — so this one is masked
  on greenness instead (see below). Head at x 500→735, y 130→380; the lit
  hands on the pot are the brightest thing low in the frame, at (797, 629).
  A 780px square centred on (695, 460) lands at `153% auto` / `73% 60%`,
  holding head, hands and pot with him 40% across. No fill.

None of them currently needs `fill` — that's for a subject you have to shrink
below `100%`, which leaves bare disc at the edges.

Every number came from measuring the file, not eyeballing it: load the image
into a canvas, threshold on whatever separates subject from ground, and take
the bounding box. Pick the measure that actually discriminates:

- a **luminance** threshold for a lit subject on black (the cube, the figure),
  or for a subject in shadow against a lit ground — the Introspector splits at
  35, with her at 10-25 and the sunlit wall behind her at 50-62
- the **blue channel** for foliage against sky — the tree's grass is
  yellow-green with red ≈ green, so green-vs-red finds nothing
- **horizontal texture**, the mean absolute step in luminance along a row, for
  a horizon: sky is a smooth gradient near zero, water and grass are rippled
  and jump an order of magnitude at the line
- **greenness**, `G - max(R, B)`, for a person among plants — the Gardener is
  dark on dark, so luminance finds nothing, but foliage runs positive on this
  and hair and cloth do not

## Deriving the numbers

For a square crop of side `C` at `(left, top)` in a `W×H` source:

```
background-size      = 100 * W / C          (with `auto` height)
background-position  = 100 * left / (W - C)   100 * top / (H - C)
```

Keep `0 ≤ left ≤ W - C` and `0 ≤ top ≤ H - C` and the crop stays inside the
image. Go outside that range and you get letterboxing — legitimate, but pair
it with a `fill`.

A missing or misnamed file is harmless — the silhouette simply stays.
