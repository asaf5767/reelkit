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
      "mode": "top",         // "top" | "stage" | "full"
      "intent": "Hook - a notification claims AI took the job",
      "layout": { "top": 220 },   // optional: overrides the mode's vertical padding
                                  // (what `verify --fix` writes)
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

| mode | scrim | content sits at | use for |
| --- | --- | --- | --- |
| `top` | light gradient | y ≈ 140 | compact beats while the speaker carries the moment |
| `stage` | heavy gradient | y ≈ 300 | the visual is the point; the speaker recedes |
| `full` | moderate gradient | y ≈ 220 | title cards, outros, anything that owns the frame |
| `split` | none | inside the canvas | a light panel over the top of the frame, speaker undimmed below |

The speaker stays visible in every mode by default. For an intentional
full-frame takeover - the speaker should vanish behind the card - set
`"takeover": true` on a `full` beat; its scrim turns near-opaque.

Beats must not overlap in time. `end` is clamped to the media duration.

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
  "data": { "kicker": "…", "headline": "…" }
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

The default 56% is measured from a reference cut, and it is a ceiling, not a
guarantee: on footage where the speaker sits high in frame it would clip the eye
line. `build` therefore detects the head in the footage and caps every split
beat's canvas above the eye line (persisting the resolved pixels into
`layout.canvas`, so build and verify see the same panel). When the speaker is so
high that even the minimum 320px panel would cross the eyes, build warns that the
framing is too tight for split mode and `verify` fails the beat - pick another
mode for it. When no head is detected (cv2 missing, or no face in frame), the
requested height is kept and the note is printed, so do not hand-tune the
default: run the gate.

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
`{ "kicker": "…", "headline": "…" }`
Only for `mode: "split"`. Start-aligned, so it reads correctly in both
directions. Keep the headline to a few words: it sets at 96px.

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
