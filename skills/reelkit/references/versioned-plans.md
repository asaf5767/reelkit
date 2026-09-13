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

## Opening hook title

Every reel starts with a short hook text title in the upper text zone. It may overlap the opening speech in time, but it must stay clear of the whole head and the caption zone. The hook is an editorial promise, not a transcript duplicate.

Auto-pick the strongest scroll-stopping title and render without blocking the video-in/video-out pipeline. A hook should be short, create tension or a curiosity gap, and read like native social copy rather than a documentary summary. Include two or three runners-up in the render report; the user can swap one with a single `{frame, note}` graphics-plan correction during normal review. The cut-plan never changes for a hook-title choice.

## Hook taste calibration

Accepted Hebrew pattern: `נתקעתם? אל תשחקו אותה גיבורים` - direct address, tension, and a native pattern interrupt before the reel explains itself.

Rejected pattern: lesson-summary hooks such as `מתי להרים דגל?`, `לא צריך להילחם בשקט`, and `לבקש עזרה זו מיומנות`. They accurately summarize the topic but do not stop the scroll. Accuracy is necessary; summary shape is not enough.

## Service-compatible, not a service

Keep each stage explicit, config-driven, cacheable and callable with project paths so a future service wrapper can orchestrate the same commands. Do not add SaaS-only work now: no multi-tenancy, user auth, hosted control plane, billing, provider queue abstraction, or remote job database. The current product is the single-user video-in/video-out pipeline.
