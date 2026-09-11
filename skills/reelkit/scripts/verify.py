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
from cards import split_canvas_h   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

try:
    import cv2
    HAVE_CV2 = True
except Exception:
    HAVE_CV2 = False

try:
    from playwright.sync_api import sync_playwright
    HAVE_PW = True
except Exception:
    HAVE_PW = False


def sh(cmd):
    return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True)


# ------------------------------------------------------------------ face
def detect_faces(video, times, W, H):
    """Median head box across sampled frames, in canvas pixels."""
    if not HAVE_CV2:
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


# ------------------------------------------------------------------ geometry
HARNESS = """<!doctype html><html><head><meta charset="utf-8"/>
<style>%(theme)s
html,body{margin:0;width:%(w)dpx;height:%(h)dpx;overflow:hidden;}
#host{position:absolute;left:0;top:0;width:%(w)dpx;height:%(h)dpx;overflow:hidden;}
#host .card{position:relative;width:100%%;height:100%%;overflow:hidden;}
</style></head><body><div id="host">%(card)s</div></body></html>"""


def measure_cards(project, plan, W, H):
    """Lay out every card fragment in a real browser and read its settled box."""
    pub = os.path.join(project, "public")
    idx = open(os.path.join(pub, "index.html"), encoding="utf-8").read()
    theme = idx.split("<style>", 1)[1].split("</style>", 1)[0]
    theme = theme.replace("url('fonts/", "url('" + os.path.join(pub, "fonts") + "/")
    res = {}
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--no-sandbox"])
        pg = br.new_page(viewport={"width": W, "height": H})
        for beat in plan["beats"]:
            cid = beat["id"]
            cpath = os.path.join(pub, "cards", f"{cid}.html")
            if not os.path.exists(cpath):
                continue
            card = open(cpath, encoding="utf-8").read()
            with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                             dir=pub, encoding="utf-8") as fh:
                fh.write(HARNESS % {"theme": theme, "card": card, "w": W, "h": H})
                tmp = fh.name
            try:
                pg.goto("file://" + tmp)
                pg.wait_for_timeout(180)
                box = pg.evaluate("""() => {
                  const root = document.querySelector('.card .root');
                  if (!root) return null;
                  let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9,n=0;
                  root.querySelectorAll('*').forEach(el => {
                    if (el.classList.contains('scrim')) return;
                    const r = el.getBoundingClientRect();
                    if (r.width < 2 || r.height < 2) return;
                    const cs = getComputedStyle(el);
                    if (cs.visibility === 'hidden' || cs.display === 'none') return;
                    x0=Math.min(x0,r.left); y0=Math.min(y0,r.top);
                    x1=Math.max(x1,r.right); y1=Math.max(y1,r.bottom); n++;
                  });
                  return n ? {x:x0,y:y0,w:x1-x0,h:y1-y0,n} : null;
                }""")
                if box:
                    res[cid] = {k: round(v, 1) for k, v in box.items()}
            finally:
                os.unlink(tmp)
        br.close()
    return res


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
            if face:
                fx, fy, fw, fh = face
                so = overlap_pct(cbox, (fx, fy + fh * 0.30, fw, fh * 0.70))
                row["canvasFaceOverlapPct"] = so
                if so >= 12:
                    findings.append(("ERROR", cid,
                                     f"split canvas covers {so}% of the speaker's eyes/mouth - "
                                     f"lower layout.canvas (currently {ch}px of {H})"))
                elif so >= 4:
                    findings.append(("WARN", cid,
                                     f"split canvas clips {so}% of the speaker's eyes/mouth"))
            if cap_on:
                cc = overlap_pct(cbox, cap_box)
                row["canvasCaptionOverlapPct"] = cc
                if cc >= 2:
                    findings.append(("ERROR", cid,
                                     f"split canvas reaches into the caption band ({cc}%)"))
        if not HAVE_PW:
            report.append(row)
            continue
        if box:
            if box["x"] < -2 or box["y"] < -2 or box["x"] + box["w"] > W + 2 or box["y"] + box["h"] > H + 2:
                findings.append(("ERROR", cid, "card extends outside the canvas - content will be clipped"))
            if face:
                # Only the lower ~70% matters: cards arrive from above, and
                # clipping the top of the hair is harmless. Eyes and mouth are not.
                fx, fy, fw, fh = face
                expr = (fx, fy + fh * 0.30, fw, fh * 0.70)
                fo = overlap_pct(box, expr)
                row["faceOverlapPct"] = fo
                dims = mode == "stage" or (mode == "full" and b.get("takeover"))
                row["_note"] = f"{mode} dims the speaker deliberately" if dims else ""
                if mode == "top":          # the speaker is the subject here
                    if fo >= 12:
                        findings.append(("ERROR", cid,
                                         f"card covers {fo}% of the speaker's eyes/mouth in 'top' mode"))
                    elif fo >= 4:
                        findings.append(("WARN", cid, f"card clips {fo}% of the speaker's eyes/mouth"))
                elif fo >= 55:             # even a dimmed speaker should not vanish
                    findings.append(("WARN", cid,
                                     f"card covers {fo}% of the speaker in '{mode}' mode - "
                                     f"intended, but check the speaker is still readable"))
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

    out = {"canvas": {"w": W, "h": H}, "faceDetection": HAVE_CV2, "cardGeometry": HAVE_PW,
           "beats": report,
           "findings": [{"level": l, "id": i, "message": m} for l, i, m in findings]}
    json.dump(out, open(os.path.join(project, "verify.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    if fix:
        applied = apply_fixes(project, plan, boxes, faces, findings)
        if applied:
            print(f"reelkit verify: applied {applied} fix(es) to plan.json - rebuild to take effect")

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
                  f" faceOv={r.get('faceOverlapPct','-')}% capOv={r.get('captionOverlapPct','-')}%")
        print()
        for lvl, cid, msg in findings:
            print(f"  {lvl:5s} {cid:9s} {msg}")
        errs = sum(1 for l, _, _ in findings if l == "ERROR")
        print(f"\n{len(findings)} finding(s), {errs} error(s) -> verify.json")
    return 1 if any(l == "ERROR" for l, _, _ in findings) else 0


def apply_fixes(project, plan, boxes, faces, findings):
    """Only mechanical remedies. Anything needing judgement is reported, not fixed."""
    changed = 0
    # split: shrink the canvas until it clears the eyes. Mechanical - the canvas
    # top edge is fixed, so only its height is in question.
    split_bad = {cid for lvl, cid, msg in findings
                 if lvl in ("ERROR", "WARN") and "split canvas" in msg and "eyes/mouth" in msg}
    for b in plan["beats"]:
        if b["id"] not in split_bad or b.get("mode") != "split":
            continue
        face = faces.get(b["id"])
        if not face:
            continue
        fy, fh = face[1], face[3]
        safe = int(fy + fh * 0.30) - 32          # clear of the eye line
        if safe >= 320:
            b.setdefault("layout", {})["canvas"] = safe
            changed += 1

    bad = {cid for lvl, cid, msg in findings if lvl == "ERROR" and "eyes/mouth" in msg
           and "split canvas" not in msg}
    for b in plan["beats"]:
        if b["id"] not in bad:
            continue
        box = boxes.get(b["id"]); face = faces.get(b["id"])
        if not box or not face:
            continue
        headroom = face[1] - 40                       # space above the head
        if box["h"] <= headroom - 60:                 # it fits above the face
            b.setdefault("layout", {})["top"] = max(40, int(headroom - box["h"]))
            changed += 1
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
