#!/usr/bin/env python3
"""Style profiles - where a reference-derived default lands.

A profile is data, not code: the editing moves observed in the reference reels
live in `assets/style/<name>.json` and the build reads them. Adding a move is a
line in a JSON file and a diff a human can review, not an edit spread across
four scripts.

Resolution order, each layer stating only its deltas:

    code defaults  ->  style profile  ->  plan.json  ->  per-beat

`base` is the floor and is exactly reelkit's pre-profile behaviour, so a
profile that says nothing changes nothing. `assaf-v1` is the house style and
`extends` base, so its file is a readable list of what the house does
differently.

Two rules keep a config surface from lying about itself:

  1. **Unknown keys are fatal.** A profile may only carry what the build
     actually reads. A key nothing consumes looks configured and is not, which
     is worse than no key at all - so each later capability widens the schema
     in the same commit that consumes it.
  2. **The gate is not configurable.** A profile expresses a preference. It can
     never move the face-zone constants, the readable-scale floor, the hook or
     the SFX cues, and nothing here is reachable from those.
"""
import copy, hashlib, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
STYLE_DIR = os.path.join(SKILL, "assets", "style")
DEFAULT_PROFILE = "assaf-v1"
MAX_EXTENDS = 8

# The schema IS the contract. A section maps to the set of keys the build reads
# today; anything else is refused by name. Sections arrive with the capability
# that consumes them, never ahead of it.
SCHEMA = {
    "captions": {"maxWords", "maxChars", "size", "top", "height",
                 "strokeWidth", "strokeColor", "detonate", "maxDetonations"},
    "motion": {"defaults", "kinds"},
    "pacing": {"dwellMin", "dwellMax", "severity"},
    # Slice 2. Voice processing and cue ducking are preferences; cue PLACEMENT
    # is not, and is deliberately absent - losing a cue is a defect, never a
    # profile setting.
    "audio": {"voice", "duck"},
    # Slice 3. How many marks a moment may carry and how long one draws for.
    # WHICH mark and where it points is the plan's business, not the profile's.
    "doodle": {"maxMarks", "drawSeconds", "severity"},
}
VOICE_KEYS = {"enabled", "highpassHz", "compressor", "eq", "limiter"}
DUCK_KEYS = {"enabled", "threshold", "ratio", "attackMs", "releaseMs"}
MOTION_PRIMS = {"fade", "pop", "slide"}
MOTION_KEYS = {"duration", "ease", "scale"}
TOP_LEVEL = {"name", "version", "extends", "brand"} | set(SCHEMA)
SEVERITIES = {"error", "warn", "off"}


def path(name):
    return os.path.join(STYLE_DIR, f"{name}.json")


def _die(msg):
    raise SystemExit(f"reelkit style: {msg}")


def read(name):
    """One profile file, validated. Raises rather than guessing."""
    p = path(name)
    if not os.path.exists(p):
        have = ", ".join(sorted(f[:-5] for f in os.listdir(STYLE_DIR)
                                if f.endswith(".json"))) if os.path.isdir(STYLE_DIR) else ""
        _die(f"no profile {name!r} in {STYLE_DIR}" + (f" (have: {have})" if have else ""))
    try:
        with open(p, encoding="utf-8") as fh:
            prof = json.load(fh)
    except Exception as e:
        _die(f"{p} is not readable JSON: {e}")
    if not isinstance(prof, dict):
        _die(f"{p} must be a JSON object")
    validate(prof, name)
    return prof


def validate(prof, name):
    unknown = sorted(set(prof) - TOP_LEVEL)
    if unknown:
        _die(f"profile {name!r} has unknown key(s): {', '.join(unknown)}. "
             "A profile may only carry what the build reads - a section arrives "
             "with the capability that consumes it.")
    if not isinstance(prof.get("version", 1), int):
        _die(f"profile {name!r}: version must be an integer")
    for sec, allowed in SCHEMA.items():
        body = prof.get(sec)
        if body is None:
            continue
        if not isinstance(body, dict):
            _die(f"profile {name!r}: {sec} must be an object")
        bad = sorted(set(body) - allowed)
        if bad:
            _die(f"profile {name!r}: unknown key(s) in {sec}: {', '.join(bad)} "
                 f"(allowed: {', '.join(sorted(allowed))})")
    _validate_motion(prof.get("motion") or {}, name)
    _validate_audio(prof.get("audio") or {}, name)
    dsev = (prof.get("doodle") or {}).get("severity")
    if dsev is not None and dsev not in SEVERITIES:
        _die(f"profile {name!r}: doodle.severity must be one of {', '.join(sorted(SEVERITIES))}")
    sev = (prof.get("pacing") or {}).get("severity")
    if sev is not None and sev not in SEVERITIES:
        _die(f"profile {name!r}: pacing.severity must be one of {', '.join(sorted(SEVERITIES))}")


def _validate_motion(motion, name):
    for prim, spec in (motion.get("defaults") or {}).items():
        if prim not in MOTION_PRIMS:
            _die(f"profile {name!r}: motion.defaults has unknown primitive {prim!r} "
                 f"(have: {', '.join(sorted(MOTION_PRIMS))})")
        _validate_spec(spec, name, f"motion.defaults.{prim}")
    for kind, specs in (motion.get("kinds") or {}).items():
        if not isinstance(specs, dict):
            _die(f"profile {name!r}: motion.kinds.{kind} must be an object")
        for prim, spec in specs.items():
            if prim not in MOTION_PRIMS:
                _die(f"profile {name!r}: motion.kinds.{kind} has unknown primitive {prim!r}")
            _validate_spec(spec, name, f"motion.kinds.{kind}.{prim}")


def _validate_audio(audio, name):
    for sec, allowed in (("voice", VOICE_KEYS), ("duck", DUCK_KEYS)):
        body = audio.get(sec)
        if body is None:
            continue
        if not isinstance(body, dict):
            _die(f"profile {name!r}: audio.{sec} must be an object")
        bad = sorted(set(body) - allowed)
        if bad:
            _die(f"profile {name!r}: unknown key(s) in audio.{sec}: {', '.join(bad)} "
                 f"(allowed: {', '.join(sorted(allowed))})")
    for band in (audio.get("voice") or {}).get("eq") or []:
        if not isinstance(band, dict) or "hz" not in band or "gainDb" not in band:
            _die(f"profile {name!r}: each audio.voice.eq band needs hz and gainDb")


def audio_cfg(resolved):
    """(voice, duck) for the mix stage. Absent means off."""
    a = resolved.get("audio") or {}
    return a.get("voice") or {}, a.get("duck") or {}


def _validate_spec(spec, name, where):
    if not isinstance(spec, dict):
        _die(f"profile {name!r}: {where} must be an object")
    bad = sorted(set(spec) - MOTION_KEYS)
    if bad:
        _die(f"profile {name!r}: unknown key(s) in {where}: {', '.join(bad)} "
             f"(allowed: {', '.join(sorted(MOTION_KEYS))})")
    if "duration" in spec and not (isinstance(spec["duration"], (int, float))
                                   and 0 < spec["duration"] <= 5):
        _die(f"profile {name!r}: {where}.duration must be seconds in (0, 5]")


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load(name=None):
    """Resolve a profile and its `extends` chain into one flat profile.

    Returns (resolved, provenance) where provenance records the chain, each
    file's sha256 and the resolved digest - so a finished reel can say exactly
    which style produced it, and a changed profile is visible rather than
    inferred.
    """
    name = name or DEFAULT_PROFILE
    chain, seen = [], set()
    cur = name
    while cur:
        if cur in seen:
            _die(f"profile {name!r}: circular extends at {cur!r}")
        if len(chain) >= MAX_EXTENDS:
            _die(f"profile {name!r}: extends chain deeper than {MAX_EXTENDS}")
        seen.add(cur)
        prof = read(cur)
        chain.append((cur, prof))
        cur = prof.get("extends")

    resolved = {}
    for cur, prof in reversed(chain):        # base first, the named profile last
        resolved = _merge(resolved, {k: v for k, v in prof.items() if k != "extends"})
    resolved["name"] = name

    files = [{"name": n, "sha256": _sha_file(path(n))} for n, _ in chain]
    prov = {"profile": name,
            "version": resolved.get("version", 1),
            "extends": [n for n, _ in chain[1:]],
            "files": files,
            "resolvedSha256": hashlib.sha256(
                json.dumps(resolved, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    return resolved, prov


def _sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def for_plan(plan):
    """The profile a plan asks for. `plan.style` names it; absent means the house."""
    ref = (plan or {}).get("style")
    if ref is not None and not isinstance(ref, str):
        _die("plan.style must be a profile name")
    return load(ref)


# ------------------------------------------------------------------ consumers

def captions(resolved, plan, brand):
    """Caption knobs, code -> profile -> plan. Brand supplies the floor because
    that is where these lived before profiles existed."""
    out = {"maxWords": brand["captionMaxWords"], "maxChars": brand["captionMaxChars"],
           "size": brand["captionSize"], "top": brand["captionTop"],
           "height": brand["captionHeight"]}
    out.update({k: v for k, v in (resolved.get("captions") or {}).items() if v is not None})
    out.update({k: v for k, v in (plan.get("captions") or {}).items()
                if k in out and v is not None})
    return out


def motion_for(resolved, kind):
    """Per-kind motion: a kind's entry overrides the profile defaults, which
    override whatever the primitive's own signature says. Q1 answered per-kind,
    so a doodle drawing on and a keyword slamming are different rows, not one
    global feel."""
    m = resolved.get("motion") or {}
    out = copy.deepcopy(m.get("defaults") or {})
    for prim, spec in ((m.get("kinds") or {}).get(kind) or {}).items():
        out[prim] = _merge(out.get(prim) or {}, spec)
    return out


def caption_findings(resolved, caps, plan):
    """Detonation is sparse by construction: past the cap it stops reading as
    emphasis and starts reading as a template."""
    import captionfx
    cfg = resolved.get("captions") or {}
    cap = cfg.get("maxDetonations")
    sev = (resolved.get("pacing") or {}).get("severity", "off")
    if cap is None or sev == "off":
        return []
    return captionfx.detonation_findings(
        caps, captionfx.normalise((plan.get("captions") or {}).get("emphasis")),
        cap, "ERROR" if sev == "error" else "WARN")


def doodle_findings(resolved, plan):
    """Mark budget. The reference hand puts one or two marks on a moment; a
    third reads as clutter rather than emphasis, so the cap is enforced at the
    profile's severity like the cadence is."""
    cfg = resolved.get("doodle") or {}
    sev = cfg.get("severity", "off")
    cap = cfg.get("maxMarks")
    if sev == "off" or cap is None:
        return []
    level = "ERROR" if sev == "error" else "WARN"
    out = []
    for b in plan.get("beats", []):
        n = len((b.get("data") or {}).get("marks") or [])
        if n > cap:
            out.append((level, b["id"],
                        f"{n} hand-drawn marks on one beat; the {resolved['name']} profile "
                        f"allows {cap}. Past that they read as clutter rather than emphasis."))
    return out


def pacing_findings(resolved, plan):
    """Dwell enforcement. Q2 answered ENFORCED, so this is a gate finding and
    its severity is the profile's - `off` for a plan that predates the house
    style, `error` for the house."""
    p = resolved.get("pacing") or {}
    sev = p.get("severity", "off")
    lo, hi = p.get("dwellMin"), p.get("dwellMax")
    if sev == "off" or lo is None or hi is None:
        return []
    level = "ERROR" if sev == "error" else "WARN"
    out = []
    for b in plan.get("beats", []):
        d = round(float(b["end"]) - float(b["start"]), 2)
        if d < lo or d > hi:
            out.append((level, b["id"],
                        f"beat dwells {d}s; the {resolved['name']} profile holds a layout "
                        f"{lo}-{hi}s. A beat outside that reads as a slideshow rather than "
                        f"an edit - re-cut the beat, or set \"style\" to a profile that "
                        f"does not enforce pacing."))
    return out
