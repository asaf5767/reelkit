---
name: reelkit
description: >
  Turn a raw talking-head clip into a finished vertical social reel - word-level
  captions burned in sync with speech, plus timed visual beats (mock UI, diagrams,
  charts, drawn SVG, or generated images) layered over footage that plays untouched.
  Use for "make a reel from this video", "add captions and visuals to my talking
  head", "package this clip for Instagram/TikTok/LinkedIn/Shorts". Handles RTL
  languages (Hebrew, Arabic) correctly, which most caption tooling does not.
  Renders through HyperFrames. If the request is a video built from scratch with no
  existing footage, use the HyperFrames workflows instead.
---

# reelkit

**What it does.** Takes one talking-head clip and a `plan.json` and produces a
rendered vertical reel: the speaker plays full-bleed and untouched, word-by-word
captions track the speech, and designed visual beats appear above the speaker's
head. Every visual beat can be a drawn HTML/SVG card *or* a generated image —
the same plan works either way, so an agent with image generation and an agent
without both produce a finished reel.

**What it is not.** Not a from-scratch video builder (that is HyperFrames'
`product-launch-video` / `faceless-explainer`). Not a plain subtitler (that is
`embedded-captions`). It does not cut or reorder footage — see
`references/trimming.md` for the recipe if a take needs trimming.

**Relationship to HyperFrames.** reelkit is a thin layer. HyperFrames owns
transcription, linting, snapshots and rendering; reelkit owns the plan → composition
generator, the RTL-safe caption engine, the visual-beat card library, and the
image-slot contract. If HyperFrames is missing, nothing renders.

---

## 0. Prerequisites

```bash
npx hyperframes@latest --version          # must succeed
npx hyperframes@latest skills update talking-head-recut   # once, provides gsap + render deps
python3 scripts/reelkit.py doctor         # ffmpeg, ffprobe, node, fonts, gsap, verify deps
```

On a slow or headless machine every `snapshot`/`render` call needs:

```bash
export PRODUCER_PAGE_NAVIGATION_TIMEOUT_MS=90000
export PRODUCER_PLAYER_READY_TIMEOUT_MS=90000
```

Without these the CLI dies with `Navigation timeout of 10000 ms exceeded` and it
looks like a broken composition. It is not; it is a slow box.

---

## 1. Scaffold

```bash
python3 scripts/reelkit.py scaffold --project videos/myreel --video /abs/path/raw.mp4 --upscale
```

Stages fonts and GSAP, extracts `audio.mp3`, and re-encodes the source to
`public/input-video.mp4` at the target canvas with **dense keyframes**
(`-g fps -keyint_min fps`). The dense GOP is not optional: a sparse-GOP source
freezes on seek and the render comes out as one frozen frame under moving overlays.

Check the printed source resolution. Anything below the canvas is an upscale and
will look soft — say so plainly rather than shipping a blurry reel silently. A clip
that arrived over WhatsApp is typically 480×850 and worth re-requesting.

## 2. Transcribe

```bash
npx hyperframes@latest transcribe videos/myreel/audio.mp3 -d videos/myreel \
  --json --model large-v3 --language he --timeout 1800000
```

**Pick the model deliberately.** HyperFrames defaults to `small.en`, which is
English-only and returns garbage for every other language. Any non-English audio
needs `--model large-v3` plus `--language <code>`. On 2 CPUs, 90 s of audio takes
roughly 12 minutes — run it in the background and poll.

Then **read `transcript.json` and fix it** before planning. It is a flat array of
`{text, start, end}`. Correct homophones, product names and technical terms in
place, keeping each word's timestamps. Every downstream time depends on this file
being right. Flag any correction you inferred rather than heard, so the author can
check it.

## 3. Plan the beats

Optional first pass — get a draft instead of an empty file:

```bash
python3 scripts/reelkit.py plan --project videos/myreel --lang he --max-beats 14
```

Writes `plan.draft.json`. Its **timing is derived from real word gaps and is
usually right**; its **kind guesses are not — expect to change about half**.
Anything it cannot classify becomes an `image` slot with a drafted prompt, on
purpose: an unfilled slot renders a loud placeholder that cannot ship by accident,
whereas a wrong-but-plausible card can. Review it, replace every `TODO`, delete
beats that do not earn a visual, then rename to `plan.json`.

Or author `videos/myreel/plan.json` yourself. Full schema: `references/plan-schema.md`.
How to choose what a beat should show: **`references/visual-beats.md` — read it,
this is where reels are won or lost.** The one rule that matters most:

> A visual must **depict something**, not re-typeset the words already being
> spoken and already in the captions. A chart, a chat thread, a diagram, a device
> screen, a drawing. If your card is just the sentence in a bigger font, cut it.

Beat count: aim for one visual every 4–7 s of speech, and let each beat land on a
clause boundary from the transcript, not on a round number.

## 4. Build

```bash
python3 scripts/reelkit.py build --project videos/myreel
```

Writes `public/index.html`, one fragment per beat in `public/cards/`, plus
`visuals.json` (the image-slot manifest) and `BEATS.md` (the beat sheet and music
hit points). Deterministic: same plan + same media ⇒ identical HTML.

## 5. Images (optional, and the reason this skill exists)

Any beat may declare an `image` block with a `prompt`. After `build`, read
`visuals.json`: it lists every slot with its exact pixel box, aspect ratio, whether
transparency is required, and the prompt. **If you can generate images**, render
each slot to `public/images/<beatId>.png` at the given aspect and re-run `build` —
the image replaces (or sits behind) the drawn card automatically. **If you cannot**,
do nothing: the drawn HTML card is already there and the reel is complete.

Details, prompt-writing guidance and the transparency rules:
`references/image-slots.md`.

## 6. Validate, verify, then look at it

```bash
cd videos/myreel && npx hyperframes@latest check public
```

Fix every error before rendering. The linter catches real defects — it is the
reason this skill knows that `<html dir="rtl">` renders a black video.

Then run the automated gate — it catches the collisions a human used to catch by
squinting at frames:

```bash
python3 scripts/reelkit.py verify --project videos/myreel        # exit 1 on errors
python3 scripts/reelkit.py verify --project videos/myreel --fix  # nudge fixable cards
```

It measures each card's real bounding box in a browser, detects the speaker's head
in the footage, and reports cards over the face, over the caption band, or off
canvas. Mode-aware: `stage` beats dim the speaker on purpose, so overlap there is
not a defect. See `references/verify.md`.

Then **look at actual frames** for the things no checker can judge:

```bash
npx hyperframes@latest snapshot public --at "3.4,12,20,27,54,63" --timeout 60000 --no-end
```

Read `public/snapshots/contact-sheet.jpg` and check, honestly:

- do RTL lines read as sentences, or as reversed word salad?
- is the frame so dark the speaker has disappeared?
- does every beat depict something, or did one slip back into being a caption?

(Card-over-face, card-over-captions, off-canvas and empty-card timing are now
checked for you — `verify` and `build` report them.)

Fix, rebuild, re-snapshot. Snapshots cost seconds; a render costs minutes.

## 7. Render

```bash
npx hyperframes@latest render public -o output.mp4 --fps 30
```

Roughly 8 min per 2000 frames on 2 CPUs. Then compress for delivery — most chat
and upload paths cap around 30 MB:

```bash
ffmpeg -y -i output.mp4 -c:v libx264 -preset medium -crf 23 -profile:v high \
  -pix_fmt yuv420p -movflags +faststart -c:a aac -b:a 160k final.mp4
```

## 8. Trimming (opt-in)

Footage is untouched by default. When a take needs tightening, cut **before** the
pipeline and re-transcribe, so the transcript always describes the footage exactly:

```bash
python3 scripts/reelkit.py cut --video raw.mp4 --out cut.mp4 --keep "0:44,56:90"
```

Then scaffold and transcribe `cut.mp4` as a fresh source. Never reuse the old
transcript — its timestamps describe the uncut footage. `references/trimming.md`
covers what is worth cutting.

## 9. Audio

**Sound effects are supported and tested.** Add cues to any beat:

```jsonc
"sfx": [ { "name": "pop", "at": 0.15 }, { "name": "chime", "at": 2.0 } ]
```

They resolve from the library bundled with HyperFrames' `media-use` skill — no key,
no login. reelkit normalises each file's peak (the library spans ~32 dB, so a flat
volume means nothing) and compensates for leading silence (several files open with
~0.4 s of it and would otherwise fire late). Eight to twelve cues per 90 s is
plenty; more is exhausting.

**Music is not included** — no licensed catalogue is available here. `BEATS.md`
lists every card-entry hit point so you can land a track in any editor in minutes.
See `references/audio.md`.

---

## Hard rules

These are not style preferences. Each one is a defect that shipped or nearly shipped.

1. **Never put `dir` on `<html>`.** It previews perfectly and renders a fully black
   video. Direction goes on individual text elements.
2. **Every animation is `fromTo`, never `to`.** A bare `.to()` samples its start
   value at first render, so seeking to a frame yields a different image than
   playing to it. Renders seek.
3. **Wrap words before characters.** Per-character `inline-block` spans alone let a
   word break mid-word across lines.
4. **Use `svgOrigin` for SVG rotation**, not `transformOrigin` — the latter resolves
   against the element bbox, not the viewBox, and silently misplaces the pivot.
5. **Never hardcode a text direction.** Take it from the composition
   (`DIR(br)` in `cards.py`), which resolves from `meta.lang`. Bidi reorders text
   runs, not boxes you positioned — so hardcoded `dir="rtl"` renders English
   kinetic type and captions reversed, and every gate still passes.
6. **Load a font that has the script.** Inter, Caveat and most bundled faces carry
   no Hebrew or Arabic glyphs; text renders as tofu boxes. reelkit ships Heebo.
7. **Clamp every time to the media duration.** Whisper returns a final word ending
   a hair past the clip; an uncapped card produces a black tail.
8. **Keep the speaker's face clear.** Content beats belong in the empty space above
   the head. Covering the mouth of a talking head is the most common self-inflicted
   wound in this format.

Full explanations and the RTL specifics: `references/rtl-and-fonts.md` and
`references/troubleshooting.md`.

## References

| File | Read it when |
| --- | --- |
| `references/plan-schema.md` | authoring `plan.json`; every kind and its `data` |
| `references/verify.md` | the automated quality gate and how it is calibrated |
| `scripts/reelkit.py plan` | a heuristic first draft when starting from a blank page |
| `references/visual-beats.md` | choosing what each beat should show |
| `references/image-slots.md` | wiring generated images in; writing prompts |
| `references/rtl-and-fonts.md` | any non-Latin script, especially RTL |
| `references/captions.md` | changing caption grouping, style or placement |
| `references/audio.md` | SFX cues and levels, the beat sheet, why there is no music |
| `references/trimming.md` | the take needs cutting or reordering |
| `references/troubleshooting.md` | anything renders wrong, black, frozen or tofu |

A complete worked example — plan, transcript and notes for a 90 s Hebrew reel —
is in `examples/ai-took-my-job/`.
