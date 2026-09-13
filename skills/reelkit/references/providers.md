# Provider seams

Three stages call something outside this repo: **transcribe**, **planAuthor**,
**image**. Each is a command declared in `config/providers.json` and invoked by
`scripts/assets.py`. No vendor name appears in pipeline code, and swapping one is
a config edit plus an adapter script - never a code edit (CLAUDE.md, coding
standards).

| Seam | Env var | Contract |
| --- | --- | --- |
| transcribe | `REELKIT_TRANSCRIBE_CMD` | write a JSON array of `{text,start,end}`, **one entry per word** |
| planAuthor | `REELKIT_PLAN_AUTHOR_CMD` | read `{request}` JSON, write a graphics plan to `{response}` |
| image | `REELKIT_IMAGE_GENERATOR_CMD` | write one PNG to `{output}` at `{width}x{height}` |

Placeholders are substituted with shell-quoted paths. Secrets never appear in a
command template or a project file - the adapter reads its own key from the
environment at runtime (`fal_adapter.py` reads `FAL_KEY`).

## Writing an adapter

An adapter is any executable that accepts the flags and honours the contract.
`whisper_adapter.py` (local Whisper via the HyperFrames CLI) and `fal_adapter.py`
(fal.ai images) are the references. A hosted adapter for another vendor is a
sibling script with the same flags:

```bash
export REELKIT_TRANSCRIBE_CMD='python3 skills/reelkit/scripts/whisper_adapter.py \
  --audio {audio} --out {out} --lang {lang} --model {model}'
```

## Word-level timestamps are not negotiable

Every caption line, beat boundary and animation cue is derived from word times.
A hosted transcription API that returns **segment**-level timestamps cannot drive
this pipeline: the captions would change once per sentence instead of once per
word, and beat boundaries would land on nothing.

`assets.py` rejects segment-level output rather than letting it through - words
carry no internal space in any language reelkit supports, so a transcript whose
entries mostly contain spaces is segments wearing a word-shaped schema. Before
adopting any hosted transcriber, check two things on **real footage in the target
language**: that it exposes word granularity at all, and that its accuracy holds.
Local `large-v3` still needed five corrections on 47 seconds of Hebrew.

## Caching

All three seams are content-addressed, so a re-render never re-spends:

- transcribe - keyed on `sha256(audio) + model + language`, recorded in `transcript-ledger.json`
- image - keyed on `prompt + box + alpha + provider + model`, recorded in `asset-ledger.json`

A cached transcript means the adapter is optional on re-runs; `assets.py
transcribe` only demands `REELKIT_TRANSCRIBE_CMD` when the cache misses.

## Images are an upgrade, not a dependency

A declared slot with no file falls back to its drawn card and the reel is
complete (`references/image-slots.md`). `worker.py` therefore runs the asset
stage only when an adapter is configured or a cache already holds PNGs - an unset
image adapter must never fail an otherwise good job.
