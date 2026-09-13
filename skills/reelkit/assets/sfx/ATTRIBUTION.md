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
| [Riser sound effect short](https://freesound.org/people/syntheffects/sounds/685256/) | syntheffects | CC0 1.0 | Freesound sound page - only CC link is the CC0 dedication |

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
| riser | 685256 (trimmed, see below) |

Cues were chosen by measurement, not by filename alone - duration, peak and
spectral centroid. `impact-bass-2` carries 99% of its energy below 250 Hz, which
is what makes it read as a soft low hit under a data reveal; `pop` and `ping` sit
around 3 kHz; the swishes are 0.10-0.23 s, short enough to land on a beat
entrance without smearing into the speech.

## The riser, and one caveat worth reading

`riser` came from Freesound rather than the game-asset libraries, which carry no
cinematic transitions at all. Eight CC0 candidates were checked on their own
pages and measured; this one was chosen because its energy builds monotonically
over the 1.4 s before its peak (+11.6 dB) and then cuts off hard, which is what a
riser into an edit has to do. It is trimmed to the 1.53 s leading into that peak,
so the climax lands on the beat the placer aims at.

**It is a transcode, not the master.** Freesound gates original files behind an
account; the file here is the high-quality preview its public embed player
streams. CC0 places no restriction on that, and for a ~1.5 s cue that sits under
speech and is peak-normalised at render time the difference is small - but it is
a double MP3 encode, and anyone with a Freesound account can replace it with the
master at the same path and update `manifest.json`.

## Not covered

`typing` is unmapped: it is a run of keystrokes rather than a single transient,
and mapping one keypress to it would have been wrong. It falls through to the
synthesised stand-in, as does any cue name added to the placer later.
