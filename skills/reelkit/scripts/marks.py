#!/usr/bin/env python3
"""The hand-drawn mark family - doodles a plan can name instead of hand-author.

`doodle` was an escape hatch: the author pasted 1-3 KB of inline SVG per beat
and listed the tweens by element id. That is still supported and still useful,
but it meant every annotation was a one-off, so nothing looked like it came from
the same hand twice.

These four marks are the family, each drawn as a single open stroke path so the
whole thing can draw on with `stroke-dashoffset` - the cheapest motion in the
repo and the most recognisable "creator" signature available:

  circle-scribble  a looping ring around the artifact
  underline        a swept rule beneath it
  curved-arrow     a hooked arrow entering from an edge, pointing inward
  sparkle          three radiating ticks at a corner

Every mark is laid out in a 0-1000 square viewBox mapped onto the card, and
every one points AT the artifact by construction: the ring encloses the middle,
the underline sits beneath it, the arrow enters from an edge and terminates
inward, the sparkle sits on a corner of it. There is no way to author a mark
that points at nothing, because no mark takes a free position.

Nothing here spends the heavy-overlay budget: plain strokes, no blur, no
gradient, no clip-path.

Determinism: build is a pure function of the plan, so the scribble's wobble is
derived from the beat id rather than sampled - the same plan renders the same
path forever.
"""
import hashlib, math

NAMES = ("circle-scribble", "underline", "curved-arrow", "sparkle")
VIEW = 1000                      # marks are authored in a 0-1000 square
EDGES = ("left", "right", "top", "bottom")


def _rng(seed):
    """A tiny deterministic sequence in [-1, 1] from a string seed."""
    h = hashlib.sha256(seed.encode()).digest()
    i = 0
    while True:
        yield (h[i % len(h)] / 127.5) - 1.0
        i += 1


def _path_len(pts):
    """Polyline length - the dasharray the draw-on needs. Approximating a curve
    by its control polygon runs slightly long, which is the safe direction: a
    dash longer than the path leaves it fully hidden until the tween starts."""
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def circle_scribble(seed, loops=2):
    """A ring that overshoots itself, the way a real pen circles something."""
    r = _rng(seed)
    cx = cy = VIEW / 2
    rx, ry = VIEW * 0.42, VIEW * 0.34
    pts, steps = [], 46
    total = loops * 2 * math.pi + 0.55          # overshoot past the start
    for i in range(steps + 1):
        a = -2.0 + total * (i / steps)
        wob = 1.0 + 0.045 * next(r)
        pts.append((cx + rx * wob * math.cos(a), cy + ry * wob * math.sin(a)))
    return pts


def underline(seed):
    """A single swept rule with a lift at the end."""
    r = _rng(seed)
    y = VIEW * 0.72
    pts = []
    for i in range(15):
        f = i / 14
        pts.append((VIEW * (0.10 + 0.80 * f), y + 26 * math.sin(f * math.pi) + 9 * next(r)))
    pts.append((VIEW * 0.93, y - 34))           # the flick
    return pts


def curved_arrow(seed, edge="left"):
    """Enters from an edge and ends pointing inward at the artifact."""
    if edge not in EDGES:
        raise ValueError(f"curved-arrow edge must be one of {EDGES}, got {edge!r}")
    start = {"left": (VIEW * 0.04, VIEW * 0.20), "right": (VIEW * 0.96, VIEW * 0.20),
             "top": (VIEW * 0.22, VIEW * 0.04), "bottom": (VIEW * 0.22, VIEW * 0.96)}[edge]
    end = {"left": (VIEW * 0.40, VIEW * 0.50), "right": (VIEW * 0.60, VIEW * 0.50),
           "top": (VIEW * 0.50, VIEW * 0.40), "bottom": (VIEW * 0.50, VIEW * 0.60)}[edge]
    bow = {"left": (VIEW * 0.10, VIEW * 0.62), "right": (VIEW * 0.90, VIEW * 0.62),
           "top": (VIEW * 0.62, VIEW * 0.10), "bottom": (VIEW * 0.62, VIEW * 0.90)}[edge]
    pts = []
    for i in range(19):                          # quadratic bezier, sampled
        t = i / 18
        pts.append((( 1 - t) ** 2 * start[0] + 2 * (1 - t) * t * bow[0] + t * t * end[0],
                    (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * bow[1] + t * t * end[1]))
    # head: two barbs back along the final direction
    dx, dy = pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]
    n = math.hypot(dx, dy) or 1.0
    dx, dy = dx / n, dy / n
    h = VIEW * 0.075
    for ang in (2.5, -2.5):
        bx = pts[-1][0] + h * (dx * math.cos(ang) - dy * math.sin(ang))
        by = pts[-1][1] + h * (dx * math.sin(ang) + dy * math.cos(ang))
        pts += [(bx, by), pts[-1]]
    return pts


def sparkle(seed, corner="top-right"):
    """Three radiating ticks at a corner of the artifact."""
    cx, cy = {"top-right": (VIEW * 0.80, VIEW * 0.20), "top-left": (VIEW * 0.20, VIEW * 0.20),
              "bottom-right": (VIEW * 0.80, VIEW * 0.80),
              "bottom-left": (VIEW * 0.20, VIEW * 0.80)}.get(corner, (VIEW * 0.80, VIEW * 0.20))
    pts, arm = [], VIEW * 0.085
    for a in (-math.pi / 2, math.pi / 6, 5 * math.pi / 6):
        pts += [(cx, cy), (cx + arm * math.cos(a), cy + arm * math.sin(a)), (cx, cy)]
    return pts


BUILDERS = {"circle-scribble": lambda s, o: circle_scribble(s, int(o.get("loops", 2))),
            "underline": lambda s, o: underline(s),
            "curved-arrow": lambda s, o: curved_arrow(s, o.get("edge", "left")),
            "sparkle": lambda s, o: sparkle(s, o.get("corner", "top-right"))}


def d_attr(pts):
    return "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts)


def mark_svg(eid, name, seed, opts=None, color="#111", width=10):
    """One mark as an SVG <path>, plus the dash length its draw-on needs."""
    if name not in BUILDERS:
        raise ValueError(f"unknown mark {name!r}; have {', '.join(NAMES)}")
    pts = BUILDERS[name](seed, opts or {})
    length = int(_path_len(pts)) + 1
    path = (f'<path id="{eid}" d="{d_attr(pts)}" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" '
            f'stroke-dasharray="{length}" stroke-dashoffset="{length}"/>')
    return path, length
