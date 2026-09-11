# verify — the automated quality gate

Until this existed, the only thing standing between a bad reel and a rendered one
was a person looking at a contact sheet and noticing that a card sat on the
speaker's mouth. `verify` makes that check mechanical.

```bash
python3 scripts/reelkit.py verify --project videos/myreel [--json] [--fix]
```

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

## How the face check is calibrated

Two details matter, and getting them wrong makes the check useless:

- **Only the lower 70% of the face counts.** Cards arrive from above, and clipping
  the top of someone's hair is harmless. Eyes and mouth are not.
- **The check is mode-aware.** In `top` mode the speaker is the subject, so a card
  on their face is an error at 12% and a warning at 4%. In `stage`/`full` the
  speaker is deliberately dimmed and overlap is the intent — only a card burying
  more than 55% of them is worth a warning.

Without the mode rule every `stage` beat in a normal reel reports as a defect,
which trains you to ignore the tool.

## `--fix`

Applies only remedies that are mechanical: a `top`-mode card covering the eyes or
mouth gets a `layout.top` that places it above the head, when it fits. Everything
else is reported, never silently rewritten — a card that overlaps the caption band
might want to move, shrink, change mode or be deleted, and only a person or an
agent with the context can say which.

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
