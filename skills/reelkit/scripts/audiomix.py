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
import os, shutil, subprocess, sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loudness  # noqa: E402

SFX_TRACK_MIN = 20          # build puts cue clips on tracks 20+
RATE = 48000                # one sample rate through the whole graph
# How far a cue may be lifted to clear the voice. Past this it is fighting a
# loud word rather than punctuating a beat, and the word is the reel - the gate
# reports such a cue instead of shouting over the sentence.
MAX_LIFT_DB = 24.0
# A filter gain, not a fader: above 1.0 is normal and necessary here, because
# the cue assets are quiet next to a compressed voice - the first cut of this
# loop capped at 1.0 and stalled 9 dB short of the bar with every cue clamped.
# The master limiter below is what keeps the sum honest.
MAX_VOLUME = 8.0
# The dry retry fights no duck, so it may reach higher; the master limiter
# still guards the sum. Measured: lift scales ~0.4 dB per dB of dry gain in
# the band where voice and cue overlap, so headroom here must be generous.
FALLBACK_MAX_VOLUME = 16.0
MIN_VOLUME = 0.02
MASTER_LIMIT = 0.95
# Where a cue sits relative to the voice across the reel before any per-cue
# correction. Under the voice, because the word is the reel - but only just,
# because a cue 20 dB under it is decoration nobody hears.
CUE_UNDER_VOICE_DB = -4.0
# ...but never below this in absolute terms. Programme-relative alone still
# silences cues on a quiet source: a voice at -43 dB puts the base at -47, which
# is nothing. A reel whose speaker was recorded quietly still needs cues you can
# hear, and an SFX at -30 dBFS is modest, not loud.
CUE_FLOOR_DBFS = -30.0
# Measured on the sample: the codec-noise floor between the mixed and source
# files sits at -63..-67 dBFS and a real cue reads -17..-22, so -45 separates
# them with margin on both sides.


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
    """Mix speech and cues; bypassDuck cues join after the sidechain."""
    vf = voice_filters(voice)
    if not cue_list and not vf:
        return None, None

    norm = f"aformat=sample_fmts=fltp:sample_rates={RATE}:channel_layouts=stereo"
    parts = [f"[{speech}:a]" + norm + ("," + ",".join(vf) if vf else "") + "[sp]"]
    if not cue_list:
        return ";".join(parts), "[sp]"

    labels, bypass = [], []
    for n, c in enumerate(cue_list):
        delay = max(0, int(round(c["start"] * 1000)))
        parts.append(f"[{cue_base + n}:a]{norm},volume={c['volume']:.4f},"
                     f"adelay={delay}|{delay}[c{n}]")
        (bypass if c.get("bypassDuck") else labels).append(f"[c{n}]")

    mixed = ["[sp]"]
    if labels:
        parts.append("".join(labels) +
                     f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0[sfxraw]")
        if duck and duck.get("enabled"):
            parts.append("[sp]asplit=2[sp1][spk]")
            parts.append(f"[sfxraw][spk]sidechaincompress=threshold={duck.get('threshold', 0.05)}:"
                         f"ratio={duck.get('ratio', 8)}:attack={duck.get('attackMs', 5)}:"
                         f"release={duck.get('releaseMs', 250)}[sfx]")
            mixed = ["[sp1]", "[sfx]"]
        else:
            mixed.append("[sfxraw]")
    mixed.extend(bypass)
    parts.append("".join(mixed) +
                 f"amix=inputs={len(mixed)}:normalize=0:dropout_transition=0,"
                 f"alimiter=limit={MASTER_LIMIT}[mix]")
    return ";".join(parts), "[mix]"


def mix(project, video_in, source_audio, out, voice=None, duck=None, log=print):
    """Four normal mix attempts, then at most one cue-specific dry fallback."""
    cue_list = cues(project)
    if not cue_list and not voice_filters(voice):
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", video_in, "-i", source_audio,
               "-map", "0:v:0", "-map", "1:a:0", "-dn", "-sn", "-write_tmcd", "0",
               "-map_chapters", "-1",
               "-c", "copy", "-shortest", out]
        log("reelkit audio: no cues and no voice chain - straight mux")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"reelkit audio: mix failed\n{r.stderr[-1200:]}")
        return out

    ref = os.path.join(os.path.dirname(os.path.abspath(out)) or ".",
                       ".reelkit-voice-only.wav")
    voice_only(source_audio, ref, voice, duck)
    try:
        cue_list = calibrate(cue_list, ref, log=log) if cue_list else cue_list
        rows = []
        for attempt in range(4):
            _render(video_in, source_audio, cue_list, out, voice, duck, log,
                    quiet=attempt > 0)
            rows = measure(out, ref, cue_list)
            short = [(c, r) for c, r in zip(cue_list, rows)
                     if not r.get("skipped")
                     and r["headroomDb"] < loudness.AUDIBLE_TARGET - 1.0]
            if not short or attempt == 3:
                break
            changed = 0
            for c, r in short:
                lift = min(loudness.AUDIBLE_TARGET - r["headroomDb"], MAX_LIFT_DB)
                volume = round(min(MAX_VOLUME, c["volume"] * 10 ** (lift / 20.0)), 4)
                if volume > c["volume"]:
                    c["volume"] = volume
                    changed += 1
            if not changed:
                break
            log(f"reelkit audio: lifting {changed} cue(s) and re-mixing")

        # The duck eats lifts (an 8:1 sidechain passes ~1/8 of each gain), so a
        # stuck cue can stay below MAX_VOLUME through every lift round - the
        # ceiling is not the signal that the loop has failed, the still-failing
        # measurement is. Any in-range cue under the bar after the lift loop
        # gets one measured dry retry.
        fallback = [(c, r) for c, r in zip(cue_list, rows)
                    if (duck or {}).get("enabled") and not c.get("bypassDuck")
                    and not r.get("skipped")
                    and r["headroomDb"] < loudness.AUDIBLE_MIN]
        for c, r in fallback:
            # Reset the accumulated duck compensation. Estimate only the dry
            # gain needed for the gate; the encoded result remains authoritative.
            off = max(0.0, r["at"] - float(c["start"]))
            gain, _ = loudness.needed_gain_db(
                loudness.asset_bands(c["path"], off),
                loudness.voice_floor(ref, r["at"]),
                target=loudness.AUDIBLE_MIN + 2.0)
            c["volume"] = round(max(MIN_VOLUME, min(FALLBACK_MAX_VOLUME,
                                                    10 ** (gain / 20.0))), 4)
            c["bypassDuck"] = True
            log(f"reelkit audio: bypassing duck for {c['src']} at {r['at']:.2f}s "
                f"after the lift loop left it inaudible; dry volume "
                f"{c['volume']:.4f}")
        if fallback:
            _render(video_in, source_audio, cue_list, out, voice, duck, log,
                    quiet=True)
            rows = measure(out, ref, cue_list)
            # The dry-gain estimate reads the asset and the voice floor, not
            # the encoded mix; speech dynamics move the real floor by a few
            # dB. Top up from the MEASURED shortfall, generously because the
            # band lift grows sub-linearly once the cue already shows.
            for _ in range(2):
                short = [(c, r) for c, r in zip(cue_list, rows)
                         if c.get("bypassDuck") and not r.get("skipped")
                         and r["headroomDb"] < loudness.AUDIBLE_MIN
                         and c["volume"] < FALLBACK_MAX_VOLUME]
                if not short:
                    break
                for c, r in short:
                    need = (loudness.AUDIBLE_MIN + 1.0 - r["headroomDb"]) * 2.0
                    c["volume"] = round(min(FALLBACK_MAX_VOLUME,
                                            c["volume"] * 10 ** (need / 20.0)), 4)
                    log(f"reelkit audio: topping up {c['src']} at "
                        f"{r['at']:.2f}s to {c['volume']:.4f} "
                        f"(measured {r['headroomDb']:+.1f} dB)")
                _render(video_in, source_audio, cue_list, out, voice, duck,
                        log, quiet=True)
                rows = measure(out, ref, cue_list)
        return _finish(out, ref, cue_list, rows, log)
    finally:
        if os.path.exists(ref):
            os.remove(ref)


def _render(video_in, source_audio, cue_list, out, voice, duck, log, quiet=False):
    fc, label = filtergraph(cue_list, voice, duck, speech=1, cue_base=2)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", video_in, "-i", source_audio]
    for c in cue_list:
        cmd += ["-i", c["path"]]
    cmd += ["-filter_complex", fc, "-map", "0:v:0", "-map", label,
            "-dn", "-sn", "-write_tmcd", "0", "-map_chapters", "-1",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", out]
    if not quiet:
        log(f"reelkit audio: {len(cue_list)} cue(s)"
            + (", voice chain" if voice_filters(voice) else "")
            + (", ducked" if (duck or {}).get("enabled") else ""))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"reelkit audio: mix failed\n{r.stderr[-1200:]}")


def _finish(out, ref, cue_list, rows, log):
    prove(out, ref, cue_list, log=log, rows=rows)
    return out


def voice_only(source_audio, out, voice=None, duck=None):
    """The delivered voice with the cues removed, through the SAME chain.

    This is the reference every measurement here is taken against, and getting
    it wrong is how the old gate passed a mix nobody could hear a cue in. The
    obvious reference - the raw source audio - is not the right one: the voice
    chain compresses, EQs and adds makeup gain, so a mix compared against the
    raw source reads several dB of "extra" at every timestamp that is the voice
    chain, not the cue. Measured on wareel, that error flattered every cue by
    3-6 dB and turned an inaudible mix into a passing one.
    """
    fc, label = filtergraph([], voice, duck, speech=0, cue_base=1)
    if fc is None:
        shutil.copyfile(source_audio, out)
        return out
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", source_audio,
                        "-filter_complex", fc, "-map", label,
                        "-map_chapters", "-1",
                        "-c:a", "pcm_s16le", out], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"reelkit audio: could not build the voice-only "
                         f"reference\n{r.stderr[-800:]}")
    return out


def moment(cue):
    """When to measure a cue: its own loudest instant, not its nominal start.

    A riser opens near silence and builds for seconds. Measuring it where it
    starts reads the silence in front of it and calls a correctly placed cue
    missing - a measurement bug that cost a review round once already.
    """
    try:
        return round(float(cue["start"]) + loudness.peak_offset(cue["path"]), 3)
    except Exception:
        return float(cue["start"])


def calibrate(cue_list, ref, log=print):
    """Set each cue's gain from the voice it has to share a reel with.

    The old calibration normalised every cue asset to a fixed -11 dBFS and
    scaled it by a taste number - about -19 dB by the time it reached the graph.
    That is an ABSOLUTE target, and the thing a cue competes with is not
    absolute: when the voice chain moved the delivered mix from -23.2 to -18.4
    LUFS, every cue lost 5 dB of presence without a single number changing.
    Measured on a real reel, the authored 0.11 should have been about 1.0 - the
    cues were entering roughly 20 dB below where they needed to be, which is
    why the answer to "can you hear the SFX" was "I don't hear any. Anything."

    The base level is PROGRAM-relative: the cue sits a fixed distance under the
    voice's own level across the reel. Deliberately not the instantaneous floor
    - a first cut of this set each cue `target` dB above the voice AT that
    instant, which silently turned cues DOWN in quiet passages, where the floor
    is near silence and 10 dB above near silence is still near silence. A cue is
    never attenuated to meet a bar; the bar is a floor, not a setpoint.

    Then the loop in `mix` lifts whatever still fails the perceptual gate. Base
    plus correction, rather than one clever formula, because the duck, the
    limiter and the other cues all have a say and none of them is predictable
    from the assets alone.
    """
    program = loudness.level_db(ref)
    out = []
    for c in cue_list:
        off = loudness.peak_offset(c["path"])
        at = round(float(c["start"]) + off, 3)
        asset = loudness.level_db(c["path"], off, loudness.WINDOW)
        gain = max(program + CUE_UNDER_VOICE_DB, CUE_FLOOR_DBFS) - asset
        out.append(dict(c, at=at, authoredVolume=c.get("volume"),
                        volume=round(max(MIN_VOLUME, min(MAX_VOLUME,
                                                         10 ** (gain / 20.0))), 4)))
        log(f"reelkit audio: {c['src']} at {at:.2f}s -> {out[-1]['volume']:.3f} "
            f"(asset {asset:.1f} dB, voice programme {program:.1f} dB)")
    return out


def measure(out, ref, cue_list):
    """One row per cue, including explicit skips outside the delivered audio."""
    if not cue_list:
        return []
    try:
        delivered = loudness.duration(out)
    except Exception as e:
        raise SystemExit(
            f"reelkit audio: could not measure delivered audio duration: "
            f"{type(e).__name__} - refusing to ship audio nobody has checked") from e
    rows = []
    for c in cue_list:
        at = float(c["at"]) if "at" in c else moment(c)
        # Half a sample accommodates floating-point boundary arithmetic only.
        if at < 0 or at + loudness.WINDOW > delivered + 0.5 / loudness.RATE:
            rows.append({"src": c["src"], "at": at, "skipped": True,
                         "reason": f"window {at:.3f}-{at + loudness.WINDOW:.3f}s "
                                   f"outside delivered audio (0-{delivered:.3f}s)"})
            continue
        try:
            d, band, mixed_db, voice_db = loudness.headroom(out, ref, at)
        except Exception as e:
            raise SystemExit(
                f"reelkit audio: could not measure the mix at {at:.2f}s "
                f"({c['src']}): {type(e).__name__} - refusing to ship audio "
                "nobody has checked")
        rows.append({"src": c["src"], "at": at, "headroomDb": float(d),
                     "band": list(band), "mixedDb": float(mixed_db),
                     "voiceDb": float(voice_db)})
    return rows


def prove(out, ref, cue_list, log=print, rows=None):
    """Refuse inaudible in-range cues; log every out-of-range cue as skipped."""
    if not cue_list:
        return []
    rows = measure(out, ref, cue_list) if rows is None else rows
    if len(rows) != len(cue_list):
        raise SystemExit("reelkit audio: incomplete audibility measurements - refusing export")
    quiet, checked = [], []
    for c, r in zip(cue_list, rows):
        if r.get("skipped"):
            log(f"reelkit audio: skipping {c['src']} at {r['at']:.2f}s: {r['reason']}")
            continue
        checked.append(r)
        if r["headroomDb"] < loudness.AUDIBLE_MIN:
            quiet.append(r)
    if quiet:
        detail = "; ".join(
            f"{r['src']} at {r['at']:.2f}s rises {r['headroomDb']:+.1f} dB over the "
            f"voice in {r['band'][0]}-{r['band'][1]}Hz"
            for r in quiet)
        raise SystemExit(
            f"reelkit audio: {len(quiet)} of {len(checked)} cue(s) are not "
            f"audible in the mixed output (bar is +{loudness.AUDIBLE_MIN:g} dB "
            f"over the voice in the cue's own band) - {detail}. A cue a human "
            "cannot hear is a failed export.")
    if checked:
        worst = min(r["headroomDb"] for r in checked)
        log(f"reelkit audio: {len(checked)} cue(s) audible, worst +{worst:.1f} dB "
            f"over the voice in its own band")
    else:
        log("reelkit audio: no complete cue windows in delivered audio; gate skipped")
    return rows
