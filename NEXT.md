# NEXT.md - known backlog

Ordered roughly by value. Check with Instinct before picking one up.

1. **verify.py inside the render kernel** - the overlap/geometry gate exists but
   does not run in the Kaggle pipeline; today overlap is gated by hand on
   snapshots. Wire verify into build/render so a head-zone collision fails the
   render automatically.
2. **plan.json box vs CSS geometry** - card size is CSS-driven (.root padding,
   .imgframe width, image aspect); plan box values are advisory and drifted once
   already (label landed on the speaker's eyebrows). Make plan geometry derived
   from CSS math or drop the field.
3. **SFX: real library on Kaggle** - synthesized stand-ins work; hosting the
   licensed bundle for kernel runs (or better synths) would upgrade the sound.
4. **Assaf-avatar source** - future project, explicitly parked by the owner:
   a lookalike talking-head source so he can produce reels without filming.
   Do not start without his go-ahead.
5. **Railway dockerization prep** - package the pipeline (Node 22 + Chrome deps +
   Python) as a reproducible container so renders leave Kaggle's ad-hoc kernels.
6. **render stage: preview/full double render** - preview then full re-renders
   everything; checkpoint reuse between them is partial at best.
