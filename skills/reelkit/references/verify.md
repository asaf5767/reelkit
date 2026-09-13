# verify — the automated quality gate

Until this existed, the only thing standing between a bad reel and a rendered one
was a person looking at a contact sheet and noticing that a card sat on the
speaker's mouth. `verify` makes that check mechanical.

```bash
python3 scripts/reelkit.py verify --project videos/myreel [--json] [--fix]
```

## It also runs itself, immediately before every render

`reelkit.py render` runs this gate first and refuses to start when it reports an
ERROR - so a head-zone collision costs a failed command instead of a rendered
reel that a human has to catch on a snapshot.

**Why render and not only build.** `build` already refuses a card it cannot fit
above the head, which is the right place to fail while authoring. But build is
not the last step before the spend: a driver can render a project that was built
earlier, on another machine, or before the fit pass existed. `render_project()`
is the one funnel every path goes through - the CLI, `worker.py`, and
`segmentrender.py` once per segment - so the gate lives there as the backstop
nothing can bypass. Both checks stay: build fails fast, render fails closed.

**A gate that cannot run blocks the render.** Without Playwright or OpenCV,
`verify` skips the card-geometry or face checks and still exits 0 - which is
precisely the run that ships a card on the speaker's face with a green light. The
render refuses in that case and prints what to install:

```
reelkit: geometry gate failed - refusing to render:
  the gate could not run - opencv-python-headless unavailable. Install:
  pip install -r skills/reelkit/requirements-verify.txt
  && python3 -m playwright install --with-deps chromium
```

`requirements-verify.txt` is the single declaration of those dependencies; the
Dockerfile installs from it rather than repeating the list. The opencv pin below
5 is load-bearing - OpenCV 5 removed `cv2.CascadeClassifier`, so on 5.x every
face check degrades to "no head detected" without erroring.

Writes `verify.json` and prints a report. **Exit code 1 if any ERROR.** Run it
after `build` and before `render` — it takes seconds, a render takes minutes.

## What it measures

**Card geometry — measured, not guessed.** Every card fragment is laid out in a
headless browser at the real canvas size and its settled bounding box read from
the DOM. Card height depends on content, so computing it from CSS would be a
guess; this is the actual number. Needs `playwright` (pip) with a chromium
browser installed; without it the geometry and collision checks are skipped with
a note, and the plan-level checks (beat overlap, captions vs mouth) still run.

**Face position.** The speaker's head box is detected in the source footage at
three points across each beat and the median taken. Needs `opencv-python`; if it
is not installed the face checks are skipped with a note and everything else
still runs.

**Collisions.** Per beat: card over the speaker, card over the caption band, card
outside the canvas. Plus beat-overlap and a caption-band-versus-mouth check
across the whole reel.

## How the head check is calibrated

**It protects the whole head, not the detected face box.** OpenCV's frontal-face
box starts at mid-forehead: measured across a 90-second cut at seven timestamps,
the hair top sat 0.097–0.145 of the box height *above* the box. A rule built on
the box therefore protects the eyes and mouth and leaves the forehead and
hairline exposed — which is how a reel could pass this gate at 0% overlap and
still look like the graphics were sitting on the speaker's head.

`head_rect()` grows the detected box by `HAIR_RATIO` (0.28 of its height) upward,
`JAW_RATIO` (0.08) down and `HEAD_PAD_X` (0.06) each side. The hair ratio is
roughly double the measured worst case, so it still holds for taller hair, a cap
or a tilted head on footage nobody has seen.

**One rule for every mode that plays over live footage.** `top`, `stage` and
`split` are all checked the same way, because none of them dims the speaker any
more — there is no longer a mode in which covering him is "intended". Overlap is
measured **head-relative**: a percentage of the head, not of the card, so a big
card cannot dilute the number. Any overlap ≥1% is an ERROR, anything above 0 a
WARN. `full` is exempt rather than tolerant: it is B-roll and replaces the frame
outright, so there is no speaker to cover.

`split` is checked against the **panel**, not the card: the light panel is opaque,
so anything under it is gone. Builder and checker share `split_canvas_h()`,
`head_rect()` and the same face detection, so they cannot disagree about where
the panel sits or where the head starts. `build` already caps the panel clear of
the head per beat; this check is the enforcement behind it, including for plans
written before that cap existed.

**A split panel clips its own overflow**, so a payload that does not fit fails
silently in the render — it just looks like a cropped picture. Two measurements
make it loud instead:

- **Overrun.** The settled content box against the panel rectangle. The panel
  centres its content, so a too-tall block hangs equally above *and* below;
  the check reads both edges, not just the bottom. Any overrun is an ERROR.
- **Squeeze.** When the beat carries an image, the `.cimgframe` rect is measured
  on its own, because the frame is flex-sized against the resolved canvas and
  its settled height is the only honest answer to "did the picture actually
  fit". Below 180px it is an ERROR: the panel is too shallow for a payload on
  this footage.

Neither has a mechanical fix — cutting the image, shortening the headline and
changing the beat's mode are different editorial decisions — so `--fix` leaves
them alone and reports.

## `--fix`

Applies only remedies that are mechanical, in this order for a card on the head:

1. **Move it up.** If the card fits above `head_clear_y`, it gets a `layout.top`
   that puts it there.
2. **Shrink it.** If it does not fit at its current size, it gets a
   `layout.scale` computed from the headroom actually measured. The box is
   measured *with* any existing scale applied, so repeated runs compound rather
   than fight each other.
3. **Nothing.** Below `SCALE_FLOOR` (0.62) the card stops being readable at phone
   size. The ERROR stands, and the message names the real options: B-roll, or a
   kind that says the same thing in less space. Shrinking a card into
   illegibility to satisfy a checker is worse than failing.

A `split` panel on the head gets a `layout.canvas` in pixels that stops clear of
it, when at least 320px of panel remains.

Everything else is reported, never silently rewritten — a card that overlaps the
caption band might want to move, shrink, change mode or be deleted, and only a
person or an agent with the context can say which.

On a 14-beat reel shot as a tight selfie, this took 10 head-collision errors down
to 1; the one that remained was a phone-mockup card 817px tall, which genuinely
cannot coexist with the speaker at that framing and became a B-roll beat.

Re-run `build` after `--fix` for the change to reach the composition.

## Reading verify.json

```jsonc
{ "canvas": { "w": 1080, "h": 1920 },
  "faceDetection": true,
  "beats": [ { "id": "b03", "kind": "chat", "mode": "stage",
               "box": { "x": 40, "y": 300, "w": 1000, "h": 732 },
               "face": [372, 590, 336, 336],
               "faceOverlapPct": 22.3, "captionOverlapPct": 0.0 } ],
  "findings": [ { "level": "ERROR", "id": "b09", "message": "…" } ] }
```

An agent can act on `findings` directly without rendering or looking at anything.

## What it still does not catch

- A card that *depicts nothing* and just restates the spoken sentence. That is a
  judgement call; `references/visual-beats.md` is the only defence.
- A fluent but wrong transcript.
- Whether the reel is any good.
