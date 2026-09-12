# plan.json schema

`reelkit.py plan --project DIR --lang he` writes a heuristic `plan.draft.json` to
start from: beat boundaries come from real word gaps and are usually right, kinds
are guessed and are often wrong, and anything unclassifiable becomes an `image`
slot with a drafted prompt. Review it, replace the `TODO`s, rename to `plan.json`.

One file describes the whole reel. `reelkit.py build` turns it into a HyperFrames
composition. Nothing else is authored by hand.

```jsonc
{
  "meta": {
    "title": "…",            // free text, for humans
    "lang": "he",            // goes on <html lang>, and picks the composition
                             // direction (rtl for he/ar/fa/ur/..., else ltr).
                             // NEVER set dir on <html> itself.
    "dir": "rtl",            // optional override when the lang tag is misleading
    "fps": 30, "width": 1080, "height": 1920,
    "duration": 90.03,       // optional; probed from the video when absent
    "trimTail": true         // drop the final frame (default true) - avoids a black tail
  },

  "brand": "assaf",          // preset name in assets/brand/, or an inline object

  "captions": {
    "enabled": true,
    "highlight": "#FF7A1A",  // defaults to brand accent 0
    "top": 1500, "height": 360
  },

  "framing": {               // the video layer, animated as one wrapper
    "scale": 1.0,            // base zoom. >1 crops - use it to remove a watermark
    "origin": "50% 30%",     // transform-origin; "50% 0%" anchors the top edge
    "punches": [ { "at": 3.95, "from": 1.0, "to": 1.06, "dur": 0.9 } ]
  },

  "audio": {
    "sourceVolume": 1,       // the speaking voice
    "sfxVolume": 0.8,        // default relative level for cues (1.0 == target)
    "sfxTargetDb": -11.0,    // peak each sfx file is normalised to
    "sfxDir": null,          // override the auto-discovered media-use library
    "sfx": []                // global cues with absolute "at"
  },

  "beats": [
    {
      "id": "b01",           // stable, unique; also the image filename
      "start": 0.88, "end": 6.90,
      "kind": "notification",
      "mode": "top",         // "top" | "stage" | "split" | "full"
      "intent": "Hook - a notification claims AI took the job",
      "plate": true,         // optional: force the local plate on or off
      "layout": {            // optional, and what `verify --fix` writes
        "top": 120,          //   vertical padding, overriding the mode's default
        "scale": 0.74        //   shrink the card to fit above the speaker's head
      },
      "data": { /* kind-specific, see below */ },
      "sfx": [ { "name": "pop", "at": 0.15, "volume": 0.85 } ],   // at = relative to beat start
      "image": {             // optional image slot
        "prompt": "…",
        "mode": "replace",   // "replace" the drawn card, or sit "behind" it
        "alpha": false,
        "box": [70, 300, 940, 700],
        "zoom": 1.08,
        "caption": "…"
      }
    }
  ]
}
```

## mode

| mode | over the footage | content sits at | use for |
| --- | --- | --- | --- |
| `top` | nothing | y ≈ 120 | compact beats while the speaker carries the moment |
| `stage` | nothing | y ≈ 150 | the visual is the point and wants more room |
| `split` | nothing | inside the canvas | an opaque light panel across the top, speaker undimmed below |
| `full` | **replaces it** | centred | B-roll: the frame is the content, the speaker is gone |

**Nothing dims the speaker. Ever.** There is no scrim, no gradient, no tint over
the frame in any mode. Dimming the frame to lift a card also dims the person
talking, and he is the subject — "the visuals make the rest of the screen darker
and it affects how I look" is what the old global scrims did.

Where a card needs separation from the footage it gets a **plate**: a local dark
surface the size of the card and nothing more. It is on by default for kinds
that are bare type or line art on live footage, and off for kinds that already
draw their own surface (`notification`, `chat`, `code`, `diff`, `checklist`,
`chips`, `image`). Force it either way with `"plate": true | false` on the beat.

`takeover` is gone. `full` is always a takeover now, because that is the only
honest version of one: an opaque ground, not a card floating over a half-visible
speaker. A beat that still carries the key gets a build warning.

Beats must not overlap in time. `end` is clamped to the media duration.

### `full` — moving B-roll only

`full` is intentionally strict: it requires directly relevant moving footage.
Put a local MP4 or WebM under the project's `public/` folder and point to it:

```jsonc
{
  "id": "b05", "start": 18.2, "end": 20.8,
  "kind": "image", "mode": "full",
  "intent": "show the actual app carrying out the step",
  "broll": { "src": "broll/app-workflow.mp4", "trim": 2.4 },
  "data": { "caption": "optional short context" }
}
```

- `broll.src` is relative to `public/`. External URLs and parent paths are rejected.
- `trim` is the source-video start time in seconds and defaults to zero.
- The B-roll frame is tied to the composition timeline, so snapshots and renders
  seek to the same frame.
- A top-level `image` on a `full` beat is rejected. Generated stills, abstract
  illustrations and static cards do not justify removing the speaker.
- Keep the voice audio running underneath. Prefer 1-3 second cutaways to actions,
  screens or physical details that directly prove the spoken line.

### `split`

`split` divides the frame instead of layering over it: an opaque light panel
occupies the top, the footage plays untouched below it, and there is no scrim.
It reads as a different register from the other three modes, so use it for the
structural beats of a reel - the point being made, not the decoration around it.

```jsonc
{
  "id": "b04", "start": 12.0, "end": 17.4,
  "mode": "split",
  "kind": "canvas",
  "layout": { "canvas": 0.56 },        // fraction of frame height, or explicit px
  "counterLabel": "2 / 5",             // optional; default is "i / n" over split beats
  "data": {
    "kicker": "…", "headline": "…",
    "image": {                         // optional payload on the panel
      "prompt": "…",                   // what a generator should draw
      "fit": "wide",                   // "wide" under the text | "tall" beside it
      "frame": "soft",                 // "soft" bordered | "bare" no frame
      "zoom": 1.03,                    // slow push; 1.0 holds still
      "caption": "…"
    }
  }
}
```

- `layout.canvas` defaults to **0.56** (56% of frame height). A value `<= 1` is a
  fraction, anything larger is pixels. Clamped to leave room for the speaker.
- Split beats **hard-cut** in and out - no cross-fade. Two adjacent split beats
  therefore feel like slides advancing.
- The counter pill sits at the bottom start edge of the panel and numbers the
  split beats in order (`1 / 3`, `2 / 3`…). `i / n` rather than an English word
  so it needs no translation; override per beat with `counterLabel`.
- Panel colours come from the brand: `canvasBg`, `canvasText`, `canvasMuted`.
- `kind: "canvas"` is the only kind designed for the light panel. Every other
  kind assumes a dark surface and will render low-contrast inside it.

The default is 44% of frame height, and it is a ceiling rather than a guarantee.
`build` detects the head and caps every split beat's canvas **above the whole
head** — hair and forehead, not the eye line — persisting the resolved pixels
into `layout.canvas` so build and verify see the same panel. When the speaker
sits so high that even the minimum 320px panel would touch him, build warns that
the framing is too tight for split mode and `verify` fails the beat: use B-roll
for it. When no head is detected (cv2 missing, or no face in frame) the requested
height is kept and a note is printed. Do not hand-tune the default — run the gate.

### What "clear of the head" means

The thing protected is the **whole head**, not the detected face box.

OpenCV's frontal-face box starts at mid-forehead. Measured across a 90-second
talking-head cut at seven timestamps, the hair top sat between 0.097 and 0.145 of
the box height *above* the box — so a rule that protects the box protects the
eyes and mouth and leaves the forehead and hairline exposed. That is how a beat
could report 0% face overlap and still look like the graphic was sitting on the
speaker's head.

`head_rect()` expands the detected box by 28% of its height upward for hair and
forehead (roughly double the measured worst case, so it still holds for taller
hair, a cap, or a tilted head), 8% downward for the jaw, and 6% each side for
ears. `head_clear_y()` subtracts a further 72px of breathing room, and that is
the line a card or panel must end above.

A card that does not fit above it has exactly one mechanical remedy —
`layout.scale`, which `verify --fix` writes — and below 0.62 the card stops being
readable at phone size. At that point the beat needs an editorial decision rather
than a layout one: B-roll, or a kind that says the same thing in less space.

#### Images on the panel

A canvas beat can carry a real picture — a screenshot, a product shot, a
diagram — alongside its text. It declares that in **`data.image`**, not the
top-level `image` block every other mode uses, because the slot's box is not
authorable: the panel's height is resolved per beat against the detected face,
so the shape only exists once the canvas does. Everything downstream is the
same path as a `kind: "image"` beat — the file goes at
`public/images/<beat-id>.png`, the slot appears in `visuals.json` with its exact
box and aspect, and a missing file renders the loud dashed placeholder carrying
the prompt, inside the panel, at the size the picture would have had.

`fit` picks the arrangement, and it is a statement about the *picture*, not the
panel:

| fit | arrangement | the slot it publishes |
| --- | --- | --- |
| `wide` (default) | picture stacked under the kicker + headline, full panel width | landscape — roughly 1.5:1 at a full-height panel, wider as the face cap lowers it |
| `tall` | picture beside the text, on the panel's end edge | portrait — roughly 0.45:1, so a phone screenshot keeps its height |

Read `visuals.json` after `build` for the exact box rather than assuming those
ratios: the face cap changes the panel height per beat, and the published box
changes with it.

The picture is sized by flexbox against the resolved panel and drawn with
`object-fit: contain`, so it can never spill or distort. What a too-short panel
produces instead is a squeezed frame, and `verify` fails the beat when the
picture settles below 180px or when the text block overruns the panel — see
`references/verify.md`. If a beat trips that, the panel is genuinely too shallow
for a payload on this footage: cut the image, shorten the headline, or give the
beat another mode.

## kinds

### `hero` — kinetic headline
`{ "text": "…", "note": "…", "icon": "bolt", "small": false, "rtl": true }`
Icons: `spark check shield target bolt clock warn`.

### `notification` — stacked notification banners
`{ "items": [ { "app": "…", "body": "…", "tone": "ok", "icon": "check" } ], "gap": 1.9 }`
`tone: "ok"` tints the icon with the success accent.

### `chat` — phone conversation thread
`{ "msgs": [ { "side": "l", "text": "…" }, { "side": "r", "text": "…" } ], "typing": true }`
`l` = the other party, `r` = the speaker. Keep each message under ~6 words: the
bubble must be readable in one glance at phone size.

### `code` — editor window, lines sliding in
`{ "title": "agent.ts", "lines": ["<span class='kw'>const</span> x = …"] }`
Allowed inline classes: `kw` (keyword), `fn` (function), `st` (string). Lines are
raw HTML on purpose — nothing else in a plan is.

### `diff` — review diff plus verdict chips
`{ "title": "review",
   "rows": [ { "op": "-", "text": "…" }, { "op": "+", "text": "…" } ],
   "chips": [ { "text": "correct", "icon": "check" } ] }`

### `checklist` — rows ticking in, optional sweeping clock
`{ "items": ["…", "…"], "clock": true }`

### `donut` — proportion ring plus legend
`{ "segments": [ { "label": "…", "pct": 44, "color": "#…" } ] }`
Percentages should total 100.

### `bars` — before/after stacked columns
`{ "groups": [ { "cap": "then", "segments": [ { "label": "…", "pct": 70 } ] },
               { "cap": "now", "hot": true, "segments": [ … ] } ],
   "legend": [ { "label": "…", "color": "#…" } ], "scale": 3.1 }`
`scale` is pixels per percent. `hot` tints a group's caption with accent 0.

### `pipeline` — vertical node chain with drawn arrows
`{ "nodes": ["…", "…", "…"] }`  Three to five nodes; more and the type shrinks.

### `contrast` — A struck through, arrow, B
`{ "from": "gone", "to": "moved" }`

### `chips` — pill row
`{ "items": [ { "text": "…", "check": true } ] }`

### `stat` — big count-up number
`{ "from": 0, "to": 20, "unit": "…", "note": "…", "dur": 1.15 }`

### `follow` — end card
`{ "kicker": "…", "headline": "…", "name": "…", "handle": "…",
   "initial": "A", "cta": "Follow" }`

### `canvas` — kicker + headline on the light split panel
`{ "kicker": "…", "headline": "…", "image": { … } }`
Only for `mode: "split"`. Start-aligned, so it reads correctly in both
directions. Keep the headline to a few words: it sets at 96px, and on a
face-capped panel a long one is what pushes an image below its minimum.
`image` is optional — see **Images on the panel** above.

### `image` — a generated image is the whole beat
`{ "caption": "…", "frame": "soft", "zoom": 1.08 }`
Requires `public/images/<id>.png`. Without it the build renders a loud dashed
placeholder carrying the prompt — visible, lintable, impossible to ship by accident.

### `doodle` — escape hatch, any inline SVG
```jsonc
{ "svg": "<svg viewBox='0 0 900 560'>…</svg>",
  "width": 980,
  "caption": "…", "captionAt": 3.0,
  "anims": [ { "id": "elementId", "anim": "pop", "at": 0.1, "dur": 0.5 } ] }
```
`{A0}`…`{A4}` inside the SVG are substituted with brand accents. Animations:
`pop fade slide draw spin pulse move`. `slide` takes `dx`/`dy`; `move` takes
`from`/`to` as `[x, y]` pairs and is how you animate a path (a bouncing ball, a
travelling marker); `draw` takes `length`
and needs `stroke-dasharray="<length>"` in the markup; `spin` takes `from`/`to`
and `origin` in **viewBox user units**.

Use `doodle` whenever the library has no fitting kind. It is the reason the
library is not a straitjacket — do not bend an unrelated kind into shape instead.
