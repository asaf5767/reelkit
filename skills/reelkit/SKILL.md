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
head. A visual beat can be a concrete HTML/SVG process card or a compact image. Generated
imagery is optional and never allowed to replace the whole frame as a static still.

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

### Try it without footage

```bash
python3 scripts/reelkit.py sample --project videos/sample
```

generates a synthetic 12s clip (ffmpeg gradient, nothing real), scaffolds it, and
drops in a canned transcript and plan, so the whole pipeline below can be
exercised end to end. Face detection finds no head in a gradient - that check
only exercises on real footage.

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

Before authoring, choose a named versioned style-DNA template and keep cut-plan and graphics-plan histories independent. Every reel requires an opening hook text title in the upper zone; it may overlap the opening speech. Auto-pick the strongest scroll-stopping option and render without blocking; include 2-3 runners-up in the render report for a one-note review swap. Review corrections use `{frame, note}` patches and per-render version numbers. See `references/versioned-plans.md`.


Optional first pass — get a draft instead of an empty file:

```bash
python3 scripts/reelkit.py plan --project videos/myreel --lang he --max-beats 14
```

Writes `plan.draft.json`. Its **timing is derived from real word gaps and is
usually right**; its **kind guesses are not — expect to change about half**.
Anything it cannot classify stays on the speaker, with a sparse punch-in at some
clause boundaries. This is deliberate: generated decoration is worse than no card. Review it, replace every `TODO`, delete
beats that do not earn a visual, then rename to `plan.json`.

Or author `videos/myreel/plan.json` yourself. Full schema: `references/plan-schema.md`.
How to choose what a beat should show: **`references/visual-beats.md` — read it,
this is where reels are won or lost.** The one rule that matters most:

> A visual must **depict something**, not re-typeset the words already being
> spoken and already in the captions. A chart, a chat thread, a diagram, a device
> screen, a drawing. If your card is just the sentence in a bigger font, cut it.

Beat count: do not force a visual cadence. Keep most of the reel on the face;
add a beat only when it shows concrete evidence or process that the face and
captions cannot. Let each beat land on a clause boundary, not a round number.

**Splitting the frame.** Three modes layer a card over the footage; `split` divides
it instead — an opaque light panel across the top 56%, the speaker undimmed below,
hard cuts in and out, and a `1 / n` counter pill. It looks like slides advancing
next to a presenter, so save it for a reel's structural beats (the numbered points,
the conclusion) rather than using it throughout. Use `kind: "canvas"` inside it;
the other kinds are drawn for a dark surface. `verify` measures the panel against
the detected face and `--fix` lowers it when it clips the eye line — the 56%
default is a starting point, not a constant.

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
canvas. Mode-aware: `stage` beats (and `full` beats with `takeover: true`) dim the
speaker on purpose, so overlap there is not a defect. See `references/verify.md`.

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

## 7. Preview, checkpoint and render

Use Reelkit's wrapper rather than calling HyperFrames directly. It resolves duration,
fps and frame count, chooses workers, prints the sizing decision, writes a portable
composition checkpoint, and runs the existing phone-safe export:

```bash
# Fast iteration lane: draft quality and at most 10fps. Inspect this before a full render.
python3 scripts/reelkit.py render --project videos/myreel --preview \
  --workers 2 --checkpoint-dir checkpoints --out preview.mp4

# Delivery render: full authored fps and standard quality.
python3 scripts/reelkit.py render --project videos/myreel --workers 2 \
  --checkpoint-dir checkpoints --out final.mp4
python3 scripts/reelkit.py verify --project videos/myreel
```

Worker precedence is `--workers`, then `REELKIT_RENDER_WORKERS`, then
`PRODUCER_MAX_WORKERS`, then auto. Auto starts at roughly half the available CPU
cores, capped at 8. Each worker launches Chrome and uses about 256 MB; an explicit
count bypasses HyperFrames' auto-sizing, so oversubscribing a small box is slower,
not faster. Benchmark the actual host with `npx hyperframes@latest benchmark public`.
Two workers are usually the useful ceiling on a small 2-4 core box. Four workers on
a sufficiently large host are expected to approach 3x sequential throughput; eight
can approach 6-7x only when CPU, RAM and storage sustain them. These are targets to
measure, not promises.

`--checkpoint-dir` writes `reelkit-render-checkpoint.tgz` atomically before capture.
It contains the plan, transcript, built composition, cards, images, fonts, beat sheet
and asset ledger, but deliberately excludes the large source video. Keep the source
in durable storage and copy or attach this small bundle before a long render, so a
fresh machine can resume from the authored state. HyperFrames' extracted-frame cache
can also be put on durable disk with `HYPERFRAMES_EXTRACT_CACHE_DIR` when available.

Acceptance runs pin software rendering and prove parallel equivalence:

```bash
python3 scripts/reelkit.py render --project videos/myreel --workers 1 --software-gpu --out seq.mp4
python3 scripts/reelkit.py render --project videos/myreel --workers 2 --software-gpu --out par2.mp4
python3 scripts/renderdiff.py seq.mp4 par2.mp4 --workers 2 --project videos/myreel
```

The gate requires equal duration/frame count/fps, per-frame SSIM >= 0.999 and PSNR
>= 50 dB, exact decoded bitmap hashes on about 20 frames including every slice
boundary +/-1, hash-identical decoded audio, and a passing `verify` run. Repeat with
four workers on a host that can run four Chrome captures without oversubscription.

The wrapper's export writes the phone-safe container: moov index first (+faststart),
explicit bt709 colour tags, h264 High yuv420p, AAC. A moov atom at the end of the
file can fail on phones and WhatsApp. Never hand-patch delivery with a bare
`ffmpeg -i` copy.

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

**Sound effects are automatic, tested, and code-enforced.** `build` places
event-tied cues on its own - whoosh on every beat entrance, pop on hero text,
click on UI cards, soft hit on data reveals, riser into the CTA - and ducks every
cue under the measured voice. A plan with beats and zero resolved cues is a hard
error, not a warning: a silent export is a failed render. When the bundled
media-use library is absent (CI, Kaggle, fresh clones), reelkit synthesizes its
own stand-ins into `~/.cache/reelkit/sfx-synth` so the layer can never silently
vanish; install the real library to upgrade the sounds.
A beat with its own `sfx` list overrides the automation for that beat:

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
2. **Two `fromTo` calls on one element need a baseline.** GSAP applies from-values
   at authoring time, so the last-authored one becomes the resting state. Add a
   `tl.set()` at the sequence's start and `immediateRender: false` on the tweens,
   or the element renders in the wrong state until its first tween runs.
3. **Every animation is `fromTo`, never `to`.** A bare `.to()` samples its start
   value at first render, so seeking to a frame yields a different image than
   playing to it. Renders seek.
4. **Wrap words before characters.** Per-character `inline-block` spans alone let a
   word break mid-word across lines.
5. **Use `svgOrigin` for SVG rotation**, not `transformOrigin` — the latter resolves
   against the element bbox, not the viewBox, and silently misplaces the pivot.
6. **Never hardcode a text direction.** Take it from the composition
   (`DIR(br)` in `cards.py`), which resolves from `meta.lang`. Bidi reorders text
   runs, not boxes you positioned — so hardcoded `dir="rtl"` renders English
   kinetic type and captions reversed, and every gate still passes.
7. **Load a font that has the script.** Inter, Caveat and most bundled faces carry
   no Hebrew or Arabic glyphs; text renders as tofu boxes. reelkit ships Heebo.
8. **Clamp every time to the media duration.** Whisper returns a final word ending
   a hair past the clip; an uncapped card produces a black tail.
9. **Keep the speaker's face clear.** Content beats belong in the empty space above
   the head. Covering the mouth of a talking head is the most common self-inflicted
   wound in this format.
10. **Never ship an MP4 with its index at the end.** Desktop players tolerate a
    trailing moov atom; phones and WhatsApp refuse to open the file. Deliver
    through `reelkit.py export` (faststart + bt709 tags) and let `verify` gate
    it - local playback is not evidence of compatibility.

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

### Restartable full renders

For environments that may rebuild mid-render, use `scripts/segmentrender.py`.
It prepares short independent subprojects at visual-beat boundaries, shifts each
segment's plan/transcript/media to local zero, retains completed segment MP4s, and
skips them on retry. Final assembly joins video-only segments and muxes the original
staged audio once, avoiding AAC encoder delay at every boundary.

```bash
python3 scripts/segmentrender.py --project videos/myreel --work-dir checkpoints/segments \
  --segment-seconds 12 --workers 2 --out final.mp4
```

**`--preview` renders a subset, not a lower-fidelity copy.** This is a change of
meaning: it used to render the whole timeline at 10fps draft, which produced
nothing the full pass could use. It now renders the **leading segments at the
authored fps and standard quality**, into the same `segment-NNN.mp4` files a full
render writes — so a full render over the same work-dir resumes them instead of
redoing them.

```bash
# look at the first ~12s for real, then finish the rest later
python3 scripts/segmentrender.py --project videos/myreel --work-dir checkpoints/segments \
  --segment-seconds 12 --preview --preview-segments 1 --out preview.mp4
python3 scripts/segmentrender.py --project videos/myreel --work-dir checkpoints/segments \
  --segment-seconds 12 --out final.mp4          # resumes segment 0, renders the rest
```

Reuse is safe because a preview segment is produced by the **identical command on
identical inputs** - same segment subproject, same build output, same fps and
quality, the same code path a full render takes. Measured on the 12s sample: a
cold full render is 73s; a 2-of-3 preview followed by a full render is 48s + 28s,
so the preview costs about 4% instead of a duplicated pass.

It is *not* byte-identical on real footage, and neither is a full render against
itself. Two renders of one unchanged segment produce only two distinct outputs
that differ in occasional individual frames - four of five sampled frames hash
equal, the fifth does not - at min SSIM 0.989 with identical audio. The synthetic
sample does come out byte-identical, which is what makes this easy to miss. So
the guarantee a kept segment carries is "an equally valid render of this
segment", not "the same bytes". That predates segment reuse and applies to every
resume the pipeline has ever done; it also means `renderdiff.py`'s exact-bitmap
and SSIM >= 0.999 thresholds cannot pass on real video, only on the sample.

The trade is that a preview is now **short but real** rather than long and rough.
To see the whole timeline quickly and throw it away, `reelkit.py render --preview`
still does 10fps draft over everything — it just produces nothing reusable.

**What reuse is available.** Same-fidelity only, which is now everything the
segmented path produces. A 10fps draft carries no frame a 30fps output can use,
which is precisely why the preview stopped being one.

HyperFrames' extracted-frame cache (`--frames-cache-dir` /
`HYPERFRAMES_EXTRACT_CACHE_DIR`) does not help across fps either: its key includes
the render fps and frames inside a bucket are indexed sequentially, so a 10fps
bucket's `frame_00005` is a different moment from a 30fps bucket's. Measured on
the 12s sample under the old semantics, a preview left 120 cached frames and the
full render then added 360 more, reusing none. Pointing both passes at one cache
directory is still worth doing for repeated renders — but measured it was worth
about 6% (51s cold, 48s fully warm), because the cost is Chrome capture, not
frame extraction. Do not go looking for a big win in that cache.
