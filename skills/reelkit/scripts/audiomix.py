#!/usr/bin/env python3
"""The audio mix stage - the single owner of a reel's delivered audio.

It exists because the two render paths disagreed about audio, and one of them
was silently wrong.

  direct render    HyperFrames mixed the speaker's audio with the SFX clips and
                   export passed that through. Cues audible.
  segmented render segmentrender joins video with `-an` and re-muxes the ORIGINAL
                   file's audio (`-map 1:a:0`), because segment AAC carries
                   encoder priming at every boundary. Correct about sync, and it
                   threw away every SFX cue with it.

Measured on the 12s sample at two cue timestamps: source -18.1 / -18.0 dBFS,
segmented final -18.1 / -18.0 (identical - no cue), direct final -14.3 / -13.9
(the cue is there). The segmented path is the one Kaggle renders through, so
"SFX by construction" was not holding where it mattered.

Mixing here fixes that without reopening the priming problem: cues are placed
against the ORIGINAL audio at absolute times with sample accuracy, so segment
boundaries never enter into it. Both paths now render video only and get their
audio from this stage, which makes them identical by construction rather than
by inspection.

It is also where voice processing belongs. The chain and the ducking are read
from the style profile, so they are configuration; the cue placement is not -
losing a cue is a defect, never a preference.

No music bed: this processes the speaker's own voice and the bundled CC0 cues,
and adds no licensed material.
"""
import os, subprocess
from html.parser import HTMLParser

SFX_TRACK_MIN = 20          # build puts cue clips on tracks 20+
RATE = 48000                # one sample rate through the whole graph
PROOF_WINDOW = 0.45         # shortest span sampled when proving a cue landed
PROOF_MAX_SPAN = 4.0        # a long cue is proven from its first seconds
# Measured on the sample: the codec-noise floor between the mixed and source
# files sits at -63..-67 dBFS and a real cue reads -17..-22, so -45 separates
# them with margin on both sides.
PROOF_FLOOR_DB = -45.0      # below this the mix added nothing audible


class _Cues(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cues = []

    def handle_starttag(self, tag, attrs):
        if tag != "audio":
            return
        a = dict(attrs)
        if "clip" not in (a.get("class") or "").split():
            return
        try:
            self.cues.append({"src": a["src"],
                              "start": float(a.get("data-start", 0)),
                              "duration": float(a.get("data-duration", 0)),
                              "volume": float(a.get("data-volume", 1))})
        except (KeyError, ValueError):
            pass                       # a malformed tag is not a cue


def cues(project):
    """Every SFX cue the build placed, read back from the composition.

    The composition is the source of truth rather than plan.json, because the
    hook beat and the automatic cues are materialised during build - reading the
    plan would miss exactly the cues doctrine says are never optional.
    """
    idx = os.path.join(project, "public", "index.html")
    if not os.path.exists(idx):
        return []
    p = _Cues()
    with open(idx, encoding="utf-8") as fh:
        p.feed(fh.read())
    pub = os.path.join(project, "public")
    out = []
    for c in p.cues:
        path = os.path.join(pub, c["src"])
        if os.path.exists(path):
            out.append(dict(c, path=path))
    return sorted(out, key=lambda c: c["start"])


def voice_filters(cfg):
    """The voice chain, as ffmpeg filters. Empty when the profile leaves it off.

    Order is the one that survives contact with a phone-recorded voice: cut the
    rumble first so the compressor is not pumped by it, compress, shape, then
    limit last so nothing downstream can exceed the ceiling.
    """
    if not cfg or not cfg.get("enabled"):
        return []
    f = []
    hp = cfg.get("highpassHz")
    if hp:
        f.append(f"highpass=f={int(hp)}")
    comp = cfg.get("compressor") or {}
    if comp.get("enabled", True):
        f.append("acompressor=threshold={t}dB:ratio={r}:attack={a}:release={rel}:makeup={m}".format(
            t=comp.get("thresholdDb", -18), r=comp.get("ratio", 3),
            a=comp.get("attackMs", 5), rel=comp.get("releaseMs", 120),
            m=comp.get("makeupDb", 2)))
    for band in (cfg.get("eq") or []):
        f.append("equalizer=f={f}:t=q:w={w}:g={g}".format(
            f=band["hz"], w=band.get("q", 1.0), g=band["gainDb"]))
    lim = cfg.get("limiter") or {}
    if lim.get("enabled", True):
        f.append(f"alimiter=limit={lim.get('limit', 0.95)}")
    return f


def filtergraph(cue_list, voice, duck, speech=1, cue_base=2):
    """(filter_complex, output label) mixing speech with the cue bus.

    `speech` and `cue_base` are ffmpeg input indices, passed in rather than
    assumed: the caller decides the input order, and a graph that hardcodes them
    is one argument change away from mixing the wrong stream silently.

    Returns (None, None) when there is nothing to do, so a project with no cues
    and no processing keeps its original audio stream instead of paying a
    re-encode for a no-op.
    """
    vf = voice_filters(voice)
    if not cue_list and not vf:
        return None, None

    # Every input is normalised to one rate and layout FIRST. The speaker's
    # audio is commonly mono at 44.1k while a cue is stereo, and leaving ffmpeg
    # to insert conversions wherever it likes makes the graph's behaviour depend
    # on the build rather than on the plan.
    norm = f"aformat=sample_fmts=fltp:sample_rates={RATE}:channel_layouts=stereo"
    parts = [f"[{speech}:a]" + norm + ("," + ",".join(vf) if vf else "") + "[sp]"]
    if not cue_list:
        return ";".join(parts), "[sp]"

    labels = []
    for n, c in enumerate(cue_list):
        delay = max(0, int(round(c["start"] * 1000)))
        parts.append(f"[{cue_base + n}:a]{norm},volume={c['volume']:.4f},"
                     f"adelay={delay}|{delay}[c{n}]")
        labels.append(f"[c{n}]")
    parts.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0[sfxraw]")

    if duck and duck.get("enabled"):
        # The cue bus ducks under the voice, never the other way round: a cue
        # that competes with a word costs the word, and the word is the reel.
        parts.append("[sp]asplit=2[sp1][spk]")
        parts.append(f"[sfxraw][spk]sidechaincompress=threshold={duck.get('threshold', 0.05)}:"
                     f"ratio={duck.get('ratio', 8)}:attack={duck.get('attackMs', 5)}:"
                     f"release={duck.get('releaseMs', 250)}[sfx]")
        parts.append("[sp1][sfx]amix=inputs=2:normalize=0:dropout_transition=0[mix]")
    else:
        parts.append("[sp][sfxraw]amix=inputs=2:normalize=0:dropout_transition=0[mix]")
    return ";".join(parts), "[mix]"


def mix(project, video_in, source_audio, out, voice=None, duck=None, log=print):
    """Write `out` = video from video_in, audio = processed speech + cues.

    Inputs are ordered video, speech, then one per cue, and the graph is built
    against those indices. Falls back to a straight mux when there is nothing to
    mix, so the stage is always safe to call.
    """
    cue_list = cues(project)
    fc, label = filtergraph(cue_list, voice, duck, speech=1, cue_base=2)
    if fc is None:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", video_in, "-i", source_audio,
               "-map", "0:v:0", "-map", "1:a:0", "-dn", "-sn", "-write_tmcd", "0",
               "-map_chapters", "-1",
               "-c", "copy", "-shortest", out]
        log("reelkit audio: no cues and no voice chain - straight mux")
    else:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", video_in, "-i", source_audio]
        for c in cue_list:
            cmd += ["-i", c["path"]]
        cmd += ["-filter_complex", fc, "-map", "0:v:0", "-map", label,
                "-dn", "-sn", "-write_tmcd", "0", "-map_chapters", "-1",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", out]
        log(f"reelkit audio: {len(cue_list)} cue(s)"
            + (", voice chain" if voice_filters(voice) else "")
            + (", ducked" if (duck or {}).get("enabled") else ""))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"reelkit audio: mix failed\n{r.stderr[-1200:]}")
    prove(out, source_audio, cue_list, log=log)
    return out


def added_db(mixed, source, at, span=PROOF_WINDOW):
    """Peak of (mixed - source) across a cue's span: what the mix put there.

    Two things this has to get right, both learned by getting them wrong:

    The seek must be sample accurate. `-ss` before `-i` is approximate, and a
    few milliseconds of misalignment stops the two signals cancelling - the
    difference then reads as loud as the source everywhere, which looks like
    every cue passing when nothing is being measured at all.

    The window must cover the cue, not its first instant. A riser opens near
    silence and builds; sampling 0.45s at its onset reported it missing when it
    was correctly placed and audible a second later.
    """
    span = max(PROOF_WINDOW, min(float(span or 0) or PROOF_WINDOW, PROOF_MAX_SPAN))
    trim = f"atrim={at}:{at + span},asetpts=PTS-STARTPTS"
    fmt = f"aformat=sample_fmts=fltp:sample_rates={RATE}:channel_layouts=mono"
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", mixed, "-i", source, "-filter_complex",
         f"[0:a]{fmt},{trim}[a];[1:a]{fmt},{trim},volume=-1.0[b];"
         f"[a][b]amix=inputs=2:normalize=0:dropout_transition=0,volumedetect",
         "-f", "null", "-"], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "max_volume" in line:
            try:
                return float(line.split(":")[-1].replace("dB", "").strip())
            except ValueError:
                return None
    return None


def prove(out, source_audio, cue_list, log=print):
    """Measure the delivered file at every cue and refuse a silent result.

    A mix that runs cleanly and places nothing is the failure mode this whole
    stage exists to fix, and it is inaudible to every other gate: the file
    decodes, the levels look ordinary, and the cues are simply not there. The
    command's exit code cannot see it, so the only honest check is to listen to
    the output and compare it against the source at the same instants.

    Fail-closed in the direction that matters: a cue that cannot be measured
    blocks, because "I could not tell" and "it is fine" are not the same answer.
    """
    if not cue_list:
        return
    quiet = []
    for c in cue_list:
        got = added_db(out, source_audio, c["start"], c.get("duration"))
        if got is None:
            raise SystemExit(
                f"reelkit audio: could not measure the mix at {c['start']:.2f}s "
                f"({c['src']}) - refusing to ship audio nobody has checked")
        if got < PROOF_FLOOR_DB:
            quiet.append((c, got))
    if quiet:
        detail = "; ".join(f"{c['src']} at {c['start']:.2f}s (added {got:.1f} dBFS)"
                           for c, got in quiet)
        raise SystemExit(
            f"reelkit audio: {len(quiet)} of {len(cue_list)} cue(s) are not "
            f"audible in the mixed output - {detail}. The mix ran and placed "
            "nothing, which is exactly the drop this stage exists to prevent.")
    log(f"reelkit audio: {len(cue_list)} cue(s) proven audible in the output")
