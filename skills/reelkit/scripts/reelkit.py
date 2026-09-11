#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reelkit - turn a raw talking-head clip into a captioned, visual-rich vertical reel.

A thin layer on top of HyperFrames: HyperFrames owns transcription, linting and
rendering; reelkit owns the transcript-driven composition, RTL-safe word-level
captions, the visual-beat card library, and the image-slot contract that lets an
image-capable agent drop real artwork into named boxes.

  reelkit.py scaffold  --project DIR --video FILE [--upscale] [--fps 30]
  reelkit.py build     --project DIR                     (plan.json -> composition)
  reelkit.py doctor

Everything is deterministic: same plan.json + same media => byte-identical HTML.
"""
import argparse, json, os, re, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cards import (KINDS, Anim, esc, kinetic, icon,      # noqa: E402
                   lang_direction as cards_lang_direction, split_canvas_h)

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
DEFAULT_BRAND = {
    "name": "default",
    "accents": ["#FF7A1A", "#4CC9F0", "#A78BFA", "#4ADE80", "#FB7185"],
    "bg": "#05060a", "text": "#ffffff",
    "font": "Heebo", "latinFont": "Inter",
    "captionSize": 76, "captionMaxWords": 3, "captionMaxChars": 15,
    "captionTop": 1500, "captionHeight": 360,
    "captionPlate": "rgba(5,6,10,.60)", "captionIdle": "#FFFFFF",
    # split-mode canvas is a LIGHT surface - the opposite mood from stage/full
    "canvasBg": "#F7F7F4", "canvasText": "#14161C", "canvasMuted": "#8A8F98",
}


def die(msg):
    print(f"reelkit: {msg}", file=sys.stderr); sys.exit(1)


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=isinstance(cmd, str), check=False,
                          capture_output=True, text=True, **kw)


def load_brand(project, plan):
    b = dict(DEFAULT_BRAND)
    ref = plan.get("brand")
    if isinstance(ref, str):
        for cand in (os.path.join(project, f"{ref}.json"),
                     os.path.join(SKILL, "assets", "brand", f"{ref}.json")):
            if os.path.exists(cand):
                b.update(json.load(open(cand, encoding="utf-8"))); break
        else:
            die(f"brand preset '{ref}' not found in project or assets/brand/")
    elif isinstance(ref, dict):
        b.update(ref)
    return b


# ------------------------------------------------------------------ captions
BREAK_PUNCT = (",", ".", "?", "!", ":", "،", "؟")


def group_words(words, max_words, max_chars, gap=0.42):
    lines, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        txt = " ".join(x["text"] for x in cur)
        brk = nxt is None
        if nxt is not None:
            if nxt["start"] - w["end"] > gap: brk = True
            if len(cur) >= max_words: brk = True
            if len(txt) >= max_chars and len(cur) >= 2: brk = True
            if w["text"].endswith(BREAK_PUNCT) and len(cur) >= 2: brk = True
        if brk:
            lines.append(cur); cur = []
    if cur: lines.append(cur)
    return lines


def caption_clips(words, br, dur, an):
    lines = group_words(words, br["captionMaxWords"], br["captionMaxChars"])
    out = []
    for i, ln in enumerate(lines):
        s = ln[0]["start"] - 0.10
        e = ln[-1]["end"] + 0.45
        if i + 1 < len(lines):
            e = min(e, lines[i + 1][0]["start"] - 0.10)
        s = max(0.0, an.q(s)); e = an.q(min(e, dur))
        if e - s < 0.20:
            e = an.q(min(s + 0.20, dur))
        out.append({"id": f"cap-{i:02d}", "start": s, "end": e, "words": ln})
    return out


# ------------------------------------------------------------------ theme css
def theme_css(br):
    A = br["accents"]
    return f"""
:root{{--bg:{br['bg']};--text:{br['text']};--accent-0:{A[0]};--accent-1:{A[1]};
--accent-2:{A[2]};--accent-3:{A[3]};--accent-4:{A[4]};}}
*{{box-sizing:border-box;}}
html,body{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:{br['bg']};
font-family:'{br['font']}','{br['latinFont']}',ui-sans-serif,system-ui,sans-serif;}}
#stage{{position:relative;width:100%;height:100%;overflow:hidden;}}
.video-wrapper{{position:absolute;left:0;top:0;width:100%;height:100%;overflow:hidden;}}
.video-wrapper video{{width:100%;height:100%;object-fit:cover;}}
.bottomveil{{position:absolute;left:0;right:0;bottom:0;height:430px;
background:linear-gradient(180deg,rgba(5,6,10,0) 0%,rgba(5,6,10,.30) 45%,rgba(5,6,10,.58) 100%);}}
.card-host{{position:absolute;pointer-events:none;overflow:hidden;}}
.card-host .card{{position:relative;width:100%;height:100%;overflow:hidden;}}
.card-host .char{{display:inline-block;visibility:visible;}}
.cap-host{{overflow:visible;}}
.cap-host .cw{{display:inline-block;}}
.capline{{display:flex;flex-wrap:wrap;gap:8px 28px;justify-content:center;align-items:center;
width:920px;margin:0 auto;padding:22px 30px;border-radius:28px;background:{br['captionPlate']};
font-family:'{br['font']}',sans-serif;font-weight:900;font-size:{br['captionSize']}px;line-height:1.20;
text-align:center;color:{br['captionIdle']};
text-shadow:0 4px 22px rgba(0,0,0,.9),0 2px 6px rgba(0,0,0,.95);}}
""".strip()


def card_css(cid, mode, br, layout=None, canvas_h=0):
    D = br.get("_dir", "rtl"); START = "right" if D == "rtl" else "left"
    P = f'.card[data-card-id="{cid}"]'
    A = br["accents"]
    top = (layout or {}).get("top")
    # `full` sits at 220, between `top` (140) and `stage` (300): the card is
    # the focus but the speaker stays visible by default - 140 crowds the top
    # edge and leaves a dead band below, while 300 pushes a focus card too low.
    pad = (f"{int(top)}px 0 0 0" if top is not None
           else ("300px 0 0 0" if mode == "stage"
                 else ("220px 0 0 0" if mode == "full" else "140px 0 0 0")))
    if mode == "split":
        pad = "0"      # the canvas owns the upper band and carries its own surface
    # Emitted only for split beats: every other card would carry 15 lines of dead
    # rules, and existing projects must still rebuild byte-identically.
    canvas_css = f"""
{P} .canvas {{ position:absolute;left:0;top:0;width:100%;height:{canvas_h}px;
 background:{br.get('canvasBg', '#F7F7F4')};border-bottom:4px solid {A[0]};
 display:flex;flex-direction:column;align-items:stretch;justify-content:center;
 gap:22px;padding:72px 64px 84px;overflow:hidden; }}
{P} .cblock {{ display:flex;flex-direction:column;gap:18px;text-align:{START};
 direction:{D}; }}
{P} .ckicker {{ font-size:34px;font-weight:800;letter-spacing:.16em;
 text-transform:uppercase;color:{br.get('canvasMuted', '#8A8F98')}; }}
{P} .chead {{ font-size:96px;font-weight:900;line-height:1.10;
 color:{br.get('canvasText', '#14161C')};letter-spacing:-.015em; }}
{P} .cpill {{ position:absolute;{START}:64px;bottom:34px;
 font-family:'{br['latinFont']}',sans-serif;font-size:28px;font-weight:900;
 letter-spacing:.10em;color:{br.get('canvasText', '#14161C')};
 background:rgba(0,0,0,.06);border:2px solid rgba(0,0,0,.16);
 border-radius:999px;padding:10px 26px; }}""" if mode == "split" else ""
    return f"""
{P} .root {{ width:100%;height:100%;position:relative;display:flex;align-items:flex-start;
 justify-content:center;padding:{pad};font-family:'{br['font']}','{br['latinFont']}',sans-serif;
 color:{br['text']};background:transparent; }}
{P} .scrim {{ position:absolute;inset:0;background:linear-gradient(180deg,rgba(5,6,10,.58) 0%,
 rgba(5,6,10,.30) 26%,rgba(5,6,10,0) 48%,rgba(5,6,10,.10) 74%,rgba(5,6,10,.30) 100%); }}
{P} .scrim.stage {{ background:linear-gradient(180deg,rgba(5,6,10,.82) 0%,rgba(5,6,10,.74) 46%,
 rgba(5,6,10,.46) 68%,rgba(5,6,10,.34) 100%); }}
{P} .scrim.full {{ background:linear-gradient(180deg,rgba(5,6,10,.68) 0%,
 rgba(5,6,10,.40) 30%,rgba(5,6,10,.14) 52%,rgba(5,6,10,.24) 76%,rgba(5,6,10,.48) 100%); }}
{P} .scrim.full.takeover {{ background:rgba(5,6,10,.90); }}
{P} .stack {{ position:relative;width:980px;display:flex;flex-direction:column;gap:20px;
 padding:0 26px;direction:{D};text-align:{START}; }}
{P} .stack.center {{ align-items:center;text-align:center; }}
{P} .blk {{ position:relative;width:960px;padding:0 24px;direction:{D};text-align:{START}; }}
{P} .blk.center {{ display:flex;flex-direction:column;align-items:center;text-align:center; }}
{P} .stagewrap {{ position:relative;width:1000px;padding:0 20px;display:flex;flex-direction:column;
 align-items:center;gap:26px; }}
{P} .row2 {{ position:relative;width:990px;padding:0 24px;display:flex;align-items:center;
 gap:38px;direction:{D}; }}
{P} .ico {{ width:100%;height:100%;display:block; }}
{P} .char {{ display:inline-block; }}
{P} .wd {{ display:inline-block;white-space:nowrap; }}
{P} .hero {{ font-size:172px;font-weight:900;line-height:1.0;letter-spacing:-.03em;
 text-shadow:0 10px 48px rgba(0,0,0,.6); }}
{P} .hero.sm {{ font-size:132px; }}
{P} .heroicon {{ width:150px;height:150px;margin-bottom:6px; }}
{P} .btitle {{ font-size:92px;font-weight:900;line-height:1.06;text-shadow:0 8px 34px rgba(0,0,0,.7); }}
{P} .rule {{ height:8px;width:0;background:{A[0]};border-radius:6px; }}
{P} .rule.big {{ height:10px;margin:26px 0 22px; }}
{P} .note {{ font-size:38px;font-weight:600;opacity:.80; }}
{P} .note.latin {{ font-family:'{br['latinFont']}',sans-serif;font-size:26px;font-weight:700;
 letter-spacing:.34em;opacity:.62; }}
{P} .notif {{ display:flex;gap:20px;align-items:center;background:rgba(20,22,32,.94);
 border:2px solid rgba(255,255,255,.13);border-radius:28px;padding:24px 28px;
 box-shadow:0 24px 60px rgba(0,0,0,.6); }}
{P} .nico {{ width:56px;height:56px;flex:0 0 auto; }}
{P} .napp {{ font-size:26px;font-weight:700;opacity:.6; }}
{P} .nbody {{ font-size:46px;font-weight:900;line-height:1.15;margin-top:4px; }}
{P} .phone {{ width:640px;background:#0c1018;border:3px solid #2a3145;border-radius:38px;
 overflow:hidden;box-shadow:0 26px 70px rgba(0,0,0,.65); }}
{P} .phbar {{ display:flex;gap:10px;padding:18px 22px;background:rgba(255,255,255,.05); }}
{P} .phbar i {{ width:13px;height:13px;border-radius:50%;background:rgba(255,255,255,.25); }}
{P} .thread {{ display:flex;flex-direction:column;gap:16px;padding:26px 24px 30px; }}
{P} .bub {{ border-radius:22px;padding:18px 24px;max-width:78%;font-size:34px;font-weight:800;line-height:1.25; }}
{P} .bub.l {{ align-self:flex-start;background:#1b2438;border-bottom-left-radius:8px; }}
{P} .bub.r {{ align-self:flex-end;background:{A[0]};color:#10121a;border-bottom-right-radius:8px; }}
{P} .typing {{ display:flex;flex-direction:row;gap:10px;max-width:none;padding:20px 24px; }}
{P} .dot {{ width:14px;height:14px;border-radius:50%;background:rgba(255,255,255,.6);display:block; }}
{P} .win {{ width:940px;background:#0b0f18;border:2px solid #232b3d;border-radius:24px;
 overflow:hidden;box-shadow:0 26px 70px rgba(0,0,0,.6); }}
{P} .winbar {{ display:flex;align-items:center;gap:11px;padding:18px 22px;background:#141a26; }}
{P} .winbar i {{ width:15px;height:15px;border-radius:50%; }}
{P} .winbar .r {{ background:#ff5f57; }} {P} .winbar .y {{ background:#febc2e; }}
{P} .winbar .g {{ background:#28c840; }}
{P} .wt {{ margin-inline-start:14px;font:700 24px '{br['latinFont']}',sans-serif;color:#8b95ab; }}
{P} .code {{ padding:22px 24px;font:700 30px '{br['latinFont']}',ui-monospace,monospace;
 line-height:1.62;position:relative; }}
{P} .cl {{ display:flex;gap:18px;white-space:nowrap; }}
{P} .gut {{ color:#4a5468;width:32px;text-align:right;flex:0 0 auto; }}
{P} .code .kw {{ color:{A[2]}; }} {P} .code .fn {{ color:{A[1]}; }} {P} .code .st {{ color:{A[3]}; }}
{P} .ccur {{ width:16px;height:32px;background:{A[0]};display:inline-block;margin-inline-start:52px; }}
{P} .dl {{ display:flex;gap:16px;white-space:nowrap;border-radius:8px;padding:4px 10px;margin:3px 0; }}
{P} .dl span {{ width:22px;flex:0 0 auto;font-weight:900; }}
{P} .dl.del {{ background:rgba(251,113,133,.16);color:#ffc4cd; }}
{P} .dl.add {{ background:rgba(74,222,128,.15);color:#c7f5d8; }}
{P} .vchips {{ display:flex;gap:18px;justify-content:center;flex-wrap:wrap;direction:{D}; }}
{P} .vchip {{ display:flex;align-items:center;gap:14px;font-size:42px;font-weight:900;
 background:rgba(16,18,28,.9);border:2px solid rgba(255,255,255,.16);border-radius:999px;padding:16px 30px; }}
{P} .vchip span {{ width:38px;height:38px;flex:0 0 auto;display:block; }}
{P} .chips {{ display:flex;flex-wrap:wrap;gap:18px;justify-content:flex-start; }}
{P} .chip {{ display:flex;align-items:center;gap:14px;font-size:46px;font-weight:800;padding:20px 34px;
 border-radius:999px;background:rgba(18,18,26,.80);border:2px solid {A[0]};
 box-shadow:0 10px 34px rgba(0,0,0,.45); }}
{P} .tick {{ width:38px;height:38px;flex:0 0 auto;display:block; }}
{P} .dot2 {{ width:16px;height:16px;border-radius:50%;flex:0 0 auto; }}
{P} .clock {{ width:330px;height:330px;flex:0 0 auto; }}
{P} .klist {{ display:flex;flex-direction:column;gap:16px;flex:1; }}
{P} .krow {{ display:flex;align-items:center;gap:16px;font-size:42px;font-weight:800;
 background:rgba(14,16,24,.82);border-radius:16px;padding:16px 22px; }}
{P} .kt {{ width:36px;height:36px;flex:0 0 auto; }}
{P} .lgrow {{ display:flex;align-items:center;gap:16px;font-size:36px;font-weight:800;
 background:rgba(14,16,24,.82);border-radius:16px;padding:14px 20px; }}
{P} .sw {{ width:26px;height:26px;border-radius:7px;flex:0 0 auto; }}
{P} .lgn {{ flex:1; }} {P} .lgp {{ font-family:'{br['latinFont']}',sans-serif;font-weight:900; }}
{P} .svg {{ width:100%;height:auto;display:block;overflow:visible; }}
{P} .ntxt {{ font:900 30px '{br['font']}',sans-serif; }}
{P} .bars {{ display:flex;gap:90px;align-items:flex-end;justify-content:center;height:420px; }}
{P} .bcol {{ display:flex;flex-direction:column;align-items:center;gap:18px; }}
{P} .bstack {{ display:flex;flex-direction:column-reverse;width:190px;border-radius:16px;overflow:hidden; }}
{P} .bar {{ width:100%;display:flex;align-items:center;justify-content:center;overflow:hidden; }}
{P} .bpc {{ font:900 34px '{br['latinFont']}',sans-serif;color:#0d1017; }}
{P} .bcap {{ font-size:44px;font-weight:900;opacity:.85; }}
{P} .bcap.hot {{ color:{A[0]};opacity:1; }}
{P} .blegend {{ display:flex;flex-direction:column;gap:14px;align-items:center; }}
{P} .lg {{ display:flex;align-items:center;gap:14px;font-size:38px;font-weight:800;opacity:.95; }}
{P} .lg i {{ width:22px;height:22px;border-radius:6px;display:block; }}
{P} .shiftrow {{ display:flex;align-items:center;gap:26px;direction:{D}; }}
{P} .sbox {{ font-size:60px;font-weight:900;padding:22px 42px;border-radius:24px; }}
{P} .sbox.off {{ background:rgba(20,22,32,.9);border:3px solid {A[4]};color:#ffb3bd;
 text-decoration:line-through;text-decoration-thickness:6px; }}
{P} .sbox.on {{ background:{A[0]};color:#10121a; }}
{P} .sarrow {{ width:150px;height:64px;flex:0 0 auto;transform:scaleX(-1); }}
{P} .bignum {{ font-family:'{br['latinFont']}',sans-serif;font-size:280px;font-weight:900;line-height:1;
 text-shadow:0 12px 50px rgba(0,0,0,.6); }}
{P} .unit {{ font-size:56px;font-weight:800;opacity:.9; }}
{P} .fcard {{ width:940px;background:rgba(12,14,22,.95);border:2px solid rgba(255,255,255,.14);
 border-radius:36px;padding:44px 40px;box-shadow:0 30px 80px rgba(0,0,0,.7); }}
{P} .fq {{ font-size:30px;font-weight:800;letter-spacing:.02em;margin-bottom:14px; }}
{P} .fbig {{ font-size:74px;font-weight:900;line-height:1.12;margin-bottom:34px; }}
{P} .frow {{ display:flex;align-items:center;gap:20px;direction:{D}; }}
{P} .fav {{ width:86px;height:86px;border-radius:50%;color:#10121a;font-size:44px;font-weight:900;
 display:flex;align-items:center;justify-content:center;flex:0 0 auto; }}
{P} .fnm {{ flex:1;display:flex;flex-direction:column;text-align:{START}; }}
{P} .fnm b {{ font:900 38px '{br['latinFont']}',sans-serif; }}
{P} .fnm span {{ font-size:28px;opacity:.66;font-weight:700; }}
{P} .fbtn {{ color:#10121a;font-size:38px;font-weight:900;padding:16px 40px;border-radius:999px; }}
{P} .doodle {{ width:720px;max-width:100%; }}
{P} .doodle svg {{ width:100%;height:auto;display:block;overflow:visible; }}
{P} .imgframe {{ width:940px;border-radius:32px;overflow:hidden;position:relative;
 box-shadow:0 30px 80px rgba(0,0,0,.7); }}
{P} .imgframe.soft {{ border:2px solid rgba(255,255,255,.14); }}
{P} .imgframe.bare {{ border:0;box-shadow:none;background:transparent; }}
{P} .imgframe img {{ width:100%;height:auto;display:block; }}
{P} .imgcap {{ font-size:44px;font-weight:800;text-align:center;opacity:.92;
 text-shadow:0 4px 20px rgba(0,0,0,.8); }}
{P} .imgbehind {{ position:absolute;inset:0;z-index:0;opacity:.55; }}
{P} .imgbehind img {{ width:100%;height:100%;object-fit:cover;display:block; }}{canvas_css}
{P} .missing {{ width:900px;border:3px dashed {A[4]};border-radius:28px;padding:40px;
 background:rgba(20,10,14,.75);color:#ffd7dd;font-size:34px;font-weight:800;line-height:1.35;direction:{D}; }}
""".strip()


# ------------------------------------------------------------------ build
def build(project):
    plan_path = os.path.join(project, "plan.json")
    if not os.path.exists(plan_path):
        die("no plan.json in project - see references/plan-schema.md")
    plan = json.load(open(plan_path, encoding="utf-8"))
    meta = plan.get("meta", {})
    fps = int(meta.get("fps", 30)); W = int(meta.get("width", 1080)); H = int(meta.get("height", 1920))
    an = Anim(fps)
    br = load_brand(project, plan)
    # Composition direction follows the language. Everything that lays text out
    # as positioned boxes (kinetic chars, caption flex children) must follow it:
    # bidi can reorder a text run, but it cannot reorder boxes we positioned.
    br["_dir"] = meta.get("dir") or cards_lang_direction(meta.get("lang"))
    if br["_dir"] not in ("rtl", "ltr"):
        die(f"meta.dir must be 'rtl' or 'ltr', got {br['_dir']!r}")
    DIRC = br["_dir"]; STARTC = "right" if DIRC == "rtl" else "left"
    pub = os.path.join(project, "public")
    os.makedirs(os.path.join(pub, "cards"), exist_ok=True)
    os.makedirs(os.path.join(pub, "images"), exist_ok=True)

    vid = os.path.join(pub, "input-video.mp4")
    if not os.path.exists(vid):
        die("public/input-video.mp4 missing - run `reelkit.py scaffold` first")
    dur = float(meta.get("duration") or probe_duration(vid))
    dur = round(dur - 1.0 / fps, 4) if meta.get("trimTail", True) else dur

    words = []
    tpath = os.path.join(project, "transcript.json")
    if os.path.exists(tpath):
        words = json.load(open(tpath, encoding="utf-8"))
        if isinstance(words, dict):
            words = words.get("words") or words.get("segments") or []

    hosts, tls, visuals, missing = [], [], [], []

    # ---- video framing: base scale + optional punch-ins -------------------
    fr = plan.get("framing", {})
    base = float(fr.get("scale", 1.0))
    origin = fr.get("origin", "50% 30%").replace("%", "\\u0025")
    tls.append(f"tl.set('#video-wrap',{{transformOrigin:'{origin}',scale:{base}}},0);")
    for p in fr.get("punches", []):
        tls.append(f"tl.fromTo('#video-wrap',{{scale:{round(base*float(p['from']),4)}}},"
                   f"{{scale:{round(base*float(p['to']),4)},duration:{p.get('dur',0.9)},"
                   f"ease:'power2.inOut'}},{an.q(p['at'])});")

    # ---- static checks before anything is written -------------------------
    warn = []
    srt = sorted(plan["beats"], key=lambda b: float(b["start"]))
    for i in range(len(srt) - 1):
        if float(srt[i]["end"]) > float(srt[i + 1]["start"]) + 1e-6:
            warn.append(f"beats {srt[i]['id']} and {srt[i+1]['id']} overlap "
                        f"({srt[i]['end']} > {srt[i+1]['start']}) - both will render")
    for b in plan["beats"]:
        if float(b["start"]) >= dur:
            warn.append(f"beat {b['id']} starts at {b['start']}s, past the media ({dur}s) - it will never show")

    # Counter pills read "i / n" across the split beats only.
    _splits = [b["id"] for b in plan["beats"] if b.get("mode") == "split"]
    split_index = {bid: (i + 1, len(_splits)) for i, bid in enumerate(_splits)}

    # ---- beats ------------------------------------------------------------
    for beat in plan["beats"]:
        cid = beat["id"]; st = an.q(beat["start"]); en = an.q(min(beat["end"], dur))
        if en <= st:
            die(f"beat {cid}: end ({en}) must be after start ({st})")
        kind = beat["kind"]; mode = beat.get("mode", "top")
        if kind not in KINDS:
            die(f"beat {cid}: unknown kind '{kind}'. Known: {', '.join(sorted(KINDS))}")

        img = beat.get("image")
        img_file = os.path.join(pub, "images", f"{cid}.png")
        has_img = bool(img) and os.path.exists(img_file)
        if img:
            box = img.get("box") or ([70, 300, 940, 700] if mode == "stage"
                                     else ([70, 220, 940, 480] if mode == "full"
                                           else [70, 140, 940, 480]))
            visuals.append({
                "id": cid, "start": st, "end": en, "kind": kind,
                "file": f"public/images/{cid}.png", "present": has_img,
                "box": {"x": box[0], "y": box[1], "w": box[2], "h": box[3]},
                "aspect": round(box[2] / box[3], 3),
                "alpha": bool(img.get("alpha", False)),
                "mode": img.get("mode", "replace"),
                "prompt": img.get("prompt", ""),
                "intent": beat.get("intent", ""),
            })
            if not has_img:
                missing.append(cid)

        if has_img and img.get("mode", "replace") == "replace":
            body, g = KINDS["image"](cid, {
                "caption": img.get("caption") or beat.get("data", {}).get("caption"),
                "frame": "bare" if img.get("alpha") else img.get("frame", "soft"),
                "zoom": img.get("zoom", 1.08)}, br, an, st, en)
        elif kind == "image" and not has_img:
            # honest placeholder: renders, lints, and screams in the preview
            p = esc((img or {}).get("prompt", "") or beat.get("intent", ""))
            body = (f'<div class="stagewrap"><div class="missing">IMAGE SLOT <b>{cid}</b> '
                    f'&mdash; drop a PNG at public/images/{cid}.png<br/><br/>{p}</div></div>')
            g = [an.fade(f"'.card[data-card-id=\"{cid}\"] .missing'", st + 0.1, 0.3)]
        else:
            body, g = KINDS[kind](cid, beat.get("data", {}), br, an, st, en)
            if has_img:   # mode == "behind"
                body = (f'<div class="imgbehind" id="{cid}-bg"><img src="images/{cid}.png" alt=""/></div>'
                        + body)
                g.append(an.fade(f"'.card[data-card-id=\"{cid}\"] #{cid}-bg'", st + 0.05, 0.5))

        takeover = mode == "full" and beat.get("takeover")
        canvas_h = split_canvas_h(beat.get("layout"), H) if mode == "split" else 0
        if mode == "split":
            # No scrim at all: the speaker below the canvas plays undimmed. The
            # canvas is a LIGHT surface with dark text - the opposite mood from
            # stage/full, which dim the frame.
            pill = ""
            if beat.get("counter", True) and cid in split_index:
                i, n = split_index[cid]
                label = beat.get("counterLabel") or f"{i} / {n}"
                pill = f'<div class="cpill" id="{cid}-pill">{esc(label)}</div>'
            body = f'<div class="canvas" id="{cid}-canvas">{body}{pill}</div>'
            # The panel itself gets NO entrance tween. Fading it in would leave
            # the upper band showing bare footage for the length of the fade -
            # between two adjacent splits that reads as a blink, not a cut. The
            # surface is simply there, like a slide advancing; only the content
            # on it staggers in (see k_canvas).
            if pill:
                g.append(an.pop(f"'.card[data-card-id=\"{cid}\"] #{cid}-pill'", st + 0.18, 0.28, 0.75))
            scrim = ""
        else:
            scrim = ('<div class="scrim full%s"></div>' % (" takeover" if takeover else "") if mode == "full"
                     else '<div class="scrim stage"></div>' if mode == "stage"
                     else '<div class="scrim"></div>')
        frag = (f'<div class="card" data-card-id="{cid}">\n<style>\n'
                f'{card_css(cid, mode, br, beat.get("layout"), canvas_h)}\n</style>\n'
                f'<div class="root">{scrim}{body}</div>\n</div>')
        open(os.path.join(pub, "cards", f"{cid}.html"), "w", encoding="utf-8").write(frag)

        first_at = None
        for st_ in g:
            m = re.search(r",([0-9.]+)\);\s*$", st_)
            if m:
                v = float(m.group(1))
                first_at = v if first_at is None else min(first_at, v)
        if first_at is not None and first_at - st > 0.8:
            warn.append(f"beat {cid} renders {round(first_at - st, 2)}s before its first animation - "
                        f"it will sit visibly empty")

        hosts.append(f'<div class="card-host clip" id="card-{cid}" data-card-id="{cid}" data-composition-id="{cid}" '
                     f'data-start="{st:.4f}" data-duration="{en-st:.4f}" data-track-index="2" '
                     f'style="left:0;top:0;width:{W}px;height:{H}px;visibility:hidden;opacity:0;">\n{frag}\n</div>')
        sel = f"'.card-host[data-card-id=\"{cid}\"]'"
        tls.append(f"tl.set({sel},{{visibility:'visible'}},{st});")
        if mode == "split":
            # Hard cut between canvas layouts - a crossfade would show two
            # canvases stacked while one fades out.
            tls.append(f"tl.set({sel},{{opacity:1}},{st});")
            tls += g
            # Instant, not a tween: still a hard cut, but the finished host is
            # transparent as well as hidden. Leaving opacity at 1 makes every
            # past canvas a stacked text block to any static analysis (and to
            # anything that honours opacity but not visibility).
            tls.append(f"tl.set({sel},{{opacity:0}},{en});")
        else:
            tls.append(f"tl.fromTo({sel},{{opacity:0}},{{opacity:1,duration:0.30,ease:'power2.out'}},{st});")
            tls += g
            tls.append(f"tl.to({sel},{{opacity:0,duration:0.26,ease:'power2.in'}},{an.q(en-0.26)});")
        tls.append(f"tl.set({sel},{{visibility:'hidden'}},{en});")

    # ---- captions ---------------------------------------------------------
    caps = []
    if plan.get("captions", {}).get("enabled", True) and words:
        caps = caption_clips(words, br, dur, an)
        hi = plan.get("captions", {}).get("highlight") or br["accents"][0]
        top = int(plan.get("captions", {}).get("top", br["captionTop"]))
        hgt = int(plan.get("captions", {}).get("height", br["captionHeight"]))
        for cp in caps:
            ws = "".join(f'<span class="cw" id="{cp["id"]}-w{j}">{esc(w["text"])}</span>'
                         for j, w in enumerate(cp["words"]))
            frag = (f'<div class="card" data-card-id="{cp["id"]}">\n<style>\n'
                    f'.card[data-card-id="{cp["id"]}"] .root {{ width:100%;height:100%;display:flex;'
                    f'align-items:center;justify-content:center; }}\n</style>\n'
                    f'<div class="root"><div class="capline" dir="{DIRC}">{ws}</div></div>\n</div>')
            s, e = cp["start"], cp["end"]
            hosts.append(f'<div class="card-host clip cap-host" id="caption-{cp["id"]}" data-card-id="{cp["id"]}" '
                         f'data-composition-id="{cp["id"]}" data-start="{s:.4f}" data-duration="{e-s:.4f}" '
                         f'data-track-index="3" style="left:0;top:{top}px;width:{W}px;height:{hgt}px;'
                         f'visibility:hidden;opacity:0;">\n{frag}\n</div>')
            sel = f"'.card-host[data-card-id=\"{cp['id']}\"]'"
            tls.append(f"tl.set({sel},{{visibility:'visible'}},{s});")
            tls.append(f"tl.fromTo({sel},{{opacity:0,y:14}},{{opacity:1,y:0,duration:0.16,ease:'power2.out'}},{s});")
            for j, w in enumerate(cp["words"]):
                wsel = f"'.card[data-card-id=\"{cp['id']}\"] #{cp['id']}-w{j}'"
                t0 = an.q(max(s, w["start"]))
                t1 = an.q(min(e - 0.02, max(w["end"], t0 + 0.14)))
                if t1 <= t0 + 0.05:
                    t1 = an.q(t0 + 0.10)
                on = round(min(0.09, max(0.0333, t1 - t0 - 0.0001)), 4)
                off = round(min(0.13, max(0.0666, e - 0.02 - t1)), 4)
                # Baseline + immediateRender:false. GSAP applies a fromTo's
                # from-values at AUTHORING time, so with two fromTo calls per word
                # the second one's from-state (highlighted) silently became the
                # word's resting state - every word rendered pre-highlighted before
                # it was spoken, and the karaoke only read on the way out.
                tls.append(f"tl.set({wsel},{{color:'{br['captionIdle']}',opacity:.52,scale:1}},{s});")
                tls.append(f"tl.fromTo({wsel},{{color:'{br['captionIdle']}',opacity:.52,scale:1}},"
                           f"{{color:'{hi}',opacity:1,scale:1.06,duration:{on},ease:'power2.out',"
                           f"immediateRender:false}},{t0});")
                tls.append(f"tl.fromTo({wsel},{{color:'{hi}',opacity:1,scale:1.06}},"
                           f"{{color:'{br['captionIdle']}',opacity:.94,scale:1,duration:{off},"
                           f"ease:'power2.in',immediateRender:false}},{t1});")
            # A very short caption line would otherwise start fading out before its
            # fade-in finished - two tweens on one property at once.
            out_at = an.q(max(s + 0.16, e - 0.12))
            out_dur = round(max(0.04, e - out_at), 4)
            tls.append(f"tl.to({sel},{{opacity:0,duration:{out_dur},ease:'power2.in'}},{out_at});")
            tls.append(f"tl.set({sel},{{visibility:'hidden'}},{e});")

    sfx_tags, sfx_names = resolve_sfx(plan, pub, dur, an)

    # ---- document ---------------------------------------------------------
    # Emit @font-face only for files that actually exist, whatever their script
    # suffix - hardcoding "-hebrew" would break every other language.
    fdir = os.path.join(pub, "fonts")
    have = sorted(os.listdir(fdir)) if os.path.isdir(fdir) else []
    fonts = ""
    seen = set()
    for fam in (br["font"], br["latinFont"]):
        for f in have:
            m = re.match(rf"^{re.escape(fam)}-(\d{{3}})-[A-Za-z0-9]+\.woff2$", f)
            if not m:
                continue
            key = (fam, m.group(1))
            if key in seen:
                continue
            seen.add(key)
            fonts += (f"@font-face{{font-family:'{fam}';src:url('fonts/{f}') format('woff2');"
                      f"font-weight:{m.group(1)};font-display:block;}}")
    if not fonts:
        die(f"no @font-face candidates in {fdir} for '{br['font']}'/'{br['latinFont']}' - "
            f"expected files named <Family>-<weight>-<subset>.woff2")

    # NOTE: lang goes on <html>, direction NEVER does - dir="rtl" on <html>
    # previews fine and renders a fully black video. See references/rtl-and-fonts.md
    doc = f"""<!doctype html>
<html lang="{meta.get('lang','en')}">
<head><meta charset="utf-8"/>
<style>
{fonts}
{theme_css(br)}
</style></head>
<body>
<div id="stage" data-composition-id="reelkit" data-start="0"
 data-duration="{dur}" data-fps="{fps}" data-width="{W}" data-height="{H}">
<div class="video-wrapper" id="video-wrap">
<video id="bg-video" src="input-video.mp4" muted playsinline data-start="0"
 data-duration="{dur}" data-track-index="1"></video></div>
<audio id="source-audio" src="input-video.mp4" data-start="0" data-duration="{dur}"
 data-track-index="10" data-volume="{plan.get('audio',{}).get('sourceVolume',1)}"></audio>
{"".join(sfx_tags)}
<div class="bottomveil"></div>
{"".join(hosts)}
<script src="vendor/gsap.min.js"></script>
<script>
(function(){{
var tl = window.gsap.timeline({{paused:true}});
{chr(10).join(tls)}
window.__timelines = window.__timelines || {{}};
window.__timelines["reelkit"] = tl;
}})();
</script>
</div></body></html>"""
    open(os.path.join(pub, "index.html"), "w", encoding="utf-8").write(doc)

    # ---- side artefacts ---------------------------------------------------
    json.dump({"version": 1, "project": os.path.basename(os.path.abspath(project)),
               "canvas": {"w": W, "h": H, "fps": fps, "duration": dur},
               "slots": visuals},
              open(os.path.join(project, "visuals.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    beat_rows = ["| # | time | beat | kind | image slot |", "|---|------|------|------|------------|"]
    for i, b in enumerate(plan["beats"], 1):
        slot = "-" 
        for v in visuals:
            if v["id"] == b["id"]:
                slot = "present" if v["present"] else "MISSING"
        beat_rows.append(f"| {i} | {b['start']:.2f}-{b['end']:.2f} | {b.get('intent','')} | {b['kind']} | {slot} |")
    hits = sorted({round(float(b["start"]), 2) for b in plan["beats"]})
    beats_md = ("# Beat sheet\n\n" + "\n".join(beat_rows) +
                "\n\n## Card-entry hit points (seconds)\n\nDrop a music bed and land accents on:\n\n" +
                ", ".join(f"{h:.2f}" for h in hits) + "\n")
    open(os.path.join(project, "BEATS.md"), "w", encoding="utf-8").write(beats_md)

    for w in warn:
        print(f"reelkit: ! {w}")
    print(f"reelkit: {len(plan['beats'])} beats, {len(caps)} caption lines, "
          f"{len(tls)} timeline statements, duration {dur}s")
    if visuals:
        print(f"reelkit: {len(visuals)} image slot(s); "
              f"{len(visuals)-len(missing)} present, {len(missing)} missing")
    for m in missing:
        print(f"  ! missing image: public/images/{m}.png")
    print("reelkit: wrote public/index.html, visuals.json, BEATS.md")
    return 0




# ------------------------------------------------------------------ sample project
SAMPLE_LINES = [
    (0.80, 3.40, "One file plans the whole reel."),
    (3.80, 6.40, "Captions and cards build themselves."),
    (6.80, 9.20, "Verification measures every card."),
    (9.60, 11.40, "Then render once, with confidence."),
]


def sample_words():
    """Canned transcript for the synthetic clip: the sine-tone audio has no
    speech, so there is nothing to transcribe. Words are spaced evenly across
    each line, which is all the caption grouper needs."""
    words = []
    for s, e, line in SAMPLE_LINES:
        ws = line.split()
        step = (e - s) / len(ws)
        for i, w in enumerate(ws):
            words.append({"text": w, "start": round(s + i * step, 3),
                          "end": round(s + (i + 1) * step - 0.06, 3)})
    return words


def sample_plan(fps, width, height):
    return {
        "meta": {"title": "reelkit sample - synthetic clip", "lang": "en",
                 "fps": fps, "width": width, "height": height},
        "captions": {"enabled": True},
        "beats": [
            {"id": "b01", "kind": "hero", "mode": "top", "start": 0.6, "end": 3.8,
             "intent": "hook - one file is the whole reel",
             "data": {"text": "One file, whole reel",
                      "note": "plan.json drives everything", "icon": "bolt"}},
            {"id": "b02", "kind": "checklist", "mode": "stage", "start": 4.0, "end": 7.8,
             "intent": "the workflow in three steps",
             "data": {"items": ["transcribe the take", "plan the beats",
                                "verify before render"], "clock": True}},
            {"id": "b03", "kind": "stat", "mode": "top", "start": 8.0, "end": 11.6,
             "intent": "close - the library size",
             "data": {"from": 0, "to": 16, "unit": "beat kinds",
                      "note": "one deterministic build", "dur": 1.15}},
        ],
    }


def sample_project(project, fps, width, height):
    """A full pipeline run without real footage: generate a synthetic clip with
    ffmpeg, scaffold it, and drop in a canned transcript + plan so every command
    (build / check / verify / snapshot / render) has real input to work on."""
    os.makedirs(project, exist_ok=True)
    raw = os.path.join(project, "sample-raw.mp4")
    if not os.path.exists(raw):
        cmd = ["ffmpeg", "-y",
               # A slow dark gradient, not testsrc2: talking-head reels sit over
               # dim, smooth backgrounds, and a color-noise pattern trips the
               # HyperFrames contrast lint on footage that is nothing like the
               # domain this skill serves.
               "-f", "lavfi", "-i", f"gradients=size={width}x{height}:rate={fps}:duration=12:c0=0x1a1a22:c1=0x3a3a4a:speed=0.04",
               "-f", "lavfi", "-i", "sine=frequency=180:duration=12",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
               "-shortest", raw, "-loglevel", "error"]
        r = sh(cmd)
        if r.returncode != 0 or not os.path.exists(raw):
            die(f"ffmpeg failed:\n{r.stderr[-1200:]}")
        print(f"reelkit: generated synthetic 12s clip {raw} (animated gradient, not footage)")
    scaffold(project, raw, fps, width, height, upscale=False)
    json.dump(sample_words(), open(os.path.join(project, "transcript.json"), "w",
                                   encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(sample_plan(fps, width, height),
              open(os.path.join(project, "plan.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    s = os.path.join(SKILL, "scripts", "reelkit.py")
    print("reelkit: transcript.json and plan.json are canned fixtures (the synthetic "
          "audio has no speech, so there is nothing to transcribe)")
    print(f"reelkit: next -> python3 {s} build --project {project}")
    print(f"            (cd {project} && npx hyperframes@latest check public)")
    print(f"            python3 {s} verify --project {project}")
    print("note: face detection finds no head in a gradient - that part of "
          "verify only exercises on real footage")
    return 0


# ------------------------------------------------------------------ cut (opt-in)
def cut_video(src, dest, keeps, fps):
    """Trim/reorder BEFORE the pipeline. Deliberately a separate step: the whole
    design rests on the transcript describing the footage exactly, so we cut
    first and re-transcribe, rather than remapping every downstream time through
    an edit list (which is the most bug-prone thing this could contain).

    keeps: [[start, end], ...] in source seconds, applied in the given order."""
    if not os.path.exists(src):
        die(f"video not found: {src}")
    total = probe_duration(src)
    segs = []
    for i, k in enumerate(keeps):
        a, b = float(k[0]), float(k[1])
        if b > total: b = total
        if b - a < 0.15:
            die(f"keep range {i} ({a}-{b}) is shorter than 0.15s")
        segs.append((a, b))
    if not segs:
        die("no keep ranges given")

    parts, maps = [], ""
    for i, (a, b) in enumerate(segs):
        parts.append(f"[0:v]trim={a}:{b},setpts=PTS-STARTPTS[v{i}];"
                     f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS[a{i}]")
        maps += f"[v{i}][a{i}]"
    fc = ";".join(parts) + f";{maps}concat=n={len(segs)}:v=1:a=1[v][a]"
    cmd = ["ffmpeg", "-y", "-i", src, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
           "-r", str(fps), "-c:v", "libx264", "-crf", "17", "-preset", "medium",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", dest, "-loglevel", "error"]
    r = sh(cmd)
    if r.returncode != 0 or not os.path.exists(dest):
        die(f"ffmpeg failed:\n{r.stderr[-1200:]}")
    kept = sum(b - a for a, b in segs)
    print(f"reelkit: cut {total:.2f}s -> {kept:.2f}s ({len(segs)} segment(s)) -> {dest}")
    print("reelkit: NOW RE-TRANSCRIBE the cut file. Do not reuse the old transcript - "
          "its timestamps describe the uncut footage.")
    return 0


# ------------------------------------------------------------------ sfx
SFX_SEARCH = [
    "~/.claude/skills/media-use/audio/assets/sfx",
    "~/.agents/skills/media-use/audio/assets/sfx",
]


def find_sfx_dir(explicit=None):
    """Locate the media-use bundled SFX library. Not vendored into reelkit: the
    Pixabay licence covers using these inside a rendered video, but not
    re-hosting the raw files in a public repo."""
    cands = ([explicit] if explicit else []) + SFX_SEARCH
    for c in cands:
        d = os.path.expanduser(c)
        if os.path.isdir(d):
            return d
    return None


PEAK_RE = re.compile(r"max_volume:\s*(-?[0-9.]+) dB")


def sfx_gain(path, target_db=-11.0):
    """Per-file peak normalisation. The bundled library spans ~32 dB between the
    quietest and loudest file, so a flat `volume` means wildly different perceived
    levels. Normalising to a target peak makes `volume` mean one thing."""
    r = sh(["ffmpeg", "-i", path, "-af", "volumedetect", "-f", "null", "-"])
    m = PEAK_RE.search(r.stderr or "")
    if not m:
        return 1.0
    return max(0.05, min(6.0, 10 ** ((target_db - float(m.group(1))) / 20.0)))


SIL_RE = re.compile(r"silence_end:\s*([0-9.]+)")


def sfx_lead_silence(path):
    """Several bundled files open with ~0.4 s of digital silence. Starting the
    clip at the cue time therefore plays the transient LATE and it misses the
    visual hit. Measure the lead-in and start the clip that much earlier."""
    r = sh(["ffmpeg", "-i", path, "-af", "silencedetect=n=-45dB:d=0.15", "-f", "null", "-"])
    err = r.stderr or ""
    if "silence_start: 0" not in err:
        return 0.0
    m = SIL_RE.search(err)
    return min(1.0, float(m.group(1))) if m else 0.0


def sfx_duration(sdir, name, fname):
    man = os.path.join(sdir, "manifest.json")
    if os.path.exists(man):
        try:
            m = json.load(open(man, encoding="utf-8"))
            if name in m and m[name].get("duration"):
                return float(m[name]["duration"])
        except Exception:
            pass
    return probe_duration(os.path.join(sdir, fname))


def resolve_sfx(plan, pub, dur, an):
    """Collect every cue, copy the files in, and interval-partition them across
    track indices so two overlapping cues never share a track."""
    cues = []
    # relative level: 1.0 == the normalised target, so 0.8 is "a bit under"
    default_vol = float(plan.get("audio", {}).get("sfxVolume", 0.8))
    for beat in plan["beats"]:
        for c in beat.get("sfx", []) or []:
            c = {"name": c} if isinstance(c, str) else dict(c)
            cues.append({"name": c["name"],
                         "at": an.q(float(beat["start"]) + float(c.get("at", 0))),
                         "volume": float(c.get("volume", default_vol))})
    for c in plan.get("audio", {}).get("sfx", []) or []:
        cues.append({"name": c["name"], "at": an.q(float(c["at"])),
                     "volume": float(c.get("volume", default_vol))})
    if not cues:
        return [], []

    sdir = find_sfx_dir(plan.get("audio", {}).get("sfxDir"))
    if not sdir:
        print("reelkit: ! sfx requested but no library found - install the HyperFrames "
              "media-use skill, or set audio.sfxDir. Continuing without sfx.")
        return [], []

    os.makedirs(os.path.join(pub, "sfx"), exist_ok=True)
    files, out, tracks = {}, [], []          # tracks[i] = end time of last cue on track i
    for c in sorted(cues, key=lambda x: x["at"]):
        if c["name"] not in files:
            src = os.path.join(sdir, f"{c['name']}.mp3")
            if not os.path.exists(src):
                print(f"reelkit: ! no sfx named '{c['name']}' - skipped")
                files[c["name"]] = None
            else:
                dst = os.path.join(pub, "sfx", f"{c['name']}.mp3")
                shutil.copy2(src, dst)
                files[c["name"]] = (f"{c['name']}.mp3",
                                    sfx_duration(sdir, c["name"], f"{c['name']}.mp3"),
                                    sfx_gain(dst, float(plan.get("audio", {}).get("sfxTargetDb", -11.0))),
                                    sfx_lead_silence(dst))
        got = files[c["name"]]
        if not got:
            continue
        fname, d, gain, lead = got
        at = max(0.0, an.q(c["at"] - lead))     # land the transient on the cue
        d = min(d, max(0.05, dur - at))               # never run past the media
        if d <= 0.05:
            continue
        ti = next((i for i, endt in enumerate(tracks) if endt <= at), len(tracks))
        if ti == len(tracks):
            tracks.append(0.0)
        tracks[ti] = at + d
        # id is REQUIRED: the renderer discovers media by id, and an <audio>
        # without one renders completely silent (lint: media_missing_id).
        out.append(f'<audio id="sfx-{len(out):03d}-{c["name"]}" class="clip" src="sfx/{fname}" '
                   f'data-start="{at:.4f}" data-duration="{d:.4f}" '
                   f'data-track-index="{20+ti}" data-volume="{round(min(1.0, gain*c["volume"]),3)}"></audio>')
    print(f"reelkit: {len(out)} sfx cue(s) across {len(tracks)} track(s)")
    return out, sorted({c["name"] for c in cues})


# ------------------------------------------------------------------ plan draft
# Heuristic first pass. It gets the *timing* right (clause boundaries from real
# word gaps) and guesses the visual kind, which it will often get wrong - that is
# expected and cheap to fix. Anything it cannot classify becomes an `image` slot
# with a drafted prompt, because an unfilled image slot renders a loud placeholder
# that cannot be shipped by accident, whereas a wrong-but-plausible card can.

CUES = {
    "chat":      ["?", "שאל", "שואל", "עונה", "ask", "asks", "answer", "reply", "question"],
    "code":      ["קוד", "לכתוב", "פונקצי", "code", "function", "script", "commit", "api"],
    "diff":      ["מאובטח", "בדיק", "לתקן", "review", "secure", "bug", "fix", "test"],
    "checklist": ["שעות", "רשימ", "לוודא", "hours", "checklist", "steps", "every"],
    "pipeline":  ["קודם", "אחר כך", "תהליך", "שלב", "first", "then", "after", "process", "step"],
    "contrast":  ["לעומת", "במקום", "מצד שני", "instead of", "versus", "rather than"],
    "stat":      [],   # digit-driven, see below
}
DIGIT = re.compile(r"\d")


def draft_plan(project, lang, max_beats):
    tpath = os.path.join(project, "transcript.json")
    if not os.path.exists(tpath):
        die("no transcript.json - transcribe first")
    words = json.load(open(tpath, encoding="utf-8"))
    if isinstance(words, dict):
        words = words.get("words") or []
    if not words:
        die("transcript.json has no words")

    # 1. clauses: split on real pauses and terminal punctuation
    clauses, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end = nxt is None or (nxt["start"] - w["end"]) > 0.34 or w["text"].endswith((".", "?", "!", ","))
        if end and cur:
            clauses.append(cur); cur = []
    if cur:
        clauses.append(cur)

    # 2. merge clauses into beats of roughly 4-7s, never splitting a clause
    beats, acc = [], []
    for cl in clauses:
        acc.append(cl)
        span = acc[-1][-1]["end"] - acc[0][0]["start"]
        if span >= 5.5:
            beats.append(acc); acc = []
    if acc:
        if beats and (acc[-1][-1]["end"] - acc[0][0]["start"]) < 2.0:
            beats[-1].extend(acc)          # never leave a runt beat
        else:
            beats.append(acc)
    if max_beats and len(beats) > max_beats:      # merge from the middle outwards
        while len(beats) > max_beats:
            spans = [(b[-1][-1]["end"] - b[0][0]["start"], i) for i, b in enumerate(beats[1:-1], 1)]
            _, i = min(spans)
            beats[i].extend(beats[i + 1]); del beats[i + 1]

    flats = [[w for cl in grp for w in cl] for grp in beats]
    starts = [round(f[0]["start"] - 0.08, 2) for f in flats]
    out = []
    for bi, flat in enumerate(flats):
        text = " ".join(w["text"] for w in flat)
        st = starts[bi]
        en = round(flat[-1]["end"] + 0.30, 2)
        if bi + 1 < len(flats):        # never overlap the next beat
            en = min(en, round(starts[bi + 1] - 0.04, 2))
        if en <= st + 0.5:
            en = round(st + 0.5, 2)
        low = text.lower()

        kind, data = None, {}
        if bi == 0:
            kind, data = "hero", {"text": "TODO short hook, 2-4 words", "note": ""}
        elif bi == len(beats) - 1:
            kind, data = "follow", {"kicker": "TODO", "headline": "TODO the open loop",
                                    "name": "TODO", "handle": "TODO", "initial": "A", "cta": "Follow"}
        elif DIGIT.search(text):
            nums = re.findall(r"\d+", text)
            kind = "stat"
            data = {"from": 0, "to": int(nums[-1]), "unit": "TODO", "note": ""}
        else:
            for k, cues in CUES.items():
                if k != "stat" and any(c in low for c in cues):
                    kind = k; break
            if kind == "chat":
                data = {"msgs": [{"side": "l", "text": "TODO"}, {"side": "r", "text": "TODO"}]}
            elif kind == "code":
                data = {"title": "TODO.ts", "lines": ["// TODO 3-5 short lines"]}
            elif kind == "diff":
                data = {"title": "review", "rows": [{"op": "-", "text": "TODO"}, {"op": "+", "text": "TODO"}],
                        "chips": []}
            elif kind == "checklist":
                data = {"clock": True, "items": ["TODO", "TODO", "TODO"]}
            elif kind == "pipeline":
                data = {"nodes": ["TODO", "TODO", "TODO"]}
            elif kind == "contrast":
                data = {"from": "TODO", "to": "TODO"}

        beat = {"id": f"b{bi+1:02d}", "start": st, "end": en,
                "kind": kind or "image",
                "mode": "stage" if (kind or "image") in ("chat", "code", "diff", "donut",
                                                         "bars", "pipeline", "image", "follow") else "top",
                "intent": text[:110],
                "_said": text}
        if kind:
            beat["data"] = data
        else:
            beat["data"] = {"caption": ""}
            beat["image"] = {
                "mode": "replace", "alpha": False,
                "prompt": (f"TODO describe an OBJECT or SCENE that depicts this idea - not the words. "
                           f"Context: \"{text[:90]}\". Style: flat editorial vector, deep navy ground, "
                           f"brand accents, no text."),
            }
        out.append(beat)

    plan = {
        "_draft": ("Heuristic first pass. Timing is derived from real word gaps and is usually right; "
                   "the KIND guesses are not - expect to change about half. Replace every TODO, delete "
                   "beats that do not earn a visual, and read references/visual-beats.md before keeping "
                   "any beat whose card would just restate the sentence."),
        "meta": {"title": "TODO", "lang": lang, "fps": 30, "width": 1080, "height": 1920},
        "brand": "default",
        "captions": {"enabled": True},
        "framing": {"scale": 1.0, "origin": "50% 30%", "punches": []},
        "beats": out,
    }
    dest = os.path.join(project, "plan.draft.json")
    json.dump(plan, open(dest, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    todo = sum(1 for b in out if "image" in b or "TODO" in json.dumps(b, ensure_ascii=False))
    print(f"reelkit: drafted {len(out)} beats -> {dest}")
    print(f"reelkit: {todo} beat(s) still need content. Review, rename to plan.json, then build.")
    print("reelkit: timing comes from the transcript and is usually right; the kind guesses are not.")
    return 0


# ------------------------------------------------------------------ scaffold
def probe_duration(path):
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
            "default=nw=1:nk=1", path])
    try:
        return float(r.stdout.strip())
    except ValueError:
        die(f"ffprobe could not read a duration from {path}")


def probe_wh(path):
    r = sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height", "-of", "csv=p=0:s=x", path])
    try:
        w, h = r.stdout.strip().split("x")[:2]
        return int(w), int(h)
    except Exception:
        die(f"ffprobe could not read dimensions from {path}")


def scaffold(project, video, fps, width, height, upscale):
    if not os.path.exists(video):
        die(f"video not found: {video}")
    pub = os.path.join(project, "public")
    for d in ("cards", "images", "fonts", "vendor"):
        os.makedirs(os.path.join(pub, d), exist_ok=True)

    for f in os.listdir(os.path.join(SKILL, "assets", "fonts")):
        shutil.copy2(os.path.join(SKILL, "assets", "fonts", f), os.path.join(pub, "fonts", f))
    gs = os.path.join(SKILL, "assets", "vendor", "gsap.min.js")
    if os.path.exists(gs):
        shutil.copy2(gs, os.path.join(pub, "vendor", "gsap.min.js"))
    else:
        for cand in (os.path.expanduser("~/.claude/skills/talking-head-recut/assets/vendor/gsap.min.js"),
                     os.path.expanduser("~/.agents/skills/talking-head-recut/assets/vendor/gsap.min.js")):
            if os.path.exists(cand):
                shutil.copy2(cand, os.path.join(pub, "vendor", "gsap.min.js")); break
        else:
            # Not vendored on purpose: GSAP ships under its own licence, so the
            # repo stays licence-clean and fetches it at scaffold time instead.
            r = sh("npm pack gsap --silent --pack-destination /tmp 2>/dev/null")
            tgz = next((os.path.join("/tmp", f) for f in sorted(os.listdir("/tmp"))
                        if f.startswith("gsap-") and f.endswith(".tgz")), None)
            if tgz:
                sh(f"tar -xzf {tgz} -C /tmp package/dist/gsap.min.js")
                src = "/tmp/package/dist/gsap.min.js"
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(pub, "vendor", "gsap.min.js"))
            if not os.path.exists(os.path.join(pub, "vendor", "gsap.min.js")):
                die("gsap.min.js not found. Either install the HyperFrames skills "
                    "(`npx hyperframes skills update talking-head-recut`) or "
                    "`npm i gsap` and copy dist/gsap.min.js into <project>/public/vendor/.")

    sw, sh_ = probe_wh(video)
    vf = f"scale={width}:{height}:flags=lanczos"
    if upscale or sw < width:
        vf += ",unsharp=5:5:0.65:3:3:0.35"
        print(f"reelkit: source is {sw}x{sh_}, upscaling to {width}x{height} "
              f"({width/max(1,sw):.2f}x) - expect visible softness; a higher-res "
              f"master will always look better")
    # Dense keyframes: a sparse GOP makes the renderer freeze on seek and you get
    # one frozen frame under all the overlays.
    out = os.path.join(pub, "input-video.mp4")
    cmd = ["ffmpeg", "-y", "-i", video, "-vf", vf, "-r", str(fps),
           "-c:v", "libx264", "-crf", "17", "-g", str(fps), "-keyint_min", str(fps),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-c:a", "aac", "-b:a", "192k", out, "-loglevel", "error"]
    r = sh(cmd)
    if r.returncode != 0 or not os.path.exists(out):
        die(f"ffmpeg failed:\n{r.stderr[-1200:]}")
    ap = os.path.join(project, "audio.mp3")
    sh(["ffmpeg", "-y", "-i", video, "-vn", "-acodec", "libmp3lame", "-q:a", "2",
        ap, "-loglevel", "error"])
    print(f"reelkit: staged {out} ({probe_duration(out):.2f}s) and audio.mp3")
    print("reelkit: next -> transcribe, then author plan.json, then `reelkit.py build`")
    return 0


def doctor():
    ok = True
    for tool, why in (("ffmpeg", "encode/decode"), ("ffprobe", "media probing"),
                      ("node", "HyperFrames CLI")):
        p = shutil.which(tool)
        print(f"  {'OK ' if p else 'MISS'} {tool:8s} {p or '- required for ' + why}")
        ok = ok and bool(p)
    fdir = os.path.join(SKILL, "assets", "fonts")
    n = len([f for f in os.listdir(fdir) if f.endswith(".woff2")]) if os.path.isdir(fdir) else 0
    print(f"  {'OK ' if n else 'MISS'} fonts    {n} woff2 in assets/fonts")
    gs = os.path.join(SKILL, "assets", "vendor", "gsap.min.js")
    hf = os.path.expanduser("~/.claude/skills/talking-head-recut/assets/vendor/gsap.min.js")
    print(f"  {'OK ' if (os.path.exists(gs) or os.path.exists(hf)) else 'MISS'} gsap     "
          f"{'vendored' if os.path.exists(gs) else ('via HyperFrames skill' if os.path.exists(hf) else 'not found')}")
    r = sh("npx -y hyperframes@latest --version")
    print(f"  {'OK ' if r.returncode == 0 else 'MISS'} hyperframes {r.stdout.strip() or r.stderr.strip()[:60]}")
    try:
        import playwright  # noqa: F401
        print("  OK  playwright  (verify: card geometry)")
    except Exception:
        print("  OPT playwright  not installed - `verify` card geometry unavailable")
    try:
        import cv2  # noqa: F401
        print("  OK  opencv      (verify: face detection)")
    except Exception:
        print("  OPT opencv      not installed - `verify` face checks skipped (everything else runs)")
    sfx = find_sfx_dir()
    print(f"  {'OK ' if sfx else 'OPT'} sfx        {sfx or 'media-use skill not found - sfx cues will be skipped'}")
    print("\nRender/snapshot on a slow or headless box needs:\n"
          "  PRODUCER_PAGE_NAVIGATION_TIMEOUT_MS=90000 PRODUCER_PLAYER_READY_TIMEOUT_MS=90000")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(prog="reelkit", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scaffold"); s.add_argument("--project", required=True)
    s.add_argument("--video", required=True); s.add_argument("--fps", type=int, default=30)
    s.add_argument("--width", type=int, default=1080); s.add_argument("--height", type=int, default=1920)
    s.add_argument("--upscale", action="store_true")
    b = sub.add_parser("build"); b.add_argument("--project", required=True)
    v = sub.add_parser("verify"); v.add_argument("--project", required=True)
    v.add_argument("--json", action="store_true"); v.add_argument("--fix", action="store_true")
    ct = sub.add_parser("cut"); ct.add_argument("--video", required=True)
    ct.add_argument("--out", required=True); ct.add_argument("--fps", type=int, default=30)
    ct.add_argument("--keep", required=True,
                    help='ranges in source seconds: "0:44,56:90" (applied in order)')
    d = sub.add_parser("plan"); d.add_argument("--project", required=True)
    d.add_argument("--lang", default="en"); d.add_argument("--max-beats", type=int, default=0)
    sa = sub.add_parser("sample"); sa.add_argument("--project", required=True)
    sa.add_argument("--fps", type=int, default=30)
    sa.add_argument("--width", type=int, default=1080); sa.add_argument("--height", type=int, default=1920)
    sub.add_parser("doctor")
    a = ap.parse_args()
    if a.cmd == "scaffold":
        return scaffold(a.project, a.video, a.fps, a.width, a.height, a.upscale)
    if a.cmd == "build":
        return build(a.project)
    if a.cmd == "plan":
        return draft_plan(a.project, a.lang, a.max_beats)
    if a.cmd == "verify":
        import verify as _v
        return _v.run(a.project, a.json, a.fix)
    if a.cmd == "cut":
        keeps = [[float(x) for x in seg.split(":")] for seg in a.keep.split(",")]
        return cut_video(a.video, a.out, keeps, a.fps)
    if a.cmd == "sample":
        return sample_project(a.project, a.fps, a.width, a.height)
    return doctor()


if __name__ == "__main__":
    sys.exit(main())
