#!/usr/bin/env python3
"""sc_common.py — shared, stdlib-only helpers for the Swiss Cheese plugin.

Central home for the severity scale and the config loader so that every
script (check_layers, run_guards, commit_gate, audit_log, ...) reads the
same v2 schema and the same backward-compat rules. Keeping this in one
module means the "config v1 -> defaults, never explode" contract is
implemented exactly once.

Stdlib only. Never raises to the caller for a malformed/missing config:
callers layer their own `exit 0` on top, but load_config already degrades
gracefully to defaults.
"""

import json
import os
import shlex
import shutil

# Four-step severity scale. Do NOT introduce another scale anywhere.
SEVERITY = ["low", "medium", "high", "blocker"]
_RANK = {s: i for i, s in enumerate(SEVERITY)}

V1_NOTICE = "config v1 — run /swiss-cheese:init to adopt the new layers"

DEFAULTS = {
    "version": 2,
    "block_at": "high",
    "warn_at": "medium",
    "high_risk_paths": [],
    "layers": {},
    "commit_gate": "off",  # opt-in: the commit gate is a silent no-op until set
}


def sev_rank(severity):
    """Numeric rank of a severity label; unknown labels rank lowest."""
    return _RANK.get(str(severity).lower(), -1)


def sev_at_least(severity, threshold):
    """True if `severity` is as severe as `threshold` (both on the scale)."""
    return sev_rank(severity) >= sev_rank(threshold)


def max_severity(severities):
    """Highest severity in an iterable, or None if empty/unknown."""
    ranked = [s for s in severities if sev_rank(s) >= 0]
    if not ranked:
        return None
    return max(ranked, key=sev_rank)


def binary_on_path(name):
    """True if `name` resolves on PATH. A missing tool is NEVER a pass."""
    if not name:
        return True  # no external binary required
    return shutil.which(name) is not None


def _normalize_v1(cfg):
    """Map a v1 config (layers as a list, per-layer `enabled`/`type`) onto v2.

    A scripted+enabled v1 layer becomes an `auto` v2 layer; disabled or
    non-scripted layers become `skip` so they never gate. We deliberately do
    NOT try to be clever here — just enough to keep old repos running while
    the notice nudges them to re-init.
    """
    layers = {}
    for layer in cfg.get("layers", []):
        if not isinstance(layer, dict) or not layer.get("id"):
            continue
        # v1 had no `mode`; an explicitly-disabled layer maps to `skip`, every
        # other layer to `auto`. check_layers only *runs* layers that carry a
        # command, so non-scripted layers (agents/knowledge/hook) stay present
        # and usable by their own consumers (e.g. hook_gate's agent-hooks).
        mode = "skip" if layer.get("enabled", True) is False else "auto"
        entry = {k: v for k, v in layer.items() if k != "id"}
        entry["mode"] = mode
        layers[layer["id"]] = entry
    out = dict(DEFAULTS)
    # Preserve any extra top-level keys (loop, risk_profile, ...) so callers
    # that read them still see them; only `layers` is normalized/replaced.
    out.update({k: v for k, v in cfg.items() if k != "layers"})
    out["layers"] = layers
    out["_notice"] = V1_NOTICE
    return out


def load_config(path):
    """Load a Swiss Cheese config, normalized to the v2 shape.

    Returns a dict with keys: version, block_at, warn_at, high_risk_paths,
    layers (id -> layer dict, each carrying `mode`), commit_gate, and an
    optional `_notice`. A missing file yields defaults with a `_notice`;
    a malformed file also yields defaults rather than raising, so no layer
    can ever kill the session by shipping bad JSON.
    """
    if not path or not os.path.exists(path):
        out = dict(DEFAULTS)
        out["_notice"] = f"{path or 'config'} not found — run /swiss-cheese:init"
        return out
    try:
        raw = json.load(open(path, encoding="utf-8"))
    except Exception:
        out = dict(DEFAULTS)
        out["_notice"] = f"{path} unreadable — using defaults"
        return out

    if raw.get("version") != 2:
        return _normalize_v1(raw)

    out = dict(DEFAULTS)
    # Preserve ALL top-level keys (block_at/warn_at/high_risk_paths/commit_gate
    # plus arbitrary ones like `slopsquat_online`, per-guard `guards` overrides,
    # `loop`, ...) that downstream scripts rely on; only `layers` is normalized.
    out.update({k: v for k, v in raw.items() if k != "layers"})
    layers = raw.get("layers", {})
    # v2 layers may be a dict (id -> layer) or, defensively, a list of dicts.
    if isinstance(layers, list):
        norm = {}
        for layer in layers:
            if isinstance(layer, dict) and layer.get("id"):
                norm[layer["id"]] = {k: v for k, v in layer.items() if k != "id"}
        layers = norm
    out["layers"] = {k: dict(v, mode=v.get("mode", "auto")) for k, v in layers.items()}
    out["version"] = 2
    return out


# Interpreters/wrappers assumed present in any dev shell. When a command
# starts with one of these we cannot cheaply know the *real* tool it drives
# (e.g. `npx tsc`), so we require no external binary rather than guess wrong.
_KNOWN_PRESENT = {
    "sh", "bash", "zsh", "env", "python", "python3", "py", "node", "npx",
    "npm", "yarn", "pnpm", "make", "just", "task", "poetry", "hatch", "uv",
    "pipx", "pdm", "tox", "docker", "docker-compose", "go", "cargo",
}


def layer_binary(layer):
    """The external binary a layer needs, if any (else None -> no check).

    Explicit `binary` always wins. Otherwise infer the first shell token of
    `command`; a known interpreter/wrapper means "no external binary to
    verify". We deliberately do not dig past wrappers — inferring `tsc` from
    `npx tsc` is fragile, and a false "not on PATH" skip is worse than not
    checking.
    """
    if "binary" in layer:
        return layer["binary"] or None
    command = layer.get("command", "")
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    if not tokens:
        return None
    base = os.path.basename(tokens[0])
    if base in _KNOWN_PRESENT:
        return None
    return base
