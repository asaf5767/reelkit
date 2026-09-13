# SESSION-STATE.md

Coordination snapshot for the Claude Code / Instinct collaboration on reelkit.
Written 2026-09-13. Supersedes nothing; CLAUDE.md remains the working agreement
and NEXT.md the backlog.

## Priority order (set 2026-09-13, supersedes NEXT.md ordering)

From the owner, verbatim: *"Watch Yuval's videos and see how she edits. This is
what I want. This is my end goal. Forget the service right now."*

1. **style-defaults-from-reference** - the reference reels' editing moves become
   repo defaults **as code or config, not prose**. Instinct is doing the video
   analysis and hands over concrete moves; Claude Code encodes them. Claude Code
   does **not** invent style rules.
2. **fast lane / auto-plan** - now sanctioned, but only in service of #1.
3. everything else.
4. **Railway service - parked.** Do not spend effort there. The Dockerfile and
   `worker.py` stay in the repo and stay working; nobody is deploying them.

NEXT.md's numbering is the older backlog and no longer reflects order. #1, #2,
#5 and #6 in it are done (PRs #8, #3, #6/#7, #4).

## Pull requests

| PR | Branch | State | What it is |
| --- | --- | --- | --- |
| #1 | `feat/provider-neutral-worker` | **merged** | transcribe provider seam, `worker.py` with a fail-closed gate, Dockerfile + railway.toml |
| #2 | `feat/real-sfx-pack` | **merged** | 18 CC0 cues bundled at `skills/reelkit/assets/sfx`, replacing the synth as the default |
| #3 | `feat/derived-card-geometry` | **merged** | NEXT #2: image-slot box derived from CSS; build resolves card layout against measured geometry |
| #5 | `fix/two-pass-logfile` | **merged** | size-cap encode no longer drops `ffmpeg2pass-0.log` in the working directory |
| #4 | `feat/preview-frame-reuse` | **merged** | NEXT #6: `--preview` is a full-fidelity segment subset the full render resumes |
| #6 | `fix/verify-findings-format` | **merged** | worker gate crashed with `KeyError: 0` on any verify finding |
| #7 | `fix/docker-render-browser` | **merged** | NEXT #5: container could not render; `unzip` + pinned browser path |
| #8 | `feat/render-gate` | **merged** | NEXT #1: `verify` runs as a fail-closed gate inside `render_project`, so every render path is gated |
| #9 | `feat/render-cost-cuts` | **merged** (`f5557e8`) | renderer pinned to `hyperframes@0.8.36`; measurement cache (`mcache.py`); decoded frame count cached. Kaggle: preview 150s / full 444s vs 156 / 484 baseline |

## Design decisions and their basis

**Reuse is keyed on command + inputs, not on bytes.** Every rendered segment
gets a `segment-NNN.mp4.key.json` sidecar holding a sha256 over the segment's
plan and transcript, the source clip, the render fps/quality, and the pipeline
scripts and brand presets that `build` is a pure function of. A segment is
resumed only when that hash matches *and* it decodes to the expected frame
count; otherwise it re-renders with the reason printed. Frame count alone cannot
see a changed plan, a re-cut source or an edited card library - each changes the
render while leaving the count identical. Invalidation is precise: editing one
beat re-renders only the segment carrying it.

**Render nondeterminism is a toolchain property, not a reuse defect.** Two
renders of one unchanged segment on real footage produce only two distinct
outputs, differing in occasional individual frames (four of five sampled frames
hash equal, the fifth does not; min SSIM 0.989, audio identical). Worker count
makes no difference and it is not a temporal offset. The synthetic sample *is*
byte-identical, which is what makes this easy to miss. Consequences:

- byte-identity was proposed as a guardrail for #4 and is not achievable;
  accepted basis is "identical command, identical inputs = equally valid render"
- it predates segment reuse - every resume the pipeline has ever done kept a
  segment a re-render would not reproduce bit for bit
- `renderdiff.py`'s exact-bitmap and SSIM >= 0.999 thresholds therefore cannot
  pass on real video, only on the sample. Worth a NEXT.md entry

**Build is stricter than verify, deliberately.** `build` enforces the documented
72px breathing margin above the head (`head_clear_y`); `verify` only ERRORs on
actual head contact. A card verify calls clean may still be nudged by build.

**`--preview` changed meaning** (#4): it renders leading segments at authored fps
and standard quality into the same `segment-NNN.mp4` files a full render writes,
rather than the whole timeline at 10fps draft. `reelkit.py render --preview`
keeps the old throwaway-draft meaning and says so in its output, because without
segments there is no subset to render.

**Geometry is measured, never authored** (#3). `geometry.py` holds the browser
measurement and the fit maths, imported by both `build` and `verify` so they
cannot disagree. Plan `image.box` is ignored with a warning.

**Provider seams are command adapters** (#1), declared in
`config/providers.json`: `transcribe`, `planAuthor`, `image`. Swapping a vendor
is a config edit plus an adapter script, never a code edit. `transcribe` has a
bundled default so a clean checkout works with no key.

## Railway dockerization validation (NEXT #5)

Ran in this sandbox by starting a Docker daemon, building the image, and running
`worker.py` **inside the container** on the synthetic sample.

Result: **end to end, exit 0, 58s.** Output verified rather than assumed -
1080x1920, h264/yuv420p, 30fps, 360 decoded frames, 12.0s, clean decode pass,
clean container audit (moov first, bt709). All declared assets staged.

Three things broke:

1. **Build failed on TLS** - `curl: (60) self-signed certificate in chain`
   fetching the NodeSource key. That is this sandbox's TLS-terminating egress
   proxy, not Railway. Built with the proxy CA *trusted* (never bypassed) via a
   validation-only Dockerfile overlay that is not in the repo. **No change
   needed for Railway.**
2. **Container could not render a frame** (#7, real). HyperFrames renders with
   its own chrome-headless-shell, not Playwright's browser, and fetches it on
   first render: the image had neither `unzip` to extract it nor anything
   pointing at the Chromium it already contains. Would fail identically on
   Railway. Fixed with `unzip` plus `HYPERFRAMES_BROWSER_PATH` pointing at a
   symlink resolved **at build time** - hardcoding `chromium-1234` would break
   the next time the pip package moves.
3. **Gate crashed on a WARN** (#6, real). `verify.json` serialises findings as
   `{level,id,message}` while `worker.py` read `f[0]`.

### Two unattributed 404s

The render logs two `[non-blocking] Failed to load resource: 404`. Every
declared asset is present - the video, all four staged SFX cues, gsap, and all
seven fonts referenced in the CSS were each checked, since tofu is a documented
hazard. So it is **not** a missing font or cue, and HyperFrames marks them
non-blocking, but what they are is unknown. Recorded rather than guessed; worth
a look if an asset ever goes silently absent from a render.

### Limits of that evidence

The validation ran on the 12s synthetic sample, on this box, not on Railway. It
proves the toolchain inside the image is complete and the pipeline runs to a
valid MP4. It does **not** prove Railway's memory ceiling, disk allowance or
build timeout are sufficient - that needs a real deploy. The sample has no face,
so the geometry fit pass never executed inside the container; the image still
needs a first real-footage run.

## What is next

- **NEXT #1 (in progress)** - wire `verify.py` into the render pipeline so a
  head-zone collision fails the render automatically instead of being gated by
  hand on snapshots. Open questions: where the gate belongs (build, render, or
  both) and making verify's dependencies explicit so the Kaggle kernel can
  satisfy them. Note `worker.py` already gates fail-closed, but the Kaggle
  driver does not go through the worker.
- **#4** awaiting Instinct's revalidation against head `71d6afe`.
- **Renderer nondeterminism** deserves a NEXT.md entry in its own right: it
  makes `renderdiff.py`'s acceptance thresholds unmeetable on real footage.
- **NEXT #3** (real SFX library on Kaggle) and **#4** (Assaf-avatar, parked by
  the owner - do not start without his go-ahead) unchanged.

## Environment notes for whoever picks this up

- Renders are Instinct's; this session does not render on real footage without
  being asked.
- fal.ai spend is real money. `FAL_KEY` is unset here, so the image path has
  never been exercised against the live provider.
- Docker works in this sandbox only after `dockerd` is started manually, and
  builds need `--network=host` plus the proxy CA trusted.
- Test suite: `python3 -m unittest discover -s tests`. All branches green at
  time of writing.


## Render cost profile (v9 follow-up, 2026-09-13)

Measured on the 12s sample, 2 workers, by wrapping segmentrender's subprocess
helpers and reading HyperFrames' own phase trace. No code was changed.

**The fixed cost is per render *invocation*, not per segment-second.** Two-point
fit on the same composition (38 frames = 20.34s, 360 frames = 48s):

    cost = 17.1s fixed + 0.086s per frame

So a 38-frame segment spends ~3.3s capturing frames and ~17s on everything else.
Where the 17.1s goes:

| Component | Local | Note |
| --- | --- | --- |
| `capture_disk` fixed | ~8.1s | Chrome launches (one per worker) |
| `encode` | ~4.5s | near-constant: 4.52s at 38 frames, 5.35s at 360 |
| npx/node/python startup | ~3.4s | of which `npx -y hyperframes@latest` alone is 1.6s |
| assemble | 0.56s | |
| compile + probe + extract + audio + file-server | 0.65s | |

segmentrender's own per-segment glue adds ~5s more: ffmpeg trim in `prepare`
2.8s, `build` 1.6-1.75s, `valid_video`'s decode-count probe 0.5-0.65s. Key
hashing, join and export are together under 1s and are not worth touching.

**Extrapolating to Kaggle v9** (484s, 645 frames rendered at ~2.4fps = 269s
capture): ~215s of fixed cost across 2 rendered segments plus glue, i.e. roughly
**80-100s fixed per render invocation** - about 5x this box, consistent with a
slower kernel and slower npx.

Ranked candidates (not implemented, pending Instinct's call):

1. **Fewer, longer segments.** Cost scales with segment *count*. 12s -> 24s
   segments on a 47s reel is 4 invocations -> 2, saving ~1 invocation-fixed-cost
   each. Already a flag (`--segment-seconds`); the trade is coarser resume.
2. **Pin the HyperFrames version** instead of `npx -y hyperframes@latest`. 1.6s
   per invocation locally just to resolve `@latest`, paid by build, render,
   check and snapshot alike, and worse on a slow network. Also a correctness
   win: `@latest` lets the renderer change mid-project.
3. **Let the render gate reuse build's measurement.** PR #8 adds ~1.3s locally
   per invocation (a second Chromium launch plus face detection) seconds after
   `build` measured the same things. Proportionally larger on Kaggle.
4. **Stream-copy the `prepare` trim** where boundaries land on keyframes,
   instead of re-encoding at crf 17. ~2.8s per segment locally.
5. **Cache the decoded-frame count in the sidecar**, re-deriving only when size
   or mtime changes. ~0.5s per segment locally.

Items 1 and 4 are the only ones that touch behaviour; 2, 3 and 5 are cost-only.
