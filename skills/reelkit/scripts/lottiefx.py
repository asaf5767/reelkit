#!/usr/bin/env python3
"""Lottie badge overlays: vendored assets, accounted cost, gated placement.

HyperFrames ships a Lottie runtime adapter and reelkit has never used it. A
badge is the cheap case for it - a small animated mark whose timeline is already
encoded in the asset, so the renderer only has to seek a player.

Three rules, each of them a thing that goes wrong with Lottie specifically:

LICENCE. Every asset is vendored into the repo with its licence recorded, and a
file with no licence entry is refused rather than shipped. This repo is public,
so an asset nobody can account for is a legal problem, not a missing feature.
Nothing is hotlinked: the player and the JSON are both local, which is also the
only way a render works on a kernel with no egress.

COST. A Lottie renders to SVG, and the heavy-overlay budget that turns a render
black past ~40 elements counts SVG the same as anything else. Gradient fills,
masks and mattes inside the JSON are exactly the expensive kind, so the asset is
inspected and refused if it carries them - the budget cannot be enforced on
markup the build never sees.

PLACEMENT. A badge is an overlay like any other, so it obeys the same two
boundaries: it may not reach the head zone, and it may not reach the caption
band.
"""
import json, os

BADGE = 200                      # default badge box, square
MARGIN = 24
CORNERS = ("top-right", "top-left", "bottom-right", "bottom-left")
DEFAULT_CORNER = "top-right"
# Lottie shape/effect types that cost what the heavy-overlay budget measures.
HEAVY_TYPES = {"gf": "gradient fill", "gs": "gradient stroke"}
MANIFEST_KEYS = {"license", "author", "source", "frames", "fps", "size", "note"}


def _die(msg):
    raise SystemExit(f"reelkit lottie: {msg}")


def asset_dir(skill):
    return os.path.join(skill, "assets", "lottie")


def manifest(skill):
    p = os.path.join(asset_dir(skill), "manifest.json")
    if not os.path.exists(p):
        _die(f"no manifest at {p} - every badge needs a recorded licence")
    with open(p, encoding="utf-8") as fh:
        man = json.load(fh)
    for name, meta in man.items():
        bad = sorted(set(meta) - MANIFEST_KEYS)
        if bad:
            _die(f"{name}: unknown manifest key(s) {', '.join(bad)} "
                 f"(allowed: {', '.join(sorted(MANIFEST_KEYS))})")
        if not str(meta.get("license") or "").strip():
            _die(f"{name}: no licence recorded - an asset nobody can account for "
                 "cannot ship in a public repo")
    return man


def heavy_features(doc):
    """Which expensive constructs a Lottie document carries, by name.

    Walks the whole document because these nest arbitrarily deep inside shape
    groups, and a gradient three levels down costs exactly as much as one at the
    top.
    """
    found = set()

    def walk(node):
        if isinstance(node, dict):
            ty = node.get("ty")
            if isinstance(ty, str) and ty in HEAVY_TYPES:
                found.add(HEAVY_TYPES[ty])
            if node.get("hasMask") or node.get("masksProperties"):
                found.add("mask")
            if node.get("tt"):
                found.add("track matte")
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)
    return sorted(found)


def load(skill, name):
    """One badge, validated. Returns (document, metadata)."""
    man = manifest(skill)
    if name not in man:
        have = ", ".join(sorted(man)) or "none"
        _die(f"unknown badge {name!r} (have: {have})")
    path = os.path.join(asset_dir(skill), f"{name}.json")
    if not os.path.exists(path):
        _die(f"{name} is in the manifest but {path} is missing")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    for key in ("v", "fr", "op", "w", "h", "layers"):
        if key not in doc:
            _die(f"{name}: not a Lottie document (no {key!r})")
    heavy = heavy_features(doc)
    if heavy:
        _die(f"{name} carries {', '.join(heavy)} - these are what the heavy-overlay "
             "budget measures, and a render past that budget comes back black. "
             "Use a badge built from strokes and solid fills.")
    if doc.get("assets"):
        _die(f"{name} references external assets - a badge must be one "
             "self-contained file, or the render depends on egress")
    return doc, man[name]


def badge_rect(W, H, size=BADGE, corner=DEFAULT_CORNER, margin=MARGIN):
    if corner not in CORNERS:
        _die(f"unknown corner {corner!r}; have {', '.join(CORNERS)}")
    x = margin if "left" in corner else W - size - margin
    y = margin if corner.startswith("top") else H - size - margin
    return x, y, size, size


def problems(bid, W, H, cap_top, head_rect_, badge, cap_on=True, cap_h=360):
    """A badge is an overlay: same two boundaries as everything else.

    Both tests are real interval overlaps. An earlier version asked whether the
    badge CROSSED each boundary, which let a badge sitting entirely inside the
    caption band through - it never crossed the edge because it started past it.
    """
    out = []
    size = int(badge.get("size", BADGE))
    corner = badge.get("corner", DEFAULT_CORNER)
    if corner not in CORNERS:
        return [("ERROR", bid, f"unknown badge corner {corner!r}; have {', '.join(CORNERS)}")]
    _x, y, _w, h = badge_rect(W, H, size, corner)
    top, bot = y, y + h

    if head_rect_:
        hy, hh = float(head_rect_[1]), float(head_rect_[3])
        if top < hy + hh and bot > hy:
            out.append(("ERROR", bid,
                        f"the badge occupies y={top}-{bot} and the speaker's head spans "
                        f"y={hy:.0f}-{hy + hh:.0f} - no overlay touches the face."))
    if cap_on:
        cy, cb = int(cap_top), int(cap_top) + int(cap_h)
        if top < cb and bot > cy:
            out.append(("ERROR", bid,
                        f"the badge occupies y={top}-{bot} and the caption band spans "
                        f"y={cy}-{cb} - they would overlap."))
    return out


def markup(cid, name, badge, W, H):
    """Container plus loader.

    autoplay and loop are both off: HyperFrames SEEKS the player, so an
    animation that plays itself renders a different frame than a seek to the
    same time - the determinism rule the whole pipeline rests on.
    """
    size = int(badge.get("size", BADGE))
    x, y, _w, _h = badge_rect(W, H, size, badge.get("corner", DEFAULT_CORNER))
    eid = f"{cid}-badge"
    html = (f'<div class="lbadge" id="{eid}" '
            f'style="left:{x}px;top:{y}px;width:{size}px;height:{size}px;"></div>')
    js = (f'(function(){{var c=document.getElementById("{eid}");'
          f'if(!c||!window.lottie)return;'
          f'var a=window.lottie.loadAnimation({{container:c,renderer:"svg",'
          f'loop:false,autoplay:false,path:"lottie/{name}.json"}});'
          f'window.__hfLottie=window.__hfLottie||[];window.__hfLottie.push(a);}})();')
    return html, js
