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
import audiomix, captionfx, lottiefx, pip as pipmod, progress as pgmod, style  # noqa: E402

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
                body = (f'<div id="{cid}-bcap" class="brollcap">{esc(cap)}</div>'
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
                "label": img.get("label")}, br, an, st, en)
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
                     f'data-no-timeline data-start="{st:.4f}" data-duration="{en-st:.4f}" data-track-index="2" '
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
    # Resolved before the band is drawn and recorded in built-beats.json, so the
    # gate measures the band that was BUILT rather than the one that was
    # authored - the same reason it reads the built beats.
    cap_on = plan.get("captions", {}).get("enabled", True)
    cap_top, cap_h = caption_band(project, plan, br, W, H, plan["beats"])
    caps = []
    if cap_on and words:
        caps = caption_clips(words, br, dur, an, caps_cfg)
        hi = (plan.get("captions", {}).get("highlight") or
              br.get("captionHighlight") or br["accents"][0])
        top, hgt = cap_top, cap_h
        emph = captionfx.normalise(plan.get("captions", {}).get("emphasis"))
        det_cfg = caps_cfg.get("detonate") or {}
        for cp in caps:
            ws = "".join(
                captionfx.word_span(f'{cp["id"]}-w{j}', w["text"], captionfx.rule_for(w["text"], emph))
                for j, w in enumerate(cp["words"]))
            # A detonated keyword replaces its line for the line's duration and
            # renders INSIDE the caption band - it is a caption, not an overlay,
            # so it cannot drift onto the face.
            det = [(j, w, r) for j, w in enumerate(cp["words"])
                   if (r := captionfx.rule_for(w["text"], emph)) and r["style"] == "detonate"]
            if det:
                j, w, r = det[0]
                ws = captionfx.detonation_svg(
                    f'{cp["id"]}-det', w["text"], r["emoji"], W, hgt,
                    hi, caps_cfg.get("strokeColor", "#05060A"),
                    int(caps_cfg.get("strokeWidth", 0) or 0), br["font"])
            frag = (f'<div class="card" data-card-id="{cp["id"]}">\n<style>\n'
                    f'.card[data-card-id="{cp["id"]}"] .root {{ width:100%;height:100%;display:flex;'
                    f'align-items:center;justify-content:center; }}\n</style>\n'
                    f'<div class="root"><div class="capline" dir="{DIRC}">{ws}</div></div>\n</div>')
            s, e = cp["start"], cp["end"]
            hosts.append(f'<div class="card-host clip cap-host" id="caption-{cp["id"]}" data-card-id="{cp["id"]}" '
                         f'data-composition-id="{cp["id"]}" data-no-timeline data-start="{s:.4f}" data-duration="{e-s:.4f}" '
                         f'data-track-index="3" style="left:0;top:{top}px;width:{W}px;height:{hgt}px;'
                         f'visibility:hidden;opacity:0;">\n{frag}\n</div>')
            sel = f"'.card-host[data-card-id=\"{cp['id']}\"]'"
            tls.append(f"tl.set({sel},{{visibility:'visible'}},{s});")
            tls.append(f"tl.fromTo({sel},{{opacity:0,y:14}},{{opacity:1,y:0,duration:0.16,ease:'power2.out'}},{s});")
            if det:
                # The word spans are gone - the line IS the keyword now. Pop and
                # spring it in place; nothing moves it, so it stays in the band.
                dsel = f"'.card[data-card-id=\"{cp['id']}\"] #{cp['id']}-det'"
                tls.append(f"tl.fromTo({dsel},{{opacity:0,scale:{det_cfg.get('fromScale', 0.62)}}},"
                           f"{{opacity:1,scale:1,duration:{det_cfg.get('duration', 0.42)},"
                           f"ease:'{det_cfg.get('ease', 'back.out(2.4)')}',immediateRender:false}},"
                           f"{an.q(max(s, cp['words'][det[0][0]]['start'] - 0.06))});")
            for j, w in enumerate(cp["words"]):
                if det:
                    break                 # no per-word karaoke on a detonated line
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

    # Lottie badges. Validated (licence recorded, no gradients/masks, no external
    # assets) before anything is staged, so a bad asset fails the build rather
    # than the render.
    badge_html, badge_js, badge_names = [], [], []
    for b in plan["beats"]:
        bd = b.get("badge")
        if not bd:
            continue
        if isinstance(bd, str):
            bd = {"name": bd}
        name = bd.get("name")
        if not name:
            die(f"beat {b['id']}: badge needs a `name`")
        bad = sorted(set(bd) - {"name", "corner", "size", "at"})
        if bad:
            die(f"beat {b['id']}: unknown badge key(s) {', '.join(bad)} "
                "(allowed: name, corner, size, at)")
        lottiefx.load(SKILL, name)          # raises on licence / cost / shape
        html, js = lottiefx.markup(b["id"], name, bd, W, H)
        st_b, en_b = float(b["start"]), float(b["end"])
        badge_html.append(f'<div class="clip" data-start="{st_b:.4f}" '
                          f'data-duration="{en_b - st_b:.4f}" data-track-index="4">{html}</div>')
        badge_js.append(js)
        badge_names.append(name)
        g_at = an.q(st_b + float(bd.get("at", 0.12)))
        tls.append(f"tl.fromTo('#{b['id']}-badge',{{opacity:0,scale:0.7}},"
                   f"{{opacity:1,scale:1,duration:0.34,ease:'back.out(2)',"
                   f"immediateRender:false}},{g_at});")
    if badge_names:
        # Staged at BUILD time, not scaffold: a project scaffolded before badges
        # existed would otherwise reference a player that is not there, and the
        # failure would only appear at render.
        os.makedirs(os.path.join(pub, "vendor"), exist_ok=True)
        src_player = os.path.join(SKILL, "assets", "vendor", "lottie.min.js")
        if not os.path.exists(src_player):
            die("badges are declared but assets/vendor/lottie.min.js is missing - "
                "the player is vendored, never fetched at render time")
        shutil.copy2(src_player, os.path.join(pub, "vendor", "lottie.min.js"))
    for name in sorted(set(badge_names)):
        os.makedirs(os.path.join(pub, "lottie"), exist_ok=True)
        shutil.copy2(os.path.join(SKILL, "assets", "lottie", f"{name}.json"),
                     os.path.join(pub, "lottie", f"{name}.json"))

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
{theme_css(br, caps_cfg, sty.get('title'))}
</style></head>
<body>
<div id="stage" data-composition-id="reelkit" data-start="0"
 data-duration="{dur}" data-fps="{fps}" data-width="{W}" data-height="{H}">
<div id="pip-frame"><div class="video-wrapper" id="video-wrap">
<video id="bg-video" src="input-video.mp4" muted playsinline data-start="0"
 data-duration="{dur}" data-track-index="1"></video></div></div>
<audio id="source-audio" src="input-video.mp4" data-start="0" data-duration="{dur}"
 data-track-index="10" data-volume="{plan.get('audio',{}).get('sourceVolume',1)}"></audio>
{"".join(sfx_tags)}{music_tag(plan, pub, dur, voice_envelope(project))}
<div class="bottomveil"></div>
{"".join(hosts)}
{"".join(badge_html)}
<script src="vendor/gsap.min.js"></script>
{'<script src="vendor/lottie.min.js"></script>' if badge_js else ''}
{('<script>' + "".join(badge_js) + '</script>') if badge_js else ''}
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

    refit, blocked = fit_pass(project, plan, W, H, _layouts) if _pass == 1 else ({}, [])
    if blocked:
        die("card geometry cannot clear the speaker's head:\n" +
            "\n".join(f"  {cid}: {why}" for cid, why in blocked))
    if refit:
        for cid, lay in sorted(refit.items()):
            print(f"reelkit: fit {cid} -> {lay} (measured against the detected head)")
        return build(project, refit, _pass=2)

    for w in warn:
        print(f"reelkit: ! {w}")
    print(f"reelkit: {len(plan['beats'])} beats, {len(caps)} caption lines, "
          f"{len(tls)} timeline statements, duration {dur}s")
    if visuals:
        print(f"reelkit: {len(visuals)} image slot(s); "
              f"{len(visuals)-len(missing)} present, {len(missing)} missing")
    for m in missing:
        print(f"  ! missing image: public/images/{m}.png")
    # The reel records the style that produced it: name, version and the digest
    # of every file in the extends chain. A profile that moves under a finished
    # reel is then visible rather than inferred - and segment_key() hashes
    # assets/style/ for the same reason, so a profile edit invalidates cached
    # segments instead of silently resuming pre-edit pixels.
    json.dump(sty_prov, open(os.path.join(project, "style-used.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # The beats that were actually BUILT, hook included. verify reads plan.json,
    # and the mandatory hook is materialised here rather than written back to the
    # plan - so the one card on screen at frame 0 of every reel was never
    # measured against the head zone. It is now, because the gate reads this.
    json.dump({"beats": plan["beats"],
               "captions": dict(plan.get("captions", {}),
                                enabled=cap_on, top=cap_top, height=cap_h)},
              open(os.path.join(project, "built-beats.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"reelkit: style {sty_prov['profile']} v{sty_prov['version']}"
          + (f" (extends {' -> '.join(sty_prov['extends'])})" if sty_prov["extends"] else "")
          + f", captions {caps_cfg['maxWords']} word(s)/line")
    print(f"reelkit: hook selected: {hook_title}")
    for runner in hook_runners: print(f"reelkit: hook runner-up: {runner}")
    print("reelkit: wrote public/index.html, visuals.json, BEATS.md, HOOKS.md")
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
    print(f"            (cd {project} && npx {HF} check public)")
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
    # -map_chapters -1: a phone source can carry chapters (so can an exported
    # music-tool render), they are global metadata that no -map touches, and the
    # mp4 muxer writes them out as a bin_data track further down the pipeline.
    cmd = ["ffmpeg", "-y", "-i", src, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
           "-map_chapters", "-1", "-r", str(fps), "-c:v", "libx264", "-crf", "17", "-preset", "medium",
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


BUNDLED_SFX = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "assets", "sfx")


def find_sfx_dir(explicit=None):
    """Locate the SFX library.

    media-use first when it is installed - its Pixabay-licensed files are richer,
    and they can be used inside a rendered video even though they cannot be
    re-hosted here. Then reelkit's own CC0 pack (assets/sfx), which ships in the
    repo and is what a clean clone, CI or a Kaggle kernel actually gets. The
    synthesized stand-ins are the last resort, per name rather than per library -
    see sfx_src()."""
    cands = ([explicit] if explicit else []) + SFX_SEARCH + [BUNDLED_SFX]
    for c in cands:
        d = os.path.expanduser(c)
        if os.path.isdir(d):
            return d
    return None


def sfx_src(sdir, name):
    """Path to one cue, falling back to the synthesized stand-in for a name the
    chosen library does not carry. Per-name, because no real library covers every
    cue: the CC0 pack has no `riser`, and a missing name used to mean silence at
    that edit point."""
    src = os.path.join(sdir, f"{name}.mp3")
    if os.path.exists(src):
        return src, sdir
    syn = os.path.join(synth_sfx_dir(), f"{name}.mp3")
    if os.path.exists(syn):
        print(f"reelkit: sfx '{name}' not in the library - synthesized stand-in")
        return syn, os.path.dirname(syn)
    return None, sdir


_SR = 44100


def _wavr(samples):
    """16-bit mono PCM bytes from float samples."""
    import array
    a = array.array("h", (int(max(-1.0, min(1.0, x)) * 32767) for x in samples))
    return a.tobytes()


def _env(n, attack, decay):
    import math
    out = []
    for i in range(n):
        t = i / n
        out.append(min(1.0, t / max(attack, 1e-4)) * math.exp(-decay * t))
    return out


def _synth(name):
    """One synthesized stand-in for a bundled library sound. Deterministic."""
    import math, random
    rng = random.Random(name)
    sr = _SR

    def tone(f0, f1, dur, amp=0.8, decay=6.0):
        n = int(sr * dur)
        env = _env(n, 0.004, decay)
        ph = 0.0
        out = []
        for i in range(n):
            f = f0 + (f1 - f0) * (i / n)
            ph += 2 * math.pi * f / sr
            out.append(amp * env[i] * math.sin(ph))
        return out

    def noise(dur, amp=0.6, rise=0.35, lp=0):
        n = int(sr * dur)
        raw = [rng.uniform(-1, 1) for _ in range(n + 64)]
        if lp:  # cheap one-pole lowpass
            for k in range(lp):
                raw = [(raw[i] + raw[i + 1]) / 2 for i in range(len(raw) - 1)]
        out = []
        for i in range(n):
            t = i / n
            e = (min(1.0, t / rise) if t < rise else math.exp(-7 * (t - rise) / (1 - rise)))
            out.append(amp * e * raw[i])
        return out

    if name == "pop":
        return tone(150, 65, 0.14, 0.9, 9.0)
    if name in ("click", "click-soft", "key-press"):
        f = {"click": 1400, "click-soft": 900, "key-press": 2100}[name]
        a = 0.5 if name == "click-soft" else 0.7
        body = tone(f, f * 0.7, 0.05, a, 30.0)
        return body
    if name in ("whoosh", "whoosh-short", "whoosh-cinematic"):
        dur, lp, amp = {"whoosh": (0.45, 3, 0.55), "whoosh-short": (0.24, 2, 0.5),
                        "whoosh-cinematic": (0.9, 6, 0.6)}[name]
        return noise(dur, amp, rise=0.4, lp=lp)
    if name in ("impact-bass-1", "impact-bass-2"):
        f = 58 if name.endswith("1") else 72
        body = tone(f, f * 0.8, 0.4, 0.85, 5.0)
        th = noise(0.08, 0.25, rise=0.1, lp=4)
        return [body[i] + (th[i] if i < len(th) else 0) for i in range(len(body))]
    if name == "riser":
        return noise(1.1, 0.4, rise=0.97, lp=2)
    if name == "ping":
        return tone(880, 870, 0.35, 0.6, 5.0)
    if name == "chime":
        a = tone(660, 660, 0.4, 0.4, 4.0)
        b = tone(990, 990, 0.4, 0.3, 4.0)
        return [x + y for x, y in zip(a, b)]
    if name == "notification":
        a = tone(880, 880, 0.09, 0.6, 8.0)
        b = tone(1174, 1174, 0.12, 0.6, 8.0)
        return a + [0.0] * int(0.03 * sr) + b
    if name == "sparkle":
        out = []
        for f in (1320, 1760, 2200):
            out += tone(f, f, 0.08, 0.4, 10.0) + [0.0] * int(0.02 * sr)
        return out
    if name == "error":
        return tone(220, 180, 0.25, 0.5, 4.0)
    if name.startswith("glitch"):
        n = int(sr * 0.18)
        return [rng.choice([-0.5, 0.5]) * math.exp(-6 * i / n) for i in range(n)]
    if name == "typing":
        out = []
        for _ in range(4):
            out += tone(2000, 1800, 0.03, 0.4, 25.0) + [0.0] * int(0.06 * sr)
        return out
    return None


def synth_sfx_dir():
    """Procedurally generated fallback for the bundled media-use SFX library.

    The Pixabay-licensed bundle cannot be re-hosted in this repo, and on a
    clean machine (CI, Kaggle, a fresh clone) it simply is not there - which is
    how a silent export shipped. These synthesized stand-ins are created here,
    owned by reelkit, and always available. They are deliberately plain; when
    the real library is installed it wins (find_sfx_dir runs first)."""
    import wave
    d = os.path.expanduser("~/.cache/reelkit/sfx-synth")
    man = os.path.join(d, "manifest.json")
    if os.path.exists(man):
        return d
    os.makedirs(d, exist_ok=True)
    names = ["whoosh", "whoosh-short", "whoosh-cinematic", "pop", "click",
             "click-soft", "impact-bass-1", "impact-bass-2", "riser", "ping",
             "chime", "notification", "sparkle", "key-press", "error",
             "glitch-1", "glitch-2", "glitch-3", "typing"]
    manifest = {}
    for name in names:
        samples = _synth(name)
        if not samples:
            continue
        wav = os.path.join(d, name + ".wav")
        with wave.open(wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(_SR)
            w.writeframes(_wavr(samples))
        mp3 = os.path.join(d, name + ".mp3")
        r = sh(["ffmpeg", "-y", "-v", "error", "-i", wav, "-codec:a", "libmp3lame",
                "-q:a", "4", mp3])
        os.remove(wav)
        if r.returncode != 0 or not os.path.exists(mp3):
            continue
        manifest[name] = {"duration": round(len(samples) / _SR, 3)}
    json.dump(manifest, open(man, "w"), indent=1)
    return d


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


SIL_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")
SIL_START_RE = re.compile(r"silence_start:\s*(-?[0-9.]+)")


def sfx_lead_silence(path):
    """Several bundled files open with ~0.4 s of digital silence. Starting the
    clip at the cue time therefore plays the transient LATE and it misses the
    visual hit. Measure the lead-in and start the clip that much earlier.

    Only silence that begins AT THE START of the file is a lead-in. Most of the
    short sounds are the opposite shape - a transient, then trailing silence -
    and counting that as a lead-in drags the cue earlier by nearly the whole
    file. Compare the first silence_start against zero rather than pattern
    matching the log text: "silence_start: 0.185805" contains the characters
    "silence_start: 0" without starting at zero, which is how six of the
    nineteen bundled sounds (click, click-soft, key-press, pop, whoosh,
    whoosh-short) came to play up to 0.72 s early."""
    r = sh(["ffmpeg", "-i", path, "-af", "silencedetect=n=-45dB:d=0.15", "-f", "null", "-"])
    err = r.stderr or ""
    start = SIL_START_RE.search(err)
    end = SIL_END_RE.search(err)
    if not start or not end or float(start.group(1)) > 0.01:
        return 0.0
    return min(1.0, float(end.group(1)))


def chapters(path):
    """Chapter titles embedded in a media file, or []."""
    r = sh(["ffprobe", "-v", "error", "-print_format", "json", "-show_chapters", path])
    try:
        return [c.get("tags", {}).get("title", "") for c in
                json.loads(r.stdout).get("chapters", [])]
    except Exception:
        return []


def strip_chapters(path):
    """Rewrite `path` chapter-free, in place. Returns the titles it removed.

    Chapters are GLOBAL metadata, not streams, so `-map`, `-dn` and `-sn` never
    touch them: a cue carrying one rides through every mux that takes it as an
    input, and the MP4 muxer then materialises it as a `bin_data` track in the
    deliverable. That is the leak the container audit caught on Kaggle - the
    three bundled whoosh files each carry an Ableton export residue chapter
    ("Tempo: 120.0"). Every mux now passes `-map_chapters -1`; stripping on
    ingest kills the source of it as well, for libraries we do not control
    (media-use, a custom sfxDir).

    Stream copy, so it costs milliseconds and changes no audio.
    """
    titles = chapters(path)
    if not titles:
        return []
    tmp = path + ".nochap.tmp" + os.path.splitext(path)[1]
    r = sh(["ffmpeg", "-y", "-v", "error", "-i", path,
            "-map_chapters", "-1", "-map_metadata", "-1", "-c", "copy", tmp])
    if r.returncode != 0 or not os.path.exists(tmp):
        if os.path.exists(tmp):
            os.remove(tmp)
        die(f"sfx asset {os.path.basename(path)} carries chapter metadata "
            f"({', '.join(t for t in titles if t) or 'untitled'}) and it could "
            f"not be stripped:\n{r.stderr[-600:]}\nChapters become a bin_data "
            "track in the deliverable and fail the container audit.")
    os.replace(tmp, path)
    return titles


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


# ----------------------------------------------------------- auto sound ----
# Event-tied sound design, derived from the plan instead of hand-placed.
# A beat with its own `sfx` list keeps full manual control; auto fills only
# beats that say nothing. `audio.autoSfx: false` turns the whole layer off.

_AUTO_ENTRY_WHOOSH = ("whoosh-short", "whoosh")     # alternated for variety
_AUTO_UI_KINDS = {"notification", "chat", "code", "diff"}
_AUTO_HIT_KINDS = {"stat", "contrast", "donut", "bars"}


def auto_cues(plan, an):
    """Derive (beat_id -> [cue]) and absolute global cues from edit events:
    whoosh on scene changes (split/stage entries), pop on hero text landings,
    click on UI cards, soft hit on data reveals, riser into the final CTA."""
    audio = plan.get("audio", {})
    if audio.get("autoSfx") is False:
        return {}, []
    beats = plan["beats"]
    per_beat, glob, events = {}, [], []
    whoosh_i = 0
    for i, b in enumerate(beats):
        if b.get("sfx"):                       # manual cues win the beat
            continue
        cues = []
        if i > 0 and b.get("mode") in ("split", "stage", "top", "overlay"):
            # Any beat entrance is a scene change the ear should catch; the mode
            # list used to stop at split/stage, which left top-mode overlays
            # (the common case) silent.
            cues.append({"name": _AUTO_ENTRY_WHOOSH[whoosh_i % 2], "at": 0.05,
                         "volume": 0.7})
            whoosh_i += 1
        k = b["kind"]
        if k == "hero":
            cues.append({"name": "pop", "at": 0.15, "volume": 0.8})
        elif k in _AUTO_UI_KINDS:
            cues.append({"name": "click-soft", "at": 0.25, "volume": 0.7})
        elif k in _AUTO_HIT_KINDS:
            cues.append({"name": "impact-bass-2", "at": 0.3, "volume": 0.6})
        elif k in ("chips", "checklist", "quote"):
            cues.append({"name": "click-soft", "at": 0.2, "volume": 0.7})
        elif k == "image":
            cues.append({"name": "pop", "at": 0.2, "volume": 0.6})
        if cues:
            per_beat[b["id"]] = cues
            events.extend(float(b["start"]) + float(c["at"]) for c in cues)
    # riser into the final beat's reveal (absolute time, belongs to no beat)
    if len(beats) > 1:
        last = beats[-1]
        if not last.get("sfx"):
            rise_at = max(0.0, float(last["start"]) - 1.3)
            if all(abs(rise_at - e) > 0.9 for e in events):
                glob.append({"name": "riser", "at": rise_at, "volume": 0.5})
    # density cap: transients never land within 0.9 s of each other
    flat = sorted(events)
    crowded = {t for a, b in zip(flat, flat[1:]) for t in (b,) if b - a < 0.9}
    for bid, cues in list(per_beat.items()):
        b = next(x for x in beats if x["id"] == bid)
        keep = [c for c in cues if float(b["start"]) + float(c["at"]) not in crowded]
        if keep:
            per_beat[bid] = keep
        else:
            del per_beat[bid]
    return per_beat, glob


def voice_envelope(project):
    """Voice RMS envelope (dBFS) of the transcript audio in ~0.13 s windows.
    Offline ducking is possible because the voice track is known at build time."""
    ap = os.path.join(project, "audio.mp3")
    if not os.path.exists(ap):
        return None
    try:
        import numpy as np
    except Exception:
        return None
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", ap, "-ac", "1", "-ar", "8000",
                        "-f", "s16le", "-"], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    pcm = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    win = 1024
    n = len(pcm) // win
    if n == 0:
        return None
    rms = np.sqrt((pcm[:n * win].reshape(n, win) ** 2).mean(axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-6))

    def at(t):
        i0 = max(0, min(n - 1, int(t * 8000 / win)))
        i1 = max(i0 + 1, min(n, int((t + 0.45) * 8000 / win)))
        return float(db[i0:i1].max())
    return at


def music_tag(plan, pub, dur, env):
    """Optional background bed: audio.music = {"file": "...", "volume": x}.
    Gain is measured against the voice so the bed sits under speech, not at a
    guessed fixed level. Supply a track at least as long as the reel."""
    m = plan.get("audio", {}).get("music")
    if not m:
        return ""
    project = os.path.dirname(pub)
    src = m.get("file", "")
    src = src if os.path.isabs(src) else os.path.join(project, src)
    if not os.path.exists(src):
        print(f"reelkit: ! music file {src} not found - continuing without music")
        return ""
    dst = os.path.join(pub, "music" + os.path.splitext(src)[1])
    shutil.copy2(src, dst)
    vol = float(m.get("volume", 0.0))
    if vol <= 0 and env is not None:
        # aim the bed ~14 dB under the measured voice level
        speech = max(-45.0, sum(env(t) for t in
                                [x * 0.5 for x in range(2, int(dur * 2) - 1)]) / max(1, int(dur) - 1))
        r = sh(["ffmpeg", "-i", dst, "-af", "volumedetect", "-f", "null", "-"])
        mm = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", r.stderr or "")
        music_db = float(mm.group(1)) if mm else -20.0
        vol = max(0.03, min(0.5, 10 ** ((speech - 14.0 - music_db) / 20.0)))
    if vol <= 0:
        vol = 0.15
    return (f'<audio id="music-bed" class="clip" src="{os.path.basename(dst)}" '
            f'data-start="0" data-duration="{dur:.4f}" data-track-index="40" '
            f'data-volume="{round(vol, 3)}"></audio>')



def resolve_sfx(plan, pub, dur, an):
    """Collect every cue, copy the files in, and interval-partition them across
    track indices so two overlapping cues never share a track."""
    cues = []
    # relative level: 1.0 == the normalised target, so 0.8 is "a bit under"
    default_vol = float(plan.get("audio", {}).get("sfxVolume", 0.8))
    auto, auto_global = auto_cues(plan, an)
    for beat in plan["beats"]:
        for c in (beat.get("sfx") if beat.get("sfx") is not None
                  else auto.get(beat["id"], [])):
            c = {"name": c} if isinstance(c, str) else dict(c)
            cues.append({"name": c["name"],
                         "at": an.q(float(beat["start"]) + float(c.get("at", 0))),
                         "volume": float(c.get("volume", default_vol))})
    for c in (plan.get("audio", {}).get("sfx") or []) + auto_global:
        cues.append({"name": c["name"], "at": an.q(float(c["at"])),
                     "volume": float(c.get("volume", default_vol))})
    if not cues:
        return [], []

    env = voice_envelope(os.path.dirname(pub))
    duck_on = plan.get("audio", {}).get("voiceDuck", True)
    if env is not None and duck_on:
        for c in cues:
            vdb = env(c["at"])
            duck_db = max(0.0, min(7.0, (vdb + 38.0) * 0.6))
            if duck_db > 0.5:
                c["volume"] = round(c["volume"] * 10 ** (-duck_db / 20.0), 3)

    sdir = find_sfx_dir(plan.get("audio", {}).get("sfxDir"))
    if not sdir:
        sdir = synth_sfx_dir()
        print("reelkit: no sfx library found - using synthesized stand-ins "
              "(~/.cache/reelkit/sfx-synth).")

    os.makedirs(os.path.join(pub, "sfx"), exist_ok=True)
    files, out, tracks = {}, [], []          # tracks[i] = end time of last cue on track i
    for c in sorted(cues, key=lambda x: x["at"]):
        if c["name"] not in files:
            src, from_dir = sfx_src(sdir, c["name"])
            if not src:
                print(f"reelkit: ! no sfx named '{c['name']}' - skipped")
                files[c["name"]] = None
            else:
                dst = os.path.join(pub, "sfx", f"{c['name']}.mp3")
                shutil.copy2(src, dst)
                gone = strip_chapters(dst)
                if gone:
                    print(f"reelkit: stripped {len(gone)} chapter(s) from sfx "
                          f"'{c['name']}' on ingest")
                files[c["name"]] = (f"{c['name']}.mp3",
                                    sfx_duration(from_dir, c["name"], f"{c['name']}.mp3"),
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
    if plan.get("beats") and plan.get("audio", {}).get("autoSfx") is not False \
            and not out:
        die("plan has beats but zero sfx cues resolved - a silent export is a "
            "failed render. Check that every beat kind maps to a cue in "
            "auto_cues, or set audio.autoSfx: false to waive sound explicitly.")
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

    # 2. merge clauses into beats, never splitting a clause. The target is the
    # profile's own dwell window, not a constant: the house profile holds a
    # layout 2-4s, and a draft grouped to the old 5.5s emitted beats that every
    # one of its own cards would fail the pacing gate on. With pacing off the
    # old 5.5s/2.0s numbers stand, so a base-profile draft is unchanged.
    sty, _ = style.for_plan({})
    lo, hi = style.dwell_window(sty)
    close_at = (float(lo) + float(hi)) / 2 if lo and hi else 5.5
    runt = float(lo) if lo else 2.0
    beats, acc = [], []
    for cl in clauses:
        acc.append(cl)
        span = acc[-1][-1]["end"] - acc[0][0]["start"]
        if span >= close_at:
            beats.append(acc); acc = []
    if acc:
        if beats and (acc[-1][-1]["end"] - acc[0][0]["start"]) < runt:
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
        # The card's dwell, held inside the profile's window. A card does not
        # have to span the whole clause it illustrates: capping at the maximum
        # ends the graphic while the speech runs on, which is the cadence the
        # window describes. Below the minimum there is nothing to show - the
        # beat is dropped and the face carries the moment.
        if hi and en - st > float(hi):
            en = round(st + float(hi), 2)
        floor = float(lo) if lo else 0.5
        if en < st + floor:
            room = round(starts[bi + 1] - BEAT_GAP, 2) if bi + 1 < len(flats) else None
            want = round(st + floor, 2)
            if room is not None and want > room:
                continue                # no room to hold it long enough
            en = want
        low = text.lower()

        kind, data = None, {}
        if bi == 0:
            hook_title, hook_runners, hook_reason = select_hook(words, lang)
            kind, data = "hero", {"text": hook_title, "note": ""}
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

        if not kind:
            continue                    # the face is the visual; captions still run
        beat = {"id": f"b{bi+1:02d}", "start": st, "end": en,
                "kind": kind,
                "mode": "stage" if kind in ("chat", "code", "diff", "donut",
                                               "bars", "pipeline", "follow") else "top",
                "intent": text[:110], "_said": text, "data": data}
        out.append(beat)

    plan = {
        "_draft": ("Face-first heuristic draft. Known concrete processes become cards; unclassified "
                   "speech stays on the speaker instead of becoming generated decoration. Replace every "
                   "TODO and read references/visual-beats.md before adding any visual."),
        "meta": {"title": "TODO", "lang": lang, "fps": 30, "width": 1080, "height": 1920},
        "brand": "default",
        "hook": {"title": select_hook(words, lang)[0], "runnersUp": select_hook(words, lang)[1],
                 "rationale": select_hook(words, lang)[2], "autoSelected": True},
        "captions": {"enabled": True},
        "framing": {"scale": 1.0, "origin": "50% 30%", "punches": [
            {"at": round(float(f[0]["start"]), 2),
             "from": (1.0 if (i // 2) % 2 else 1.045),
             "to": (1.045 if (i // 2) % 2 else 1.0), "dur": 0.28}
            for i, f in enumerate(flats) if i and i % 2 == 0
        ]},
        "beats": out,
    }
    dest = os.path.join(project, "plan.draft.json")
    json.dump(plan, open(dest, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    todo = sum(1 for b in out if "TODO" in json.dumps(b, ensure_ascii=False))
    print(f"reelkit: drafted {len(out)} concrete beat(s) -> {dest}")
    print(f"reelkit: {todo} beat(s) still need content. Unclassified clauses stay on the face.")
    print("reelkit: timing comes from the transcript; delete any guessed card that does not add evidence.")
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
    # The Lottie player and every badge are vendored, never hotlinked: a render
    # kernel may have no egress, and a CDN fetch is also an unaccounted licence.
    lt = os.path.join(SKILL, "assets", "vendor", "lottie.min.js")
    if os.path.exists(lt):
        shutil.copy2(lt, os.path.join(pub, "vendor", "lottie.min.js"))
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
                    f"(`npx {HF} skills update talking-head-recut`) or "
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


# --------------------------------------------------------------- export ----
# The WhatsApp-safe deliverable container. A moov atom written at the END of
# the file (ffmpeg's default) opens fine on desktop and errors on phones and
# in WhatsApp - a defect that shipped exactly this way. The deliverable
# profile is: h264 High yuv420p video, explicit bt709 colour tags, moov
# before mdat (+faststart), AAC audio.

def _mp4_atoms(path):
    """Top-level atom types in file order, reading only box headers."""
    import struct
    types, pos, total = [], 0, os.path.getsize(path)
    with open(path, "rb") as f:
        while pos + 8 <= total:
            f.seek(pos)
            size, typ = struct.unpack(">I4s", f.read(8))
            hdr = 8
            if size == 1:
                size = struct.unpack(">Q", f.read(8))[0]; hdr = 16
            elif size == 0:
                size = total - pos
            types.append(typ.decode("latin1"))
            if size < hdr:
                break
            pos += size
    return types


def _stream_info(path):
    r = sh(["ffprobe", "-v", "error", "-print_format", "json",
            "-show_entries", "stream=codec_type,codec_name,pix_fmt,color_space", path])
    try:
        streams = json.loads(r.stdout).get("streams", [])
    except Exception:
        streams = []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    return v, a


def _extra_streams(path):
    """Stream kinds that are neither video nor audio."""
    r = sh(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
            "-of", "default=nw=1:nk=1", path])
    return [k for k in r.stdout.split() if k not in ("video", "audio")]


def container_problems(path):
    """Phone-safe container audit for a deliverable MP4. Returns
    [(level, message)]: ERROR = phones/WhatsApp fail to open it,
    WARN = plays but renders wrong."""
    probs = []
    atoms = _mp4_atoms(path)
    if "moov" in atoms and "mdat" in atoms and atoms.index("moov") > atoms.index("mdat"):
        probs.append(("ERROR", "MP4 index (moov) sits after the media data - WhatsApp and "
                               "many mobile players fail to open it; run `reelkit.py export`"))
    v, a = _stream_info(path)
    if v.get("codec_name") not in (None, "h264"):
        probs.append(("ERROR", f"video codec {v.get('codec_name')} is not phone-safe (need h264)"))
    if v and v.get("pix_fmt") not in (None, "yuv420p"):
        probs.append(("ERROR", f"pixel format {v.get('pix_fmt')} is not phone-safe (need yuv420p)"))
    if v and v.get("color_space") != "bt709":
        probs.append(("WARN", "no explicit bt709 colour tags - phones guess the colour space; "
                              "`reelkit.py export` writes them"))
    if a and a.get("codec_name") != "aac":
        probs.append(("WARN", f"audio codec {a.get('codec_name')} - AAC is the safe choice"))
    # Anything that is not the video or the audio has no business in a
    # deliverable. A phone source can carry a timecode or telemetry data track,
    # and a `-c copy` without explicit maps carries it all the way through - it
    # survived every gate because nothing was looking for it.
    # Chapters are global metadata rather than streams, so they survive -map,
    # -dn and -sn; the MP4 muxer then writes them out as a bin_data track. Name
    # them explicitly, because "unexpected bin_data stream" sends you looking
    # for a stream that was never there.
    chaps = chapters(path)
    if chaps:
        probs.append(("ERROR", f"{len(chaps)} chapter(s) embedded in the container "
                               f"({', '.join(t for t in chaps if t) or 'untitled'}) - "
                               "they surface as a bin_data track on phones; mux with "
                               "`-map_chapters -1`"))
    extra = _extra_streams(path)
    if extra:
        kinds = ", ".join(sorted(extra))
        probs.append(("ERROR", f"{len(extra)} unexpected stream(s) in the container "
                               f"({kinds}) - a deliverable carries video and audio only; "
                               "map them explicitly when muxing"))

    return probs


def export_deliverable(project, inp, out):
    src = inp if os.path.isabs(inp) else os.path.join(project, inp)
    if not os.path.exists(src):
        die(f"{src} not found - render first (`npx {HF} render public -o {inp}`)")
    dst = out if os.path.isabs(out) else os.path.join(project, out)
    v, a = _stream_info(src)
    if v.get("codec_name") == "h264" and v.get("pix_fmt") == "yuv420p" \
            and a.get("codec_name") in (None, "aac"):
        # Codecs already safe: lossless remux to bring the index forward and
        # write the colour tags.
        # Map explicitly. Without it `-c copy` carries whatever the source has,
        # and a phone clip's timecode/telemetry track rides all the way into the
        # deliverable - the leak the container audit caught on Kaggle. `0:a:0?`
        # keeps a silent source working rather than failing on a missing stream.
        cmd = ["ffmpeg", "-y", "-i", src,
               "-map", "0:v:0", "-map", "0:a:0?", "-dn", "-sn", "-write_tmcd", "0",
               "-map_chapters", "-1",
               "-c", "copy", "-movflags", "+faststart",
               "-color_primaries", "1", "-color_trc", "1", "-colorspace", "1",
               dst, "-loglevel", "error"]
        how = "remuxed (codecs already phone-safe)"
    else:
        cmd = ["ffmpeg", "-y", "-i", src,
               "-map", "0:v:0", "-map", "0:a:0?", "-dn", "-sn", "-write_tmcd", "0",
               "-map_chapters", "-1",
               "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-profile:v", "high",
               "-pix_fmt", "yuv420p", "-color_primaries", "1", "-color_trc", "1",
               "-colorspace", "1", "-movflags", "+faststart",
               "-c:a", "aac", "-b:a", "160k", dst, "-loglevel", "error"]
        how = "re-encoded to the phone-safe profile"
    r = sh(cmd)
    if r.returncode != 0 or not os.path.exists(dst):
        die(f"ffmpeg failed:\n{r.stderr[-1200:]}")
    left = [(l, m) for l, m in container_problems(dst) if l == "ERROR"]
    if left:
        die("export wrote a file that still fails its own container check: "
            + "; ".join(m for _, m in left))
    # WhatsApp's video bar is 16MB. crf-23 quality encoding ignores size, so a
    # high-motion render sails past it (a 32s reel landed at 36MB once). When
    # that happens, fall back to a two-pass targeted encode derived from the
    # real duration; the cap keeps headroom for container overhead.
    SIZE_CAP = 15 * 1024 * 1024
    if os.path.getsize(dst) > SIZE_CAP:
        dur = probe_duration(dst)
        vkbps = max(200, int(SIZE_CAP * 8 / 1000 / dur) - 128)
        tmp = dst + ".cap.tmp.mp4"
        # -passlogfile, or ffmpeg writes ffmpeg2pass-0.log(.mbtree) into the
        # CURRENT WORKING DIRECTORY and leaves them there. Two exports running
        # from one directory would also share that fixed name and feed each
        # other's statistics into the second pass.
        plog = dst + ".passlog"
        base = ["ffmpeg", "-y", "-i", dst,
                "-map", "0:v:0", "-map", "0:a:0?", "-dn", "-sn", "-write_tmcd", "0",
               "-map_chapters", "-1",
                "-c:v", "libx264", "-preset", "slow",
                "-b:v", f"{vkbps}k", "-pix_fmt", "yuv420p", "-passlogfile", plog,
                "-color_primaries", "1", "-color_trc", "1", "-colorspace", "1"]
        try:
            r1 = sh(base + ["-pass", "1", "-an", "-f", "null", os.devnull,
                            "-loglevel", "error"])
            r2 = sh(base + ["-pass", "2", "-c:a", "aac", "-b:a", "128k",
                            "-movflags", "+faststart", tmp, "-loglevel", "error"])
            if r1.returncode == 0 and r2.returncode == 0 and os.path.exists(tmp) \
                    and os.path.getsize(tmp) <= 16 * 1024 * 1024:
                os.replace(tmp, dst)
                how += ", then size-capped under the 16MB WhatsApp bar"
            else:
                if os.path.exists(tmp):
                    os.remove(tmp)
                die(f"export is {os.path.getsize(dst)} bytes and the two-pass "
                    f"size-cap encode failed:\n{(r1.stderr + r2.stderr)[-1200:]}")
        finally:
            for stray in glob.glob(plog + "*"):
                try: os.remove(stray)
                except OSError: pass
        left = [(l, m) for l, m in container_problems(dst) if l == "ERROR"]
        if left:
            die("size-capped export fails the container check: "
                + "; ".join(m for _, m in left))
    print(f"reelkit: {how} -> {dst} ({probe_duration(dst):.2f}s)")
    print("reelkit: container audit clean (moov first, bt709 tagged, h264/yuv420p/aac)")
    return 0



def _project_timing(project):
    """Return (fps, duration) from the authored plan and grounded transcript/media."""
    plan_path = os.path.join(project, "plan.json")
    plan = json.load(open(plan_path, encoding="utf-8")) if os.path.exists(plan_path) else {}
    meta = plan.get("meta", {})
    fps = int(meta.get("fps") or 30)
    duration = float(meta.get("duration") or 0)
    tpath = os.path.join(project, "transcript.json")
    if not duration and os.path.exists(tpath):
        words = json.load(open(tpath, encoding="utf-8"))
        if isinstance(words, dict): words = words.get("words") or words.get("segments") or []
        if words: duration = max(float(w.get("end", 0)) for w in words)
    video = os.path.join(project, "public", "input-video.mp4")
    if os.path.exists(video):
        # Media is authoritative for the tail; transcript often ends before the final breath.
        duration = max(duration, probe_duration(video))
    return fps, duration


def _auto_workers():
    cores = os.cpu_count() or 2
    # Chrome capture is memory-heavy and explicit worker counts bypass HyperFrames sizing.
    return max(1, min(8, cores // 2))


def _checkpoint_bundle(project, checkpoint_dir):
    """Write a small atomic bundle that can reconstruct the authored composition.

    Source video is intentionally excluded: callers should keep it in durable storage.
    The bundle contains the plan, transcript, generated composition, local images/fonts,
    and a manifest. It is safe to attach or copy while a render runs.
    """
    os.makedirs(checkpoint_dir, exist_ok=True)
    out = os.path.join(checkpoint_dir, "reelkit-render-checkpoint.tgz")
    tmp = out + ".tmp"
    manifest = {
        "version": 1, "created_at": int(time.time()),
        "project": os.path.basename(os.path.abspath(project)),
        "excludes": ["public/input-video.mp4", "*.mp4 render outputs"],
    }
    mpath = os.path.join(project, ".reelkit-render-manifest.json")
    json.dump(manifest, open(mpath, "w", encoding="utf-8"), indent=2)
    wanted = ["plan.json", "transcript.json", "ASSETS.md", "visuals.json", "BEATS.md", "HOOKS.md", "asset-ledger.json", "asset-cache",
              ".reelkit-render-manifest.json", "public/index.html", "public/cards",
              "public/images", "public/fonts", "public/sfx"]
    with tarfile.open(tmp, "w:gz") as tf:
        for rel in wanted:
            src = os.path.join(project, rel)
            if os.path.exists(src): tf.add(src, arcname=rel)
    os.replace(tmp, out)
    return out


VERIFY_REQS = os.path.join(SKILL, "requirements-verify.txt")
# cardGeometry/faceDetection in verify.json are capability flags - whether the
# checker COULD measure, not whether it found anything.
# A gate that cannot measure blocks delivery, so each capability verify reports
# is named with what provides it. compositionCheck needs node and a browser -
# the same toolchain the render itself needs, so a render path that cannot run
# it could not have rendered anyway.
GATE_DEPS = (("cardGeometry", "playwright"), ("faceDetection", "opencv-python-headless"),
             ("compositionCheck", "node + `npx hyperframes check`"))


def gate_problems(v):
    """Reasons a verify result must stop a render. Empty list means clear.

    Separated from the plumbing so the decision is testable without a browser."""
    out = []
    missing = [dep for key, dep in GATE_DEPS if not v.get(key)]
    if missing:
        out.append(f"the gate could not run - {', '.join(missing)} unavailable. "
                   f"Install: pip install -r {VERIFY_REQS} "
                   "&& python3 -m playwright install --with-deps chromium")
    for f in v.get("findings", []):
        if isinstance(f, dict):
            lvl, cid, msg = f.get("level"), f.get("id"), f.get("message")
        elif isinstance(f, (list, tuple)) and len(f) >= 3:
            lvl, cid, msg = f[0], f[1], f[2]
        else:
            continue
        if lvl == "ERROR":
            out.append(f"{cid}: {msg}")
    return out


def render_gate(project):
    """Run the geometry gate immediately before spending render minutes.

    This is the backstop, not the only check - `build` already refuses a card it
    cannot fit above the head. But build is not the last step before the spend,
    and a driver can render a project that was built earlier or elsewhere.
    render_project() is the one funnel every path goes through (the CLI,
    worker.py, and segmentrender.py per segment), so gating here is what makes a
    head-zone collision impossible to render rather than merely discouraged."""
    if not os.path.exists(os.path.join(project, "plan.json")):
        die("no plan.json - the geometry gate cannot run, refusing to render")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import verify as _verify          # local: verify imports reelkit, so not at module level
    code = _verify.run(project, False, False)
    vj = os.path.join(project, "verify.json")
    if not os.path.exists(vj):
        die("verify wrote no verify.json - the geometry gate cannot run, refusing to render")
    problems = gate_problems(json.load(open(vj, encoding="utf-8")))
    if not problems and code != 0:
        problems = [f"verify exited {code}"]
    if problems:
        die("geometry gate failed - refusing to render:\n" +
            "\n".join("  " + p for p in problems))
    print("reelkit: geometry gate passed")


def render_project(project, output, workers=None, preview=False, checkpoint_dir=None,
                   software_gpu=False, keep_raw=False, mix_audio=True):
    """Render through HyperFrames with deterministic sizing and a fast preview lane."""
    project = os.path.abspath(project)
    public = os.path.join(project, "public")
    if not os.path.exists(os.path.join(public, "index.html")):
        die("public/index.html missing - run `reelkit.py build` first")
    # First, before any sizing work or a checkpoint bundle: nothing else here is
    # worth doing for a render that must not happen.
    render_gate(project)
    fps, duration = _project_timing(project)
    env_workers = os.environ.get("REELKIT_RENDER_WORKERS") or os.environ.get("PRODUCER_MAX_WORKERS")
    source = "auto"
    if workers is not None:
        nworkers, source = int(workers), "--workers"
    elif env_workers:
        nworkers, source = int(env_workers), "environment"
    else:
        nworkers = _auto_workers()
    if nworkers < 1: die("workers must be >= 1")
    cores = os.cpu_count() or 2
    suggested = max(1, cores // 2)
    print(f"reelkit: render sizing: {duration:.2f}s at {fps}fps = "
          f"{round(duration * fps)} frames; {nworkers} worker(s) ({source})")
    if nworkers > suggested:
        print(f"reelkit: warning - {nworkers} explicit workers exceeds this box's ~{suggested} "
              "useful default; oversubscription can be slower")
    if checkpoint_dir:
        bundle = _checkpoint_bundle(project, os.path.abspath(checkpoint_dir))
        print(f"reelkit: wrote reconstruction checkpoint {bundle}")
    out = output if os.path.isabs(output) else os.path.join(project, output)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    raw = out + ".rendering.mp4"
    render_fps = min(fps, 10) if preview else fps
    cmd = ["npx", "-y", HF, "render", public,
           "-o", raw, "--fps", str(render_fps), "--workers", str(nworkers),
           "--quality", "draft" if preview else "standard",
           "--browser-timeout", "90", "--player-ready-timeout", "90000",
           "--protocol-timeout", "300000", "--best-effort"]
    if software_gpu: cmd.append("--no-browser-gpu")
    print("reelkit: " + ("preview" if preview else "full") +
          f" render ({render_fps}fps, {'draft' if preview else 'standard'})")
    if preview:
        # segmentrender.py --preview renders leading segments at full fidelity and
        # a later full render resumes them. This lane trades that away for speed.
        print("reelkit: this draft is throwaway - a full render cannot reuse any of "
              "it. For a preview whose work carries over, use segmentrender.py --preview")
    r = subprocess.run(cmd, cwd=project)
    if r.returncode or not os.path.exists(raw):
        die(f"HyperFrames render failed with exit {r.returncode}")
    # The audio mix stage owns the delivered audio in BOTH render paths, so the
    # direct and segmented renders cannot disagree about what a reel sounds
    # like. The renderer's own audio track is dropped here on purpose: cues are
    # re-placed against the original file at absolute times, which is what lets
    # the segmented path carry them at all.
    # A segment's audio is thrown away by the join's `-an`, so mixing it there
    # is work nobody hears. segmentrender turns this off and mixes once, on the
    # joined video, against the original audio.
    if not mix_audio:
        export_deliverable(project, raw, out)
        if not keep_raw:
            os.remove(raw)
        print(f"reelkit: render complete -> {out} (audio mix deferred to the join)")
        return 0
    plan_ = json.load(open(os.path.join(project, "plan.json"), encoding="utf-8"))
    sty_, _p = style.for_plan(plan_)
    voice_, duck_ = style.audio_cfg(sty_)
    mixed = raw + ".mixed.mp4"
    audiomix.mix(project, raw, os.path.join(project, "public", "input-video.mp4"),
                 mixed, voice=voice_, duck=duck_)
    # Preview and full output both pass through the existing phone-safe export.
    export_deliverable(project, mixed, out)
    os.remove(mixed)
    if not keep_raw: os.remove(raw)
    print(f"reelkit: render complete -> {out}")
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
    r = sh(f"npx -y {HF} --version")
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
    which = ("media-use" if sfx and "media-use" in sfx else
             "bundled CC0 pack" if sfx == BUNDLED_SFX else "custom")
    print(f"  {'OK ' if sfx else 'MISS'} sfx        "
          f"{sfx + ' (' + which + ')' if sfx else 'no library and assets/sfx is missing - broken checkout'}")
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
    e = sub.add_parser("export"); e.add_argument("--project", required=True)
    e.add_argument("--input", default="output.mp4"); e.add_argument("--out", default="final.mp4")
    rr = sub.add_parser("render"); rr.add_argument("--project", required=True)
    rr.add_argument("--no-audio-mix", action="store_true",
                    help="render video only; the caller mixes audio (segmentrender)")
    rr.add_argument("--out", default="final.mp4"); rr.add_argument("--workers", type=int)
    rr.add_argument("--preview", action="store_true", help="10fps draft iteration render")
    rr.add_argument("--checkpoint-dir", help="write a reconstruction bundle before rendering")
    rr.add_argument("--software-gpu", action="store_true", help="pin SwiftShader for comparisons")
    rr.add_argument("--keep-raw", action="store_true")
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
    if a.cmd == "export":
        return export_deliverable(a.project, a.input, a.out)
    if a.cmd == "render":
        return render_project(a.project, a.out, a.workers, a.preview,
                              a.checkpoint_dir, a.software_gpu, a.keep_raw,
                              mix_audio=not a.no_audio_mix)
    if a.cmd == "cut":
        keeps = [[float(x) for x in seg.split(":")] for seg in a.keep.split(",")]
        return cut_video(a.video, a.out, keeps, a.fps)
    if a.cmd == "sample":
        return sample_project(a.project, a.fps, a.width, a.height)
    return doctor()


if __name__ == "__main__":
    sys.exit(main())
