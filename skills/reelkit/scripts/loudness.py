#!/usr/bin/env python3
"""Is a cue AUDIBLE - not merely present.

The gate this replaces measured whether the delivered audio differed from the
source at a cue's timestamp. It passed every time, including on mixes where a
human hears nothing at all, because "the samples changed" and "you can hear it"
are different questions. The owner's verdict on a reel that passed it was "I
don't hear any SFX. Anything."

Audibility is a question about MASKING, and masking is band-local: a cue is
heard when it rises above the voice inside some frequency band, not when it
raises the broadband level. So every measurement here is (a) band-limited,
(b) taken at the cue's own loudest moment rather than its nominal start, and
(c) expressed RELATIVE to the voice under it at that instant.

Relative is what makes the bar portable. The delivered mix moved from -23.2 to
-18.4 LUFS between two cuts of the same reel; an absolute cue target would have
been wrong in one of them by construction, while "this far above the voice
beneath it" holds in both.
"""
import os
import re
import subprocess

try:
    import numpy as np
except ImportError:                                       # pragma: no cover
    raise SystemExit(
        "reelkit audio: numpy is required to measure whether a cue is audible "
        "(pip install numpy). A gate that cannot run blocks delivery - shipping "
        "audio nobody has measured is the failure this stage exists to prevent.")

RATE = 48000
# Roughly octave-wide, covering where a talking-head reel's cues live. Narrower
# bands would chase individual partials; broader ones would let a cue hide
# behind voice energy in the same band.
BANDS = ((125, 250), (250, 500), (500, 1000), (1000, 2000),
         (2000, 4000), (4000, 8000), (8000, 16000))

# The window a transient is judged over. Long enough to hold a whoosh or a pop
# whole, short enough that a quiet moment either side does not average it away.
WINDOW = 0.30

# How far above the voice, in the cue's own band, counts as heard. 3 dB is
# around where a masked signal becomes detectable at all; the gate asks for
# more than "detectable in a quiet room with headphones on" because the reel is
# watched on a phone, and the target the mix aims for leaves room for a cue to
# drift and still clear the gate.
AUDIBLE_MIN = 5.0        # below this the export has failed
AUDIBLE_TARGET = 10.0    # what the mix calibrates cues to


def _decode(path, at=0.0, span=None):
    """Mono float samples for one window, decoded sample-accurately.

    `-ss` before `-i` seeks by keyframe and lands milliseconds away, which is
    enough to miss a transient entirely; the trim goes in the filter chain
    after a full decode, as everything in this pipeline that has to be sample
    accurate does.
    """
    trim = f"atrim=start={at}" + (f":end={at + span}" if span else "")
    af = f"{trim},asetpts=PTS-STARTPTS,aformat=sample_fmts=flt:sample_rates={RATE}:channel_layouts=mono"
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-af", af,
                        "-f", "f32le", "-"], capture_output=True)
    return np.frombuffer(r.stdout, dtype="<f4")


def band_db(samples, rate=RATE):
    """Power per band, in dB. Silence reads as a floor rather than -inf."""
    n = len(samples)
    if n < 64:
        return {b: -120.0 for b in BANDS}
    win = samples * np.hanning(n)
    spec = np.abs(np.fft.rfft(win)) ** 2
    freq = np.fft.rfftfreq(n, 1.0 / rate)
    # Hann costs 3/8 of the power; correcting keeps a band figure comparable
    # with the same band measured any other way.
    scale = 1.0 / (n * n * 0.375)
    out = {}
    for lo, hi in BANDS:
        p = float(spec[(freq >= lo) & (freq < hi)].sum()) * scale
        out[(lo, hi)] = 10.0 * np.log10(p) if p > 1e-12 else -120.0
    return out


def peak_offset(path, limit=8.0):
    """Where inside a cue asset its loudest moment sits.

    A riser ramps for seconds before it arrives. Measuring it at its nominal
    start reads the silence in front of it and calls the cue missing - which is
    a measurement bug, not a mix defect, and it cost a review round once already.
    """
    s = _decode(path, 0.0, limit)
    if len(s) < int(RATE * WINDOW):
        return 0.0
    step = int(RATE * 0.05)
    w = int(RATE * WINDOW)
    best, at = -1.0, 0.0
    for i in range(0, len(s) - w, step):
        e = float(np.dot(s[i:i + w], s[i:i + w]))
        if e > best:
            best, at = e, i / RATE
    return round(at, 3)


def headroom(mixed, source, at, span=WINDOW):
    """How far the cue rises above the voice, in the band where it rises most.

    Returns (delta_db, band, mixed_db, voice_db). Taking the best band is the
    point rather than a convenience: a cue is audible if it pokes out ANYWHERE,
    and which band that is depends on the cue, so pinning one band per asset
    would mean hand-tagging a library and getting it wrong for the next one.
    """
    m = band_db(_decode(mixed, at, span))
    v = band_db(_decode(source, at, span))
    best = max(BANDS, key=lambda b: m[b] - v[b])
    return round(m[best] - v[best], 1), best, round(m[best], 1), round(v[best], 1)


def voice_floor(source, at, span=WINDOW):
    """The voice's band levels under a cue - what the cue has to clear."""
    return band_db(_decode(source, at, span))


def asset_bands(path, at=0.0, span=WINDOW):
    """A cue asset's own band levels, at unity gain."""
    return band_db(_decode(path, at, span))


def level_db(path, at=0.0, span=None):
    """Broadband RMS of a file, or a window of it, in dB."""
    s = _decode(path, at, span)
    if len(s) == 0:
        return -120.0
    p = float(np.dot(s, s) / len(s))
    return 10.0 * np.log10(p) if p > 1e-12 else -120.0


def needed_gain_db(asset, floor, target=AUDIBLE_TARGET):
    """The gain that puts this cue `target` dB over the voice in its best band.

    "Best" is the band where the cue stands out most from the voice under it -
    the band a listener will actually notice it in - so the cue is lifted by
    what that band needs rather than by what its loudest band needs, which on a
    bass-heavy cue under a bass-heavy voice are not the same number.
    """
    band = max(BANDS, key=lambda b: asset[b] - floor[b])
    return round(target - (asset[band] - floor[band]), 2), band
