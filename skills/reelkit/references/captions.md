# Captions

Word-level highlighting on a plate, one short line at a time. Most reels are
watched muted, so this layer does more work than any other.

## Grouping

Words are grouped into lines by, in order: a speech gap over 0.42 s, a maximum
word count (`captionMaxWords`, default 3), a maximum character count
(`captionMaxChars`, default 15) once a line holds at least two words, and
terminal punctuation.

Three words is deliberate. Longer lines force the eye to travel, the highlight
falls behind the voice, and on a phone the text has to shrink. If lines look
cramped, lower `captionMaxChars` before lowering the font size.

## Timing

Each line starts 0.10 s before its first word and holds 0.45 s past its last,
truncated so it never overlaps the next line. Every word gets two `fromTo` tweens —
into the highlight at its `start`, back out at its `end` — with the "out" tween
guaranteed to begin after the "in" tween finishes. Overlapping tweens on one
property of one element is a lint error and produces a visible flicker.

## Placement

`captionTop` defaults to 1500 px on a 1920 px canvas. Two constraints fight:

- Too high and the plate covers the speaker's mouth. Distracting and it hides the
  lip movement viewers use to follow speech.
- Too low and platform UI covers it. Instagram and TikTok both occupy roughly the
  bottom 250 px with captions, handles and buttons.

1500–1520 is the usable band for a centred talking head. Always confirm on a
snapshot — face position varies with framing, and a base `scale` above 1 with a
top-anchored origin pushes the face **down**, straight into the caption band.

## Styling

Brand keys: `captionSize`, `captionPlate`, `captionIdle`, `captionMaxWords`,
`captionMaxChars`. The highlight colour comes from `captions.highlight`, falling
back to brand accent 0.

The semi-opaque plate is not decoration. Footage brightness changes shot to shot
and white text on a bright wall fails contrast; the plate makes readability
independent of what is behind it. If you remove it, run `check` and read the
contrast section before shipping.

## Turning them off

`"captions": { "enabled": false }`. The beats still build. Only do this for a reel
with no speech — for anything spoken, captions are the highest-value layer here.
