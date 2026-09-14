# GSAP 3.15.0 — vendored

`gsap.min.js` is GSAP 3.15.0, taken verbatim from the `gsap` npm package
(`npm pack gsap`, dist/gsap.min.js, sha256 recorded below).

    Copyright 2026, GreenSock. All rights reserved.
    Subject to the terms at https://gsap.com/standard-license
    Author: Jack Doyle, jack@greensock.com

## Read this before treating it like the other vendored file

This is **not** an OSI-permissive licence, and it is not the MIT that
`lottie.min.js` next to it carries. GSAP ships under GreenSock's Standard
"no charge" licence: free to use in the overwhelming majority of projects,
including commercial ones, but the terms live at the URL above and are not
reproduced here because GreenSock does not ship a LICENSE file in the package.
The one obligation that bites a repository is that the copyright banner at the
top of the file must stay intact — it is there, unmodified, and must not be
stripped by any minifier or build step.

Everything else in `assets/` is CC0 or MIT precisely so the raw files can be
re-hosted here without a second thought. This file is the exception, carried
deliberately: the render kernel has no reliable egress, and a build that fetches
its animation engine from npm at runtime fails on the machine that matters.
That trade was made by the reviewer, not inferred — if the licence reading is
wrong, delete this file and the scaffold falls back to fetching the package,
which is what it did before.

## Provenance

    package  gsap@3.15.0
    file     package/dist/gsap.min.js
    fetched  npm pack gsap --pack-destination .
    sha256   92bb9a96476f983d212a2bc4f54c889039c1696dd4461d40a736860938570fbb
