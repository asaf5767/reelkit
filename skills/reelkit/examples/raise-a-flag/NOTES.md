# Worked example — "אין דבר כזה שאלה טיפשית"

A 47 s Hebrew talking-head reel: a selfie walk-and-talk about knowing when to stop
grinding alone and ask for help. Five visual beats and 44 caption lines over
untouched footage.

## Files

- `plan.json` — the complete plan, including two image slots with prompts
- `transcript.json` — corrected Whisper `large-v3` output (Hebrew, word-level)
- `BEATS.md` — the generated beat sheet and music hit points

## Reproducing

```bash
S=../../scripts/reelkit.py
python3 $S scaffold --project . --video /path/to/raw.mp4 --upscale
python3 $S build --project .
npx hyperframes@latest check public
python3 $S verify --project .
python3 $S render --project . --workers 2 --out final.mp4
```

## What this example demonstrates

- **`doodle` carrying the literal imagery** — `b01` (the same answer, three times),
  `b02` (running the track alone, then the flag going up) and `b04` (one task laid
  across four weeks) are hand-authored SVG. Every drawn subject is something the
  speaker actually names, so no beat needed a generated still to be finished.
- **Animated labels on the drawings** — the numbered markers in `b01`, the
  `בקשת עזרה` pill in `b02` and the week digits in `b04` are declarative `anims`
  entries, not static type. `b02` and `b04` also declare `image.label`, so the
  same label rides along if the slots are ever filled.
- **Image slots with fallbacks** — `b02` and `b04` declare `mode: "replace"`.
  Neither PNG exists, so both fall back to their drawn cards and the reel is
  complete as shipped. Generate the two PNGs and re-run `build` to swap them in.
- **Beats that depict** — three identical reply bubbles for "I kept giving the
  same answer", a calendar spread for what the silence costs, a chat exchange for
  "there is no such thing as a stupid question". None of them restate the
  sentence being spoken.
- **`framing` doing two jobs at once** — see below.

## Notes from the real production

- The source arrived over WhatsApp at 478×850 — a 2.26× upscale to 1080×1920 and
  visibly soft. Always ask for the original file.
- The recording app burned a `RECORDED ON BIGVU` watermark into the bottom of the
  frame, measured at y≈1666 on the 1920 canvas. `framing.scale: 1.18` with
  `origin: "50% 0%"` crops it off the bottom edge, and because a top-anchored
  zoom pushes the subject *down*, the same setting opened up the band the cards
  live in. Check the caption band on a snapshot after doing this — the same push
  moves the mouth toward it.
- **Headroom was the binding constraint.** Measured with `detect_faces` at one
  sample per second, `head_clear_y` ran from 239 px to 531 px across the clip.
  Every beat was then timed to a window where the head sits low and sized to fit
  above it; `split` mode was never an option, since `CANVAS_MIN` is 320 px and
  most of this clip has less room than that. Measure first, then author.
- Whisper needed five corrections: `הריאנתי` → `ראיינתי`, `הרעיון` → `הראיון`,
  and `תרים מודגל` → `תרימו דגל` (confirmed by re-transcribing that slice on its
  own). `להתבחבש` is not a word and was read as `להתחבש` — that one is inferred
  from context, not heard clearly, so check it against the audio.
- **`move` alone does not hide an element before its entrance.** The flag in
  `b02` is authored at the top of the pole and animated up from `y: 150`, so for
  every frame before the tween it sat raised, then dropped and rose again. A
  `fade` on the flag path at the same timestamp is what holds it out of frame
  until it is pulled up. Any `move` used as an entrance needs a companion
  opacity tween.

## Sound

3 SFX cues, all placed by `build`'s automation and left alone. There is no music;
`BEATS.md` carries the hit points for adding one.
