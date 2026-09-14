#!/usr/bin/env python3
"""PiP head inset: the speaker shrinks to a corner while the artifact fills.

The doctrine around it matters more than the geometry. Face full frame is the
default; PiP is the justified exception. A PiP cut is allowed only when the
B-roll literally shows the thing being said - the code being written, the screen
being described, the grill being named - and the plan has to say what that is.
A pip beat with no `justification` fails the build, in the same spirit as a
profile key nothing reads: a cut nobody can justify is decoration, and
decoration is what this rule exists to keep out.

Geometry is computed, never authored, for the same reason card boxes are: the
inset has to be provably clear of the caption band, and a number someone typed
into a plan drifts. The default corner is at the TOP because the caption band
owns the bottom of the frame - an inset that shares it would put the speaker's
face behind the words.
"""
CORNERS = ("top-right", "top-left", "bottom-right", "bottom-left")
DEFAULT_CORNER = "top-right"
DEFAULT_SCALE = 0.30
MARGIN = 48            # gap from the canvas edge
RADIUS = 44            # rounded rect, matching the card radius


def inset_rect(W, H, scale=DEFAULT_SCALE, corner=DEFAULT_CORNER, margin=MARGIN):
    """(x, y, w, h) of the head inset in canvas pixels."""
    if corner not in CORNERS:
        raise SystemExit(f"reelkit pip: unknown corner {corner!r}; have {', '.join(CORNERS)}")
    if not 0.12 <= scale <= 0.60:
        raise SystemExit(f"reelkit pip: inset scale {scale} is outside 0.12-0.60 - "
                         "smaller than that the face is unreadable, larger and it is "
                         "not an inset")
    w, h = round(W * scale), round(H * scale)
    x = margin if "left" in corner else W - w - margin
    y = margin if corner.startswith("top") else H - h - margin
    return x, y, w, h


def clears_captions(W, H, cap_top, scale=DEFAULT_SCALE, corner=DEFAULT_CORNER,
                    margin=MARGIN):
    """Does the inset stay out of the caption band? Bottom corners rarely do."""
    _x, y, _w, h = inset_rect(W, H, scale, corner, margin)
    return (y + h) <= cap_top


def problems(beat, W, H, cap_top, cap_on=True):
    """Everything that disqualifies a pip beat, as (level, id, message)."""
    out = []
    bid = beat.get("id", "?")
    pip = beat.get("pip") or {}
    just = str(beat.get("justification") or pip.get("justification") or "").strip()
    if not just:
        out.append(("ERROR", bid,
                    "a pip beat must carry `justification` naming the literal thing the "
                    "B-roll shows (e.g. \"B-roll shows the grill being named\"). Face full "
                    "frame is the default; PiP is the justified exception, and a cut "
                    "nobody can justify is decoration."))
    elif len(just) < 12:
        out.append(("ERROR", bid,
                    f"`justification` is {len(just)} characters - name what is on screen, "
                    "not a placeholder."))
    if not (beat.get("broll") or {}).get("src"):
        out.append(("ERROR", bid,
                    "a pip beat needs `broll.src`: the artifact fills the frame while the "
                    "speaker insets. Without it there is nothing to cut to."))
    corner = pip.get("corner", DEFAULT_CORNER)
    scale = float(pip.get("scale", DEFAULT_SCALE))
    if corner in CORNERS and cap_on and not clears_captions(W, H, cap_top, scale, corner):
        x, y, w, h = inset_rect(W, H, scale, corner)
        out.append(("ERROR", bid,
                    f"the head inset reaches y={y + h} but the caption band starts at "
                    f"y={cap_top} - the speaker's face would sit behind the words. Use a "
                    "top corner, or a smaller inset."))
    return out


def tweens(bid, W, H, st, en, an, sel="'#pip-frame'", pip=None):
    """Shrink to the corner for the beat, then return. fromTo both ways so a
    seek to any frame lands on the right state."""
    pip = pip or {}
    scale = float(pip.get("scale", DEFAULT_SCALE))
    corner = pip.get("corner", DEFAULT_CORNER)
    x, y, w, h = inset_rect(W, H, scale, corner)
    # The wrapper scales from its own top-left, so the translation is the
    # inset's origin - no transformOrigin juggling, and it composes with the
    # framing scale that lives on the inner element.
    dur = float(pip.get("duration", 0.5))
    out = [f"tl.fromTo({sel},{{scale:1,x:0,y:0,borderRadius:0}},"
           f"{{scale:{scale},x:{x},y:{y},borderRadius:{RADIUS},duration:{dur},"
           f"ease:'power3.inOut',immediateRender:false}},{an.q(st)});",
           f"tl.fromTo({sel},{{scale:{scale},x:{x},y:{y},borderRadius:{RADIUS}}},"
           f"{{scale:1,x:0,y:0,borderRadius:0,duration:{dur},ease:'power3.inOut',"
           f"immediateRender:false}},{an.q(max(st + dur, en - dur))});"]
    return out
