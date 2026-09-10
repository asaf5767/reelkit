# Audio

## What ships tested: the beat sheet

`build` writes `BEATS.md` with every card-entry hit point in seconds. Hand it to
whoever is scoring the reel along with the silent master: dropping a track and
landing accents on those times takes a couple of minutes in any editor, and the
result is reliable because a human ear checked it.

The source audio is preserved by mounting the same file as a separate root
`<audio>` track (`data-track-index="10"`) while the visual `<video>` stays muted.
That keeps the speaking voice independently mixable — you can duck it, fade it or
gain it without touching the picture. `audio.sourceVolume` in the plan sets its level.

## What does not ship: automated scoring

reelkit does **not** bundle music. There is no licensed catalogue here, and
shipping an untested audio path that silently produces a bad mix is worse than
shipping none.

## Experimental path

If you want it automated, HyperFrames already has the pieces and reelkit
deliberately does not wrap them:

- `/media-use` resolves BGM and SFX from HeyGen's catalogue. Needs the `heygen`
  CLI installed and an OAuth login — an interactive step no agent can complete
  alone. Check with `node <media-use>/scripts/resolve.mjs --doctor`.
- `/hyperframes-audio` covers ducking, voiceover carve, fades and effect chains
  once tracks are placed.

The shape that works: place the bed at `data-track-index="20"` under the source
voice, carve the bed against the voice rather than setting a flat low gain, and
put short accents on the `BEATS.md` hit points. Keep the bed at least 12 dB under
speech — reels are watched on phone speakers where music masks consonants first.

**This path is unverified in reelkit.** Nobody has run it end to end here. Treat
the first attempt as debugging, not as a feature, and check the render's audio
before publishing.
