# reelkit

Turn a raw talking-head clip into a finished vertical reel: word-level captions
burned in sync with the speech, and timed visual beats layered over footage that
plays untouched.

Built as a thin layer on [HyperFrames](https://github.com/heygen-com/hyperframes),
which does the transcription, linting and rendering. reelkit adds the parts that
were missing for social reels — a transcript-driven composition generator, captions
that are correct in right-to-left languages, a library of visual beats, and an
**image-slot contract** so an agent that can generate images drops real artwork
into named boxes while an agent that cannot still ships a finished reel.

## Why

Most caption tooling is built and tested in English, and most "AI visuals" turn out
to be the speaker's own sentence in a bigger font. reelkit is opinionated about both:
RTL is a first-class case, and a visual has to *depict something* the captions do
not already say. It also places timed sound effects, normalising their levels and
compensating for the leading silence several stock files carry.

## Install

```bash
git clone https://github.com/asaf5767/reelkit
cd reelkit
npx hyperframes@latest skills update talking-head-recut   # render deps + gsap
python3 skills/reelkit/scripts/reelkit.py doctor
```

Or install as a Claude plugin from `.claude-plugin/marketplace.json`.

## Use

```bash
S=skills/reelkit/scripts/reelkit.py
python3 $S scaffold --project videos/myreel --video raw.mp4 --upscale
npx hyperframes@latest transcribe videos/myreel/audio.mp3 -d videos/myreel \
    --json --model large-v3 --language he
# fix transcript.json
python3 $S plan --project videos/myreel --lang he      # optional heuristic draft
# review plan.draft.json, replace the TODOs, rename to plan.json
python3 $S build --project videos/myreel
cd videos/myreel && npx hyperframes@latest check public
python3 $S verify --project videos/myreel        # card-over-face, captions, off-canvas
npx hyperframes@latest snapshot public --at "3,12,20,30" --no-end   # look at it
npx hyperframes@latest render public -o output.mp4 --fps 30
```

Agents: read `skills/reelkit/SKILL.md` first. It is the whole workflow.

## Image slots

Any beat can declare an image prompt. `build` writes `visuals.json` with each
slot's pixel box, aspect ratio and prompt. Generate to `public/images/<beatId>.png`,
re-run `build`, and the image replaces the drawn card. Skip it and the drawn card
ships. Same plan, both paths. See `skills/reelkit/references/image-slots.md`.

## What is in the box

```
skills/reelkit/
  SKILL.md                 the workflow, and the hard rules
  references/              plan schema, visual-beat doctrine, RTL, captions,
                           image slots, audio, trimming, troubleshooting
  scripts/reelkit.py       scaffold / cut / plan / build / verify / doctor
  scripts/verify.py        measured card geometry, face detection, collisions
  scripts/cards.py         15 visual-beat kinds + seek-safe animation primitives
  assets/fonts/            Heebo (OFL) + Inter
  assets/brand/            colour and caption presets
  examples/ai-took-my-job/ a complete 90 s Hebrew reel: plan, transcript, notes
```

## Requirements

`ffmpeg`, `ffprobe`, `node` 18+, `python3`, and HyperFrames. No API keys: Whisper
runs locally through the HyperFrames CLI.

## Licence

MIT. Heebo is SIL OFL and bundled with its licence. GSAP is fetched at scaffold
time, not redistributed.
