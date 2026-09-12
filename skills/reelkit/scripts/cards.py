# -*- coding: utf-8 -*-
"""reelkit card library.

Each builder returns (body_html, [gsap_statements]).
Every card is a self-contained HTML fragment scoped by .card[data-card-id="<id>"].
Contract rules that MUST hold (HyperFrames lint + RTL safety):
  * no <script> inside a card fragment
  * no external URLs
  * every CSS rule prefixed with the scope selector
  * dir="rtl" goes on individual TEXT elements, never on <html>
  * words are wrapped in .wd (white-space:nowrap) so they never break mid-word
"""
import html, os, statistics

def esc(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------- gsap helpers
def S(cid, eid):
    return "'.card[data-card-id=\"%s\"] #%s'" % (cid, eid)


class Anim:
    """Deterministic, seek-safe GSAP emitters. Everything is fromTo on purpose:
    a bare .to() records its start value on first render, which makes a random
    seek produce a different frame than a linear play-through."""

    def __init__(self, fps=30):
        self.fps = fps

    def q(self, t):
        return round(round(float(t) * self.fps) / self.fps, 4)

    def fade(self, sel, t, d=0.40, fr=0):
        return f"tl.fromTo({sel},{{opacity:{fr}}},{{opacity:1,duration:{d},ease:'power2.out'}},{self.q(t)});"

    def pop(self, sel, t, d=0.45, sc=0.55):
        return (f"tl.fromTo({sel},{{opacity:0,scale:{sc}}},"
                f"{{opacity:1,scale:1,duration:{d},ease:'back.out(1.7)'}},{self.q(t)});")

    def slide(self, sel, t, d=0.42, dx=0, dy=0):
        return (f"tl.fromTo({sel},{{opacity:0,x:{dx},y:{dy}}},"
                f"{{opacity:1,x:0,y:0,duration:{d},ease:'power3.out'}},{self.q(t)});")

    def grow_h(self, sel, t, d, h):
        return f"tl.fromTo({sel},{{height:0}},{{height:{h},duration:{d},ease:'power2.out'}},{self.q(t)});"

    def grow_w(self, sel, t, d, w):
        return f"tl.fromTo({sel},{{width:0}},{{width:{w},duration:{d},ease:'power2.out'}},{self.q(t)});"

    def draw(self, sel, t, d, length):
        """Stroke draw-on. Element needs stroke-dasharray=<length> in markup."""
        return (f"tl.fromTo({sel},{{strokeDashoffset:{length}}},"
                f"{{strokeDashoffset:0,duration:{d},ease:'power2.inOut'}},{self.q(t)});")

    def spin(self, sel, t, d, a, b, svg_origin="150 150"):
        """SVG rotation. Uses svgOrigin - transformOrigin on an SVG child is
        resolved against its own bbox, not the viewBox, which silently puts the
        pivot in the wrong place (this ate an hour once)."""
        return (f"tl.set({sel},{{svgOrigin:'{svg_origin}'}},{self.q(t)});"
                f"tl.fromTo({sel},{{rotation:{a}}},{{rotation:{b},duration:{d},ease:'none'}},{self.q(t)});")

    def chars(self, sel, t, d=0.42, stagger=0.024):
        return (f"tl.fromTo({sel}+' .char',{{opacity:0,y:12,scale:.85}},"
                f"{{opacity:1,y:0,scale:1,duration:{d},ease:'power2.out',stagger:{stagger}}},{self.q(t)});")

    def count(self, sel, t, d, frm, to):
        return ("(function(){var o={v:%s};tl.to(o,{v:%s,duration:%s,ease:'power2.out',"
                "onUpdate:function(){var el=document.querySelector(%s);"
                "if(el)el.textContent=String(Math.round(o.v));}},%s);})();"
                % (frm, to, d, sel, self.q(t)))

    def pulse(self, sel, t, d=0.36, sc=1.10, reps=5):
        return (f"tl.fromTo({sel},{{scale:1}},{{scale:{sc},duration:{d},"
                f"yoyo:true,repeat:{reps},ease:'power1.inOut'}},{self.q(t)});")

    def move(self, sel, t, d, frm, to, ease="power1.inOut"):
        # immediateRender:false - `move` is always part of a sequence, and without
        # it the LAST authored hop's from-position becomes the element's resting
        # state for any seek before the sequence starts.
        return (f"tl.fromTo({sel},{{x:{frm[0]},y:{frm[1]}}},"
                f"{{x:{to[0]},y:{to[1]},duration:{d},ease:'{ease}',"
                f"immediateRender:false}},{self.q(t)});")

    def kenburns(self, sel, t, d, a=1.0, b=1.08):
        return (f"tl.fromTo({sel},{{scale:{a}}},{{scale:{b},duration:{d},ease:'none'}},{self.q(t)});")


# ---------------------------------------------------------------- inline icons
ICON = {
 "spark": '<path d="M12 2 L13.6 9.2 L20.8 10.8 L13.6 12.4 L12 19.6 L10.4 12.4 L3.2 10.8 L10.4 9.2 Z" fill="currentColor"/>',
 "check": '<path d="M4 12.5 L9.5 18 L20 6.5" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>',
 "shield": ('<path d="M12 2.6 L20 5.6 V12 c0 5.2 -3.4 8.1 -8 9.4 C7.4 20.1 4 17.2 4 12 V5.6 Z" fill="none" '
            'stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>'
            '<path d="M8.4 12.2 L11 14.8 L15.8 9.6" fill="none" stroke="currentColor" stroke-width="2.2" '
            'stroke-linecap="round" stroke-linejoin="round"/>'),
 "target": ('<circle cx="12" cy="12" r="8.4" fill="none" stroke="currentColor" stroke-width="2"/>'
            '<circle cx="12" cy="12" r="4.2" fill="none" stroke="currentColor" stroke-width="2"/>'
            '<circle cx="12" cy="12" r="1.3" fill="currentColor"/>'),
 "bolt": '<path d="M13 2 L5 13.4 h5.2 L10 22 l8.4 -11.6 H13.2 Z" fill="currentColor"/>',
 "clock": ('<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/>'
           '<path d="M12 6.6 V12 l3.6 2.4" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>'),
 "warn": ('<path d="M12 3.2 L21.4 20 H2.6 Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>'
          '<path d="M12 9.4 v4.6" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>'
          '<circle cx="12" cy="17" r="1.3" fill="currentColor"/>'),
}


def icon(name, cls="ico"):
    return f'<svg viewBox="0 0 24 24" class="{cls}" aria-hidden="true">{ICON.get(name, ICON["spark"])}</svg>'


def text_direction(text):
    """Direction of the text itself, from its first strong directional
    character. A Latin headline in a Hebrew (RTL) project must lay out LTR -
    per-char spans under dir=rtl render the whole string mirrored."""
    import unicodedata
    for ch in str(text):
        bidi = unicodedata.bidirectional(ch)
        if bidi == "L":
            return "ltr"
        if bidi in ("R", "AL"):
            return "rtl"
    return None


def kinetic(eid, text, cls, direction="rtl"):
    """Split into per-word spans (nowrap) containing per-char spans.

    Per-CHARACTER inline-block spans alone let a word break across lines, which
    looks like a rendering bug in any language and is unreadable in Hebrew."""
    direction = text_direction(text) or direction
    parts = []
    for tok in str(text).split(" "):
        inner = "".join(f'<span class="char">{esc(ch)}</span>' for ch in tok)
        parts.append(f'<span class="wd">{inner}</span>')
    d = f' dir="{direction}"'
    return f'<div id="{eid}" class="{cls}"{d}>{" ".join(parts)}</div>'


# ---------------------------------------------------------------- kinds
# Every builder: build(cid, d, br, an, st, en) -> (html, [gsap statements])
#   cid  card id      d   the beat's "data" dict      br  brand dict
#   an   Anim         st  start seconds               en  end seconds
# `A(i)` is accent i from the brand palette.

def _mk(br):
    return lambda i: br["accents"][i % len(br["accents"])]


# Scripts written right-to-left. Everything else is ltr. The composition's
# direction comes from plan.meta.lang and is threaded in as br["_dir"]; the
# default stays "rtl" so existing Hebrew projects are byte-identical.
RTL_LANGS = {"he", "iw", "ar", "arc", "fa", "ur", "yi", "ji", "dv", "ps",
             "ckb", "sd", "ug", "nqo", "syr", "sam", "ku-arab", "pa-arab"}


def lang_direction(lang):
    if not lang:
        return "ltr"
    base = str(lang).replace("_", "-").lower()
    return "rtl" if (base in RTL_LANGS or base.split("-")[0] in RTL_LANGS) else "ltr"


def split_canvas_h(layout, H):
    """Height of a split beat's upper canvas, in pixels. Accepts a fraction
    (<=1) or explicit pixels. Shared by the builder and verify so the two cannot
    disagree about where the canvas sits.

    The default is 44% of frame height, down from 56%: a panel should ask for
    the space it needs rather than half the screen by default, and on tight
    framing the head-clearance cap was cutting it down anyway."""
    v = (layout or {}).get("canvas")
    if v is None:
        return int(round(H * 0.44))
    v = float(v)
    px = int(round(H * v)) if v <= 1.0 else int(round(v))
    return max(160, min(H - 200, px))       # always leave room for the speaker


# ------------------------------------------------------------ head clearance
# What gets protected is the WHOLE HEAD, not the detected face box.
#
# Haar's frontalface box starts at mid-forehead, not at the hair. Measured
# across a 90 s talking-head cut at seven timestamps, the hair top sat between
# 0.097 and 0.145 of the box height ABOVE the box, median 0.122. So a rule that
# protects the box protects the eyes and mouth and leaves the forehead and
# hairline exposed - which is exactly what "the visuals overlap my face, should
# try to not hide my forehead" was about, and why a beat could measure 0%
# overlap and still look wrong.
#
# HAIR_RATIO is set to roughly double the measured worst case so it still holds
# for taller hair, a cap, or a tilted head on footage nobody has seen yet.
EYE_LINE = 0.30       # kept: some callers still reason about the eye line
HAIR_RATIO = 0.28     # hair/forehead above the detected box, as a fraction of it
JAW_RATIO = 0.08      # jaw and beard below it
HEAD_PAD_X = 0.06     # ears and hair sit outside the box horizontally
HEAD_MARGIN = 72      # breathing room above the hair - not a hairline kiss
CANVAS_MARGIN = HEAD_MARGIN     # back-compat alias; the canvas uses the same rule
CANVAS_MIN = 320      # below this a split canvas is too shallow to be useful


def head_rect(face):
    """The whole head - hair, forehead, ears, jaw - as (x, y, w, h) in canvas
    pixels, or None when no head was detected. This is the thing visuals must
    not touch; the detected face box is only its middle."""
    if not face:
        return None
    x, y, w, h = face
    top = y - h * HAIR_RATIO
    return (x - w * HEAD_PAD_X, top, w * (1 + 2 * HEAD_PAD_X),
            (y + h * (1 + JAW_RATIO)) - top)


def head_clear_y(face):
    """Lowest y a card or panel may reach and still leave the head alone,
    margin included. None when no head was detected - callers treat that as
    "no information", never as "nothing to avoid"."""
    r = head_rect(face)
    return None if r is None else int(r[1]) - HEAD_MARGIN


def face_safe_canvas_h(face, H):
    """Largest split-canvas height that clears the whole head. None when no
    head was detected (caller keeps the requested height)."""
    return head_clear_y(face)


def split_canvas_h_face(layout, H, face):
    """The requested split canvas, capped so the panel never reaches the head.
    Returns (px, cleared): cleared=False means even CANVAS_MIN cannot clear the
    head - the framing is too tight for split mode and the caller should say so
    instead of pretending the canvas is safe."""
    req = split_canvas_h(layout, H)
    safe = face_safe_canvas_h(face, H)
    if safe is None:
        return req, True
    if safe < CANVAS_MIN:
        return CANVAS_MIN, False
    return min(req, safe), True


# ------------------------------------------------------------- local plates
# The speaker is never dimmed, so a card that is bare type on live footage needs
# its own separation. Kinds below already draw an opaque surface of their own -
# a notification banner, a phone, an editor window, pill rows - and a plate
# behind those stacks two panels and reads as a mistake.
SELF_SURFACED = {"notification", "chat", "code", "diff", "checklist",
                 "chips", "image", "canvas"}


def wants_plate(kind, beat):
    """Whether this beat gets a plate behind its card. `beat.plate` overrides."""
    if beat.get("plate") is not None:
        return bool(beat["plate"])
    return kind not in SELF_SURFACED


# ------------------------------------------------------- split image payloads
CANVAS_PAD_T, CANVAS_PAD_X, CANVAS_PAD_B = 72, 64, 84
CANVAS_TEXT_H = 300     # kicker + a two-line headline, measured from the CSS
CANVAS_IMG_MIN = 180    # below this the picture is a strip, not a payload


def canvas_image_box(canvas_h, fit, direction, W):
    """Nominal pixel box for an image inside a split panel, published to
    visuals.json so a generator makes the right shape.

    The real layout is flexbox against the resolved panel, because the panel's
    height is decided per beat by the face cap - this box is the target, and
    verify measures what actually happened. `fit` picks the arrangement:
    "wide" stacks the picture under the text across the full panel, "tall" puts
    it beside the text on the end edge, where a portrait shot keeps its height."""
    inner_w = W - 2 * CANVAS_PAD_X
    inner_h = canvas_h - CANVAS_PAD_T - CANVAS_PAD_B
    if fit == "tall":
        w = int(inner_w * 0.44)
        x = CANVAS_PAD_X if direction == "rtl" else W - CANVAS_PAD_X - w
        return [x, CANVAS_PAD_T, w, max(1, inner_h)]
    y = CANVAS_PAD_T + CANVAS_TEXT_H + 22
    return [CANVAS_PAD_X, y, inner_w, max(1, canvas_h - CANVAS_PAD_B - y)]


def detect_faces(video, times, W, H):
    """Median head box per key across sampled timestamps, in canvas pixels.
    Shared by the builder (face-aware split sizing) and verify (enforcement)
    so both reason about the same head. Returns {} when cv2 is unavailable -
    callers treat that as "no information", never as "no head"."""
    try:
        import cv2
    except Exception:
        return {}
    casc = cv2.CascadeClassifier(
        os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    vw = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or W
    vh = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or H
    sx, sy = W / vw, H / vh
    out = {}
    for key, ts in times.items():
        boxes = []
        for t in ts:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
            ok, frame = cap.read()
            if not ok:
                continue
            g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            g = cv2.equalizeHist(g)
            f = casc.detectMultiScale(g, 1.15, 6, minSize=(int(vw * 0.10), int(vw * 0.10)))
            if len(f):
                x, y, w, h = max(f, key=lambda b: b[2] * b[3])
                boxes.append((x * sx, y * sy, w * sx, h * sy))
        if boxes:
            out[key] = [round(statistics.median([b[i] for b in boxes]), 1) for i in range(4)]
    cap.release()
    return out


def DIR(br):
    return (br or {}).get("_dir", "rtl")


def START(br):
    """The inline-start edge, for text-align."""
    return "right" if DIR(br) == "rtl" else "left"


def k_hero(cid, d, br, an, st, en):
    D = DIR(br)
    A = _mk(br); g = []
    note = d.get("note", "")
    latin = D == "rtl" and note.isascii() and note != ""
    b = ('<div class="blk center">'
         + (f'<div id="{cid}-ic" class="heroicon" style="color:{A(0)}">{icon(d["icon"])}</div>' if d.get("icon") else "")
         + kinetic(f"{cid}-t", d["text"], "hero" + (" sm" if d.get("small") else ""),
                   ("rtl" if d["rtl"] else "ltr") if "rtl" in d else D)
         + f'<div id="{cid}-r" class="rule big"></div>'
         + (f'<div id="{cid}-s" class="note{" latin" if latin else ""}" '
            f'dir="{"ltr" if latin else D}">{esc(note)}</div>' if note else "")
         + '</div>')
    if d.get("icon"): g.append(an.pop(S(cid, cid + "-ic"), st + 0.05, 0.55))
    g.append(an.chars(S(cid, cid + "-t"), st + (0.24 if d.get("icon") else 0.10), 0.42, 0.032))
    g.append(an.grow_w(S(cid, cid + "-r"), st + 0.52, 0.45, 300))
    if note: g.append(an.fade(S(cid, cid + "-s"), st + 0.70, 0.42))
    return b, g


def k_notification(cid, d, br, an, st, en):
    D = DIR(br)
    A = _mk(br); g = []; rows = ""
    for i, it in enumerate(d["items"]):
        col = A(3) if it.get("tone") == "ok" else A(0)
        ic = icon(it.get("icon", "check" if it.get("tone") == "ok" else "spark"))
        rows += (f'<div id="{cid}-n{i}" class="notif"><span class="nico" style="color:{col}">{ic}</span>'
                 f'<div class="ntx"><div class="napp" dir="{D}">{esc(it.get("app",""))}</div>'
                 f'<div class="nbody" dir="{D}">{esc(it["body"])}</div></div></div>')
        g.append(an.slide(S(cid, cid + f"-n{i}"), st + 0.15 + i * float(d.get("gap", 1.9)), 0.55, dy=-90))
    return f'<div class="stack">{rows}</div>', g


def k_chat(cid, d, br, an, st, en):
    D = DIR(br)
    g = []; rows = ""
    msgs = d["msgs"]
    for i, m in enumerate(msgs):
        side = "r" if m.get("side") in ("r", "me", "right") else "l"
        rows += f'<div id="{cid}-m{i}" class="bub {side}"><span dir="{D}">{esc(m["text"])}</span></div>'
    typing = f'<div id="{cid}-typ" class="bub l typing"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>' if d.get("typing", True) else ""
    b = (f'<div class="stagewrap"><div class="phone"><div class="phbar"><i></i><i></i><i></i></div>'
         f'<div class="thread">{rows}{typing}</div></div></div>')
    step = max(0.28, (en - st - 1.3) / max(1, len(msgs)))
    for i in range(len(msgs)):
        g.append(an.pop(S(cid, cid + f"-m{i}"), st + 0.25 + i * step, 0.34, 0.7))
    if typing:
        g.append(an.fade(S(cid, cid + "-typ"), st + 0.25 + len(msgs) * step, 0.3))
    return b, g


def k_code(cid, d, br, an, st, en):
    D = DIR(br)
    g = []
    rows = "".join(f'<div id="{cid}-l{i}" class="cl"><span class="gut">{i+1}</span><code>{ln}</code></div>'
                   for i, ln in enumerate(d["lines"]))
    b = (f'<div class="stagewrap"><div class="win"><div class="winbar"><i class="r"></i><i class="y"></i>'
         f'<i class="g"></i><span class="wt">{esc(d.get("title","main"))}</span></div>'
         f'<div class="code">{rows}<div id="{cid}-cur" class="ccur"></div></div></div></div>')
    step = max(0.20, min(0.45, (en - st - 1.0) / max(1, len(d["lines"]))))
    for i in range(len(d["lines"])):
        g.append(an.slide(S(cid, cid + f"-l{i}"), st + 0.35 + i * step, 0.28, dx=-40))
    g.append(an.fade(S(cid, cid + "-cur"), st + 0.30, 0.2))
    return b, g


def k_diff(cid, d, br, an, st, en):
    D = DIR(br)
    A = _mk(br); g = []
    rows = "".join(f'<div id="{cid}-d{i}" class="dl {"add" if r["op"]=="+" else "del"}">'
                   f'<span>{esc(r["op"])}</span><code>{esc(r["text"])}</code></div>'
                   for i, r in enumerate(d["rows"]))
    chips = ""
    for i, c in enumerate(d.get("chips", [])):
        chips += (f'<div id="{cid}-c{i}" class="vchip" dir="{D}">'
                  f'<span style="color:{A(i+1)}">{icon(c.get("icon","check"))}</span>{esc(c["text"])}</div>')
    b = (f'<div class="stagewrap"><div class="win"><div class="winbar"><i class="r"></i><i class="y"></i>'
         f'<i class="g"></i><span class="wt">{esc(d.get("title","review"))}</span></div>'
         f'<div class="code">{rows}</div></div>'
         + (f'<div class="vchips">{chips}</div>' if chips else "") + '</div>')
    for i in range(len(d["rows"])):
        g.append(an.slide(S(cid, cid + f"-d{i}"), st + 0.30 + i * 0.40, 0.30, dx=-40))
    for i in range(len(d.get("chips", []))):
        g.append(an.pop(S(cid, cid + f"-c{i}"), st + 0.30 + len(d["rows"]) * 0.40 + i * 0.5, 0.42))
    return b, g


def k_checklist(cid, d, br, an, st, en):
    D = DIR(br)
    A = _mk(br); g = []
    li = "".join(f'<div id="{cid}-k{i}" class="krow" dir="{D}">'
                 f'<span class="kt" style="color:{A(3)}">{icon("check")}</span>{esc(x)}</div>'
                 for i, x in enumerate(d["items"]))
    clock = ""
    if d.get("clock"):
        ticks = "".join(f'<line x1="150" y1="26" x2="150" y2="46" stroke="#8a93a8" stroke-width="5" '
                        f'transform="rotate({a} 150 150)"/>' for a in range(0, 360, 30))
        clock = (f'<svg viewBox="0 0 300 300" class="clock"><circle cx="150" cy="150" r="138" fill="#0d1220" '
                 f'stroke="{A(1)}" stroke-width="6"/>{ticks}'
                 f'<line id="{cid}-hh" x1="150" y1="150" x2="150" y2="86" stroke="#fff" stroke-width="11" stroke-linecap="round"/>'
                 f'<line id="{cid}-mh" x1="150" y1="150" x2="150" y2="52" stroke="{A(0)}" stroke-width="7" stroke-linecap="round"/>'
                 f'<circle cx="150" cy="150" r="9" fill="{A(0)}"/></svg>')
        dur = max(1.0, en - st - 0.3)
        g.append(an.spin(S(cid, cid + "-mh"), st + 0.15, dur, 0, 1440))
        g.append(an.spin(S(cid, cid + "-hh"), st + 0.15, dur, 0, 120))
    step = max(0.35, (en - st - 1.2) / max(1, len(d["items"])))
    for i in range(len(d["items"])):
        g.append(an.slide(S(cid, cid + f"-k{i}"), st + 0.5 + i * step, 0.40, dx=50))
    return f'<div class="row2">{clock}<div class="klist">{li}</div></div>', g


def k_donut(cid, d, br, an, st, en):
    D = DIR(br)
    A = _mk(br); g = []
    C = 2 * 3.141592653589793 * 120
    paths = ""; leg = ""; off = 0
    for i, sgm in enumerate(d["segments"]):
        pc = float(sgm["pct"]); col = sgm.get("color") or A(i + 1)
        L = C * pc / 100.0
        paths += (f'<circle id="{cid}-s{i}" cx="150" cy="150" r="120" fill="none" stroke="{col}" stroke-width="46" '
                  f'stroke-dasharray="{round(L,2)} {round(C-L,2)}" stroke-dashoffset="{round(-C*off/100.0,2)}" '
                  f'transform="rotate(-90 150 150)"/>')
        leg += (f'<div id="{cid}-g{i}" class="lgrow" dir="{D}"><span class="sw" style="background:{col}"></span>'
                f'<span class="lgn">{esc(sgm["label"])}</span>'
                f'<span class="lgp" style="color:{col}">{int(pc)}%</span></div>')
        g.append(f"tl.fromTo({S(cid, cid+f'-s{i}')},{{strokeDasharray:'0 {round(C,2)}'}},"
                 f"{{strokeDasharray:'{round(L,2)} {round(C-L,2)}',duration:0.55,ease:'power2.out'}},{an.q(st+0.2+i*0.30)});")
        g.append(an.slide(S(cid, cid + f"-g{i}"), st + 0.30 + i * 0.30, 0.36, dx=50))
        off += pc
    b = (f'<div class="row2"><svg viewBox="0 0 300 300" class="clock">'
         f'<circle cx="150" cy="150" r="120" fill="none" stroke="#1a2033" stroke-width="46"/>{paths}</svg>'
         f'<div class="klist">{leg}</div></div>')
    return b, g


def k_bars(cid, d, br, an, st, en):
    D = DIR(br)
    A = _mk(br); g = []; cols = ""
    for gi, grp in enumerate(d["groups"]):
        segs = ""
        for si, sgm in enumerate(grp["segments"]):
            hgt = int(float(sgm["pct"]) * float(d.get("scale", 3.1)))
            col = sgm.get("color") or A(si)
            segs += (f'<div id="{cid}-b{gi}{si}" class="bar" style="height:{hgt}px;background:{col}">'
                     f'<span class="bpc">{int(float(sgm["pct"]))}%</span></div>')
            g.append(an.grow_h(S(cid, cid + f"-b{gi}{si}"), st + 0.25 + gi * 1.35 + si * 0.30, 0.58, hgt))
        cols += (f'<div class="bcol"><div class="bstack">{segs}</div>'
                 f'<div class="bcap{" hot" if grp.get("hot") else ""}" dir="{D}">{esc(grp["cap"])}</div></div>')
    leg = "".join(f'<span class="lg" dir="{D}"><i style="background:{l.get("color") or A(i)}"></i>{esc(l["label"])}</span>'
                  for i, l in enumerate(d.get("legend", [])))
    return (f'<div class="stagewrap"><div class="bars">{cols}</div>'
            + (f'<div class="blegend">{leg}</div>' if leg else "") + '</div>'), g


def k_pipeline(cid, d, br, an, st, en):
    D = DIR(br)
    A = _mk(br); g = []; bx = ""
    n = len(d["nodes"]); h = 86; gap = 32
    for i, nm in enumerate(d["nodes"]):
        y = 18 + i * (h + gap); col = A(i + 1)
        bx += (f'<g id="{cid}-b{i}"><rect x="70" y="{y}" width="560" height="{h}" rx="20" fill="#FFFFFF" '
               f'stroke="{col}" stroke-width="4"/><text x="350" y="{y+54}" text-anchor="middle" class="ntxt" '
               f'fill="#18181B">{esc(nm)}</text></g>')
        if i < n - 1:
            bx += (f'<path id="{cid}-a{i}" d="M350 {y+h} L350 {y+h+gap}" stroke="#7c879e" stroke-width="6" '
                   f'stroke-dasharray="{gap+2}" stroke-linecap="round"/>'
                   f'<path id="{cid}-h{i}" d="M338 {y+h+gap-12} L350 {y+h+gap} L362 {y+h+gap-12}" fill="none" '
                   f'stroke="#7c879e" stroke-width="6" stroke-linecap="round" stroke-dasharray="36"/>')
    step = max(0.7, (en - st - 1.0) / max(1, n))
    for i in range(n):
        g.append(an.pop(S(cid, cid + f"-b{i}"), st + 0.25 + i * step, 0.45, 0.8))
        if i < n - 1:
            g.append(an.draw(S(cid, cid + f"-a{i}"), st + 0.25 + i * step + step * 0.45, 0.30, gap + 2))
            g.append(an.draw(S(cid, cid + f"-h{i}"), st + 0.25 + i * step + step * 0.55, 0.22, 36))
    vh = 18 + n * (h + gap)
    return f'<div class="stagewrap"><svg viewBox="0 0 700 {vh}" class="svg">{bx}</svg></div>', g


def k_contrast(cid, d, br, an, st, en):
    D = DIR(br)
    A = _mk(br); g = []
    b = (f'<div class="stack center"><div class="shiftrow">'
         f'<div id="{cid}-x" class="sbox off" dir="{D}">{esc(d["from"])}</div>'
         f'<svg viewBox="0 0 140 60" class="sarrow"><path id="{cid}-ar" d="M12 30 L112 30" stroke="{A(0)}" '
         f'stroke-width="9" stroke-linecap="round" stroke-dasharray="104"/>'
         f'<path id="{cid}-ah" d="M96 16 L114 30 L96 44" fill="none" stroke="{A(0)}" stroke-width="9" '
         f'stroke-linecap="round" stroke-dasharray="52"/></svg>'
         f'<div id="{cid}-y" class="sbox on" dir="{D}">{esc(d["to"])}</div></div></div>')
    g += [an.pop(S(cid, cid + "-x"), st + 0.12, 0.4),
          an.draw(S(cid, cid + "-ar"), st + 0.55, 0.35, 104),
          an.draw(S(cid, cid + "-ah"), st + 0.80, 0.22, 52),
          an.pop(S(cid, cid + "-y"), st + 0.95, 0.45)]
    return b, g


def k_chips(cid, d, br, an, st, en):
    D = DIR(br)
    A = _mk(br); g = []; cs = ""
    for i, c in enumerate(d["items"]):
        mark = (f'<span class="tick" style="color:{A(3)}">{icon("check")}</span>'
                if c.get("check") else f'<span class="dot2" style="background:{A(i+1)}"></span>')
        cs += f'<div id="{cid}-c{i}" class="chip" style="border-color:{A(i+1)}" dir="{D}">{mark}<span>{esc(c["text"])}</span></div>'
        g.append(an.pop(S(cid, cid + f"-c{i}"), st + 0.10 + i * 0.30, 0.45))
    return f'<div class="stack"><div class="chips" dir="{D}">{cs}</div></div>', g


def k_stat(cid, d, br, an, st, en):
    D = DIR(br)
    A = _mk(br); g = []
    b = (f'<div class="blk center">'
         + (f'<div id="{cid}-n" class="note" dir="{D}">{esc(d["note"])}</div>' if d.get("note") else "")
         + f'<div id="{cid}-num" class="bignum" style="color:{A(1)}">{int(d.get("from",0))}</div>'
         + (f'<div id="{cid}-u" class="unit" dir="{D}">{esc(d["unit"])}</div>' if d.get("unit") else "") + '</div>')
    if d.get("note"): g.append(an.fade(S(cid, cid + "-n"), st + 0.05, 0.35))
    g.append(an.count(S(cid, cid + "-num"), st + 0.30, float(d.get("dur", 1.15)), int(d.get("from", 0)), int(d["to"])))
    if d.get("unit"): g.append(an.fade(S(cid, cid + "-u"), st + 0.45, 0.40))
    return b, g


def k_follow(cid, d, br, an, st, en):
    D = DIR(br)
    A = _mk(br); g = []
    b = (f'<div class="stagewrap"><div id="{cid}-card" class="fcard">'
         + (f'<div class="fq" style="color:{A(0)}" dir="{D}">{esc(d["kicker"])}</div>' if d.get("kicker") else "")
         + kinetic(f"{cid}-t", d["headline"], "fbig", D)
         + f'<div class="frow"><div class="fav" style="background:{A(0)}">{esc(d.get("initial","•"))}</div>'
           f'<div class="fnm"><b>{esc(d.get("name",""))}</b><span dir="{D}">{esc(d.get("handle",""))}</span></div>'
           f'<div id="{cid}-btn" class="fbtn" style="background:{A(0)}" dir="{D}">{esc(d.get("cta","Follow"))}</div>'
           f'</div></div></div>')
    g += [an.pop(S(cid, cid + "-card"), st + 0.10, 0.5, 0.85),
          an.chars(S(cid, cid + "-t"), st + 0.55, 0.45, 0.022),
          an.pulse(S(cid, cid + "-btn"), st + 1.7)]
    return b, g


def k_canvas(cid, d, br, an, st, en):
    """Kicker + headline on the light split canvas, optionally over a framed
    image. Start-aligned, so it reads correctly in both directions.
    Deliberately the only canvas kind: every other kind is designed for a dark
    surface and would need a light variant, which is a design-system job rather
    than this slice."""
    D = DIR(br); g = []
    kick = (f'<div id="{cid}-k" class="ckicker" dir="{D}">{esc(d["kicker"])}</div>'
            if d.get("kicker") else "")
    head = kinetic(f"{cid}-h", d["headline"], "chead", D)
    # The panel is already there at `st` (split mode gives it no entrance), so
    # the content starts almost immediately - a longer delay leaves a blank
    # light rectangle on screen, which reads as a missing asset.
    if kick:
        g.append(an.slide(S(cid, cid + "-k"), st + 0.04, 0.26, dy=-14))
    g.append(an.chars(S(cid, cid + "-h"), st + 0.10, 0.30, 0.014))
    block = f'<div class="cblock">{kick}{head}</div>'

    img = d.get("image")
    if not img:
        return block, g

    # The image is sized by flexbox against the resolved panel, not by a fixed
    # height: the panel's height is decided per beat by the face cap, so any
    # constant here would be wrong on the next clip. object-fit:contain means
    # the picture can never spill or distort - what a too-short panel produces
    # is a squashed frame, which verify measures and fails.
    present = bool(br.get("_canvasImg"))
    inner = (f'<img id="{cid}-cimg" src="images/{cid}.png" alt=""/>' if present
             else f'<div class="cimgslot" dir="{D}">IMAGE SLOT <b>{cid}</b> &mdash; '
                  f'drop a PNG at public/images/{cid}.png<br/><br/>'
                  f'{esc(img.get("prompt", "") or d.get("headline", ""))}</div>')
    cap = (f'<div id="{cid}-ccap" class="cimgcap" dir="{D}">{esc(img["caption"])}</div>'
           if img.get("caption") else "")
    frame = (f'<div id="{cid}-cframe" class="cimgframe {img.get("frame", "soft")}">'
             f'{inner}</div>')
    # Settled within ~0.5s of the hard cut: the panel is already up, so a slow
    # reveal just reads as the image being late.
    g.append(an.pop(S(cid, cid + "-cframe"), st + 0.12, 0.32, 0.90))
    if present:
        z = float(img.get("zoom", 1.03))
        if z != 1.0:
            g.append(an.kenburns(S(cid, cid + "-cimg"), st + 0.12,
                                 max(0.5, en - st - 0.3), 1.0, z))
    if cap:
        g.append(an.slide(S(cid, cid + "-ccap"), st + 0.22, 0.24, dy=12))
    return f'<div class="cpane">{block}<div class="cmedia">{frame}{cap}</div></div>', g


def k_doodle(cid, d, br, an, st, en):
    D = DIR(br)
    """Escape hatch: the agent supplies raw inline SVG plus a list of
    {id, anim, at, dur, ...} so anything not in the library is still authorable
    without touching this file."""
    A = _mk(br); g = []
    svg = d["svg"].replace("{A0}", A(0)).replace("{A1}", A(1)).replace("{A2}", A(2)) \
                  .replace("{A3}", A(3)).replace("{A4}", A(4))
    cap = (kinetic(f"{cid}-t", d["caption"], "btitle", D) if d.get("caption") else "")
    wdt = int(d.get("width", 720))
    b = f'<div class="stack center"><div class="doodle" style="width:{wdt}px">{svg}</div>{cap}</div>'
    for a in d.get("anims", []):
        sel = S(cid, a["id"]); t = st + float(a.get("at", 0)); dd = float(a.get("dur", 0.45))
        kind = a.get("anim", "pop")
        if kind == "pop":     g.append(an.pop(sel, t, dd))
        elif kind == "fade":  g.append(an.fade(sel, t, dd))
        elif kind == "slide": g.append(an.slide(sel, t, dd, dx=a.get("dx", 0), dy=a.get("dy", 0)))
        elif kind == "draw":  g.append(an.draw(sel, t, dd, a.get("length", 300)))
        elif kind == "spin":  g.append(an.spin(sel, t, dd, a.get("from", 0), a.get("to", 360), a.get("origin", "150 150")))
        elif kind == "pulse": g.append(an.pulse(sel, t, dd, a.get("scale", 1.1), a.get("repeat", 5)))
        elif kind == "move":  g.append(an.move(sel, t, dd, a.get("from", [0, 0]), a.get("to", [0, 0]),
                                               a.get("ease", "power1.inOut")))
    if d.get("caption"):
        g.append(an.chars(S(cid, cid + "-t"), st + float(d.get("captionAt", 0.6)), 0.42, 0.03))
    return b, g


def k_image(cid, d, br, an, st, en):
    D = DIR(br)
    """Pure image beat. The <img> is filled by the image-slot resolver; if no
    file was supplied the caller substitutes the placeholder body instead."""
    g = []
    cap = (f'<div id="{cid}-cap" class="imgcap" dir="{D}">{esc(d["caption"])}</div>' if d.get("caption") else "")
    b = (f'<div class="stagewrap"><div id="{cid}-frame" class="imgframe {d.get("frame","soft")}">'
         f'<img id="{cid}-img" src="images/{cid}.png" alt=""/></div>{cap}</div>')
    g.append(an.pop(S(cid, cid + "-frame"), st + 0.10, 0.55, 0.86))
    g.append(an.kenburns(S(cid, cid + "-img"), st + 0.10, max(0.5, en - st - 0.3), 1.0, float(d.get("zoom", 1.08))))
    if d.get("caption"):
        g.append(an.slide(S(cid, cid + "-cap"), st + 0.55, 0.42, dy=26))
    return b, g


KINDS = {
    "hero": k_hero, "notification": k_notification, "chat": k_chat, "code": k_code,
    "diff": k_diff, "checklist": k_checklist, "donut": k_donut, "bars": k_bars,
    "pipeline": k_pipeline, "contrast": k_contrast, "chips": k_chips, "stat": k_stat,
    "follow": k_follow, "doodle": k_doodle, "image": k_image, "canvas": k_canvas,
}
