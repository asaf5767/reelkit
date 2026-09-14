# The B-roll library

Convention only. Nothing here is implemented, and nothing should be until real
clips exist - a matcher with no library to match against is a guess dressed as a
feature.

## Why it exists

B-roll doctrine is settled at the reference level: **real artifacts beat abstract
imagery.** A screen recording of the thing being described proves the line; a
stock clip of "technology" decorates it. The personal library is the same idea
one step further - footage of the owner actually doing the thing, so a reel about
grilling can cut to him grilling rather than to a generated approximation.

## Where clips live

```
Drive (raw drop zone)         unreviewed takes, any length, any format
  -> assets/broll/            reviewed clips that ship with the repo
     assets/broll/manifest.json
```

Drive is the inbox. A clip earns its way into `assets/broll/` after review -
framing, length, licence-to-self, and whether it is actually legible at phone
size. The repo holds only clips that passed.

Two constraints the repo imposes, both already live for other assets:

- Anything committed here is **re-hosted publicly**, so it follows the same bar
  as the CC0 SFX pack: the owner's own footage is fine, anything else needs a
  licence artifact beside it.
- Clips are media, and `videos/` and `*.mp4` are gitignored today. A real
  `assets/broll/` needs an explicit un-ignore, the way the SFX pack has one.

## The manifest

`assets/broll/manifest.json`, one entry per clip:

```jsonc
{
  "grill-closeup-01.mp4": {
    "topics": ["grill", "bbq", "fire", "cooking"],
    "duration": 6.4,
    "source": "filmed 2026-09, backyard, 4K60 -> 1080x1920 crop",
    "note": "hands turning skewers; face not visible, so it cuts anywhere"
  }
}
```

`topics` are plain keywords matched against transcript words. Deliberately not
embeddings: a keyword match is inspectable, deterministic, and a planner that
cannot explain why it chose a clip should not be choosing one.

## The planner rule

Fold into the plan-author brief when the library is real:

> When the transcript says a tagged topic and a library clip carries that tag,
> prefer the real clip over any generated or abstract visual. Name the clip in
> the beat and say what it proves. **No clip, no cut** - if nothing in the
> library shows the thing, the speaker stays full frame.

That last clause is the whole rule. It is the same shape as the PiP
`justification` field shipped in this slice, and for the same reason: a cut that
cannot say what it shows is decoration, and decoration is what the doctrine
exists to keep out. The failure mode to design against is a planner reaching for
*a* clip because a cut felt due.

## What implementation would need

Not now, but so the shape is on record:

1. `assets/broll/` un-ignored, with the manifest as the source of truth.
2. A resolver: transcript words -> tagged clips -> candidate beats. Keyword
   overlap, scored by tag specificity, ties broken by clip duration against the
   beat's dwell.
3. `segment_key()` must hash the manifest, exactly as it hashes the brand and
   style directories - swapping a clip changes pixels, and a cached segment that
   does not know is stale.
4. `full` requires `broll.src`; `pip` reads it when present and falls back to
   the beat's own card as the artifact. Either way a library clip is just a
   resolved src, so no new gate is needed. One difference worth knowing when
   tagging: `pip` accepts a still (png/jpg/webp) as well as video, because the
   speaker stays on screen in the inset and a photo therefore cannot turn the
   reel into a slideshow. `full` still takes moving footage only.
