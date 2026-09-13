# reelkit render container - NEXT.md #5.
#
# Carries everything the pipeline shells out to, so a render is reproducible off
# Kaggle's ad-hoc kernels: ffmpeg, Node 22 for the HyperFrames CLI, Chromium for
# snapshot/render/verify, and the Python gate dependencies.
#
# Provider credentials are NEVER baked in. FAL_KEY and the adapter commands come
# from the runtime environment.
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    NODE_MAJOR=22 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    # A slow/headless box needs these or the CLI dies with a 10s navigation
    # timeout that reads like a broken composition.
    PRODUCER_PAGE_NAVIGATION_TIMEOUT_MS=90000 \
    PRODUCER_PLAYER_READY_TIMEOUT_MS=90000

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg git ffmpeg unzip \
 && mkdir -p /etc/apt/keyrings \
 && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" \
      > /etc/apt/sources.list.d/nodesource.list \
 && apt-get update && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

# Gate dependencies. opencv is pinned below 5 on purpose: OpenCV 5 dropped
# cv2.CascadeClassifier, which is what detect_faces() uses - on 5.x every face
# check silently turns into "no head detected".
COPY skills/reelkit/requirements-verify.txt /tmp/requirements-verify.txt
RUN pip install --no-cache-dir -r /tmp/requirements-verify.txt pillow numpy \
 && python -m playwright install --with-deps chromium

# Warm the HyperFrames CLI and its render skill into the image so a cold worker
# does not npx-download them on the first job.
# HF_VERSION must match reelkit.py's HF_VERSION: the image warms one version and
# the pipeline asks for another otherwise, which re-downloads at render time and
# quietly renders on a different renderer than the one this image was tested on.
# The check below fails the build rather than shipping that mismatch.
ARG HF_VERSION=0.8.36
RUN npx --yes hyperframes@$HF_VERSION --version \
 && npx --yes hyperframes@$HF_VERSION skills update talking-head-recut

# HyperFrames renders with its OWN chrome-headless-shell, not Playwright's
# browser, and fetches it on first render. In a container that download is both a
# cold-start cost and a failure the job only discovers at render time - it needs
# unzip (installed above) and working egress. Point it at the Chromium already in
# the image instead: any Chrome build works for the screenshot capture path, and
# nothing is downloaded at run time.
# Resolved at build time, never hardcoded: Playwright's revision directory
# (chromium-<rev>) changes whenever the pip package moves. The build fails loudly
# if no browser is found rather than leaving a dangling path for a job to hit.
RUN set -eu; \
    chrome="$(find /opt/pw-browsers -maxdepth 3 -type f -name chrome | head -1)"; \
    [ -n "$chrome" ] || { echo "no chromium under /opt/pw-browsers"; exit 1; }; \
    ln -sf "$chrome" /usr/local/bin/hf-chrome; \
    /usr/local/bin/hf-chrome --version
ENV HYPERFRAMES_BROWSER_PATH=/usr/local/bin/hf-chrome

WORKDIR /app
COPY skills/ /app/skills/
COPY CLAUDE.md README.md /app/

RUN pinned="$(python3 -c 'import sys;sys.path.insert(0,"/app/skills/reelkit/scripts");import reelkit;print(reelkit.HF_VERSION)')"; \
    [ "$pinned" = "$HF_VERSION" ] || { echo "image warms hyperframes@$HF_VERSION but reelkit.py pins $pinned"; exit 1; }

RUN python3 /app/skills/reelkit/scripts/reelkit.py doctor

# Override with the job's own arguments, e.g.
#   docker run --rm -e REELKIT_TRANSCRIBE_CMD=... -e FAL_KEY=... img \
#     --project /work/reel --video /work/raw.mp4
ENTRYPOINT ["python3", "/app/skills/reelkit/scripts/worker.py"]
CMD ["--help"]
