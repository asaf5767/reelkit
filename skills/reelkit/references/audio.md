# Audio

## Sound effects — supported and tested

reelkit places timed SFX on their own tracks. Cues live on a beat:

```jsonc
{ "id": "b04", "start": 23.2, "end": 30.1, "kind": "checklist",
  "sfx": [ { "name": "ping", "at": 0.55, "volume": 0.8 },
           { "name": "ping", "at": 2.10 } ] }
```

`at` is seconds **relative to the beat's start**. `volume` is relative to the
normalised target (see below), default `audio.sfxVolume` = 0.8. Global cues that
belong to no beat go in `audio.sfx[]` with absolute `at`.

### Where the sounds come from

The 19-file library bundled with the HyperFrames `media-use` skill
(`~/.claude/skills/media-use/audio/assets/sfx/`), auto-discovered. No API key, no
login. Set `audio.sfxDir` to point elsewhere.

Names: `chime click click-soft error glitch-1 glitch-2 glitch-3 impact-bass-1
impact-bass-2 key-press notification ping pop riser sparkle typing whoosh
whoosh-short whoosh-cinematic`. A name that does not resolve is skipped with a
warning — a missing sound never blocks a render.

Those files are Pixabay-licensed: free to use commercially inside a rendered
video, no attribution. reelkit does **not** vendor them, because re-hosting the
raw files in a public repo is a different permission than using them in a video.

### Two corrections reelkit applies for you

**Peak normalisation.** The library spans about 32 dB between its quietest and
loudest file — `typing` averages −37 dB, `impact-bass-1` averages −5 dB. A flat
`volume: 0.35` therefore means something different for every sound; measured in a
real render, `ping` was inaudible at the same setting where `pop` was obvious.
Each file is normalised to `audio.sfxTargetDb` (default −11 dBFS peak) before the
cue's relative `volume` is applied, so one number means one thing.

**Lead-silence compensation.** Several files open with roughly 0.4 s of digital
silence — `chime` and `typing` both do. Starting the clip at the cue time plays
the transient late and it misses the visual hit. reelkit measures the lead-in and
starts the clip that much earlier so the audible onset lands on the cue.

### Placing them well

- **Punctuate, do not narrate.** A sound on all fourteen beats is exhausting.
  Eight to twelve cues across ninety seconds is plenty.
- **Sync to the visual landing**, not to the card's fade-in. A `pop` belongs on the
  frame where the element arrives.
- **Vary the sound.** The same `pop` fourteen times reads as a bug.
- **Repeated actions want repeated sounds** — a rally, a checklist ticking, nodes
  appearing in a pipeline. That is where SFX genuinely add information.
- **Keep them under the voice.** These are accents; if a cue competes with a word,
  lower its relative `volume` rather than moving the word.

## Music

reelkit does not add a music bed. There is no licensed catalogue available to it,
and shipping an untested scoring path would just hand you a bad mix to debug.

`build` writes `BEATS.md` with every card-entry hit point in seconds. Drop a track
in any editor and land the accents on those times.

If you want it automated, the pieces exist in HyperFrames: `/media-use` resolves
BGM from HeyGen's catalogue (needs an interactive OAuth login no agent can
complete alone) and `/hyperframes-audio` covers ducking and carve once tracks are
placed. Put the bed at `data-track-index="20"` or above, carve it against the voice
rather than setting a flat low gain, and keep it at least 12 dB under speech —
reels are heard on phone speakers, where music masks consonants first.
**That path is unverified in reelkit.** The SFX path above is not: it was measured
in a rendered file.

## The source voice

Mounted as a separate root `<audio>` track (`data-track-index="10"`) while the
visual `<video>` stays muted, so the voice stays independently mixable.
`audio.sourceVolume` sets its level.

## One trap worth knowing

An `<audio>` element with `data-start` but **no `id`** renders completely silent.
The renderer discovers media by id. HyperFrames lints this as `media_missing_id`;
reelkit always emits ids. If you hand-add an audio tag, give it one.
