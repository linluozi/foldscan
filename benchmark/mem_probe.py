#!/usr/bin/env python3
"""Peak-RSS probe for one implementation/mode in a fresh process."""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmark"))

import reference  # noqa: E402
from foldscan import count as fast_count  # noqa: E402


def build(mode):
    if mode == "dense":
        return b"a" * 4_000_000, b"A"
    if mode == "sparse":
        return (b"x" * 4_000_000) + b"NeEdLe", b"nEeDlE"
    raise SystemExit(f"unknown mode {mode}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--impl", choices=["reference", "foldscan"], required=True)
    ap.add_argument("--mode", choices=["dense", "sparse"], required=True)
    args = ap.parse_args()
    hay, needle = build(args.mode)
    fn = reference.count if args.impl == "reference" else fast_count
    start = time.perf_counter()
    result = fn(hay, needle)
    elapsed = time.perf_counter() - start
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(json.dumps({
        "impl": args.impl,
        "mode": args.mode,
        "haystack_bytes": len(hay),
        "result": result,
        "seconds": elapsed,
        "peak_rss_kb": peak,
    }))


if __name__ == "__main__":
    main()
