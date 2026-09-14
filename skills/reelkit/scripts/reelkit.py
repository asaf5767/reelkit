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
import argparse, glob, json, os, re, shutil, statistics, subprocess, sys, tarfile, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cards import (KINDS, Anim, esc, kinetic, icon,      # noqa: E402
                   lang_direction as cards_lang_direction, split_canvas_h,
                   split_canvas_h_face, detect_faces,
                   canvas_image_box, wants_plate, head_rect, head_clear_y,
                   HEAD_MARGIN)
from geometry import image_slot_box, fit_layout, measure_cards  # noqa: E402
import audiomix, captionfx, lottiefx, marks, pip as pipmod, progress as pgmod, style  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)

# The renderer is pinned, never resolved as @latest. This is a correctness fix
# first: @latest can move between the preview pass and the full pass of the same
# reel, which silently breaks the "identical command, identical inputs = equally
# valid render" basis the segment reuse cache rests on. Measured warm, pinning
# saves no time - @latest and an exact version both cost ~1.2s of node/npx
# startup - so the registry lookup only shows up on a cold npx cache, which is
# every fresh Kaggle kernel and every fresh container.
# Upgrade procedure is in SKILL.md - it is a deliberate, tested bump, not a
# side effect of somebody rendering on a Tuesday.
HF_VERSION = "0.8.36"
HF = f"hyperframes@{HF_VERSION}"
BRAND_DIR = os.path.join(SKILL, "assets", "brand")

# Two beats may touch but never overlap - verify errors on `a.end > b.start` -
# so anything that extends a beat leaves this much of a gap in front of the
# next one.
BEAT_GAP = 0.04

def _load_default_brand():
    """The built-in brand IS assets/brand/default.json, never a copy of it.

    It used to be a dict literal here, and the two drifted: a plan with no brand
    key rendered canvasBg #F7F7F4 while `"brand": "default"` rendered #FAFAF9,
    with nothing to catch it. Same defect class as the plan-box vs CSS drift
    geometry.py removed - two sources of truth for one number - so it gets the
    same treatment: one source, and a test that they cannot diverge again.

    Read once at import. A missing or unreadable preset is fatal rather than
    silently falling back to hardcoded values, which is how the copy got here.
    """
    path = os.path.join(BRAND_DIR, "default.json")
    try:
        with open(path, encoding="utf-8") as fh:
            b = json.load(fh)
    except Exception as e:
        raise SystemExit(f"reelkit: cannot read the default brand preset {path}: {e}")
    if not isinstance(b, dict) or "accents" not in b:
        raise SystemExit(f"reelkit: {path} is not a brand preset (no accents)")
    return b


DEFAULT_BRAND = _load_default_brand()


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
                     os.path.join(BRAND_DIR, f"{ref}.json")):
            if os.path.exists(cand):
                with open(cand, encoding="utf-8") as fh:
                    b.update(json.load(fh))
                break
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


def caption_clips(words, br, dur, an, capcfg=None):
    """capcfg carries the resolved caption knobs (brand -> profile -> plan); br
    remains the fallback so a caller that predates profiles still works."""
    capcfg = capcfg or {"maxWords": br["captionMaxWords"], "maxChars": br["captionMaxChars"]}
    lines = group_words(words, capcfg["maxWords"], capcfg["maxChars"])
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
def theme_css(br, capcfg=None, titlecfg=None):
    A = br["accents"]
    CAPSTROKE = captionfx.stroke_css(capcfg or {})
    SCRIPTFONT = (titlecfg or {}).get("scriptFont") or "Georgia,'Times New Roman',serif"
    return f"""
:root{{--bg:{br['bg']};--text:{br['text']};--accent-0:{A[0]};--accent-1:{A[1]};
--accent-2:{A[2]};--accent-3:{A[3]};--accent-4:{A[4]};}}
*{{box-sizing:border-box;}}
html,body{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:{br['bg']};
font-family:'{br['font']}','{br['latinFont']}',ui-sans-serif,system-ui,sans-serif;}}
#stage{{position:relative;width:100%;height:100%;overflow:hidden;}}
#pip-frame{{position:absolute;left:0;top:0;width:100%;height:100%;
 transform-origin:0 0;overflow:hidden;will-change:transform;}}
.video-wrapper{{position:absolute;left:0;top:0;width:100%;height:100%;overflow:hidden;}}
.video-wrapper video{{width:100%;height:100%;object-fit:cover;}}
.bottomveil{{position:absolute;left:0;right:0;bottom:0;height:430px;
background:linear-gradient(180deg,rgba(5,6,10,0) 0%,rgba(5,6,10,.30) 45%,rgba(5,6,10,.58) 100%);}}
.card-host{{position:absolute;pointer-events:none;overflow:hidden;}}
.card-host .card{{position:relative;width:100%;height:100%;overflow:hidden;}}
.card-host .char{{display:inline-block;visibility:visible;}}
.cap-host{{overflow:visible;}}
/* Captions carry a heavy dark outline instead of a plate: legible over any
   footage, and it costs nothing from the heavy-overlay budget. */
.capline .cw{{{CAPSTROKE}}}
/* Emphasis is TYPE - weight, italic serif, or one flat accent block. Never a
   glowing container: no shadow, blur or gradient anywhere in here. */
.capline .cw-highlight{{background:var(--accent-0);color:#0B0D12;border-radius:14px;
 padding:0 .18em;-webkit-text-stroke:0;}}
.capline .cw-serif{{font-family:Georgia,'Times New Roman',serif;font-style:italic;
 font-weight:700;}}
/* Emoji sit inside their word's span so bidi orders them with the word rather
   than stranding them at whichever edge the line direction picked. */
.capline .cemo{{margin-inline-start:.22em;-webkit-text-stroke:0;font-style:normal;}}
/* The detonated keyword is SVG text fitted with textLength, so it cannot
   overflow the canvas or be clipped in either direction. */
.cdet{{display:block;width:100%;height:100%;overflow:visible;}}
/* A Lottie badge is a positioned overlay like any other, and its box is fixed
   so the player cannot resize the layout mid-render. */
.lbadge{{position:absolute;pointer-events:none;}}
.lbadge svg{{width:100%;height:100%;display:block;}}
/* Progress-dim: the spoken section is lit, the covered ones dim behind it.
   Dimming is opacity and colour only - a filter would be the obvious way to
   grey a row out and it is also the one that spends the heavy-overlay budget. */
.progress{{display:flex;flex-direction:column;gap:18px;}}
.progress .pgtitle{{font-size:44px;font-weight:800;opacity:0;color:#AEB4C0;}}
.progress .pglist{{display:flex;flex-direction:column;gap:16px;}}
.progress .pgrow{{display:flex;align-items:center;gap:18px;font-size:58px;
 font-weight:800;line-height:1.15;}}
.progress .pgnum{{flex:0 0 auto;min-width:1.7em;height:1.7em;border-radius:999px;
 background:var(--pgacc);color:#0B0D12;font-size:.62em;font-weight:900;
 display:inline-flex;align-items:center;justify-content:center;}}
/* The lower-third band: a rule, a name, a role. No plate, no glow. */
.lthird{{display:flex;align-items:stretch;gap:20px;}}
.lthird .ltrule{{flex:0 0 10px;border-radius:999px;background:var(--ltacc);}}
.lthird .lttext{{display:flex;flex-direction:column;gap:6px;justify-content:center;}}
.lthird .ltname{{font-size:56px;font-weight:900;opacity:0;}}
.lthird .ltrole{{font-size:34px;font-weight:600;opacity:0;color:#C8CEDA;}}
/* The branded end card. A LINEAR gradient only: radial-gradient is in the
   heavy-overlay pattern that turns a render black, linear is not. One card,
   one gradient, once per reel. */
/* Not absolutely positioned: an absolute box resolves against whichever
   ancestor happens to be positioned, which measured the card outside the canvas.
   A plain full-size block is measured where it actually is. */
.outro{{width:100%;height:100%;min-height:100%;display:flex;flex-direction:column;
 gap:22px;align-items:center;justify-content:center;text-align:center;
 background:linear-gradient(180deg,#0B0D12 0%,#161A23 100%);}}
.outro .oname{{font-size:104px;font-weight:900;letter-spacing:-.02em;opacity:0;}}
.outro .otype{{font-size:40px;font-weight:600;opacity:0;color:#AEB4C0;}}
.outro .opill{{font-size:38px;font-weight:800;opacity:0;color:#0B0D12;
 background:var(--oacc);border-radius:999px;padding:14px 38px;}}
.outro .octa{{font-size:34px;font-weight:600;opacity:0;color:#E7EAF0;}}
/* Title lockup: a bold sans line, a script accent line, ONE accent. Emphasis is
   type and a single flat colour - no glowing container, nothing that spends the
   heavy-overlay budget. */
.lockup{{display:flex;flex-direction:column;gap:16px;align-items:center;text-align:center;}}
.lockmain{{font-size:96px;font-weight:900;line-height:1.06;letter-spacing:-.01em;
 display:flex;flex-wrap:wrap;gap:.24em;justify-content:center;}}
.lockmain .lw{{display:inline-block;opacity:0;}}
/* The accent word is where the typefaces mix: the base line stays heavy sans,
   the accent takes the script italic face. That contrast IS the lockup. */
.lockmain .lw-accent{{font-family:{SCRIPTFONT};font-style:italic;font-weight:700;}}
/* One treatment behind it, never two, never a glow. */
.lockmain .lw-marker{{color:#0B0D12;background:var(--lhi);border-radius:16px;
 padding:0 .16em;}}
.lockmain .lw-circle{{position:relative;color:var(--lhi);padding:0 .10em;}}
.lockmain .lw-circle .lwt{{position:relative;z-index:1;}}
/* The ring is stretched onto the accent's own box, so it encircles the word
   without anything being measured at build time. */
.lockmain .lwring{{position:absolute;left:-9%;top:-20%;width:118%;height:140%;
 overflow:visible;pointer-events:none;}}
.lockscript{{font-family:{SCRIPTFONT};font-style:italic;font-weight:600;
 font-size:52px;opacity:0;}}
.cap-host .cw{{display:inline-block;}}
.capline{{display:flex;flex-wrap:wrap;gap:8px 28px;justify-content:center;align-items:center;
width:920px;margin:0 auto;padding:22px 30px;border-radius:28px;background:{br['captionPlate']};
font-family:'{br['font']}',sans-serif;font-weight:900;font-size:{br['captionSize']}px;line-height:1.20;
text-align:center;color:{br['captionIdle']};
text-shadow:0 4px 22px rgba(0,0,0,.9),0 2px 6px rgba(0,0,0,.95);}}
""".strip()


def card_css(cid, mode, br, layout=None, canvas_h=0, fit="wide", cimg=False, kind=""):
    D = br.get("_dir", "rtl"); START = "right" if D == "rtl" else "left"
    P = f'.card[data-card-id="{cid}"]'
    A = br["accents"]
    top = (layout or {}).get("top")
    # `stage` used to sit at 300 because it dimmed the frame: the card was meant
    # to be low, inside the darkest part of the gradient, with the speaker
    # receding behind it. There is no gradient any more, so 300 just pushes the
    # card down onto the speaker's head. Every mode that plays over live footage
    # now hugs the top edge, which is the only place a card can live without
    # touching him; the modes differ in how much room the card takes, not in how
    # far down it starts. `full` is B-roll and owns the frame, so it centres.
    # The end card owns the whole frame like `full` B-roll does: it is the last
    # thing on screen and nothing plays behind it, so a top inset would leave a
    # band of footage above the gradient and push the card off the canvas.
    owns_frame = mode == "full" or kind == "outro"
    pad = (f"{int(top)}px 0 0 0" if top is not None and not owns_frame
           else ("150px 0 0 0" if mode == "stage"
                 else ("0px 0 0 0" if owns_frame else "120px 0 0 0")))
    if mode == "split":
        pad = "0"      # the canvas owns the upper band and carries its own surface
    # A card that cannot fit above the head has one mechanical remedy short of
    # changing the beat's mode: take less room. `layout.scale` is what
    # `verify --fix` writes, and it scales from the top edge so shrinking never
    # moves the card back down onto him.
    scale = float((layout or {}).get("scale", 1) or 1)
    scale_css = ("\n%s .root > *:not(.broll) { transform:scale(%s);transform-origin:top center; }"
                 % (P, round(scale, 3))) if scale != 1 else ""
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
 text-transform:uppercase;color:{br.get('canvasMuted', '#858A93')}; }}
{P} .chead {{ font-size:96px;font-weight:900;line-height:1.10;
 color:{br.get('canvasText', '#14161C')};letter-spacing:-.015em; }}
{P} .cpill {{ position:absolute;{START}:64px;bottom:34px;
 font-family:'{br['latinFont']}',sans-serif;font-size:28px;font-weight:900;
 letter-spacing:.10em;color:{br.get('canvasText', '#14161C')};
 background:rgba(0,0,0,.06);border:2px solid rgba(0,0,0,.16);
 border-radius:999px;padding:10px 26px; }}""" if mode == "split" else ""
    # Image-payload rules exist only on beats that carry one, so an
    # imageless split project still rebuilds byte-identically.
    canvas_css += f"""
{P} .cpane {{ display:flex;flex-direction:{'row' if fit == 'tall' else 'column'};
 /* flex row order follows the content direction: in RTL the text block leads
    from the right edge and the picture lands on the left, matching the box
    canvas_image_box() publishes to visuals.json */
 direction:{D};
 gap:{'40px' if fit == 'tall' else '22px'};align-items:stretch;
 flex:1 1 auto;min-height:0;min-width:0;
 /* the counter pill is absolutely positioned in the panel's bottom-start
    corner; reserve its strip or an image caption lands on top of it */
 padding-bottom:56px; }}
/* flex:0 0 auto, NOT 0 1 auto. Letting the text block shrink below its own
   content means the headline overflows into the media area and the image paints
   over it - which is what a shorter default canvas immediately produced. The
   text takes what it needs; the picture takes what is left, and the squeeze
   check fails the beat when that is not enough. */
{P} .cpane > .cblock {{ {'flex:1 1 auto;min-width:0' if fit == 'tall' else 'flex:0 0 auto'};
 justify-content:center; }}
{P} .cmedia {{ display:flex;flex-direction:column;gap:14px;
 flex:1 1 auto;min-height:0;min-width:0;justify-content:center; }}
{P} .cimgframe {{ flex:1 1 auto;min-height:0;min-width:0;overflow:hidden;
 border-radius:24px;background:rgba(0,0,0,.04);
 display:flex;align-items:center;justify-content:center; }}
{P} .cimgframe.soft {{ border:2px solid rgba(0,0,0,.12);
 box-shadow:0 18px 46px rgba(0,0,0,.16); }}
{P} .cimgframe.bare {{ border:0;box-shadow:none;background:transparent; }}
{P} .cimgframe img {{ width:100%;height:100%;object-fit:contain;display:block; }}
{P} .cimgslot {{ padding:28px;font-size:30px;font-weight:800;line-height:1.35;
 color:{br.get('canvasText', '#14161C')};direction:{D};text-align:{START};
 border:3px dashed {A[4]};border-radius:20px;background:rgba(0,0,0,.03); }}
{P} .cimgcap {{ flex:0 0 auto;font-size:30px;font-weight:700;text-align:{START};
 direction:{D};color:{br.get('canvasMuted', '#858A93')}; }}""" if cimg else ""
    return f"""
{P} .root {{ width:100%;height:100%;position:relative;display:flex;
 align-items:{'center' if mode == 'full' else 'flex-start'};
 justify-content:center;padding:{pad};font-family:'{br['font']}','{br['latinFont']}',sans-serif;
 color:{br['text']};background:transparent; }}
/* No global scrim anywhere. Dimming the frame to lift a card also dims the
   speaker, and the speaker is the subject - "the visuals make the rest of the
   screen darker and it affects how I look". Separation, where a card needs it,
   comes from .plate: a local surface the size of the card and nothing more. */
{P} .broll {{ position:absolute;inset:0;background:{br['bg']};overflow:hidden; }}
{P} .broll img, {P} .broll video {{ width:100%;height:100%;object-fit:cover;display:block; }}
{P} .brollcap {{ position:absolute;left:0;right:0;bottom:460px;padding:0 90px;
 font-size:46px;font-weight:800;line-height:1.25;text-align:center;direction:{D};
 text-shadow:0 6px 28px rgba(0,0,0,.85); }}
/* Deliberately NO backdrop-filter. A blurred plate looks better in a still and
   is a render hazard: HyperFrames lints heavy-overlay elements (filter:blur,
   radial-gradient, clip-path) because past ~40 of them the capture layer
   returns solid black for the first half of the render. Fourteen plates took
   this composition from 0 to 105 heavy elements in one commit. A flat
   translucent fill plus a shadow reads as the same object and cannot do that. */
/* Near-opaque on purpose. At 66% over a light wall the plate came out a washed
   mid-grey that reads as a rendering artefact rather than a card. "Subtle"
   here means small in EXTENT - it covers the card and nothing else - not
   see-through. */
{P} .plate {{ position:relative;border-radius:44px;padding:32px 36px;
 background:rgba(9,11,17,.90);
 border:1px solid rgba(255,255,255,.10);
 box-shadow:0 24px 64px rgba(0,0,0,.42); }}
/* Card footprints are deliberately smaller than the frame: a visual earns the
   space it takes, and the default should leave the speaker room. */
{P} .stack {{ position:relative;width:820px;display:flex;flex-direction:column;gap:18px;
 padding:0 18px;direction:{D};text-align:{START}; }}
{P} .stack.center {{ align-items:center;text-align:center; }}
{P} .blk {{ position:relative;width:820px;padding:0 18px;direction:{D};text-align:{START}; }}
{P} .blk.center {{ display:flex;flex-direction:column;align-items:center;text-align:center; }}
{P} .stagewrap {{ position:relative;width:860px;padding:0 16px;display:flex;flex-direction:column;
 align-items:center;gap:22px; }}
{P} .row2 {{ position:relative;width:860px;padding:0 18px;display:flex;align-items:center;
 gap:30px;direction:{D}; }}
{P} .ico {{ width:100%;height:100%;display:block; }}
{P} .char {{ display:inline-block; }}
{P} .wd {{ display:inline-block;white-space:nowrap; }}
{P} .hero {{ font-size:136px;font-weight:900;line-height:1.0;letter-spacing:-.03em;
 text-shadow:0 10px 48px rgba(0,0,0,.6); }}
{P} .hero.sm {{ font-size:108px; }}
{P} .heroicon {{ width:118px;height:118px;margin-bottom:6px; }}
{P} .btitle {{ font-size:76px;font-weight:900;line-height:1.06;text-shadow:0 8px 34px rgba(0,0,0,.7); }}
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
{P} .phone {{ width:560px;background:#FFFFFF;color:#18181B;border:2px solid #D4D4D8;border-radius:28px;
 overflow:hidden;box-shadow:0 14px 34px rgba(0,0,0,.18); }}
{P} .phbar {{ display:flex;gap:10px;padding:18px 22px;background:#F4F4F5; }}
{P} .phbar i {{ width:13px;height:13px;border-radius:50%;background:#A1A1AA; }}
{P} .thread {{ display:flex;flex-direction:column;gap:16px;padding:26px 24px 30px; }}
{P} .bub {{ border-radius:22px;padding:18px 24px;max-width:78%;font-size:34px;font-weight:800;line-height:1.25; }}
{P} .bub.l {{ align-self:flex-start;background:#F4F4F5;color:#18181B;border:1px solid #E4E4E7;border-bottom-left-radius:8px; }}
{P} .bub.r {{ align-self:flex-end;background:{A[0]};color:#FFFFFF;border-bottom-right-radius:8px; }}
{P} .typing {{ display:flex;flex-direction:row;gap:10px;max-width:none;padding:20px 24px; }}
{P} .dot {{ width:14px;height:14px;border-radius:50%;background:rgba(255,255,255,.6);display:block; }}
{P} .win {{ width:820px;background:#FFFFFF;color:#18181B;border:2px solid #D4D4D8;border-radius:20px;
 overflow:hidden;box-shadow:0 14px 34px rgba(0,0,0,.18); }}
{P} .winbar {{ display:flex;align-items:center;gap:11px;padding:18px 22px;background:#F4F4F5; }}
{P} .winbar i {{ width:15px;height:15px;border-radius:50%; }}
{P} .winbar .r {{ background:#ff5f57; }} {P} .winbar .y {{ background:#febc2e; }}
{P} .winbar .g {{ background:#28c840; }}
{P} .wt {{ margin-inline-start:14px;font:700 24px '{br['latinFont']}',sans-serif;color:#71717A; }}
{P} .code {{ padding:22px 24px;font:700 30px '{br['latinFont']}',ui-monospace,monospace;
 line-height:1.62;position:relative; }}
{P} .cl {{ display:flex;gap:18px;white-space:nowrap; }}
{P} .gut {{ color:#576073;width:32px;text-align:right;flex:0 0 auto; }}
{P} .code .kw {{ color:{A[2]}; }} {P} .code .fn {{ color:{A[1]}; }} {P} .code .st {{ color:{A[3]}; }}
{P} .ccur {{ width:16px;height:32px;background:{A[0]};display:inline-block;margin-inline-start:52px; }}
{P} .dl {{ display:flex;gap:16px;white-space:nowrap;border-radius:8px;padding:4px 10px;margin:3px 0; }}
{P} .dl span {{ width:22px;flex:0 0 auto;font-weight:900; }}
{P} .dl.del {{ background:#FFF1F2;color:#9F1239; }}
{P} .dl.add {{ background:#F0FDF4;color:#166534; }}
{P} .vchips {{ display:flex;gap:18px;justify-content:center;flex-wrap:wrap;direction:{D}; }}
{P} .vchip {{ display:flex;align-items:center;gap:14px;font-size:42px;font-weight:900;
 background:#FFFFFF;color:#18181B;border:2px solid #D4D4D8;border-radius:999px;padding:16px 30px; }}
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
 background:#FFFFFF;color:#18181B;border:1px solid #E4E4E7;border-radius:14px;padding:16px 22px;
 box-shadow:0 8px 24px rgba(0,0,0,.12); }}
{P} .kt {{ width:36px;height:36px;flex:0 0 auto; }}
{P} .lgrow {{ display:flex;align-items:center;gap:16px;font-size:36px;font-weight:800;
 background:#FFFFFF;color:#18181B;border:1px solid #E4E4E7;border-radius:14px;padding:14px 20px;
 box-shadow:0 8px 24px rgba(0,0,0,.12); }}
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
{P} .doodle {{ width:640px;max-width:100%; }}
{P} .doodle svg {{ width:100%;height:auto;display:block;overflow:visible; }}
/* Hand-drawn marks overlay the artifact rather than stacking under it - a mark
   beside the thing it points at is a decoration, not an annotation. Plain
   strokes only: nothing here spends the heavy-overlay budget. */
{P} .dwrap {{ position:relative; }}
{P} .dwrap > svg.dmarks {{ position:absolute;inset:0;width:100%;height:100%;
 pointer-events:none;overflow:visible; }}
/* Marks with no authored SVG under them have nothing to size against. */
{P} .dwrap > svg.dmarks:only-child {{ position:relative;aspect-ratio:1/1; }}
{P} .imgframe {{ width:820px;border-radius:32px;overflow:hidden;position:relative;
 box-shadow:0 30px 80px rgba(0,0,0,.7); }}
{P} .imgframe.soft {{ border:2px solid rgba(255,255,255,.14); }}
{P} .imgframe.bare {{ border:0;box-shadow:none;background:transparent; }}
{P} .imgframe img {{ width:100%;height:auto;display:block; }}
{P} .imgcap {{ font-size:44px;font-weight:800;text-align:center;opacity:.92;
 text-shadow:0 4px 20px rgba(0,0,0,.8); }}
{P} .imglabel {{ position:absolute;right:22px;top:22px;z-index:2;padding:11px 22px 13px;
 border-radius:18px;background:rgba(9,11,17,.94);border:2px solid rgba(255,255,255,.20);
 box-shadow:0 10px 30px rgba(0,0,0,.48);color:#FFFFFF; }}
{P} .imglabeltext {{ font-size:43px;font-weight:900;line-height:1.05;white-space:nowrap;
 text-shadow:0 3px 12px rgba(0,0,0,.55); }}
{P} .imgbehind {{ position:absolute;inset:0;z-index:0;opacity:.55; }}
{P} .imgbehind img {{ width:100%;height:100%;object-fit:cover;display:block; }}{canvas_css}
{P} .missing {{ width:800px;border:3px dashed {A[4]};border-radius:28px;padding:40px;
 background:rgba(20,10,14,.75);color:#ffd7dd;font-size:34px;font-weight:800;line-height:1.35;direction:{D}; }}
{scale_css}
""".strip()


# ------------------------------------------------------ mandatory hook title
# The hook is a generated editorial layer, not a copy of the opening caption.
# Selection is deterministic so video-in/video-out never blocks on a question.
HE_HOOK_RULES = [
    ({"נתקע", "להילחם", "לבד", "עזרה", "דגל"},
     ["נתקעתם? אל תשחקו אותה גיבורים", "אם נתקעתם בשקט - כבר טעיתם", "זו לא עצמאות. זו טעות."]),
    ({"טעות", "נכון", "לא נכון"},
     ["רוב האנשים טועים דווקא כאן", "זה נשמע נכון. זה לא.", "הטעות שלא רואים בזמן"]),
    ({"עבודה", "משרה", "ראיון"},
     ["זה מה שלא מספרים בראיון", "הטעות שמפילה מועמדים", "רגע לפני שאתם עונים"]),
]


def select_hook(words, lang):
    """Return (winner, runners_up, rationale) from transcript words.

    Hooks are short pattern interrupts with tension/curiosity. Accurate lesson
    summaries are deliberately not candidates. More language packs can be added
    without changing the build contract.
    """
    text = " ".join(str(w.get("text", "")) for w in words).lower()
    if str(lang).lower().split("-")[0] in ("he", "iw"):
        best = None
        for cues, candidates in HE_HOOK_RULES:
            score = sum(1 for cue in cues if cue in text)
            if best is None or score > best[0]: best = (score, candidates, cues)
        if best and best[0]:
            return best[1][0], best[1][1:3], "matched transcript tension cues: " + ", ".join(sorted(c for c in best[2] if c in text))
        # Still a pattern interrupt, never a documentary title.
        return "רגע - אתם בטוחים שזה נכון?", ["כאן רוב האנשים מפספסים", "זה נשמע הגיוני. עד שזה קורה."], "Hebrew curiosity fallback"
    first = " ".join(w.get("text", "") for w in words[:7]).strip(" .,!?")
    return "Wait - this changes the answer", ["Most people miss this part", "It sounds right. It isn't."], "generic tension fallback; opening context: " + first


def ensure_mandatory_hook(project, plan, words, _style=None, dur=None):
    """Materialize a mandatory hook beat and a review report.

    The hook may overlap speech, but not another graphic. A graphic occupying
    its opening window is delayed behind it, then re-cut so what is left still
    holds for the profile's minimum dwell - extended when the next beat leaves
    room, dropped when it does not. It used to be left at whatever remained,
    which is how a 4.9s beat became a 1.3s one under a profile that holds a
    layout 2-4s: the build emitted a plan its own pacing gate rejects.
    """
    lang = plan.get("meta", {}).get("lang", "en")
    hook = plan.get("hook") or {}
    title = str(hook.get("title") or "").strip()
    runners = hook.get("runnersUp") or []
    rationale = hook.get("rationale") or "authored hook"
    if not title:
        title, runners, rationale = select_hook(words, lang)
    # The hook belongs to the REEL, not to a slice of it. segmentrender builds
    # every segment as its own project, so this ran once per segment: a title
    # lockup landing again at 12s and at 24s, and the first beat of each later
    # segment shoved past a hook window that had no business being there. A
    # segment that does not start the reel carries no hook.
    if float(plan.get("meta", {}).get("reelOffset", 0) or 0) > 0:
        plan["beats"] = [b for b in plan.get("beats", []) if b.get("id") != "reelkit-hook"]
        return title, runners[:3]
    end = round(min(4.0, max(2.6, float(hook.get("end", 3.6)))), 2)
    # Under a profile that asks for it the hook IS the title lockup, and it
    # opens on frame 0 rather than fading in after a lead-in. base keeps the
    # hero card, so nothing changes for a reel that predates the treatment.
    tcfg = (_style or {}).get("title") or {}
    hk = dict(hook.get("lockup") or {})
    if tcfg.get("lockup"):
        kind = "lockup"
        data = {"main": hk.get("main") or title, "script": hk.get("script", ""),
                "highlight": hk.get("highlight", ""),
                "accentStyle": hk.get("accentStyle") or tcfg.get("accentStyle", "marker"),
                "accentColor": tcfg.get("highlightColor"),
                "wordStep": tcfg.get("wordStep", 0.085)}
    else:
        kind = "hero"
        data = {"text": title, "note": "", "rtl": cards_lang_direction(lang) == "rtl"}
    hook_beat = {"id": "reelkit-hook", "start": 0.0, "end": end,
                 "kind": kind, "mode": "top",
                 "intent": "mandatory scroll-stop hook",
                 "layout": {"top": 48, "scale": 0.72},
                 "data": data}
    beats = sorted([b for b in plan.get("beats", []) if b.get("id") != "reelkit-hook"],
                   key=lambda x: float(x.get("start", 0)))
    # What the beat has to still hold for once the hook has taken its opening.
    # Under a profile that enforces pacing that is the profile's own minimum, so
    # the build cannot emit what the gate rejects; with pacing off it is the old
    # half-second, and a plan that predates the house style behaves as before.
    lo, _hi = style.dwell_window(_style or {})
    floor = max(0.5, float(lo)) if lo else 0.5
    kept = []
    for i, b in enumerate(beats):
        b = dict(b)
        if float(b.get("start", 0)) < end and float(b.get("end", 0)) > 0:
            b["start"] = end
            if float(b["end"]) - end < floor:
                # Extend into the gap before the next beat rather than leave a
                # runt; drop the beat when there is no gap to extend into. The
                # face carries the moment either way - captions still run.
                want = round(end + floor, 2)
                nxt = next((float(x["start"]) for x in beats[i + 1:]
                            if float(x["start"]) > end), None)
                lim = [v for v in (None if nxt is None else nxt - BEAT_GAP, dur)
                       if v is not None]
                if lim and want > min(lim):
                    continue
                b["end"] = want
        kept.append(b)
    plan["hook"] = {"title": title, "runnersUp": runners[:3], "rationale": rationale,
                    "autoSelected": not bool(hook.get("title")), "style": "scroll-stop-v1"}
    plan["beats"] = [hook_beat] + kept
    report = ["# Hook selection", "", f"**Selected:** {title}", "", f"Reason: {rationale}", "", "## Runners-up"]
    report += [f"- {x}" for x in runners[:3]] or ["- none"]
    open(os.path.join(project, "HOOKS.md"), "w", encoding="utf-8").write("\n".join(report) + "\n")
    return title, runners[:3]


# ------------------------------------------------------------------ build
def caption_band(project, plan, br, W, H, beats):
    """Where the caption band sits, measured against the speaker rather than
    assumed. Returns (top, height).

    A fixed top is a guess about framing. 1500 clears a mid-shot and lands on
    the chin of a closer one, which is exactly what happened on the runner: a
    band authored at 1500 met a head reaching y=1515 and the face-zone gate
    refused the render. The head is measured at the same timestamps the gate
    samples, so the two cannot disagree about where it is.

    The band only ever moves DOWN. An author who wants captions lower keeps
    their value; doctrine wins when theirs would touch the face. The margin is
    the first thing given up when the canvas runs out of room - clearing the
    head is the rule, the breathing room is the preference - and if even that
    does not fit, the band stays where it lands and verify refuses it. Build is
    not the gate.

    No detected head means no information, never "nothing to avoid": the
    authored value stands and the gate still has to pass on its own.
    """
    cfg = plan.get("captions", {})
    top = int(cfg.get("top", br["captionTop"]))
    hgt = int(cfg.get("height", br["captionHeight"]))
    vid = os.path.join(project, "public", "input-video.mp4")
    if not os.path.exists(vid):
        return top, hgt
    times = {b["id"]: [b["start"] + (b["end"] - b["start"]) * f for f in (0.2, 0.5, 0.8)]
             for b in beats}
    faces = detect_faces(vid, times, W, H, cache_dir=project)
    if not faces:
        return top, hgt
    # The lowest the head reaches anywhere a card is on screen. The gate errors
    # on the first beat whose head the band touches, so the strictest beat is
    # the one that decides the band.
    rects = [r for r in (head_rect(f) for f in faces.values()) if r]
    if not rects:
        return top, hgt
    lowest = max(r[1] + r[3] for r in rects)
    # The mouth check uses the median face and asks for 40px; clearing the jaw
    # of the worst beat clears it, but ask for both so neither gate is a
    # surprise on footage where the head barely moves.
    med = [statistics.median([f[i] for f in faces.values()]) for i in range(4)]
    need = max(lowest, med[1] + med[3] * 0.75 + 40)
    want = int(need) + HEAD_MARGIN
    if want > top:
        was = top
        # Never off the bottom of the canvas: a band pushed past H - height is
        # clipped, and a clipped caption fails silently. When no position both
        # fits and clears the head the band stays on canvas and verify refuses
        # the reel - loud beats invisible.
        top = min(want, max(0, H - hgt))
        print(f"reelkit: caption band y={was} -> {top} (the head reaches "
              f"y={int(need)}; captions clear it by {top - int(need)}px)")
    return top, hgt


def fit_pass(project, plan, W, H, already):
    """Resolve every over-the-footage card against what was actually rendered.

    Runs after the cards exist, because a card's height is content-driven and
    only a browser knows it. Returns (layouts_to_apply, blocked) where blocked
    names the beats no layout can save - those stop the build rather than
    reaching a render that the verify gate would fail anyway.

    Skipped silently when Playwright or OpenCV is absent: build is not the gate,
    `verify` is, and it still refuses to let an unmeasured reel through."""
    vid = os.path.join(project, "public", "input-video.mp4")
    beats = [b for b in plan["beats"] if b.get("mode", "top") in ("top", "stage")]
    if not beats or not os.path.exists(vid):
        return {}, []
    boxes = measure_cards(project, plan, W, H)
    if not boxes:
        return {}, []
    times = {b["id"]: [b["start"] + (b["end"] - b["start"]) * f for f in (0.2, 0.5, 0.8)]
             for b in beats}
    faces = detect_faces(vid, times, W, H, cache_dir=project)
    if not faces:
        return {}, []
    out, blocked = {}, []
    for b in beats:
        cid = b["id"]
        lay, why = fit_layout(boxes.get(cid), faces.get(cid), b.get("layout"), head_clear_y)
        if why:
            blocked.append((cid, why))
        elif lay is not None and lay != (b.get("layout") or {}):
            if already and already.get(cid) == lay:
                continue                    # already applied; do not loop
            out[cid] = lay
    return out, blocked


def build(project, _layouts=None, _pass=1):
    plan_path = os.path.join(project, "plan.json")
    if not os.path.exists(plan_path):
        die("no plan.json in project - see references/plan-schema.md")
    plan = json.load(open(plan_path, encoding="utf-8"))
    # Pass 2 rebuilds with the layouts the fit pass resolved against measured
    # geometry. plan.json is never touched: build stays a pure function of the
    # plan plus the media, so the same inputs still produce the same HTML.
    if _layouts:
        for b in plan["beats"]:
            if b["id"] in _layouts:
                b["layout"] = _layouts[b["id"]]
    meta = plan.get("meta", {})
    fps = int(meta.get("fps", 30)); W = int(meta.get("width", 1080)); H = int(meta.get("height", 1920))
    # The style profile: code defaults -> profile -> plan -> per-beat. `plan.style`
    # names one; absent means the house profile. The profile's brand is a
    # default the plan can still override, which is what keeps brand nested by
    # reference rather than folded in.
    sty, sty_prov = style.for_plan(plan)
    an = Anim(fps)
    if plan.get("brand") is None and sty.get("brand") is not None:
        plan = dict(plan, brand=sty["brand"])
    br = load_brand(project, plan)
    caps_cfg = style.captions(sty, plan, br)
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

    hook_title, hook_runners = ensure_mandatory_hook(project, plan, words, _style=sty, dur=dur)
    hosts, tls, visuals, missing = [], [], [], []

    # ---- video framing: base scale + optional clause-driven punch-ins ------
    fr = plan.get("framing", {})
    base = float(fr.get("scale", 1.0))
    origin = fr.get("origin", "50% 30%").replace("%", "\\u0025")
    tls.append(f"tl.set('#video-wrap',{{transformOrigin:'{origin}',scale:{base}}},0);")
    for p in fr.get("punches", []):
        tls.append(f"tl.fromTo('#video-wrap',{{scale:{round(base*float(p['from']),4)}}},"
                   f"{{scale:{round(base*float(p['to']),4)},duration:{p.get('dur',0.9)},"
                   f"ease:'power2.inOut'}},{an.q(p['at'])});")

    # Progress sections take their timing from the SPEECH. Resolved here, where
    # the transcript is in hand, so the card builder stays a pure function of
    # its data and a re-cut moves the sequence with it.
    for b in plan["beats"]:
        if b.get("kind") == "progress":
            dd = b.setdefault("data", {})
            dd["sections"] = pgmod.resolve_cues(dd.get("sections") or [], words,
                                                float(b["start"]), float(b["end"]))

    # PiP: the head insets to a corner for the beat and returns. The framing
    # scale stays on #video-wrap, so the two transforms compose instead of
    # fighting each other.
    for b in plan["beats"]:
        if b.get("mode") == "pip":
            tls.extend(pipmod.tweens(b["id"], W, H, float(b["start"]), float(b["end"]),
                                     an, pip=b.get("pip")))

    # ---- static checks before anything is written -------------------------
    warn = []
    srt = sorted(plan["beats"], key=lambda b: float(b["start"]))
    # Face-first editorial contract. A full-frame still is a slideshow, not
    # talking-head B-roll. Full mode is reserved for moving footage that proves
    # or demonstrates the spoken claim. Decorative images stay small, or go.
    for b in srt:
        mode = b.get("mode", "top")
        if mode not in ("top", "stage", "split", "full", "pip"):
            die(f"beat {b.get('id','?')}: unknown mode {mode!r}")
        if mode == "pip":
            # Face full frame is the default; PiP is the justified exception.
            bad = pipmod.problems(b, W, H, int(plan.get("captions", {}).get(
                "top", br["captionTop"])), plan.get("captions", {}).get("enabled", True))
            if bad:
                die(f"beat {b['id']}: " + "\n  ".join(m for _l, _i, m in bad))
        if mode == "full":
            if b.get("image"):
                die(f"beat {b['id']}: full-screen still images are not allowed; "
                    "use directly relevant moving B-roll via `broll.src`, or keep the speaker visible")
            src = (b.get("broll") or {}).get("src", "")
            if not src:
                die(f"beat {b['id']}: full mode requires directly relevant moving B-roll in `broll.src`")
            if src.startswith(("/", "http:", "https:")) or ".." in src.split("/"):
                die(f"beat {b['id']}: broll.src must be a project-relative file under public/")
            if not src.lower().endswith((".mp4", ".webm")):
                die(f"beat {b['id']}: B-roll must be MP4 or WebM video, not a still")
            if not os.path.exists(os.path.join(pub, src)):
                die(f"beat {b['id']}: B-roll file public/{src} is missing")
    for i in range(len(srt) - 1):
        if float(srt[i]["end"]) > float(srt[i + 1]["start"]) + 1e-6:
            warn.append(f"beats {srt[i]['id']} and {srt[i+1]['id']} overlap "
                        f"({srt[i]['end']} > {srt[i+1]['start']}) - both will render")
    for b in plan["beats"]:
        if float(b["start"]) >= dur:
            warn.append(f"beat {b['id']} starts at {b['start']}s, past the media ({dur}s) - it will never show")

    # ---- face-aware split canvases ----------------------------------------
    # A fixed canvas height cannot be safe on arbitrary framing: a tight
    # close-up puts the eyes where a loose wide shot has empty air. Resolve
    # each split beat's canvas against the detected head and persist the
    # result into plan.json, so build and verify reason about the same pixels.
    splits = [b for b in plan["beats"] if b.get("mode") == "split"]
    if splits:
        ftimes = {b["id"]: [float(b["start"]) + (float(b["end"]) - float(b["start"])) * f
                            for f in (0.2, 0.5, 0.8)] for b in splits}
        faces = detect_faces(vid, ftimes, W, H, cache_dir=project)
        if faces:
            changed = False
            for b in splits:
                px, cleared = split_canvas_h_face(b.get("layout"), H, faces.get(b["id"]))
                cur = split_canvas_h(b.get("layout"), H)
                hr = head_rect(faces.get(b["id"]))
                if not cleared:
                    warn.append(f"beat {b['id']}: the speaker's head starts at y="
                                f"{int(hr[1]) if hr else '?'}px - even the minimum split "
                                f"canvas would sit on it; this framing is too tight for "
                                f"split mode, use B-roll (mode 'full') for this beat")
                elif px != cur:
                    b.setdefault("layout", {})["canvas"] = px
                    changed = True
                    print(f"reelkit: split {b['id']} canvas {cur}px -> {px}px "
                          f"(capped clear of the speaker's head at y={int(hr[1]) if hr else '?'})")
            if changed:
                json.dump(plan, open(plan_path, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)
        else:
            print("reelkit: note - no head detected in the footage; split canvases keep "
                  "their requested height (verify enforces the boundary when a head is found)")

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
        broll = beat.get("broll") or {}
        img_file = os.path.join(pub, "images", f"{cid}.png")
        has_img = bool(img) and os.path.exists(img_file)

        # A canvas beat carries its picture in data.image rather than the
        # top-level image block, because its box is not authorable: the panel's
        # height is resolved per beat against the detected face, so the slot's
        # shape only exists once the canvas does. Everything downstream - the
        # file path, visuals.json, the loud placeholder - is the same path.
        canvas_h = split_canvas_h(beat.get("layout"), H) if mode == "split" else 0
        cimg = beat.get("data", {}).get("image") if mode == "split" else None
        if cimg and img:
            die(f"beat {cid}: a split beat declares both the top-level image block "
                f"and data.image - they would claim the same file and fight over the "
                f"layout. Keep data.image; the top-level block is for the other modes")
        cfit = (cimg or {}).get("fit", "wide")
        has_cimg = bool(cimg) and os.path.exists(img_file)
        if cimg:
            cbox = canvas_image_box(canvas_h, cfit, br.get("_dir", "rtl"), W)
            visuals.append({
                "id": cid, "start": st, "end": en, "kind": kind,
                "file": f"public/images/{cid}.png", "present": has_cimg,
                "box": {"x": cbox[0], "y": cbox[1], "w": cbox[2], "h": cbox[3]},
                "aspect": round(cbox[2] / cbox[3], 3),
                "alpha": False, "mode": "canvas",
                "prompt": cimg.get("prompt", ""),
                "intent": beat.get("intent", ""),
            })
            if not has_cimg:
                missing.append(cid)

        if img:
            # Derived, never authored. A plan-supplied box was advisory and drifted
            # from the CSS that actually lays the frame out, so a generator made
            # artwork for a box that did not exist. `full` never reaches here -
            # a still image in full mode is rejected in the static checks above.
            if img.get("box"):
                warn.append(f"beat {cid}: image.box is ignored - the slot box is "
                            f"derived from the CSS; delete it from the plan")
            box = image_slot_box(mode, beat.get("layout"),
                                 wants_plate(kind, beat), W)
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

        # B-roll: in `full` mode a present image IS the frame, edge to edge, so
        # it must not also be drawn as a framed card floating on top of itself.
        broll_img = mode == "full" and has_img
        if broll_img:
            cap = img.get("caption") or beat.get("data", {}).get("caption")
            if kind == "image":
                        if cap else "")
                g = ([an.slide(f"'.card[data-card-id=\"{cid}\"] #{cid}-bcap'",
                               st + 0.30, 0.40, dy=24)] if cap else [])
            else:
                an.use(style.motion_for(sty, kind))
                body, g = KINDS[kind](cid, beat.get("data", {}), br, an, st, en)
        elif has_img and img.get("mode", "replace") == "replace":
            an.use(style.motion_for(sty, "image"))
            body, g = KINDS["image"](cid, {
                "caption": img.get("caption") or beat.get("data", {}).get("caption"),
                "frame": "bare" if img.get("alpha") else img.get("frame", "soft"),
                "zoom": img.get("zoom", 1.08),
                "label": img.get("label"),
                # Annotation belongs to the artifact even when an image slot
                # resolves `kind:image` through the replacement path.
                "marks": beat.get("data", {}).get("marks", []),
                "drawSeconds": beat.get("data", {}).get("drawSeconds", 0.40)},
                br, an, st, en)
        elif kind == "image" and not has_img:
            # honest placeholder: renders, lints, and screams in the preview
            p = esc((img or {}).get("prompt", "") or beat.get("intent", ""))
            body = (f'<div class="stagewrap"><div class="missing">IMAGE SLOT <b>{cid}</b> '
                    f'&mdash; drop a PNG at public/images/{cid}.png<br/><br/>{p}</div></div>')
            g = [an.fade(f"'.card[data-card-id=\"{cid}\"] .missing'", st + 0.1, 0.3)]
        else:
            kbr = dict(br, _canvasImg=has_cimg) if cimg else br
            an.use(style.motion_for(sty, kind))
            body, g = KINDS[kind](cid, beat.get("data", {}), kbr, an, st, en)
            if has_img:   # mode == "behind"
                body = (f'<div class="imgbehind" id="{cid}-bg"><img src="images/{cid}.png" alt=""/></div>'
                        + body)
                g.append(an.fade(f"'.card[data-card-id=\"{cid}\"] #{cid}-bg'", st + 0.05, 0.5))


        if beat.get("takeover") is not None:
            warn.append(f"beat {cid}: `takeover` no longer does anything - `full` is "
                        f"always a B-roll takeover now, and no other mode dims the "
                        f"speaker. Remove the key")
        if mode == "split":
            # No scrim: the speaker below the canvas plays undimmed. The canvas
            # is a LIGHT surface with dark text, and it is opaque rather than a
            # tint over the frame.
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
            ground = ""
        elif mode == "full":
            # `full` is B-roll: the frame is REPLACED, not tinted. Either the
            # beat's own image fills it edge to edge or the brand ground does.
            # Nothing translucent, because a half-visible speaker behind a card
            # is the thing this mode exists to stop being.
            bsrc = esc(broll["src"])
            trim = float(broll.get("trim", 0))
            span = max(0.1, en - st)
            # HyperFrames owns source seeking. The media is inside a registered
            # sub-composition, so its local zero is the beat host's `start`.
            ground = (f'<div class="broll" id="{cid}-broll">'
                      f'<video id="{cid}-broll-video" src="{bsrc}" muted playsinline preload="auto" '
                      f'data-start="0" data-duration="{span}" data-media-start="{trim}" '
                      f'data-track-index="0"></video></div>')
            g.insert(0, an.fade(f"'.card[data-card-id=\"{cid}\"] #{cid}-broll'", st, 0.18))
        else:
            # top / stage: nothing at all over the footage. Separation, where a
            # card needs it, is the plate below - local to the card.
            ground = ""
        if mode != "split" and wants_plate(kind, beat) and body:
            body = f'<div class="plate" id="{cid}-plate">{body}</div>'
        frag = (f'<div class="card" data-card-id="{cid}">\n<style>\n'
                f'{card_css(cid, mode, br, beat.get("layout"), canvas_h, cfit, bool(cimg), kind)}\n</style>\n'
                f'<div class="root">{ground}{body}</div>\n</div>')
        open(os.path.join(pub, "cards", f"{cid}.html"), "w", encoding="utf-8").write(frag)
