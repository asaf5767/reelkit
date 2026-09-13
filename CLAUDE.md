# CLAUDE.md - working agreement for Claude Code on reelkit

## What this is
reelkit turns a raw vertical talking-head clip into a captioned, visual-rich reel:
video in, finished reel out. It is a thin Python layer over HyperFrames (which owns
transcript display, rendering, and export). Pipeline stages, in order:

1. **plan** - editorial plan.json: hook, beats (cards), framing, captions. Hand-authored
   or LLM-authored against the transcript; versioned siblings (cut-plan.vN, graphics-plan.vN).
2. **assets** - generated B-roll images via fal.ai (see config/providers.json; spend is
   recorded in asset-ledger.json).
3. **build** - materializes the mandatory hook beat, places automatic SFX cues,
   writes the HyperFrames project (public/index.html, cards, fonts, sfx).
4. **render** - HyperFrames renders segments, joins video, muxes the original audio back.
5. **export** - phone-safe remux/re-encode, container audit, 16MB WhatsApp size cap.

Scripts live in `skills/reelkit/scripts/` (reelkit.py is the CLI; segmentrender.py
drives long renders; verify.py is the geometry/overlap gate; cards.py owns card
layout math). Doctrine and per-topic references live in `skills/reelkit/SKILL.md`
and `skills/reelkit/references/` - read them before touching behavior.

## Doctrine (violating these is a defect, not a choice)
- **Hook by construction**: every reel gets a hook card in the first seconds;
  build materializes it, it is never optional.
- **SFX by construction**: event-tied cues (beat entrances, hero pop, riser into
  the close) are placed automatically. A plan with beats resolving to zero cues
  fails the build. Libraries resolve in order - media-use if installed, then the
  CC0 pack bundled at `skills/reelkit/assets/sfx` - and any single cue name the
  chosen library lacks falls back to a synthesized stand-in. No music bed (no
  licensed catalogue). Anything added to the bundled pack must carry a licence
  that permits re-hosting the raw files in a public repo; CC0 today.
- **Face-zone law**: no overlay ever touches the speaker's head (hairline down).
  Card geometry is CSS-driven; plan.json box values are advisory - compute overlap
  from the CSS, not the plan.
- **RTL law**: Hebrew captions and cards render right-to-left with the bundled
  Heebo fonts; never put dir on <html> (renders black).
- **Literal imagery**: generated B-roll illustrates the literal beat content,
  16:9 landscape inside the card frame.
- **Versioned plans**: cut/graphics plans are immutable versions, never edited in place.

## Coding standards
- stdlib-first; new dependencies need a reason stated in the commit.
- Content-addressed caching for generated assets (sha256 in the ledger).
- Every external spend lands in asset-ledger.json with real cost and model name.
- Model/provider swaps go through config/providers.json, not code edits.
- No secrets in code, ever. Runtime secrets come from env (e.g. FAL_KEY).
- Gates are code, not vibes: decode pass, audio loudness, visual snapshots at
  fixed timestamps, container audit. A gate that cannot run blocks delivery.

## Runtime facts
- Renders run on Kaggle CPU kernels (private, account assafakiva): Node 22 +
  Chrome libs are scaffolded in-kernel, ~10 min for a 32s reel. Source of truth
  for the pipeline is this repo; the Kaggle dataset reelkit-runtime-v2 carries a
  tgz snapshot - bump it when scripts change or the kernel runs stale code.
- fal.ai spend is real money from a small credit balance; use iteration-tier
  models for tests and record actual cost.

## Workflow contract
- Claude Code works in branches and opens PRs. Never push to main directly.
- Instinct (the user's agent) reviews every PR and runs the pipeline on real
  footage before merge. A PR is mergeable when the gates above pass on a real
  render, not when the code reads well.
- Backlog lives in NEXT.md; check it before starting new work.
