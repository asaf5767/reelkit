# Troubleshooting

Symptom → cause → fix. Every entry here is something that actually happened.

### The rendered MP4 is entirely black, but snapshots looked perfect
`dir="rtl"` on `<html>`. Confirmed silent failure. Remove it; scope direction to
text elements. Lint id: `html_dir_attribute_breaks_render`.

### `Navigation timeout of 10000 ms exceeded` on snapshot or render
A slow or headless box, not a broken composition. `--timeout` does not cover page
navigation; the environment variable does:
```bash
PRODUCER_PAGE_NAVIGATION_TIMEOUT_MS=90000 PRODUCER_PLAYER_READY_TIMEOUT_MS=90000
```

### `Missing window.__timelines registration` / `Composition starts with a bare element`
You pointed the CLI at a fragment. `snapshot`/`render` take a **project directory**
containing `index.html`, not an HTML file.

### `host_missing_composition_id`
Every element carrying `data-composition-src` also needs `data-composition-id`.

### `overlapping_gsap_tweens` where two tweens merely touch
Segments that abut — one ending exactly where the next begins, as in a hop-by-hop
motion path — are reported as overlapping at a single instant. That is correct
authoring for continuous motion; inserting a gap would freeze the element for a
frame. Not actionable. Genuine overlaps span a real interval.

### `overlapping_gsap_tweens` on caption words
A word shorter than the highlight-in duration, so the in and out tweens overlap.
reelkit clamps for this; if you hand-edited timings, make the out tween start after
the in tween ends.

### Text renders as boxes (tofu)
The font has no glyphs for the script. Check the `@font-face` chain actually
resolves to a face covering the language — Inter and Caveat do not cover Hebrew.

### A word breaks across two lines mid-word
Per-character spans without word wrappers. Use `cards.kinetic()`, or wrap words in
`.wd { display:inline-block; white-space:nowrap; }`.

### An SVG rotates around the wrong point
`transformOrigin` on an SVG child resolves against its own bbox, not the viewBox.
Use `svgOrigin: "150 150"` in viewBox user units.

### The video is one frozen frame under moving overlays
Sparse GOP in the source. Re-encode with `-g <fps> -keyint_min <fps>`.
`reelkit.py scaffold` does this.

### Caption words look highlighted before they are spoken
Two `fromTo` calls on one element with no baseline. GSAP applies a fromTo's
*from* values at **authoring time** (`immediateRender` defaults true), not at the
tween's position — so with a highlight-in and a highlight-out tween per word, the
second one's from-state (highlighted) silently becomes the word's resting state.
Every word renders pre-highlighted and the karaoke only reads on the way out.
Fix: a `tl.set()` baseline at the line's start plus `immediateRender: false` on
both tweens. HyperFrames lints this as `gsap_repeated_fromto_without_baseline` —
worth reading rather than dismissing, because nothing else catches it: `check`
passes, `verify` passes, and the frames look plausible.

The same trap applies to any element with a *sequence* of fromTo tweens, such as
a ball animated hop by hop.

### Seeking to a frame shows different content than playing to it
A bare `.to()` somewhere. GSAP records a `to` tween's start value at first render,
so a seek and a play-through disagree. Every tween must be `fromTo`.

### A black tail at the end of the render
A card or the composition duration exceeds the media duration. Whisper routinely
returns a final word ending a few hundredths past the clip. Clamp everything to the
probed duration (`meta.trimTail` handles the last frame).

### The whole frame is too dark and the speaker has vanished
Stacked scrims: a `stage` beat's scrim plus the bottom veil plus a caption plate.
Lighten the beat's mode to `top`, or accept it only where the visual is genuinely
the point.

### Contrast failures in `check`, but it looks fine to you
The checker samples the real rendered frame, so it catches text over the *bright*
parts of the footage — a shot you did not sample by eye. Give the text a plate
rather than darkening the whole frame.

### Cards look empty for a beat before content appears
The card's plate renders instantly while its contents are still animating in. Move
the first animation earlier or the card's `start` later. Nothing should sit visibly
blank for more than ~0.8 s.

### `snapshot --at` only captures the last timestamp
Pass one comma-separated string: `--at "3,10,20"`, not repeated `--at` flags.

### The render is too large to send
Most upload paths cap near 30 MB. `-crf 23 -preset medium` gets 90 s of 1080×1920
to roughly 29 MB. Check the size before sending, not after.

### Transcript is fluent but wrong
An English-only Whisper model on non-English audio. Re-run with
`--model large-v3 --language <code>` — and read the result either way.
