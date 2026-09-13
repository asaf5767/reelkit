#!/usr/bin/env python3
"""Card geometry, measured once and shared by the builder and the checker.

Card size is decided by CSS and by content that wraps, so any number written in
a plan is a guess that drifts the moment a headline gets a word longer. The
numbers here come from two measurements instead - the settled DOM box in a real
browser, and the detected head in the real footage - and both `build` and
`verify` read them through this module so they cannot disagree about where a
card is.

That was the shape of the defect this replaces: a plan claimed an image slot was
940x480 at x=70 while the CSS rendered it 820 wide and centred, so a generator
made artwork for a box that did not exist, and nothing noticed until a label
landed on the speaker's eyebrows.
"""
import os,sys,tempfile

sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import mcache  # noqa: E402

# --- CSS facts. These mirror card_css() in reelkit.py; changing one without the
# --- other is the drift this module exists to prevent.
IMG_FRAME_W = 820          # .imgframe width
PLATE_PAD_T = 32           # .plate padding-top
IMG_ASPECT = 1.958         # published target ratio for a replace/behind slot
MODE_TOP = {"top": 120, "stage": 150, "split": 0, "full": 0}
SCALE_FLOOR = 0.62         # below this a card stops being readable at phone size
MIN_TOP = 32              # the highest a card may sit before it hugs the edge

try:
    from playwright.sync_api import sync_playwright
    HAVE_PW = True
except Exception:
    HAVE_PW = False


def mode_top(mode, layout):
    """The card's top edge in canvas px, honouring an explicit layout.top."""
    t = (layout or {}).get("top")
    return int(t) if t is not None else MODE_TOP.get(mode, 120)


def image_slot_box(mode, layout, plated, W, aspect=IMG_ASPECT):
    """Where a replace/behind image actually lands, derived from the CSS.

    The frame is a fixed width, centred, and its height follows the delivered
    image's aspect - so the honest box is computed, never authored. `layout.scale`
    scales from the top centre, which moves the sides in and the bottom up but
    leaves the top edge alone."""
    scale = float((layout or {}).get("scale", 1) or 1)
    w = IMG_FRAME_W * scale
    h = w / float(aspect)
    x = (W - w) / 2.0
    y = mode_top(mode, layout) + (PLATE_PAD_T * scale if plated else 0)
    return [int(round(x)), int(round(y)), int(round(w)), int(round(h))]


def fit_layout(box, face, layout, head_clear_y):
    """Resolve a layout so the card clears the whole head, or say why it cannot.

    Returns (resolved_layout_or_None, note). resolved is None when nothing is
    needed; note is non-empty only when the beat cannot be fixed mechanically.

    Order matters: sliding the card up costs nothing, shrinking it costs
    readability. Below SCALE_FLOOR the beat needs an editorial decision (B-roll,
    or a kind that says the same thing in less space), not another few percent.
    """
    if not box or not face:
        return None, ""
    clear = head_clear_y(face)
    if clear is None:
        return None, ""
    bottom = box["y"] + box["h"]
    if bottom <= clear:
        return None, ""                       # already clear, leave it alone
    out = dict(layout or {})
    if box["h"] <= clear - MIN_TOP:
        out["top"] = max(MIN_TOP, int(clear - box["h"]))
        return out, ""
    # Cannot fit at this size even hard against the top edge. box is measured
    # WITH any scale already applied, so compound rather than replace.
    cur = float(out.get("scale", 1) or 1)
    avail = clear - MIN_TOP
    if avail <= 0 or box["h"] <= 0:
        return None, f"no room above the head at all (head clears at y={clear})"
    new = round(cur * (avail / box["h"]), 3)
    if new < SCALE_FLOOR:
        return None, (f"needs scale {new} to clear the head (card is {int(box['h'])}px, "
                      f"only {int(avail)}px is free above y={clear}); below the {SCALE_FLOOR} "
                      f"readable floor this is an editorial call - use B-roll (mode 'full') "
                      f"or a kind that says it in less space")
    out["top"] = MIN_TOP
    out["scale"] = new
    return out, ""


# ------------------------------------------------------------------ measuring
HARNESS = """<!doctype html><html><head><meta charset="utf-8"/>
<style>%(theme)s
html,body{margin:0;width:%(w)dpx;height:%(h)dpx;overflow:hidden;}
#host{position:absolute;left:0;top:0;width:%(w)dpx;height:%(h)dpx;overflow:hidden;}
#host .card{position:relative;width:100%%;height:100%%;overflow:hidden;}
</style></head><body><div id="host">%(card)s</div></body></html>"""

BOX_JS = """() => {
  const root = document.querySelector('.card .root');
  if (!root) return null;
  let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9,n=0;
  root.querySelectorAll('*').forEach(el => {
    if (el.closest && el.closest('.broll')) return;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') return;
    x0=Math.min(x0,r.left); y0=Math.min(y0,r.top);
    x1=Math.max(x1,r.right); y1=Math.max(y1,r.bottom); n++;
  });
  const fr = root.querySelector('.cimgframe');
  const f = fr ? fr.getBoundingClientRect() : null;
  return n ? {x:x0,y:y0,w:x1-x0,h:y1-y0,n, fw: f ? f.width : null,
              fh: f ? f.height : null} : null;
}"""


def measure_cards(project, plan, W, H, use_cache=True):
    """Lay out every card fragment in a real browser and read its settled box.

    Card height depends on content, so computing it from CSS would be a guess;
    this is the actual number. Returns {} without Playwright - callers treat
    that as "no information", never as "nothing to avoid".

    Cards whose HTML, theme and canvas size are unchanged since a previous pass
    are served from mcache, and the browser is launched only for the rest - so
    `verify` right after `build`, and the per-segment gate render_gate runs for
    every segment, stop re-measuring identical cards. The Playwright check stays
    ABOVE the cache on purpose: a cache hit must never stand in for the
    dependency the gate needs (see mcache rule 3).
    """
    if not HAVE_PW:
        return {}
    pub = os.path.join(project, "public")
    with open(os.path.join(pub, "index.html"), encoding="utf-8") as fh:
        idx = fh.read()
    theme = idx.split("<style>", 1)[1].split("</style>", 1)[0]
    theme = theme.replace("url('fonts/", "url('" + os.path.join(pub, "fonts") + "/")

    # Scope: everything shared by every card in this measurement. Key: the one
    # card. Restyle the theme or resize the canvas and the whole section goes.
    scope = mcache.sha("cards", W, H, HARNESS, BOX_JS, theme)
    want = {}                       # cid -> (cache key, card html)
    for beat in plan["beats"]:
        cid = beat["id"]
        cpath = os.path.join(pub, "cards", f"{cid}.html")
        if not os.path.exists(cpath):
            continue
        with open(cpath, encoding="utf-8") as fh:
            card = fh.read()
        want[cid] = (mcache.sha(card), card)

    cache = mcache.load(project) if use_cache else {}
    res, todo = {}, []
    for cid, (key, card) in want.items():
        hit = mcache.get(cache, "cards", scope, key) if use_cache else None
        if hit:
            res[cid] = hit
        else:
            todo.append((cid, card))

    if todo:
        with sync_playwright() as p:
            br = p.chromium.launch(args=["--no-sandbox"])
            pg = br.new_page(viewport={"width": W, "height": H})
            for cid, card in todo:
                with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                                 dir=pub, encoding="utf-8") as fh:
                    fh.write(HARNESS % {"theme": theme, "card": card, "w": W, "h": H})
                    tmp = fh.name
                try:
                    pg.goto("file://" + tmp)
                    pg.wait_for_timeout(180)
                    box = pg.evaluate(BOX_JS)
                    if box:
                        res[cid] = box
                finally:
                    os.unlink(tmp)
            br.close()

    if use_cache:
        # Only cards that actually measured are stored. One that measured
        # nothing is re-measured next pass rather than cached as "no box".
        mcache.replace(project, "cards", scope,
                       {key: res[cid] for cid, (key, _) in want.items() if cid in res})
    return res
