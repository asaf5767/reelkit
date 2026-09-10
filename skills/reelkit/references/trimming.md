# Trimming and reordering (recipe, not a feature)

reelkit deliberately does not cut footage. The whole pipeline rests on one
guarantee — **the transcript's timestamps describe the footage exactly** — and
every card start, caption word and punch-in is derived from it. Introduce cuts
into the composition and every downstream time needs remapping through an edit
list, which is the most bug-prone thing this design could contain.

Instead: **cut first, then treat the cut file as a fresh source.**

## The recipe

1. Transcribe the raw take and read it. Pick the ranges worth keeping.

2. Cut with ffmpeg. Re-encode rather than stream-copy so cuts land on exact frames:

```bash
# keep 0-44 s and 56-90 s
ffmpeg -y -i raw.mp4 -filter_complex \
 "[0:v]trim=0:44,setpts=PTS-STARTPTS[v0];[0:a]atrim=0:44,asetpts=PTS-STARTPTS[a0]; \
  [0:v]trim=56:90,setpts=PTS-STARTPTS[v1];[0:a]atrim=56:90,asetpts=PTS-STARTPTS[a1]; \
  [v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]" \
 -map "[v]" -map "[a]" -c:v libx264 -crf 17 -c:a aac cut.mp4
```

3. `scaffold --video cut.mp4`, then **transcribe the cut file again**. Do not remap
   the old transcript; the second pass costs one run and removes an entire class of
   off-by-a-bit errors.

4. Plan and build as normal, against ground truth.

## Is the extra pass worth it?

On 2 CPUs a 90 s clip takes about 12 minutes to transcribe with `large-v3`. That
is the whole cost, it is background work, and in exchange every timestamp in the
project is real rather than computed. When a caption drifts out of sync in a
remapped timeline the cause is nearly impossible to find by eye.

## What a cut is worth

Reels earn attention in the first two seconds and lose it to any dead stretch.
Worth cutting: the run-up before the hook, restatements of a point already made,
long pauses, and any aside that does not serve the payoff. If a reel runs over
about 75 s, the honest question is not "which visual can I add" but "which 15
seconds am I keeping out of habit".

Reordering is a harder call: talking-head speech carries connective tissue
("so", "but", "anyway") that makes moved sections audible as edits. Cut freely,
reorder rarely, and always listen to the cut file before building on it.
