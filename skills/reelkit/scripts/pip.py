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
    # `broll.src` used to be REQUIRED here and read nowhere: the renderer drew
    # the card body and never touched it, so the gate demanded a key the build
    # ignored. It is read now (it becomes the full-frame ground, the same path
    # `full` uses) and is therefore optional - a pip beat whose card IS the
    # artifact does not need one. What stays mandatory is the justification,
    # because that is the doctrine: a cut nobody can justify is decoration.
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


def map_rect(rect, W, H, scale=DEFAULT_SCALE, corner=DEFAULT_CORNER, margin=MARGIN):
    """A full-frame rect as it lands on screen once the head insets.

    The wrapper scales from its own top-left and is then translated to the
    inset's origin, so a point p maps to (inset.x + p.x*s, inset.y + p.y*s).
    Exact, not conservative: the head occupies PART of the inset, and treating
    the whole inset as head zone would forbid layouts that are actually clear.
    """
    x, y, _w, _h = inset_rect(W, H, scale, corner, margin)
    rx, ry, rw, rh = rect
    return (x + rx * scale, y + ry * scale, rw * scale, rh * scale)


def head_zone(head, W, H, pip=None):
    """Where the speaker's head really is during a pip beat, or None.

    This is the whole reason a pip beat cannot be gated like any other. verify
    measures the head in the SOURCE footage - its full-frame position - and a
    pip beat's entire point is that the head is not there: it has insetted to a
    corner. Gating a pip artifact against the full-frame head forbids the frame
    the mode exists to give you, which is exactly what it did on v33.
    """
    if not head:
        return None
    pip = pip or {}
    return map_rect(head, W, H, float(pip.get("scale", DEFAULT_SCALE)),
                    pip.get("corner", DEFAULT_CORNER))


# The inset always hides scale^2 of the frame - 9% at the default 0.30 - and on
# a full-bleed artifact that is inherent to picture-in-picture, not a defect.
# What is a defect is the inset sitting on a SMALL artifact, so the threshold is
# set well clear of the inherent figure.
OCCLUSION_WARN = 12
OCCLUSION_MAX = 25


def occlusion(box, W, H, pip=None):
    """How much of the artifact the head inset covers, as a % of the artifact."""
    if not box:
        return None
    pip = pip or {}
    ix, iy, iw, ih = inset_rect(W, H, float(pip.get("scale", DEFAULT_SCALE)),
                               pip.get("corner", DEFAULT_CORNER))
    ox = max(0.0, min(box["x"] + box["w"], ix + iw) - max(box["x"], ix))
    oy = max(0.0, min(box["y"] + box["h"], iy + ih) - max(box["y"], iy))
    area = float(box["w"]) * float(box["h"])
    return round(100.0 * ox * oy / area, 1) if area > 0 else None


def artifact_findings(bid, box, W, H, pip=None):
    """The artifact against the inset that sits on top of it.

    The artifact renders UNDER the inset, so this is not a face-zone finding -
    the face is never covered. It is a content finding: an artifact hiding
    behind the speaker's head is an artifact nobody can read.
    """
    o = occlusion(box, W, H, pip)
    if o is None:
        return []
    corner = (pip or {}).get("corner", DEFAULT_CORNER)
    if o >= OCCLUSION_MAX:
        return [("ERROR", bid,
                 f"the head inset covers {o}% of the artifact - it is behind the "
                 f"speaker rather than beside him. Move the inset to another corner "
                 f"(currently {corner}), shrink it, or give the artifact less width.")]
    if o >= OCCLUSION_WARN:
        return [("WARN", bid, f"the head inset covers {o}% of the artifact")]
    return []
