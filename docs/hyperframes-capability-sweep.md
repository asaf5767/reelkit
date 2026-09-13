# HyperFrames capability sweep: what reelkit does not use yet

Status: **survey, no implementation.** Everything below is inventory and costing.
Which moves we actually adopt is Instinct's call after the reference analysis.

Scope: the HyperFrames skill set and the live registry only. External
alternatives (Remotion, revideo, Manim, Lottie-as-a-format, raw ffmpeg filters)
are Instinct's parallel survey and are not covered here.

**One caveat on the "style move" column.** I have not seen the reference reels.
Each row says *what the capability makes possible* — the named moves are
illustrations of the capability's reach, not a claim about what Yuval actually
does. Matching them to her real moves is the analysis in flight.

---

## 1. What reelkit uses today

| Surface | Available | reelkit uses |
|---|---|---|
| Runtime adapters | 7 (GSAP, Lottie, Three.js, Anime.js, CSS keyframes, WAAPI, TypeGPU) | **1** — GSAP |
| GSAP verbs | full timeline API | **3** — `fromTo` x12, `set` x1, `to` x1 |
| Motion primitives | — | **4** — `fade`, `pop`, `slide`, `grow_h` |
| Animated channels | transforms, 3D, clip-path, masks, SVG, filters, CSS vars, shader uniforms | **4** — `opacity`, `scale`, `x`, `y` |
| Named animation rules | 48 | **0** |
| Scene blueprints | 22 | **0** |
| Named CSS transitions | ~44 across 13 families | **0** |
| Named text effects | 24 | **0** (reelkit has its own per-char `kinetic()`) |
| Registry items | **393** (174 blocks, 219 components) | **0** |
| Audio mixing (`hf-audio-group`, `data-fx-chain`, `data-automation`, `data-fx-carve`, 15 FX) | full | **0** — SFX are bare clips with a volume number |
| talking-head-recut design tokens | 4 layouts, 10 styles, 3 video frames | own card library instead |
| HyperFrames CLI verbs | ~30 | **2** — `render`, `transcribe` |

Already used and working, so not in the sweep: sub-compositions
(`data-composition-id`), four tracks, `data-no-timeline`, `data-start` /
`data-duration`, deterministic seek-safe `fromTo`, word-level transcript timing.

**Headline:** reelkit uses HyperFrames as a renderer and a transcriber. The
composition, motion and design layers are hand-rolled in `cards.py`. That is not
wrong — it is why the face-zone law and RTL handling are enforceable — but it
means the great majority of the framework is unexplored.

---

## 2. The constraint that prices everything below

From `reelkit.py`, learned the hard way and already in the code as a comment:

> HyperFrames lints heavy-overlay elements (`filter: blur`, `radial-gradient`,
> `clip-path`) because **past ~40 of them the capture layer returns solid black
> for the first half of the render**. Fourteen plates took this composition from
> 0 to 105 heavy elements in one commit.

This is the real budget. Any capability whose look depends on blur, glow, neon,
soft shadow, gradient masking or shader passes spends against it, and the failure
mode is not a warning — it is a black render that only a full pass reveals.

**Consequence for this sweep:** every row is costed with that in mind, and rows
that spend heavily are marked ⚠︎. A "heavy-element budget" is probably a
prerequisite for adopting any of them, and `verify.py` counting heavy elements
is the natural place to enforce it — the same fail-closed treatment the head
zone already gets.

Second constraint: **render cost scales with invocation count**, and the
measured floor is ~17s locally / 80–100s on Kaggle per render invocation. Effects
that raise per-frame capture time (3D, shaders, large blurs) push the 0.086s/frame
term up, which is the term that actually grows with reel length.

---

## 3. The sweep

Cost key: **C** = config only, once a style profile exists (PR #10) · **K** = new
beat kind or card builder · **P** = new pipeline stage or gate change · **D** =
new dependency / asset class · ⚠︎ = spends the heavy-element budget.

### 3.1 Text and captions — the densest opportunity

reelkit's captions are word-level, three words a line, one highlight colour. The
registry has 16 caption treatments as drop-in blocks.

| Unused capability | Style move it unlocks | Cost |
|---|---|---|
| `caption-highlight`, `caption-pill-karaoke`, `caption-editorial-emphasis` | one-word-at-a-time karaoke captions; emphasis word in a pill | **C→K** — needs caption CSS swap, RTL check |
| `caption-kinetic-slam`, `caption-weight-shift` | the hard per-word slam on a stressed word | **K** |
| `caption-gradient-fill`, `caption-texture`, `caption-neon-accent` | branded caption fill instead of flat white | **C** (gradient ⚠︎) |
| `caption-neon-glow`, `caption-glitch-rgb`, `caption-particle-burst`, `caption-matrix-decode` | glow/glitch accents | **K** ⚠︎⚠︎ — heaviest rows here |
| `caption-camera-follow`, `caption-parallax-layers` | captions that track a punch-in instead of sitting still | **K+P** — interacts with the face zone |
| `caption-emoji-pop` | emoji beat on a punchline | **K+D** (emoji font) |
| 24 named text effects (7 per-char, 8 per-word, 2 per-line, 7 whole-element) | a *named, consistent* entrance across every card instead of three ad-hoc ones | **D** — see licence note below |
| `bottom-up-letters`, `per-word-rise`, `scramble-reveal`, `tracking-in`, `split-flap-board`, `kinetic-type-swap` | hook-title reveals with real character | **K** |

> **Licence note on the 24 text effects.** They are *not* shipped in the
> HyperFrames repo. They live in Pixel Point's upstream `animate-text` skill,
> which as of the skill's own writing declares **no explicit licence** — which is
> why HyperFrames deliberately does not vendor them. reelkit bundles assets into
> a public repo, so under CLAUDE.md's licensing rule we cannot copy those specs
> in. We can name the effects and reimplement the motion ourselves from the
> vocabulary; we cannot lift the files. Flagging this before anyone plans around
> them.

### 3.2 Camera and framing — the biggest visible gap

reelkit never moves the camera. The footage is a static crop for the whole reel.

| Unused capability | Style move it unlocks | Cost |
|---|---|---|
| `push-in`, `pull-back-reveal`, `ui-focus-zoom`, `parallax-unzoom` | the punch-in on a punchline — arguably *the* short-form move | **K+P** — the face zone is computed per beat against a static frame; a zoom moves the head mid-beat, so `verify` must sample the zoomed geometry, not the source |
| `camera-dolly-zoom`, `drift-hold`, `camera-shake` | slow drift on a hold; shake on an impact | **K** |
| `focus-rack`, `rack-focus`, `depth-of-field-blur` | pull focus between speaker and graphic | **K** ⚠︎ |
| `multi-phase-camera`, `coordinate-target-zoom`, `camera-journey` (blueprint) | multi-stop camera journey across a diagram | **K+P** |
| `hyperframes-keyframes`: array/percentage keyframe ladders, `transformOrigin`, FLIP | any of the above done seek-safely rather than by hand | **P** — reelkit emits only single-segment `fromTo`; ladders are a builder change |

**This is the row I would flag hardest.** A punch-in is cheap visually and
expensive structurally, because it is the first capability that breaks the
assumption the face-zone gate rests on: that the head's position in a beat can be
measured from one frame of the source. Worth deciding early whether the gate
measures post-transform geometry.

### 3.3 Transitions between beats

reelkit cuts hard between every beat. There is no transition layer at all.

| Unused capability | Style move it unlocks | Cost |
|---|---|---|
| ~44 named CSS transitions in 13 families (push, cover, scale, dissolve, radial, blur, light, mechanical, grid, distortion, destruction, 3D, other) | whip/slide/wipe between beats instead of a cut | **K+P** — needs an overlap window; reelkit's beats are non-overlapping by construction and segment boundaries are cut points, so this touches `segmentrender` |
| 47 `transition`-tagged registry items, 19 `transition-primitive` | same, as installable blocks | **C→K** |
| `scale-swap-transition`, `card-morph-anchor`, `theme-crossfade-morph` (rules) | one card morphing into the next rather than replacing it | **K** |
| `light-sweep-pass`, `editorial-flash-overlay`, `grade-split-reveal` | the flash-cut on a beat change | **K** ⚠︎ |

⚠︎ Structural note: the transition registry works by *overlapping two scene
wrappers* and ping-ponging `data-track-index`. reelkit's segment renderer splits
on beat boundaries; an overlap that straddles a segment boundary would render
half in each segment. Adopting transitions means teaching `boundaries()` never to
cut inside an overlap window.

### 3.4 Overlays, lower-thirds and graphics

| Unused capability | Style move it unlocks | Cost |
|---|---|---|
| 26+ lower-third blocks (`lt-*`, `lower-third-bild`, `yt-lower-third`) | named-speaker / topic bar, the standard talking-head dressing reelkit has none of | **C→K** |
| Handwritten family (`hw-arrow`, `hw-box-label`, `hw-callout-circle`, `hw-path-text`, `hw-pipeline`, `hw-text-cloud`, `hw-write-title`, `whiteboard-ink`, `svg-stroke-trace`, `svg-path-draw`) | the hand-drawn circle/arrow annotating the speaker — very Kallaway | **K** — SVG path draw is cheap and does *not* spend the heavy budget |
| `orbit-3d-entry`, `locked-nucleus-orbit`, `constellation-hub`, `avatar-cloud-network` | orbit graphics (named in the brief) | **K** ⚠︎ (3D) |
| `notification-cascade`, `macos-notification`, `slack-notification-ad`, `message-thread-reveal`, `chat-thread` | reelkit has drawn `notification`/`chat` kinds; these are richer and free | **C→K** |
| `social-proof-card`, `instagram-follow`, `tiktok-follow`, `x-post`, `reddit-post`, `yt-comment-card`, `spotify-card` | social-proof and platform-native inserts | **C→K** |
| `freeze-frame-dressing` | freeze the speaker and annotate the frozen frame | **K+P** |
| `grain-overlay`, `camcorder-hud`, `chromatic-glitch`, `ambient-glow-bloom`, `motion-blur-streak` | texture/grade passes over the whole frame | **K** ⚠︎⚠︎ |
| Animated-badge equivalents (no single block; composed from `spring-pop`, `spring-pop-entrance`, `physics-press-reaction`, `press-release-spring`, `counting-dynamic-scale`) | animated badges and springy counters (brief names these) | **K** — spring easing only, cheap |

### 3.5 Data and diagrams

reelkit has `stat`, `contrast`, `donut`, `bars`, `checklist`, `chips`.

| Unused capability | Style move it unlocks | Cost |
|---|---|---|
| `animated-bar-chart`, `bar-chart-race`, `data-chart`, `decline-chart`, `number-wheel`, `conic-progress-ring`, `star-rating-fill`, `oscilloscope-trace` | richer data reveals than the drawn bars | **C→K** |
| `chart-scrub-readout` (rule) | a number that counts as a bar fills, tied to the timeline | **K** |
| `stat-bars-and-fills`, `waterfall-entry`, `dynamic-content-sequencing`, `discrete-text-sequence` | **progress-dim diagrams** (named in the brief): list items dim as the next lights up | **K** — no heavy elements; strong value/cost ratio |
| `logo-wall`, `world-map` / `us-map` family, `spain-map` | geography and logo grids | **C→K** |
| `hyperframes-creative` → `references/data-in-motion.md` | direction for the above rather than invention | **C** |

### 3.6 Audio — completely untouched

reelkit places SFX as bare clips with a volume number. The whole mixing layer is
unused: `hf-audio-group` submix buses, `data-fx-chain` (15 FX: gain, compressor,
limiter, gate, EQ x4, saturate, bitcrush, chorus, phaser, delay, reverb),
`data-automation` envelopes, `data-fx-carve` voiceover ducking.

| Unused capability | Style move it unlocks | Cost |
|---|---|---|
| `data-fx-chain` voice presets (compressor + EQ + limiter) | the speaker's voice sounding produced rather than as-recorded — a phone-recorded reel's biggest audible tell | **C→P** — a mix stage before export |
| `data-fx-carve` | SFX ducking under speech so cues stop competing with words | **C** |
| `data-automation` envelopes | cue volume riding the moment instead of one fixed number | **C** |
| `hf-audio-group` | one bus for all SFX, one fader | **C** |

**Cheapest real quality win in the whole sweep.** No heavy elements, no render
cost, no new dependency — and it addresses something every viewer hears. Note it
does *not* violate the no-music-bed doctrine: this is processing the voice and
the existing CC0 cues, not adding a licensed track.

### 3.7 CLI verbs reelkit never runs

| Unused verb | What it unlocks | Cost |
|---|---|---|
| `compare` | contact sheet of the same timestamp across two renders — **a working visual-regression check**. Worth noting: my `renderdiff.py` was abandoned because renderer nondeterminism made pixel thresholds unmeetable; a labelled human-read contact sheet sidesteps that instead of fighting it | **P** — low |
| `grade-compare` | colour-grade candidates from one frame | **P** |
| `check` / `lint` | documented in SKILL.md but **never run by the pipeline** — `verify.py` runs instead. `check` is what catches the heavy-element limit in §2, so it belongs in the gate | **P** — low, and arguably overdue |
| `remove-background` | **transparent speaker video** → speaker composited over full-bleed B-roll instead of a card beside them. A large visual unlock | **D+P** — model download, new asset class |
| `keyframes` | seek-safety diagnostics for any ladder we add in §3.2 | **P** |
| `benchmark` | measure the render host properly instead of my ad-hoc timing | **P** — trivial |
| `snapshot` | documented, run by hand; could be a build artifact | **P** — trivial |
| `beats` | music beat detection — **not applicable**, no music bed by doctrine |  — |
| `tts` | **not applicable**, the whole point is the real voice |  — |
| `cloud`, `cloudrun`, `lambda` | hosted rendering — an alternative to the parked Railway service, if render time ever becomes the bottleneck again | **P+D**, parked |

### 3.8 talking-head-recut design tokens

reelkit installs this skill for gsap and render deps but ignores its design
vocabulary: **4 layouts** (`split`, `stack`, `pip`, `overlay`), **10 styles**
(`academic`, `editorial`, `minimal`, `spotlight`, `geom`, `whiteboard`, `audit`,
`terminal`, `swiss`, `xhs`), **3 video frames** (`clean`, `hairline`,
`polaroid`), plus its portrait sizing tokens.

reelkit's own modes (`top`, `stage`, `split`, `full`, `overlay`) overlap the
layouts but `pip` and `stack` have no equivalent — `pip` in particular is the
shrink-the-speaker-into-a-corner move. **Cost: K.** The 10 styles map cleanly
onto the style profile proposed in PR #10 — that is what its `extends` field is
for. **Cost: C.**

### 3.9 Blueprints and rules not covered above

22 blueprints and 48 rules; the ones with obvious reel application and not yet
listed: `kinetic-type-beats`, `titlecard-reveal`, `ticker-takeover`,
`typewriter-reveal`, `comparison-split`, `zoom-out-workspace-reveal`,
`overwhelm-surround`, `video-text-pivot`, `transcript-scroll-artifact-reveal`,
`grid-card-assemble`, `center-outward-expansion`, `anchored-layout-expand`,
`nudge-curve`, `sine-wave-loop`, `gradient-text-sweep`, `kinetic-beat-slam`,
`vertical-spring-ticker`, `depth-scatter-assemble`, `particle-burst`.

`video-text-pivot` and `transcript-scroll-artifact-reveal` are the two most
directly on-format for a transcript-driven talking-head reel.

---

## 4. If I had to shortlist

Ranked by visible effect per unit of cost and risk, for Instinct to accept or
discard once the reference analysis lands:

1. **Audio mixing (§3.6)** — `data-fx-chain` voice preset + `data-fx-carve`
   ducking. Config-level, no heavy elements, no render cost, and it fixes the
   most audible weakness in everything shipped so far.
2. **Progress-dim sequencing and springs (§3.5, §3.4)** — `waterfall-entry`,
   `dynamic-content-sequencing`, `spring-pop`, `counting-dynamic-scale`. New
   builders, but no heavy elements and no structural change.
3. **Handwritten annotation family (§3.4)** — SVG path draw is genuinely cheap
   and is the most recognisable "creator" signature available.
4. **Caption treatments (§3.1)** — highest density of ready-made options, and
   captions are on screen for the entire reel. Start with the non-glow rows.
5. **Lower-thirds (§3.4)** — standard dressing reelkit simply lacks.
6. **`compare` + `check` in the gate (§3.7)** — not a style move, but it is what
   makes adopting rows 1–5 safe rather than hopeful.

Deliberately **not** in the shortlist despite obvious appeal: **punch-ins
(§3.2)** and **transitions (§3.3)**. Both are high-value moves, and both break an
assumption the current gates rest on — the face zone measured from a static frame,
and segment boundaries as clean cuts. They are worth doing; they are not worth
doing casually, and each deserves its own design pass.

---

## 5. What this document is not

No style rules are proposed and none are implied — the "style move" column is
capability reach, not a recommendation about the house style. No code has been
written, no dependency added, nothing installed into the repo. The registry
figures come from `npx hyperframes@0.8.36 catalog --json` run against the live
registry (393 items; three more were skipped by the CLI as having invalid
manifests, so treat 393 as a floor).
