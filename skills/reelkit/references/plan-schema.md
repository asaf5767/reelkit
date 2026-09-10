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
    "lang": "he",            // goes on <html lang>. NEVER set dir here.
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

  "audio": { "sourceVolume": 1 },

  "beats": [
    {
      "id": "b01",           // stable, unique; also the image filename
      "start": 0.88, "end": 6.90,
      "kind": "notification",
      "mode": "top",         // "top" | "stage" | "full"
      "intent": "Hook - a notification claims AI took the job",
      "data": { /* kind-specific, see below */ },
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
| `full` | near-opaque | y ≈ 300 | title cards, outros, anything that owns the frame |

Beats must not overlap in time. `end` is clamped to the media duration.

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
`pop fade slide draw spin pulse`. `slide` takes `dx`/`dy`; `draw` takes `length`
and needs `stroke-dasharray="<length>"` in the markup; `spin` takes `from`/`to`
and `origin` in **viewBox user units**.

Use `doodle` whenever the library has no fitting kind. It is the reason the
library is not a straitjacket — do not bend an unrelated kind into shape instead.
