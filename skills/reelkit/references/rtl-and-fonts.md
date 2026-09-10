# RTL, scripts and fonts

Most caption tooling is built and tested in English. Hebrew and Arabic reels fail
in ways that look like your bug but are the tooling's. These are the ones that cost
real time.

## 1. `dir` on `<html>` renders a black video

```html
<html lang="he" dir="rtl">   <!-- previews perfectly. renders 90 s of black. -->
```

The HyperFrames linter flags this as `html_dir_attribute_breaks_render`, and it is
a confirmed silent failure: snapshots look right, the MP4 is empty. Put `lang` on
`<html>` and `dir="rtl"` on individual text elements. Browsers apply the Unicode
bidi algorithm per element, so shaping and ordering are still correct.

reelkit never emits `dir` on `<html>`. If you hand-edit the composition, do not add it.

## 2. Bundled fonts have no Hebrew

Inter, Caveat, Virgil, EB Garamond, LXGW WenKai — none carry Hebrew or Arabic
glyphs. Text renders as tofu boxes, or silently falls back to something ugly.
reelkit ships **Heebo** (SIL OFL, license included) in weights 400–900 and uses it
for every Hebrew string; Inter is used only for Latin runs, digits and code.

For another script, drop its woff2 into `assets/fonts/` and point the brand's
`font` at it. Verify with a snapshot before rendering — tofu is obvious in a frame
and invisible in a plan.

## 3. Mirrored characters

In an RTL run the bidi algorithm mirrors bracket-like characters: `>` displays as
`<`, `(` as `)`. A terminal prompt `>` inside a Hebrew line comes out backwards.
Use a non-mirroring glyph (`$`, `❯`) or isolate the run with its own `dir="ltr"`.

## 4. Per-character spans break words

Kinetic type needs per-character spans to stagger. Per-character `inline-block`
spans alone let a line break *inside* a word, which is unreadable in any language
and looks like a rendering fault in Hebrew. Always wrap words first:

```html
<span class="wd"><span class="char">ש</span><span class="char">ל</span></span>
```

with `.wd { display:inline-block; white-space:nowrap; }`. `cards.kinetic()` does this.

## 5. Word order in flex captions

Caption words are flex children. With `dir="rtl"` on the flex container the first
word lands rightmost, which is correct. Verify by reading a snapshot: if the line
reads as a sentence, order is right; if it reads reversed, the container lost its
`dir`.

## 6. Transcription

Whisper's `small.en`, `base.en`, `medium.en` are English-only and return nonsense
for other languages — sometimes confident, well-formed nonsense. Always
`--model large-v3 --language <code>` for non-English audio, and always read the
transcript afterwards. Technical terms, product names and code-switched English
inside Hebrew are where it slips.

## 7. Mixed Hebrew and Latin

A Hebrew line containing `AI`, `200ms` or `downtime` is normal in tech speech. The
bidi algorithm handles it, but check a snapshot: numbers next to punctuation at a
run boundary are where ordering surprises live. Prefix a Latin token with a Hebrew
letter and a hyphen (`ב-AI`) as the speaker actually said it rather than
"correcting" it.
