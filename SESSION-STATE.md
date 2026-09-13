# SESSION-STATE.md

Handoff for the next driver on reelkit. CLAUDE.md remains the working agreement;
this is the live state on top of it. NEXT.md's numbering is historical and no
longer reflects priority.

Written at the end of the style-pack build session. `main` is at **`11fdbae`**
(PR #13 merged). Seven PRs are open in a stack.

---

## 1. Priority

From the owner: *"Watch Yuval's videos and see how she edits. This is what I
want. This is my end goal. Forget the service right now."*

1. **style-defaults-from-reference** - the reference reels' editing moves become
   repo defaults as code or config, never prose. Instinct does the video
   analysis and hands over concrete moves; Claude Code encodes them and does
   **not** invent style rules.
2. **fast lane / auto-plan** - sanctioned, but only in service of #1.
3. **Railway service - parked.** The Dockerfile and `worker.py` stay in the repo
   and stay working; nobody is deploying them.

---

## 2. The open PR chain (#14 - #20)

**Merge in this order.** Each is stacked on the one above, mostly because they
share `style.SCHEMA` and `reelkit.py`. Merging out of order will conflict.

| PR | Branch | Scope |
| --- | --- | --- |
| #14 | `feat/audio-mix` | ffmpeg audio mix stage; voice chain + SFX ducking; **fixes the segmented path silently dropping every SFX cue** |
| #15 | `feat/doodle-svg` | `doodle` upgraded in place to a named hand-drawn mark family (circle-scribble, underline, curved-arrow, sparkle), draw-on via `stroke-dashoffset` |
| #16 | `feat/caption-treatments` | caption stroke, per-word emphasis, emoji inside the line, keyword detonation; caption-band-vs-head gate |
| #17 | `feat/title-lockup` | mixed-typeface lockup at frame 0, marker or circled accent; **also gates the mandatory hook card, which no gate had ever measured** |
| #18 | `feat/pip-outro` | `pip` head inset with mandatory `justification`; branded outro; `docs/asset-library.md` |
| #19 | `feat/progress-lowerthird` | progress-dim sequencing driven by word timings; lower-third band with its own gate |
| #20 | `feat/lottie-badges` | Lottie badge overlays; vendored MIT player + self-authored CC0 badges; cost inspected inside the JSON |

Merged earlier this session: #10, #11 (docs), #12 (brand single-source + heavy
budget gate), #13 (style profiles).

---

## 3. Review by running

Nothing here is reviewed by reading it. Every defect found tonight that mattered
was found by running something and measuring the result - the SFX drop, the
timecode leak, the unmeasured hook card, the badge sitting inside the caption
band. The code read fine in all four cases.

**Local, every PR:**

```bash
python3 -m unittest discover -s tests        # NOT pytest - the suite is unittest
```

175 tests on `main` as it stands; **356 with the whole open stack merged** -
the difference is the 181 added by #14-#20. Add tests in the same commit as the
behaviour; several of tonight's gates exist because a test was written first and
failed honestly.

**Kaggle, every PR** - the real gate. Local green has passed while the kernel
failed, twice, both times on something only real footage exposes.

**For any PR touching audio, also probe cue audibility.** Peak level alone is
not evidence: a cue quieter than the speech under it never raises the peak, and
comparing a file against itself with an approximate seek reads as loud
everywhere. Measure what the mix ADDED - subtract the source with a
sample-accurate seek (`atrim` after a full decode, never `-ss` before `-i`) and
sample across the cue's own duration, because a riser opens near silence and
builds. Reference numbers on the 12s sample: a real cue reads -17 to -18 dBFS of
added signal against a -63 to -67 codec-noise floor.

**Container audit** runs inside `verify` and now ERRORs on any stream that is
not video or audio. It earned that: a phone source's timecode track rode into a
deliverable through `-c copy` with no `-map`, and the mp4 muxer re-creates a
`tmcd` track from input metadata regardless of `-map`/`-dn`/`-sn` - only
`-write_tmcd 0` stops it.

---

## 4. The Kaggle recipe

- One dataset per PR; kernel **`reelkit-next-full-render`**.
- Source is the 32.5s clip.
- **Wait-ready race:** the kernel can report ready before the dataset has
  finished attaching, and a run started in that window renders against stale
  files and looks like a code regression. Confirm the dataset is attached before
  starting, not just that the kernel is up.
- The runtime dataset carries a tgz snapshot of the scripts - bump it when
  scripts change, or the kernel runs stale code.
- Renders go through the **segmented** path, which is the one that had the audio
  bug. Assume it is the path under test.

---

## 5. Decisions - keep these

- **Unknown keys are fatal.** In style profiles, the Lottie manifest, and plan
  badge/pip objects. A configured-but-inert key is worse than a missing one.
- **A profile carries only what the build consumes.** Each capability widens
  `style.SCHEMA` in the same commit that reads it, so the file and the behaviour
  cannot drift apart.
- **The gate is never reachable from a profile.** Face-zone constants,
  `SCALE_FLOOR`, hook- and SFX-by-construction, RTL rules stay constants.
- **Cadence is an ERROR** under `assaf-v1`: a layout holds 2-4s. No warn period.
  The shipped example is pinned to `"style": "base"` because 11 of its 14 beats
  predate the rule.
- **PiP needs a `justification`** naming the literal thing on screen, or the
  build fails. Face full frame is the default; PiP is the exception.
- **Emoji ride inside their word's span**, never appended to the line - bidi
  would strand them at whichever edge the paragraph direction chose.
- **No neon boxes.** Emphasis is type, weight and one flat accent. Tested
  against `blur(`, `radial-gradient`, `box-shadow`, `text-shadow`, `filter:`.
- **Literal B-roll only**, and **no clip, no cut** - if nothing shows the thing,
  the speaker stays full frame.
- **The hook title is on screen at frame 0** - a `set`, not a `fromTo` from
  opacity 0, which would leave the first frame blank.
- **Cue placement is not configurable.** Losing a cue is a defect, not a
  preference, so there is no key for it.

---

## 6. Where the style doctrine came from

**Not reproducible from this session, and worth knowing before trusting any of
it second-hand.** The reference corpus - the Yuval north-star reel, four
reference reels, Kallaway frames, and a screen recording of a Submagic template
- was analysed by Instinct. The files were never reachable from this sandbox
(`/home/sandbox` does not exist here), so every style value in `assaf-v1` and
every "hard don't" arrived as a written brief in-session and was encoded as
given.

Practical consequence for the next driver: if a value looks wrong on a render,
it cannot be re-derived here. Ask Instinct to re-check it against the corpus.
The hard don'ts, all from the Submagic viewing, are: never cover the face, no
reversed or clipped RTL captions, no neon boxes, no generic stock B-roll.

---

## 7. The morning deliverable

A proof render on the 32.5s source with the style pack applied, including **at
least one justified PiP moment** so the owner can judge the inset live, plus a
changelog of what each slice changed.

Two things to know before planning that cut:

- **`videos/wareel`'s framing is too tight for a lower-third** at the default
  caption position: the band lands at y=1282 while the head reaches y=1322, and
  the gate refuses it. Raising `captions.top` to 1620 makes it pass. Same will
  likely apply to the 32.5s source - check before including one.
- **A reel using the outro carries a non-blocking WARN**: HyperFrames reports
  overlapping opacity tweens on the end card's host over a ~0.1s window. It
  comes from generic host-fade logic meeting a beat that ends with the reel, not
  from the card.

---

## 8. Environment notes

- Renders are Instinct's. This session does not render on real footage unasked.
- `FAL_KEY` is unset here, so the image path has never run against the live
  provider. fal.ai spend is real money.
- Docker works in this sandbox only after `dockerd` is started manually; builds
  need `--network=host`, the proxy CA trusted, and apt pointed at https (the
  egress proxy accepts only CONNECT and answers plain HTTP with 405).
- The renderer is pinned at `hyperframes@0.8.36` via `reelkit.HF_VERSION`, which
  is the single source of truth; the Dockerfile cross-checks it and fails the
  build on a mismatch.
- `segment_key()` hashes the pipeline scripts, `assets/brand/` and
  `assets/style/`. **It does not yet hash `assets/lottie/` or a future
  `assets/broll/` manifest** - both change pixels, so both need adding when
  those assets are live.
