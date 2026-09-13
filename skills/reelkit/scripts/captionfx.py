#!/usr/bin/env python3
"""Caption emphasis: stroke, per-word treatments, keyword detonation, emoji.

The reference hand does three things to a caption line that reelkit did not:

  stroke      white bold type carries a heavy dark outline, so it stays legible
              over any footage without a plate behind it
  emphasis    one word in a line reads differently - a flat accent block or an
              italic serif - rather than every word looking the same
  detonation  a single spoken keyword becomes a giant full-width word

Four rules here are gate-level, taken from a review of what a template tool got
wrong. They are enforced by construction rather than by convention:

  1. **Nothing ever touches the face.** Every treatment renders INSIDE the
     caption band, which the plan places below the head. A detonated word is a
     caption, not an overlay: it cannot be positioned, so it cannot drift up.
  2. **RTL stays clean and contained.** The detonated word is SVG text with
     `textLength` + `lengthAdjust`, which fits it to an exact width - it cannot
     overflow the canvas or be clipped, in either direction, without measuring
     anything. Emoji ride inside their word's span so bidi orders them with the
     word instead of stranding them at the line edge.
  3. **No boxes that glow.** Emphasis is type: weight, stroke, italic serif, or
     one flat accent block. Nothing here emits a shadow, blur or gradient, so
     none of it spends the heavy-overlay budget.
  4. **Sparse by construction.** Emphasis is opt-in per word from the plan, and
     the profile caps how many detonations a reel may carry.
"""
import html as _html

STYLES = ("plain", "highlight", "serif", "detonate")


def esc(s):
    return _html.escape(str(s), quote=True)


def stroke_css(cfg):
    """The heavy dark outline. `paint-order` keeps the stroke behind the fill so
    the letterform stays the shape it was drawn as, rather than being eaten from
    the inside out."""
    w = (cfg or {}).get("strokeWidth")
    if not w:
        return ""
    col = (cfg or {}).get("strokeColor", "#05060A")
    return (f"-webkit-text-stroke:{w}px {col};paint-order:stroke fill;"
            f"text-stroke:{w}px {col};")


def normalise(rules):
    """plan.captions.emphasis -> {lowercased word: rule}. Later rules win, and a
    rule naming no word is dropped rather than applied to everything."""
    out = {}
    for r in rules or []:
        w = (r.get("word") or "").strip()
        if not w:
            continue
        style = r.get("style", "highlight")
        if style not in STYLES:
            raise SystemExit(f"reelkit captions: unknown emphasis style {style!r}; "
                             f"have {', '.join(STYLES)}")
        out[w.casefold()] = {"style": style, "emoji": r.get("emoji") or "",
                             "accent": int(r.get("accent", 0))}
    return out


def rule_for(word, rules):
    return rules.get(str(word).strip().casefold())


def word_span(eid, text, rule, cls="cw"):
    """One caption word. The emoji lives INSIDE the word's span so the bidi
    algorithm orders it with the word - appended to the line it would strand
    itself at whichever edge the paragraph direction chose."""
    body = esc(text)
    if rule and rule["emoji"]:
        body += f'<span class="cemo">{esc(rule["emoji"])}</span>'
    style = rule["style"] if rule else "plain"
    extra = f" cw-{style}" if style not in ("plain", "detonate") else ""
    return f'<span class="{cls}{extra}" id="{eid}">{body}</span>'


def detonation_svg(eid, text, emoji, width, height, color, stroke, stroke_w, font):
    """The keyword, fitted to an exact width.

    SVG `textLength` with `lengthAdjust="spacingAndGlyphs"` makes the glyphs fit
    the box - which is why this cannot overflow or need measuring. A long Hebrew
    keyword condenses instead of running off the canvas or being clipped, which
    is the RTL failure this is written to avoid.
    """
    label = esc(text) + (esc(emoji) if emoji else "")
    inner = max(10, int(width * 0.92))
    sw = f' stroke="{stroke}" stroke-width="{stroke_w}" paint-order="stroke"' if stroke_w else ""
    return (f'<svg id="{eid}" class="cdet" viewBox="0 0 {width} {height}" '
            f'preserveAspectRatio="xMidYMid meet" aria-hidden="true">'
            f'<text x="{width / 2:.0f}" y="{height * 0.74:.0f}" text-anchor="middle" '
            f'textLength="{inner}" lengthAdjust="spacingAndGlyphs" '
            f'font-family="{font}" font-weight="900" font-size="{int(height * 0.72)}" '
            f'fill="{color}"{sw}>{label}</text></svg>')


def detonations(caps, rules):
    """(line index, word index, word, rule) for every word that detonates."""
    out = []
    for i, cp in enumerate(caps):
        for j, w in enumerate(cp["words"]):
            r = rule_for(w["text"], rules)
            if r and r["style"] == "detonate":
                out.append((i, j, w, r))
    return out


def detonation_findings(caps, rules, cap_max, level="ERROR"):
    """Sparse by construction: past the cap it stops being emphasis."""
    n = len(detonations(caps, rules))
    if cap_max is None or n <= cap_max:
        return []
    return [(level, "captions",
             f"{n} detonated keywords in one reel; the profile allows {cap_max}. "
             "Past that the treatment stops reading as emphasis.")]
