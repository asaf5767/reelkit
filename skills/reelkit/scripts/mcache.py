#!/usr/bin/env python3
"""Content-keyed cache for the two slow measurements.

Both gates measure the same two things: the settled card box in a real browser
(`geometry.measure_cards`) and the detected head in the footage
(`cards.detect_faces`). On the 5-beat sample reel those cost 20.3s and 15.6s.

They are paid by `build`'s fit pass and again by `verify` seconds later, and
`render_gate` runs verify immediately before EVERY render - so segmentrender,
which renders one segment at a time, pays the pair once per segment on cards it
has already measured and footage it has already scanned.

Three rules keep this from weakening the gate it speeds up:

  1. Between the scope and the key, every input that can change the answer is
     covered - the card HTML, the theme CSS, the canvas size, the measuring
     harness itself, the footage bytes, the sampled timestamps. Anything not
     covered is a miss, and a miss measures for real.
  2. Only positive measurements are stored. A card that measured nothing and a
     beat with no detected face are re-measured every time, so a cache hit can
     only ever hand back a box to AVOID - never remove one. A stale entry
     cannot turn a collision into a clean reel.
  3. Callers consult it only after confirming the measuring dependency is
     installed. This makes the gate faster; it can never make an unmeasurable
     project look measured, which is the failure the fail-closed rule exists
     for.

Stdlib only, one small JSON file per project, written atomically so an
interrupted run leaves the previous cache rather than a truncated one.
"""
import hashlib, json, os, tempfile

NAME = ".measure-cache.json"
VERSION = 1                    # bump to invalidate every entry everywhere


def path(project):
    return os.path.join(project, NAME)


def sha(*parts):
    """Stable digest over the inputs that decide a measurement."""
    h = hashlib.sha256()
    h.update(f"mcache/v{VERSION}\n".encode())
    for p in parts:
        b = p if isinstance(p, bytes) else str(p).encode("utf-8")
        h.update(str(len(b)).encode())       # length-prefixed: no field can
        h.update(b"\x00"); h.update(b)       # impersonate the next one
    return h.hexdigest()


def file_id(p, chunk=1 << 20):
    """Content identity of a file. Empty string when it is not there, which
    keys as "no footage" rather than colliding with some other project's."""
    if not p or not os.path.exists(p):
        return ""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def load(project):
    """Never raises: an unreadable or foreign cache is simply no cache."""
    try:
        with open(path(project), encoding="utf-8") as fh:
            c = json.load(fh)
    except Exception:
        return {}
    if not isinstance(c, dict) or c.get("version") != VERSION:
        return {}
    return c


def get(cache, kind, scope, key):
    """A hit only inside the current scope. A section recorded against other
    footage or another theme is not consulted at all, never merged with."""
    sec = cache.get(kind) or {}
    if sec.get("scope") != scope:
        return None
    v = (sec.get("entries") or {}).get(key)
    return v if v else None          # a falsy stored value is treated as a miss


def replace(project, kind, scope, entries):
    """Merge entries into the section, discarding anything from another scope.

    Scope is what keeps the file bounded without making partial callers
    dangerous. `build` measures the split beats and the over-footage beats in
    two separate passes and `verify` measures every beat in one; all three may
    write, and none can erase another's work, because they share a scope while
    the footage and theme are unchanged. Re-cut the footage or restyle the
    cards and the whole section is dropped in one go - those entries can never
    be right again.
    """
    c = load(project)
    sec = c.get(kind) or {}
    keep = dict(sec.get("entries") or {}) if sec.get("scope") == scope else {}
    keep.update({k: v for k, v in entries.items() if v})
    c["version"] = VERSION
    c[kind] = {"scope": scope, "entries": keep}
    try:
        d = os.path.dirname(os.path.abspath(path(project))) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".mcache-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(c, fh, indent=1, sort_keys=True)
        os.replace(tmp, path(project))
    except Exception:
        pass                          # a cache that cannot be written is not an
    return c                          # error; the next run just measures again
