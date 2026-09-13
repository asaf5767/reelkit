#!/usr/bin/env python3
"""Heavy-overlay element budget - the ceiling that decides whether a render
comes back black.

The failure, recorded upstream as HyperFrames lint rule
`composition_heavy_overlay_count_high` and hit once in this repo already: a
composition with roughly 40 heavy overlay elements - `filter: blur(...)`,
`radial-gradient(...)` or an animated `clip-path` - captures **solid black for
the first half of the render** and recovers near the end. It is the capture
layer, not the encoder, and it reproduces through screenshot capture and
`snapshot` alike. Fourteen blurred plates once took this composition from 0 to
105 heavy elements in one commit.

Two properties make this worth a gate rather than a comment:

- It is silent. Nothing fails, nothing warns; the render completes and the
  first half is black. Only watching the whole file catches it.
- It is cheap to measure. The count is static - tags and CSS in the built
  composition - so the gate costs milliseconds and needs no browser.

Thresholds are sourced, not invented:

- `WARN_AT = 25` is HyperFrames' own `HEAVY_OVERLAY_ELEMENT_COUNT_WARN`, set
  deliberately below the repro to give authors lead time.
- `MAX = 40` is the observed black-render count from the upstream field report.
  reelkit treats it as a hard ceiling, because a reel that renders black is not
  a warning.

Counting mirrors the upstream rule so the two cannot disagree about what
"heavy" means: presence is what matters, so `opacity: 0` and
`visibility: hidden` elements still count - an element only escapes the
compositor via `display: none`.
"""
import re
from html.parser import HTMLParser

# Upstream HEAVY_OVERLAY_CSS_PATTERN, transcribed.
HEAVY_CSS = re.compile(
    r"(?:filter\s*:[^;}]*\bblur\s*\()"
    r"|(?:clip-path\s*:(?!\s*(?:none|inherit|initial|unset)\b)\s*[^;}]+)"
    r"|(?:radial-gradient\s*\()", re.I)

DISPLAY_NONE = re.compile(r"(?:^|;)\s*display\s*:\s*none\b", re.I)

# Upstream HEAVY_OVERLAY_EXEMPT_TAGS: elements that never reach the compositor
# as an overlay surface.
EXEMPT_TAGS = {"audio", "body", "br", "defs", "head", "hr", "html", "link",
               "meta", "script", "source", "style", "template", "title", "use",
               "video"}

WARN_AT = 25      # HyperFrames' own warn threshold
MAX = 40          # observed solid-black repro; reelkit's hard ceiling

_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_COMMENT = re.compile(r"/\*[\s\S]*?\*/")
_COMBINATOR = re.compile(r"[\s>+~]+")


def _leftmost(sel):
    """The classes and id of a selector's leftmost compound.

    `.a .b` hooks on `.a`, `#x > .y` on `#x`. Upstream does the same, and it
    over-counts on purpose: an element carrying `.a` is counted even when it
    would not match `.a .b`. For a budget whose failure mode is a black render,
    counting high is the safe direction.
    """
    head = _COMBINATOR.split(sel.strip(), 1)[0]
    return set(re.findall(r"\.([A-Za-z0-9_-]+)", head)), \
        (re.findall(r"#([A-Za-z0-9_-]+)", head) or [None])[0]


def css_hooks(css_blocks):
    """Class and id tokens whose CSS rule body declares something heavy."""
    classes, ids = set(), set()
    for css in css_blocks:
        for header, body in _RULE.findall(_COMMENT.sub("", css)):
            header = header.strip()
            if not header or header.startswith("@"):
                continue
            if not HEAVY_CSS.search(body):
                continue
            for sel in header.split(","):
                if not sel.strip():
                    continue
                cls, cid = _leftmost(sel)
                classes |= cls
                if cid:
                    ids.add(cid)
    return classes, ids


class _Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.css, self.tags, self._in_style = [], [], False

    def handle_starttag(self, tag, attrs):
        if tag == "style":
            self._in_style = True
        self.tags.append((tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self.css.append(data)


def count(html):
    """(count, [offending element descriptions]) for one composition file."""
    s = _Scan()
    s.feed(html)
    classes, ids = css_hooks(s.css)
    n, who = 0, []
    for tag, attrs in s.tags:
        if tag in EXEMPT_TAGS:
            continue
        style = attrs.get("style") or ""
        if style and DISPLAY_NONE.search(style):
            continue                      # removed from the render tree
        why = None
        if style and HEAVY_CSS.search(style):
            why = "inline style"
        if why is None and (classes or ids):
            hit = [c for c in (attrs.get("class") or "").split() if c in classes]
            if hit:
                why = "." + hit[0]
            elif attrs.get("id") in ids:
                why = "#" + attrs["id"]
        if why:
            n += 1
            if len(who) < 12:
                who.append(f"<{tag}> via {why}")
    return n, who


def findings(html):
    """Gate findings for a built composition. ERROR at the ceiling, and the
    upstream warn threshold below it so there is lead time, not a cliff."""
    n, who = count(html)
    sample = ("; ".join(who[:4]) + (" ..." if len(who) > 4 else "")) if who else ""
    if n >= MAX:
        return n, [("ERROR", "composition",
                    f"{n} heavy overlay elements (blur / radial-gradient / clip-path); "
                    f"at ~{MAX} the capture layer renders the first half of the video solid "
                    f"black. Reduce to under {WARN_AT}, or split into sub-compositions. "
                    f"First offenders: {sample}")]
    if n >= WARN_AT:
        return n, [("WARN", "composition",
                    f"{n} heavy overlay elements; HyperFrames warns at {WARN_AT} and the "
                    f"capture layer starts rendering black around {MAX}. First offenders: {sample}")]
    return n, []
