# Worked example — "AI לקח לי את העבודה"

A 90 s Hebrew talking-head reel: hook, turn, body, payoff, open loop. Fourteen
visual beats and 91 caption lines over untouched footage.

## Files

- `plan.json` — the complete plan, including two image slots with prompts
- `transcript.json` — corrected Whisper `large-v3` output (Hebrew, word-level)

## Reproducing

```bash
S=../../scripts/reelkit.py
python3 $S scaffold --project . --video /path/to/raw.mp4 --upscale
python3 $S build --project .
npx hyperframes@latest check public
```

## What this example demonstrates

- **`doodle` as the escape hatch** — `b02` (ping-pong rally) and `b09` (code monkey)
  are hand-authored SVG with declarative animations, because no library kind fits.
- **Image slots with fallbacks** — `b02` declares `mode: "replace"` and `b01`
  declares `mode: "behind"`. Neither PNG exists in the repo, so both fall back to
  their drawn cards and the reel is complete as shipped. Generate the two PNGs and
  re-run `build` to see them swap in.
- **Beats that depict** — a chat thread for "he asks, I answer", a donut for "devs
  were never paid to just write code", before/after bars for "less coding, more
  thinking". None of them restate the sentence being spoken.
- **`framing.punches`** — small scale pushes on the hook, the mid-turn and the
  close, all `fromTo` so seeking is safe.

## Notes from the real production

- The source arrived over WhatsApp at 478×850 — a 2.26× upscale to 1080×1920 and
  visibly soft. Always ask for the original file.
- Whisper needed nine corrections, including `פינק פונק` → `פינג פונג` and
  `קוד מענקי` → `קוף מקודד`. Read the transcript; do not trust it.
- The first pass put the cards over the speaker's face. They moved to the empty
  wall above his head and the reel improved more from that one change than from
  any individual visual.
