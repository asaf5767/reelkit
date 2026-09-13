# Proposal: a style profile as the config surface for reference-derived defaults

Status: **proposal, nothing implemented.** Written for Instinct to accept, reject
or reshape before any code moves.

Context: priority #1 is *style-defaults-from-reference* - the reference reels'
editing moves become repo defaults as code or config, not prose. Instinct is
doing the video analysis. This document does not contain a single style rule and
does not guess at one; it answers the prior question of **where a finding lands
once it exists**, so the handover is "add three lines to this file" rather than
"edit four scripts and hope".

---

## 1. Where style lives today (audit)

Style is currently spread across five layers with different editability. Only the
first is data.

| # | Layer | Where | What it decides | Editable without touching code? |
|---|---|---|---|---|
| 1 | Brand preset | `skills/reelkit/assets/brand/*.json` (17 keys) | palette (5 accents), bg/text, fonts, caption size/chunking/position, canvas colours | **yes** |
| 2 | Code defaults | `reelkit.py: DEFAULT_BRAND` | the same 17 keys again, used when a plan names no brand | no |
| 3 | Motion | `cards.py: Anim` + the card builders | entrance durations and eases (`fade` 0.40 `power2.out`, `pop` 0.45 `back.out(1.7)` scale 0.55, `slide` 0.42 `power3.out`), plus **41 hardcoded per-kind timing offsets** inside the builders | no |
| 4 | SFX placement | `reelkit.py: auto_cues` | which cue fires per beat kind, its offset and its volume; riser at `last.start - 1.3` | no (only on/off, via `plan.audio.autoSfx`) |
| 5 | Layout | `geometry.py: MODE_TOP`, `cards.py` head ratios | where a card sits per mode; head-zone margins | no |

Plus **SKILL.md doctrine**, which is prose, and the **plan schema**, which lets a
single reel override things per beat (`mode`, `layout`, `kind`, `sfx`, `plate`,
`takeover`) or globally (`brand`, `captions`, `audio`, `framing`, `hook`).

**The shape of the problem:** the layer that is configurable (1) holds only
look - colour and type. Everything that reads as *editing* - how fast a card
enters, what it eases on, how beats are paced, when a sound lands - is in layers
3 and 4, in Python, as literals. Reference-derived editing moves have nowhere to
land today except a code edit per move.

### Two defects this audit turned up

Both are real today, independent of the style work, and both argue for the same
fix:

1. **The code defaults and the JSON preset disagree.** `DEFAULT_BRAND` in
   `reelkit.py` and `assets/brand/default.json` differ on three canvas colours:

   | key | `default.json` | `DEFAULT_BRAND` |
   |---|---|---|
   | `canvasBg` | `#FAFAF9` | `#F7F7F4` |
   | `canvasText` | `#18181B` | `#14161C` |
   | `canvasMuted` | `#71717A` | `#858A93` |

   A plan with no `brand` key renders different colours from one that says
   `"brand": "default"`. This is the same class of defect as the plan-box vs
   CSS drift that NEXT #2 removed, one layer up: two sources of truth for one
   number.

2. **`assaf.json` is a byte-identical copy of `default.json`** apart from
   `name`. The brand layer exists but carries no identity yet - so there is
   currently no example of a real profile to extend.

---

## 2. Proposal: one style profile, layered, data-only

Add `skills/reelkit/assets/style/<name>.json`. A profile is the single place a
reference-derived default lands. Sketch of the surface - **the section names are
the proposal; the values below are today's behaviour written down, not new
rules**:

```jsonc
{
  "name": "reference-v1",
  "version": 1,
  "extends": "base",                  // profiles compose; only state the deltas

  "brand": "default",                 // reuse the existing preset by name, or inline

  "motion": {                         // layer 3, currently literals in cards.py
    "fade":  { "duration": 0.40, "ease": "power2.out" },
    "pop":   { "duration": 0.45, "ease": "back.out(1.7)", "scale": 0.55 },
    "slide": { "duration": 0.42, "ease": "power3.out" },
    "stagger": { "word": 0.00, "char": 0.00 }
  },

  "pacing": {                         // no home at all today
    "minBeatSeconds": null,
    "maxBeatSeconds": null,
    "gapBetweenBeats": null,
    "hookEndsBy": null
  },

  "captions": {                       // today inside the brand preset
    "maxWords": 3, "maxChars": 15, "size": 76,
    "top": 1500, "height": 360
  },

  "sfx": {                            // layer 4, currently auto_cues literals
    "entry":  { "names": ["whoosh-short", "whoosh"], "at": 0.05, "volume": 0.7 },
    "hero":   { "name": "pop",           "at": 0.15, "volume": 0.8 },
    "ui":     { "name": "click-soft",    "at": 0.25, "volume": 0.7 },
    "data":   { "name": "impact-bass-2", "at": 0.30, "volume": 0.6 },
    "riser":  { "leadIn": 1.3 }
  },

  "layout": {                         // the taste half of layer 5
    "modeTop": { "top": 120, "stage": 150 }
  }
}
```

### Resolution order

```
built-in code defaults          (the floor; a profile may omit anything)
  -> style profile              (the repo's answer: reference-derived defaults)
    -> plan.json global keys    (this reel differs)
      -> per-beat overrides     (this moment differs)
```

Each layer only states its deltas. A finding like "her cards enter faster than
ours" becomes one number in `motion.slide.duration`, in one file, reviewable as
a diff, with no code change.

### Who consumes it

- **`build`** reads the resolved profile instead of the literals in layers 2-5.
- **The plan author** (priority #2, the fast lane) receives the profile as part
  of its brief, so an auto-authored plan is already in the house style rather
  than being corrected afterwards. This is the concrete sense in which #2 serves
  #1.
- **`verify`** does not read it. See the next section.

---

## 3. What must NOT become style-configurable

CLAUDE.md: *violating doctrine is a defect, not a choice*. Anything that is a
safety rule stays a constant and stays out of the profile, or the profile becomes
a way to switch the gate off:

- **The face-zone law** - `HAIR_RATIO`, `JAW_RATIO`, `HEAD_PAD_X`, `HEAD_MARGIN`
  and `head_clear_y()`. A style profile must never be able to move a card onto
  the speaker's face.
- **`SCALE_FLOOR`** - the readability floor that makes `fit_layout` refuse rather
  than squash.
- **Hook-by-construction and SFX-by-construction.** A profile may say *which*
  cue and *when*; it may not say "none".
- **The RTL rules.**

So `layout.modeTop` is in the profile (taste: where a card prefers to sit) while
the head-zone constants are not (safety: where it may never go). If a profile's
`modeTop` puts a card on a face, the existing fit pass slides it up and the gate
still fails it - the profile is a preference, never an override of the gate.

---

## 4. Consequences worth deciding before implementation

1. **Segment reuse must hash the profile.** `segment_key()` already hashes
   `scripts/*.py` and `assets/brand/*.json`, so brand changes correctly
   invalidate cached segments. A new `assets/style/` directory must be added
   there too, or editing a profile would leave stale segments resumable - the
   exact failure PR #4 was built to prevent. One line, but it must not be
   forgotten.
2. **Profiles should be versioned like plans.** Plans are immutable versioned
   siblings; a profile that changes under a finished reel makes that reel
   irreproducible. Proposal: a reel records the resolved profile (name +
   version + hash) in its build output.
3. **Fix the drift as part of this, not separately.** `DEFAULT_BRAND` should stop
   being a second copy and become a load of `assets/brand/default.json`, with a
   test that the two cannot diverge again - the same treatment `geometry.py` gave
   the card box.
4. **Migration is mechanical but not free.** Layer 3 is 41 call sites. They do
   not all need to move at once; the profile can start with `motion`, `sfx` and
   `captions` and absorb the per-kind offsets later.

---

## 5. Open questions for Instinct

1. **Granularity of motion.** Is per-primitive (`fade`/`pop`/`slide`) enough, or
   do the reference moves differ per card *kind* (a stat lands differently from a
   quote)? This decides whether `motion` is flat or nested under `kinds`.
2. **Does pacing belong here or in the plan author?** "Beats are ~2.5s and never
   overlap speech" could be a profile constraint the builder enforces, or a
   brief the author follows. Enforced is stricter; brief is more flexible.
3. **One profile or profile + brand?** Keeping `brand` as a nested reference
   preserves the existing presets. The alternative is folding the 17 brand keys
   into the profile and retiring `assets/brand/`.
4. **Is the reference a house style or Yuval's style?** It decides whether the
   profile is named for the channel or shipped as `default`.

---

## 6. What this proposal deliberately does not do

It contains no style rules. No duration, ease, palette, pacing or cue in section
2 is a suggestion - every value there is today's behaviour, transcribed so the
shape of the file is concrete. The findings are Instinct's to produce; this is
the socket they plug into.
