#!/usr/bin/env python3
"""check_layers.py — run every scripted Swiss Cheese layer in one call.

Loop mode, the commit gate, and pre-review gates call this ONE script
instead of running lint/typecheck/tests as separate agent tool calls.
Output is a compact JSON verdict; on failure only the tail of the failing
command's output is included, so the agent never pages through full logs.

Layer status model (v2):
- Every layer resolves to **passed | failed | skipped** — never a bare 0/1.
- A layer in `mode: skip`, or whose external binary is not on PATH, is
  **skipped**. A missing tool is NEVER reported as `passed`.
- Global `ok` is computed **only from `auto` layers that `failed`**. Layers
  in `comment` mode and `skipped` layers do not affect `ok`.

Usage:
    python3 check_layers.py [--config .swiss-cheese/config.json]
                            [--only lint,tests] [--fast] [--tail 30]

Exit code: 0 if `ok`, 1 otherwise. Any internal error -> exit 0 (a layer may
have holes, but it must never kill the session). Stdlib only.
"""

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sc_common import load_config, binary_on_path, layer_binary  # noqa: E402


def run_layer(layer_id, layer, tail):
    """Execute one layer and return its result dict.

    status is one of passed | failed | skipped. `command` and `output_tail`
    are only attached on failure to keep the payload small.
    """
    mode = layer.get("mode", "auto")
    command = layer.get("command")

    if mode == "skip":
        return {"layer": layer_id, "mode": mode, "status": "skipped",
                "reason": "mode: skip"}
    if not command:
        return {"layer": layer_id, "mode": mode, "status": "skipped",
                "reason": "no command configured"}

    binary = layer_binary(layer)
    if not binary_on_path(binary):
        return {"layer": layer_id, "mode": mode, "status": "skipped",
                "reason": f"{binary} — not on PATH"}

    start = time.time()
    try:
        proc = subprocess.run(command, shell=True, capture_output=True,
                              text=True, timeout=layer.get("timeout", 900))
        status = "passed" if proc.returncode == 0 else "failed"
        output = (proc.stdout + "\n" + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        status, output = "failed", f"TIMEOUT after {layer.get('timeout', 900)}s"

    entry = {"layer": layer_id, "mode": mode, "status": status,
             "seconds": round(time.time() - start, 1)}
    if status == "failed":
        entry["command"] = command
        entry["output_tail"] = "\n".join(output.splitlines()[-tail:])
    return entry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=".swiss-cheese/config.json")
    ap.add_argument("--only")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--tail", type=int, default=30)
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
        only = set(args.only.split(",")) if args.only else None

        results = []
        for layer_id, layer in cfg["layers"].items():
            if only is not None and layer_id not in only:
                continue
            if args.fast and not layer.get("fast", True):
                continue
            results.append(run_layer(layer_id, layer, args.tail))

        # `ok` is false only when an AUTO layer FAILED. comment/skipped ignored.
        ok = not any(r["status"] == "failed" and r["mode"] == "auto"
                     for r in results)

        payload = {
            "ok": ok,
            "block_at": cfg["block_at"],
            "warn_at": cfg["warn_at"],
            "ran": [r["layer"] for r in results],
            "results": results,
        }
        if cfg.get("_notice"):
            payload["notice"] = cfg["_notice"]
        json.dump(payload, sys.stdout, separators=(",", ":"))
        print()
        sys.exit(0 if ok else 1)
    except SystemExit:
        raise
    except Exception as exc:  # a layer may have holes; it must never kill the session
        json.dump({"ok": True, "error": str(exc)}, sys.stdout)
        print()
        sys.exit(0)


if __name__ == "__main__":
    main()
