# SESSION-STATE.md

Coordination snapshot for the Claude Code / Instinct collaboration on reelkit.
Written 2026-09-13. Supersedes nothing; CLAUDE.md remains the working agreement
and NEXT.md the backlog.

## Pull requests

| PR | Branch | State | What it is |
| --- | --- | --- | --- |
| #1 | `feat/provider-neutral-worker` | **merged** | transcribe provider seam, `worker.py` with a fail-closed gate, Dockerfile + railway.toml |
| #2 | `feat/real-sfx-pack` | **merged** | 18 CC0 cues bundled at `skills/reelkit/assets/sfx`, replacing the synth as the default |
| #3 | `feat/derived-card-geometry` | **merged** | NEXT #2: image-slot box derived from CSS; build resolves card layout against measured geometry |
| #5 | `fix/two-pass-logfile` | **merged** | size-cap encode no longer drops `ffmpeg2pass-0.log` in the working directory |
| #4 | `feat/preview-frame-reuse` | **open** | NEXT #6: `--preview` is a full-fidelity segment subset the full render resumes. Head `71d6afe`. Instinct revalidating after rewriting the Kaggle driver |
| #6 | `fix/verify-findings-format` | **open, merging** | worker gate crashed with `KeyError: 0` on any verify finding |
| #7 | `fix/docker-render-browser` | **open, stacks #6** | NEXT #5: container could not render; `unzip` + pinned browser path |

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
