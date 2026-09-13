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

### Automatic cues (default)

`build` derives cues from the edit itself - you do not place them by hand:

- **whoosh** on every scene change (a beat entering in `split` or `stage` mode)
- **pop** when hero text lands
- **click-soft** on UI cards (notification, chat, code, diff)
- **impact-bass** soft hit on data reveals (stat, contrast, donut, bars)
- **riser** into the final beat's reveal

Whoosh variants alternate so consecutive cuts do not repeat a sound, and
transients are never placed closer than 0.9 s apart. A beat with its own `sfx`
list keeps full manual control - auto only fills beats that say nothing.
`audio.autoSfx: false` turns the layer off for a project.

### Voice-priority mixing

The voice is known at build time, so ducking is computed, not guessed: every
cue's volume is scaled by the measured voice level at its moment (up to 7 dB
down when speech is present). `audio.voiceDuck: false` disables it.

### Enforcement (code)

A reel with beats and no SFX is a defect, and the pipeline treats it that way:
`build` dies when a plan has beats but resolves zero cues (unless
`audio.autoSfx: false` waives sound explicitly). The bundled library is
preferred; when it is missing, reelkit synthesizes stand-ins for every standard
name into `~/.cache/reelkit/sfx-synth` (created here, no licence concerns) and
prints that it did so. "Continuing without sfx" no longer exists as a path.

### Where the sounds come from

The 19-file library bundled with the HyperFrames `media-use` skill
(`~/.claude/skills/media-use/audio/assets/sfx/`), auto-discovered. No API key, no
login. Set `audio.sfxDir` to point elsewhere.

Names: `chime click click-soft error glitch-1 glitch-2 glitch-3 impact-bass-1
impact-bass-2 key-press notification ping pop riser sparkle typing whoosh
whoosh-short whoosh-cinematic`. A name that does not resolve is skipped with a
warning — a missing sound never blocks a render.

Nineteen names, eighteen sounds: `click` and `click-soft` are byte-identical
files. `click-soft` is not a quieter variant — lower its `volume` instead.

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
silence — `chime` (0.42 s), `typing` (0.44 s), `error` (0.60 s), `riser` (0.76 s),
`ping`, `glitch-3` and `whoosh-cinematic`. Starting the clip at the cue time plays
the transient late and it misses the visual hit. reelkit measures the lead-in and
starts the clip that much earlier so the audible onset lands on the cue.

Only silence at the *start* of a file counts. Most of the short sounds are the
opposite shape — transient first, then trailing silence — and `click`,
`click-soft`, `key-press`, `pop`, `whoosh` and `whoosh-short` all end that way.
Treating their tail as a lead-in drags the cue up to 0.72 s early, which is 22
frames at 30 fps and plainly audible. reelkit compares the first `silence_start`
against zero to tell the two apart.

**If you want a sound to lead into its moment**, say so in the plan with a
negative `at` — `{ "name": "whoosh-short", "at": -0.18 }` starts the swell before
the beat so it arrives on it. That is a creative choice, not a correction, which
is why it lives in the cue rather than in the measurement.

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

### `split` beats want sound more than the others do

Cues are mode-independent — a split beat takes `sfx` like any other. But split is
the one mode that **hard-cuts**, and a hard cut with no sound reads as a dropped
frame rather than a decision. The pattern that works:

```jsonc
{ "id": "b04", "mode": "split", "kind": "canvas", "start": 12.0, "end": 17.4,
  "sfx": [ { "name": "click", "at": 0, "volume": 0.7 } ] }
```

- **Advancing from one split to the next** — `click` at `at: 0`, exactly on the
  cut. It is the slide-advance sound, and it is the case that most needs it.
- **Entering split from `top`/`stage`/`full`** — a register change rather than an
  advance, so a short swell suits it better: `whoosh-short` at `at: -0.18`, which
  arrives on the cut instead of starting there.
- **Leaving split** needs nothing. The next card fades in and carries itself.

This is deliberately not automatic. Every other sound in reelkit is in the plan
because someone put it there, and a mode that played a click on its own would be
the only thing in the tool making noise you did not ask for.

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
