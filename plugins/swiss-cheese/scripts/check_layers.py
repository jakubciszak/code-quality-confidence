#!/usr/bin/env python3
"""check_layers.py — run every scripted Swiss Cheese layer in one call.

Loop mode and pre-review gates call this ONE script instead of running
lint/typecheck/tests as separate agent tool calls. Output is a compact JSON
verdict; on failure only the tail of the failing command's output is
included, so the agent never pages through full test logs.

Usage:
    python3 check_layers.py [--config .swiss-cheese/config.json]
                            [--only lint,tests] [--fast] [--tail 30]

  --only   comma-separated layer ids to run (default: all enabled scripted)
  --fast   skip layers marked "fast": false (e.g. slow e2e suites)
  --tail   lines of output kept per failing layer (default 30)

Exit code: 0 if all layers passed, 1 otherwise. Stdlib only.
"""

import argparse
import json
import os
import subprocess
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=".swiss-cheese/config.json")
    ap.add_argument("--only")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--tail", type=int, default=30)
    args = ap.parse_args()

    if not os.path.exists(args.config):
        json.dump({"error": f"{args.config} not found — run /swiss-cheese:init first"}, sys.stdout)
        print()
        sys.exit(1)

    cfg = json.load(open(args.config, encoding="utf-8"))
    only = set(args.only.split(",")) if args.only else None
    layers = [l for l in cfg.get("layers", [])
              if l.get("type") == "scripted" and l.get("enabled", True)
              and l.get("command")
              and (only is None or l["id"] in only)
              and (not args.fast or l.get("fast", True))]

    results, all_ok = [], True
    for layer in layers:
        start = time.time()
        try:
            proc = subprocess.run(layer["command"], shell=True, capture_output=True,
                                  text=True, timeout=layer.get("timeout", 900))
            ok = proc.returncode == 0
            output = (proc.stdout + "\n" + proc.stderr).strip()
        except subprocess.TimeoutExpired:
            ok, output = False, f"TIMEOUT after {layer.get('timeout', 900)}s"
        entry = {"layer": layer["id"], "ok": ok,
                 "seconds": round(time.time() - start, 1)}
        if not ok:
            all_ok = False
            tail = output.splitlines()[-args.tail:]
            entry["command"] = layer["command"]
            entry["output_tail"] = "\n".join(tail)
        results.append(entry)

    json.dump({"ok": all_ok,
               "ran": [r["layer"] for r in results],
               "results": results}, sys.stdout, separators=(",", ":"))
    print()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
