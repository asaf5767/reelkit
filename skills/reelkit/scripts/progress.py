#!/usr/bin/env python3
"""Progress-dim sequencing and the lower-third band.

PROGRESS-DIM is the structure-diagram move: a list of the argument's sections
sits on screen, the one being spoken is lit, and the ones already covered dim
behind it. It reads as a speaker walking through their own outline rather than
as a slide, and the reason it works is that the timing comes from the SPEECH -
each section lights when its cue word is actually said. A section list with
hand-typed timestamps drifts the moment the cut changes; resolving cues against
the transcript cannot.

LOWER-THIRDS are the standard talking-head dressing reelkit has never had: a
name and a title, briefly, in the band between the speaker's chin and the
captions. That band is narrow and it is shared, so the placement is gated the
way every other overlay is - it may not reach the head zone above it, and it may
not reach the caption band below it. Both are measured, not asserted.
"""
LT_HEIGHT = 190          # the band a lower-third occupies
LT_MARGIN = 28           # clearance demanded from the head and the captions


def resolve_cues(sections, words, st, en):
    """Give every section a start time, from its cue word where it has one.

    A cue is matched against the spoken words inside the beat only: the same
    word said earlier in the reel is not this section's cue. Sections with
    neither a cue nor an explicit `at` are spread evenly, so a plan can mix the
    two without the result depending on which style it used.
    """
    out, inside = [], [w for w in (words or [])
                       if st <= float(w.get("start", -1)) < en]
    span = max(0.4, float(en) - float(st))
    cursor = float(st)
    for i, sec in enumerate(sections):
        at = sec.get("at")
        if at is None and sec.get("cue"):
            cue = str(sec["cue"]).strip().casefold()
            hit = next((w for w in inside
                        if float(w.get("start", 0)) >= cursor
                        and cue in str(w.get("text", "")).strip().casefold()), None)
            if hit is None:                    # cue not spoken in this beat
                hit = next((w for w in inside
                            if cue in str(w.get("text", "")).strip().casefold()), None)
            if hit is not None:
                at = float(hit["start"])
        if at is None:
            at = float(st) + span * (i / max(1, len(sections)))
        at = max(float(st), min(float(at), float(en) - 0.12))
        cursor = max(cursor, at)
        out.append(dict(sec, at=round(at, 4)))
    # Monotonic: a cue matched out of order would light a later section first.
    for i in range(1, len(out)):
        if out[i]["at"] < out[i - 1]["at"]:
            out[i]["at"] = out[i - 1]["at"]
    return out


def band_rect(H, cap_top, head_bottom, height=LT_HEIGHT, margin=LT_MARGIN):
    """(y, height) of the lower-third band, parked just above the captions."""
    y = int(cap_top) - margin - height
    return y, height


def band_problems(bid, H, cap_top, head_bottom, cap_on=True,
                  height=LT_HEIGHT, margin=LT_MARGIN):
    """Why this lower-third cannot be placed. Empty means it fits.

    The band lives between the speaker's chin and the caption band, and both
    neighbours move: a close framing lowers the head, and a plan can raise the
    captions. So the fit is computed against the real numbers rather than
    assumed from a constant.
    """
    out = []
    y, h = band_rect(H, cap_top, head_bottom, height, margin)
    if y < 0:
        out.append(("ERROR", bid,
                    f"no room for a lower-third: the caption band starts at y={cap_top} "
                    f"and the band needs {h}px above it."))
        return out
    if head_bottom is not None and y < float(head_bottom) + margin:
        out.append(("ERROR", bid,
                    f"the lower-third band starts at y={y} but the speaker's head reaches "
                    f"y={float(head_bottom):.0f} - it would sit on his chin. Raise the "
                    f"captions, or reframe."))
    if cap_on and (y + h) > int(cap_top):
        out.append(("ERROR", bid,
                    f"the lower-third reaches y={y + h} and the caption band starts at "
                    f"y={cap_top} - they would overlap."))
    return out
