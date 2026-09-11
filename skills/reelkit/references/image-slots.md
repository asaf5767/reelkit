# Image slots

A slot lets an image-capable agent replace a drawn card with real artwork without
touching the composition. An agent with no image generation ignores the whole
mechanism and still produces a finished reel.

## The contract

1. A beat declares `"image": { "prompt": "…", "mode": "replace" | "behind", … }`.
2. `build` writes `visuals.json` listing every slot: id, time span, exact pixel box,
   aspect ratio, transparency requirement, prompt, and whether the file is present.
3. The agent renders each slot to `public/images/<beatId>.png`.
4. Re-run `build`. Present files are used; absent ones fall back to the drawn card.

Re-running `build` is always safe — it is a pure function of `plan.json` plus
whatever files exist.

```json
{
  "id": "b02", "start": 7.0, "end": 16.2, "kind": "doodle",
  "file": "public/images/b02.png", "present": false,
  "box": { "x": 40, "y": 300, "w": 1000, "h": 620 },
  "aspect": 1.613, "alpha": false, "mode": "replace",
  "prompt": "…", "intent": "The day is a ping-pong rally with the AI"
}
```

## modes

**`replace`** — the image becomes the beat. Framed with rounded corners and a slow
Ken Burns push. Use when the image *is* the idea.

**`behind`** — the image sits at 55% opacity behind the drawn card. Use for texture
and atmosphere under a chart or a notification, never for anything that must be read.

**`canvas`** — the image sits inside a `split` beat's light panel, beside or under
the kicker and headline. This one is declared in `data.image` rather than the
beat's top-level `image` block, because the panel's height is resolved per beat
against the detected face and the slot's box only exists once the canvas does.
Schema and the `wide`/`tall` choice: `references/plan-schema.md`.

The palette advice below inverts for `canvas`: the panel is a **light** surface,
so a dark-ground image is the thing that punches a hole. Ask for a light or white
background, and `"frame": "bare"` when the image already carries its own edge.

## Writing prompts that survive contact with the reel

- **Match the aspect ratio in `box`.** A square image in a 1.6:1 slot gets letterboxed.
- **Say "no text".** Generated lettering is unreliable in any language and actively
  broken in Hebrew and Arabic. All type in this format comes from the composition.
- **Name the palette.** Give the brand accents as hex in the prompt so the image
  belongs to the same reel as the cards around it.
- **Specify a dark ground** (or `"alpha": true` and a transparent background). These
  images sit over dimmed footage; a white-background image punches a hole in the frame.
- **Describe an object or a scene, not a concept.** "A ping-pong rally seen side-on,
  one paddle orange, one cyan, ball mid-arc with a motion trail" beats "collaboration
  between human and AI" — which returns a stock handshake every time.
- **Keep a consistent style phrase** across every slot in one reel: "flat editorial
  vector, deep navy ground, no text" repeated verbatim is what makes eight separately
  generated images look like one set.

## Transparency

Set `"alpha": true` when the subject should float over the footage with no frame.
The build switches the frame to `bare` — no border, no shadow, no background.
The generated PNG must actually carry an alpha channel; a white background with
`alpha: true` looks worse than the drawn fallback.

## When not to use a slot

Charts, diagrams, code, chat threads and device UI should stay drawn. They are
crisper, they animate element by element, their text is real text at any resolution,
and they cannot hallucinate a fourth bar. Reach for images for **scenes, metaphors,
characters, textures and objects** — the things vector cards are bad at.
