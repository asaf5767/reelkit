# Bundled SFX pack - sources and licences

Every file here is **CC0 1.0** (public domain dedication), which is why it can be
redistributed inside this public repository. That is the bar for anything added
to this directory: a licence that permits re-hosting the raw files, not merely
using them inside a rendered video.

CC0 imposes no attribution requirement. Kenney's licence text says crediting is
"not mandatory"; OpenGameArt's CC0 submissions carry the same dedication. This
file exists anyway - provenance for a bundled binary is worth recording, and both
authors deserve the credit.

## Sources

| Pack | Author | Licence | Verified from |
| --- | --- | --- | --- |
| [Interface Sounds](https://kenney.nl/assets/interface-sounds) | Kenney | CC0 1.0 | `License.txt` inside the download |
| [Impact Sounds](https://kenney.nl/assets/impact-sounds) | Kenney | CC0 1.0 | `License.txt` inside the download |
| [UI Audio](https://kenney.nl/assets/ui-audio) | Kenney | CC0 1.0 | `License.txt` inside the download |
| [Swishes Sound Pack](https://opengameart.org/content/swishes-sound-pack) | artisticdude | CC0 1.0 | OpenGameArt licence field (single entry, CC0) |

Kenney's licence texts are preserved verbatim under `licenses/`. The Swishes pack
ships no licence file, so its dedication is recorded in
`licenses/swishes-sound-pack.License.txt`.

Licences were checked on 2026-09-13 against the pages and files above, not from
memory. Re-check before adding anything new: OpenGameArt submissions can carry
several licences at once, and a multi-licensed asset (CC0 *and* GPL *and* CC-BY-SA)
is not a clean CC0 asset. One whoosh pack was rejected for exactly that.

## Cue map

`manifest.json` records, per cue, the original filename, pack, author and licence.
Files are mono 44.1 kHz MP3; `build` peak-normalises each cue at render time, so
the levels here are the source levels.

| Cue | Source file |
| --- | --- |
| whoosh | swish-9.wav |
| whoosh-short | swish-13.wav |
| whoosh-cinematic | swish-7.wav |
| pop | select_001.ogg |
| click | click_001.ogg |
| click-soft | click1.ogg |
| impact-bass-1 | impactPunch_heavy_000.ogg |
| impact-bass-2 | impactSoft_heavy_000.ogg |
| ping | pluck_001.ogg |
| chime | impactBell_heavy_000.ogg |
| notification | confirmation_001.ogg |
| sparkle | glass_001.ogg |
| key-press | switch1.ogg |
| error | error_001.ogg |
| glitch-1/2/3 | glitch_001/002/003.ogg |

Cues were chosen by measurement, not by filename alone - duration, peak and
spectral centroid. `impact-bass-2` carries 99% of its energy below 250 Hz, which
is what makes it read as a soft low hit under a data reveal; `pop` and `ping` sit
around 3 kHz; the swishes are 0.10-0.23 s, short enough to land on a beat
entrance without smearing into the speech.

## Not covered

**`riser`** has no CC0 source. The auto-cue placer emits one riser into the final
beat, and no verified CC0 riser was found on Kenney or OpenGameArt - both are
game-asset libraries, strong on UI and impacts, empty on cinematic transitions.
That one cue still falls through to the synthesised stand-in. Dropping in a
licence-clean riser named `riser.mp3` here is all it takes to finish the set.

`typing` is likewise unmapped: it is a run of keystrokes rather than a single
transient, and mapping one keypress to it would have been wrong.
