# Versioned editorial plans

A Reelkit project keeps the edit and the graphics independent:

- `cut-plan.vN.json` owns source ranges and their output-time mapping. A caption or graphic fix never changes it.
- `graphics-plan.vN.json` owns captions, framing, overlays, images and style-template reference.
- `plan.json` is a deterministic materialized build input from those two layers.

Each layer carries `version`, optional `parentVersion`, and a short list of patches. Never overwrite history during review.

## Correction loop

Every review note is `{ "frame": <seconds or frame number>, "note": "..." }`. Apply it as a patch to the owning layer and increment only that layer's version. Record a per-render version that names the exact cut-plan, graphics-plan and style template used.

## Style DNA

Ingest each reference reel into a named template under `templates/<name>/template.json`. Templates are versioned and drive hook treatment, captions, text zones, overlay rhythm and graphic silence identically across a batch. The supplied `yuval-face-first-hebrew@1` template is for short vertical Hebrew talking-head reels. RTL remains a Reelkit rendering layer.

Out of scope: After Effects and DaVinci targets, music beds, and long-form pacing.
