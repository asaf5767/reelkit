#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reelkit verify - close the quality gate that was previously a human squinting
at a contact sheet.

Three checks, all machine-readable:

  1. Card geometry. Each card fragment is laid out in a headless browser at the
     real canvas size and its settled bounding box measured. No guessing from CSS.
  2. Face position. The speaker's head box is detected in the source footage at
     each beat's midpoint (OpenCV; optional - skipped with a note if absent).
  3. Collisions. Card over face, card over the caption band, card outside the
     canvas - reported per beat with the overlap as a percentage of the card.

Writes verify.json and prints a report. Exit code 1 if any ERROR-level finding.

  python3 verify.py --project DIR [--json] [--fix]

`--fix` rewrites plan.json for the findings that have a mechanical remedy
(a card colliding with the face gets nudged above it).
"""
import argparse, json, os, statistics, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cards import (split_canvas_h, split_canvas_h_face, face_safe_canvas_h,
                   detect_faces, CANVAS_MIN, CANVAS_IMG_MIN,
                   head_rect, head_clear_y)  # noqa: E402
from reelkit import container_problems  # noqa: E402
from geometry import measure_cards, SCALE_FLOOR, HAVE_PW  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


try:
    import cv2
    HAVE_CV2 = True
except Exception:
    HAVE_CV2 = False



def sh(cmd):
    return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True)


# ---------------------------------------------------------------- geometry
# measure_cards, the fit maths and the CSS constants live in geometry.py so the
# builder and this checker cannot disagree about where a card is.


def overlap_pct(a, b):
    """Area of a∩b as a percentage of a."""
    if not a or not b:
        return 0.0
    ax, ay, aw, ah = a["x"], a["y"], a["w"], a["h"]
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    area = aw * ah
    return round(100.0 * ix * iy / area, 1) if area > 0 else 0.0


# ------------------------------------------------------------------ main
def run(project, as_json, fix):
    plan = json.load(open(os.path.join(project, "plan.json"), encoding="utf-8"))
    meta = plan.get("meta", {})
    W = int(meta.get("width", 1080)); H = int(meta.get("height", 1920))
    pub = os.path.join(project, "public")
    vid = os.path.join(pub, "input-video.mp4")

    cap_cfg = plan.get("captions", {})
    cap_on = cap_cfg.get("enabled", True)
    cap_top = int(cap_cfg.get("top", 1500)); cap_h = int(cap_cfg.get("height", 360))
    cap_box = (0, cap_top, W, cap_h)

    times = {b["id"]: [b["start"] + (b["end"] - b["start"]) * f for f in (0.2, 0.5, 0.8)]
             for b in plan["beats"]}
    faces = detect_faces(vid, times, W, H) if os.path.exists(vid) else {}
    boxes = measure_cards(project, plan, W, H) if HAVE_PW else {}

    findings, report = [], []
    for b in plan["beats"]:
        cid = b["id"]; box = boxes.get(cid); face = faces.get(cid)
        mode = b.get("mode", "top")
        row = {"id": cid, "kind": b["kind"], "mode": mode, "box": box, "face": face}
        if mode == "split":
            # split's contract is that the speaker stays visible and undimmed
            # below the canvas. The opaque thing is the canvas panel, not the
            # measured content, so check the panel rect.
            ch = split_canvas_h(b.get("layout"), H)
            row["canvas"] = {"x": 0, "y": 0, "w": W, "h": ch}
            cbox = {"x": 0.0, "y": 0.0, "w": float(W), "h": float(ch)}
            hr = head_rect(face)
            if hr:
                # The WHOLE head, hair and forehead included - not the eye/mouth
                # band. The band test let a panel sit on the forehead and still
                # report 0%, which is how "the visuals overlap my face" survived
                # a clean gate.
                so = overlap_pct({"x": hr[0], "y": hr[1], "w": hr[2], "h": hr[3]},
                                 (0, 0, W, ch))
                row["canvasHeadOverlapPct"] = so
                row["headTop"] = int(hr[1])
                if so >= 1:
                    findings.append(("ERROR", cid,
                                     f"split canvas covers {so}% of the speaker's head - it "
                                     f"reaches y={ch} and the head starts at y={int(hr[1])}; "
                                     f"cap layout.canvas at {head_clear_y(face)}px or use B-roll"))
                elif so > 0:
                    findings.append(("WARN", cid,
                                     f"split canvas grazes the speaker's hairline ({so}%)"))
            if cap_on:
                cc = overlap_pct(cbox, cap_box)
                row["canvasCaptionOverlapPct"] = cc
                if cc >= 2:
                    findings.append(("ERROR", cid,
                                     f"split canvas reaches into the caption band ({cc}%)"))
            # The panel clips its own overflow, so a payload that does not fit
            # fails silently in the render - it just looks like a cropped
            # picture. These two checks are what make it loud instead.
            if box:
                # Overflow escapes BOTH edges, not just the bottom: the panel
                # centres its content, so a too-tall block hangs equally above
                # and below and `overflow:hidden` clips it at both ends. Only
                # the top edge showed up the first time this was measured.
                spill = max(-box["y"], (box["y"] + box["h"]) - ch)
                row["canvasSpillPx"] = round(spill, 1)
                if spill > 2:
                    findings.append(("ERROR", cid,
                                     f"split canvas content overruns the {ch}px panel by "
                                     f"{spill:.0f}px and is clipped - shorten the headline, "
                                     f"drop the image, or give this beat another mode"))
                fh_px = box.get("fh")
                if fh_px is not None:
                    row["canvasImageH"] = round(fh_px, 1)
                    if fh_px < CANVAS_IMG_MIN:
                        findings.append(("ERROR", cid,
                                         f"the image is squeezed to {fh_px:g}px inside a "
                                         f"{ch}px panel (needs at least {CANVAS_IMG_MIN}px) - "
                                         f"this canvas is too short to carry a picture"))
        if not HAVE_PW:
            report.append(row)
            continue
        if box:
            if box["x"] < -2 or box["y"] < -2 or box["x"] + box["w"] > W + 2 or box["y"] + box["h"] > H + 2:
                findings.append(("ERROR", cid, "card extends outside the canvas - content will be clipped"))
            hr = head_rect(face) if face else None
            if hr and mode != "full":
                # One rule for every mode that plays over live footage: the
                # whole head stays clear. No mode dims the speaker any more, so
                # there is no longer a mode in which covering him is "intended"
                # - `full` is B-roll and replaces the frame outright, which is
                # why it is exempt rather than tolerant.
                fo = overlap_pct({"x": hr[0], "y": hr[1], "w": hr[2], "h": hr[3]},
                                 (box["x"], box["y"], box["w"], box["h"]))
                row["headOverlapPct"] = fo
                row["headTop"] = int(hr[1])
                clear = head_clear_y(face)
                if fo >= 1:
                    findings.append(("ERROR", cid,
                                     f"card covers {fo}% of the speaker's head - it reaches "
                                     f"y={box['y'] + box['h']:.0f} and the head starts at "
                                     f"y={int(hr[1])}; it needs to end above y={clear}, or the "
                                     f"beat wants B-roll (mode 'full')"))
                elif fo > 0:
                    findings.append(("WARN", cid,
                                     f"card grazes the speaker's hairline ({fo}%)"))
            if cap_on:
                co = overlap_pct(box, cap_box)
                row["captionOverlapPct"] = co
                if co >= 10:
                    findings.append(("ERROR", cid, f"card overlaps the caption band by {co}%"))
                elif co >= 2:
                    findings.append(("WARN", cid, f"card grazes the caption band ({co}%)"))
        else:
            findings.append(("WARN", cid, "no measurable content - card may render empty"))
        report.append(row)

    # captions vs face, measured once from the median face box
    if faces and cap_on:
        med = [statistics.median([f[i] for f in faces.values()]) for i in range(4)]
        mouth_y = med[1] + med[3] * 0.75
        if cap_top < mouth_y:
            findings.append(("ERROR", "captions",
                             f"caption band starts at y={cap_top} but the mouth is around "
                             f"y={int(mouth_y)} - captions will cover it "
                             f"(suggest captions.top >= {int(mouth_y) + 40})"))

    # beat overlaps
    bs = sorted(plan["beats"], key=lambda x: x["start"])
    for i in range(len(bs) - 1):
        if bs[i]["end"] > bs[i + 1]["start"] + 1e-6:
            findings.append(("ERROR", bs[i]["id"],
                             f"overlaps {bs[i+1]['id']} ({bs[i]['end']} > {bs[i+1]['start']})"))

    # Deliverable container audit: final.mp4 must open on phones, not only
    # on this machine. A moov atom after mdat is the "works on my desktop,
    # errors in WhatsApp" defect.
    final = os.path.join(project, "final.mp4")
    if os.path.exists(final):
        for lvl, msg in container_problems(final):
            findings.append((lvl, "final.mp4", msg))

    out = {"canvas": {"w": W, "h": H}, "faceDetection": HAVE_CV2, "cardGeometry": HAVE_PW,
           "beats": report,
           "findings": [{"level": l, "id": i, "message": m} for l, i, m in findings]}
    json.dump(out, open(os.path.join(project, "verify.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    if fix:
        applied = apply_fixes(project, plan, boxes, faces, findings)
        if applied:
            print(f"reelkit verify: applied {applied} fix(es) to plan.json - rebuild to take effect")
        if any(l == "ERROR" and c == "final.mp4" and "moov" in m for l, c, m in findings):
            r = sh(["ffmpeg", "-y", "-i", final, "-c", "copy", "-movflags", "+faststart",
                    "-color_primaries", "1", "-color_trc", "1", "-colorspace", "1",
                    final + ".fix.mp4", "-loglevel", "error"])
            if r.returncode == 0 and not [p for p in container_problems(final + ".fix.mp4")
                                          if p[0] == "ERROR"]:
                os.replace(final + ".fix.mp4", final)
                print("reelkit verify: fixed final.mp4 - index moved to front, bt709 tags written")

    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if not HAVE_PW:
            print("reelkit verify: playwright not installed - card geometry checks skipped")
        if not HAVE_CV2:
            print("reelkit verify: opencv-python not installed - face checks skipped\n")
        for r in report:
            f = f" face{r['face']}" if r.get("face") else ""
            b = f"box({r['box']['x']:.0f},{r['box']['y']:.0f} {r['box']['w']:.0f}x{r['box']['h']:.0f})" \
                if r["box"] else "box(none)"
            print(f"  {r['id']:5s} {r['kind']:12s} {r['mode']:6s} {b}"
                  f" headOv={r.get('headOverlapPct', r.get('canvasHeadOverlapPct', '-'))}%"
                  f" capOv={r.get('captionOverlapPct', r.get('canvasCaptionOverlapPct', '-'))}%")
        print()
        for lvl, cid, msg in findings:
            print(f"  {lvl:5s} {cid:9s} {msg}")
        errs = sum(1 for l, _, _ in findings if l == "ERROR")
        print(f"\n{len(findings)} finding(s), {errs} error(s) -> verify.json")
    return 1 if any(l == "ERROR" for l, _, _ in findings) else 0


def apply_fixes(project, plan, boxes, faces, findings):
    """Only mechanical remedies. Anything needing judgement is reported, not fixed."""
    H = int(plan.get("meta", {}).get("height", 1920))
    changed = 0
    # split: shrink the canvas until it clears the eyes. Mechanical - the canvas
    # top edge is fixed, so only its height is in question.
    split_bad = {cid for lvl, cid, msg in findings
                 if lvl in ("ERROR", "WARN") and "split canvas" in msg
                 and ("speaker's head" in msg or "hairline" in msg)}
    for b in plan["beats"]:
        if b["id"] not in split_bad or b.get("mode") != "split":
            continue
        face = faces.get(b["id"])
        safe = face_safe_canvas_h(face, H)
        if safe is not None and safe >= CANVAS_MIN:
            b.setdefault("layout", {})["canvas"] = safe
            changed += 1

    bad = {cid for lvl, cid, msg in findings if lvl == "ERROR"
           and "speaker's head" in msg and "split canvas" not in msg}
    for b in plan["beats"]:
        if b["id"] not in bad:
            continue
        box = boxes.get(b["id"]); face = faces.get(b["id"])
        if not box or not face:
            continue
        clear = head_clear_y(face)                    # above hair, not forehead
        if clear is None:
            continue
        if box["h"] <= clear - 60:
            # It fits; it was just sitting too low. Slide it up.
            b.setdefault("layout", {})["top"] = max(40, int(clear - box["h"]))
            changed += 1
            continue
        # It does not fit at this size. The one mechanical remedy left is to
        # take less room - which is also the house style now. box is measured
        # WITH any scale already applied, so compound rather than replace.
        cur = float((b.get("layout") or {}).get("scale", 1) or 1)
        avail = clear - box["y"]
        if avail <= 0 or box["h"] <= 0:
            continue
        new = round(cur * (avail / box["h"]), 3)
        if new >= SCALE_FLOOR:
            b.setdefault("layout", {})["scale"] = new
            changed += 1
        # Below the floor the card would be too small to read. That is not a
        # layout problem any more, it is an editorial one: the beat wants
        # B-roll, or a kind that says the same thing in less space. Leave the
        # ERROR standing and say so rather than shrinking it into illegibility.
    if changed:
        json.dump(plan, open(os.path.join(project, "plan.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    return changed


def main():
    ap = argparse.ArgumentParser(prog="reelkit verify")
    ap.add_argument("--project", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()
    return run(a.project, a.json, a.fix)


if __name__ == "__main__":
    sys.exit(main())
