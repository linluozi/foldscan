#!/usr/bin/env python3
"""Real-corpus benchmark: foldscan.count vs the idiomatic re.findall scanner.

The corpus is real CPython 3.12 standard-library source, read as bytes and
processed file by file (the documented usage).  Each round is one raw sample;
the summary reports median and p25/p75 per scale.
"""

from __future__ import annotations

import hashlib
import json
import platform
import random
import statistics
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmark"))

import reference  # noqa: E402
from foldscan import count as optimized_count  # noqa: E402

SEED = 20261114
TARGET_BYTES = 3_400_000
WARMUP = 3
ROUNDS = 7
NEEDLES = [b"def ", b"self", b"import ", b"None", b"__init__"]
RAW = ROOT / "benchmark" / "raw"


def pct(values, q):
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def cpu_info():
    try:
        out = subprocess.run(["lscpu"], capture_output=True, text=True, timeout=5).stdout
        keys = ("Model name", "CPU(s)", "Thread(s) per core", "CPU max MHz")
        return [ln.strip() for ln in out.splitlines() if ln.startswith(keys)]
    except Exception as exc:  # pragma: no cover - environment dependent
        return [f"lscpu unavailable: {exc}"]


def mem_total_kb():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1])
    return None


def select_corpus():
    stdlib = Path(sysconfig.get_paths()["stdlib"])
    candidates = sorted(
        (p for p in stdlib.rglob("*.py") if p.is_file()),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    selected, blobs, total = [], [], 0
    for path in candidates:
        data = path.read_bytes()
        selected.append(path)
        blobs.append(data)
        total += len(data)
        if total >= TARGET_BYTES and len(selected) >= 6:
            break
    return selected, blobs, total


def build_scales(files, blobs):
    def take(limit):
        chosen, size = [], 0
        for path, blob in zip(files, blobs):
            if chosen and size + len(blob) > limit:
                break
            chosen.append((path, blob))
            size += len(blob)
        return chosen

    small = take(300_000)
    medium = take(1_100_000)
    large = list(zip(files, blobs))
    scales = {"small": small, "medium": medium, "large": large}
    meta = {
        name: {
            "files": len(items),
            "bytes": sum(len(b) for _, b in items),
            "paths": [str(p) for p, _ in items],
        }
        for name, items in scales.items()
    }
    return scales, meta


def time_impl(fn, items, needle):
    start = time.perf_counter()
    total = 0
    for _path, blob in items:
        total += fn(blob, needle)
    return time.perf_counter() - start, total


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    random.seed(SEED)
    files, blobs, total = select_corpus()
    scales, scale_meta = build_scales(files, blobs)
    corpus_manifest = [
        {
            "path": str(p),
            "bytes": len(b),
            "sha256": hashlib.sha256(b).hexdigest(),
        }
        for p, b in zip(files, blobs)
    ]

    print(f"corpus: {len(files)} files, {total} bytes; python {platform.python_version()}")

    # warmup: touch both code paths and every needle on the largest scale
    for _ in range(WARMUP):
        for needle in NEEDLES:
            reference.count(blobs[0], needle)
            optimized_count(blobs[0], needle)
            for _p, blob in scales["large"]:
                reference.count(blob, needle)
                optimized_count(blob, needle)

    samples = []  # (scale, needle, impl, round, seconds)
    counts = {}
    for rnd in range(ROUNDS):
        order = [("reference", reference.count), ("foldscan", optimized_count)]
        if rnd % 2:
            order.reverse()
        for impl, fn in order:
            for scale, items in scales.items():
                for needle in NEEDLES:
                    seconds, n = time_impl(fn, items, needle)
                    samples.append((scale, needle, impl, rnd, seconds))
                    counts[(scale, needle, impl)] = n
                    payload = {
                        "scale": scale,
                        "needle": needle.decode("latin-1"),
                        "impl": impl,
                        "round": rnd,
                        "seconds": seconds,
                        "files": len(items),
                        "bytes": scale_meta[scale]["bytes"],
                        "matches": n,
                        "seed": SEED,
                    }
                    name = f"{impl}-{scale}-{needle.decode('latin-1').strip().replace(' ', '_')}-{rnd}.json"
                    (RAW / name).write_text(json.dumps(payload, indent=1) + "\n")

    summary = {}
    for scale in scales:
        row = {}
        for impl in ("reference", "foldscan"):
            per_round = [
                sum(s for sc, nd, im, r, s in samples if sc == scale and im == impl)
                for _r in range(ROUNDS)
            ]
            row[impl] = {
                "median_s": statistics.median(per_round),
                "p25_s": pct(per_round, 0.25),
                "p75_s": pct(per_round, 0.75),
                "rsd_pct": (
                    100 * statistics.stdev(per_round) / statistics.mean(per_round)
                    if len(per_round) > 1
                    else 0.0
                ),
            }
        row["speedup"] = row["reference"]["median_s"] / row["foldscan"]["median_s"]
        row["per_needle"] = {}
        for needle in NEEDLES:
            label = needle.decode("latin-1")
            ref = [s for sc, nd, im, r, s in samples if sc == scale and nd == needle and im == "reference"]
            opt = [s for sc, nd, im, r, s in samples if sc == scale and nd == needle and im == "foldscan"]
            row["per_needle"][label] = {
                "reference_median_s": statistics.median(ref),
                "foldscan_median_s": statistics.median(opt),
                "speedup": statistics.median(ref) / statistics.median(opt),
                "matches": counts[(scale, needle, "reference")],
            }
        summary[scale] = row

    env = {
        "project": "foldscan",
        "kind": "original library",
        "upstream": "none",
        "python": platform.python_version(),
        "executable": sys.executable,
        "platform": platform.platform(),
        "cpu": cpu_info(),
        "mem_total_kb": mem_total_kb(),
        "seed": SEED,
        "warmup_rounds": WARMUP,
        "timed_rounds": ROUNDS,
        "timer": "time.perf_counter",
        "command": "python3 benchmark/bench.py",
        "upstream_tests": "n/a: original library, no upstream repository",
        "corpus": {
            "source": "CPython 3.12 standard library *.py read as bytes",
            "stdlib": sysconfig.get_paths()["stdlib"],
            "files": corpus_manifest,
            "bytes": total,
        },
        "scales": scale_meta,
        "measurements": summary,
    }
    (ROOT / "benchmark" / "baseline.json").write_text(json.dumps(env, indent=2) + "\n")

    optimized = json.loads(json.dumps(env))
    optimized["measurements"] = summary
    (ROOT / "benchmark" / "optimized.json").write_text(json.dumps(optimized, indent=2) + "\n")

    print(f"{'scale':8} {'bytes':>9} {'ref ms':>9} {'fold ms':>9} {'speedup':>8}")
    for scale in ("small", "medium", "large"):
        row = summary[scale]
        print(
            f"{scale:8} {scale_meta[scale]['bytes']:9d} "
            f"{row['reference']['median_s'] * 1000:9.2f} "
            f"{row['foldscan']['median_s'] * 1000:9.2f} "
            f"{row['speedup']:8.2f}x"
        )
    print("raw samples:", len(samples))


if __name__ == "__main__":
    main()
