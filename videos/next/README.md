# videos/next — the 32.5s cut

`plan.json` is **not** in this directory, and that is deliberate rather than
unfinished. Every beat in a plan is a timestamp into a specific transcript;
the source and its transcript live on the runner, not in this repo (the only
footage here is `videos/wareel`, which is a different 47.4s reel). Timings
invented against a transcript nobody has read are not a draft, they are noise
that looks like work.

What replaces the hand-authored file is the planner, which now authors the pack
itself. Two commands on the machine that has the footage:

    python3 skills/reelkit/scripts/reelkit.py scaffold --project videos/next --source <the 32.5s mp4>
    python3 skills/reelkit/scripts/reelkit.py plan     --project videos/next --lang he
    mv videos/next/plan.draft.json videos/next/plan.json

Then fill the `TODO`s - the draft times and structures the reel, it does not
write the copy - and build.

## What the draft now reaches for, and why it did not before

The complaint was "no doodles, no animations, exactly the same as before". The
planner took the FIRST card family a beat's words matched, every time, so a
transcript that says "code" three times drafted three code cards in a row and
the reel read as one long slide. It also never reached for the doodle, the
chips or the structure diagram at all, and never authored caption emphasis, so
the whole slice-3-to-8 library was reachable only by hand.

A draft now carries:

  * the **hook lockup** at frame 1 (from the `assaf-v1` profile, always)
  * **doodle marks** from the named family, as a real card and as the fallback
    when a beat's words name no concrete artifact
  * **caption emphasis** - one detonation plus two highlights, on the most
    repeated content words in the transcript, capped by the profile
  * **chips**, **progress** and **stat** families, reachable by content
  * **no two adjacent beats of the same kind**, which is the variety the
    complaint was actually about
  * dwell inside the profile's 2-4s window, so the pacing gate passes

## The lower-third on this particular source: it does not fit

Measured on the runner: the head reaches y=1452 and the caption band starts at
y=1500. The band parks `LT_MARGIN` (28px) above the captions and is
`LT_HEIGHT` (190px) tall, so it would start at **y=1282** - 170px *inside* the
speaker's head. There is no room between the chin and the captions on this
framing.

The planner asks before authoring it and will skip it here, naming that
geometry. It is not a gate to argue with: a lower-third placed anyway would
fail the face-zone law, and the render would die having already spent the
kernel time.

## B-roll

`broll.src` is read by `full` and by `pip`. There are no clips in
`assets/broll/` yet, so a literal B-roll beat needs a file dropped in first -
see `docs/asset-library.md`.
