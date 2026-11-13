#!/usr/bin/env python3
"""Adversarial envelope: search for inputs where the fast path loses.

10,000 unique inputs are generated deterministically (seed 20261114) across
eight classes, timed against the reference scanner, and the dispatched
implementation must not regress on the envelope.  Worst witnesses are saved
byte-for-byte (base64) when small enough to embed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmark"))

import reference  # noqa: E402
from foldscan import count as fast_count  # noqa: E402

SEED = 20261114
N_CASES = 10_000
ROUNDS = 3
CLASSES = [
    "corpus_slice",
    "dense",
    "absent",
    "binary",
    "tiny_fallback",
    "long_needle",
    "metachar",
    "utf8",
]


def load_corpus():
    import sysconfig

    stdlib = Path(sysconfig.get_paths()["stdlib"])
    blobs = []
    for path in sorted(stdlib.rglob("*.py"), key=lambda p: p.stat().st_size, reverse=True):
        if len(blobs) >= 20:
            break
        data = path.read_bytes()
        if len(data) > 20_000:
            blobs.append(data)
    return blobs


def make_case(rng, blobs):
    cls = rng.choice(CLASSES)
    if cls == "corpus_slice":
        blob = rng.choice(blobs)
        size = rng.randrange(16, min(len(blob), 65_536))
        off = rng.randrange(0, max(1, len(blob) - size))
        hay = blob[off:off + size]
        if rng.random() < 0.5:
            start = rng.randrange(0, max(1, len(hay) - 8))
            needle = hay[start:start + rng.randrange(1, 33)]
        else:
            needle = rng.choice([b"def ", b"self", b"import ", b"None", b"__init__"])
    elif cls == "dense":
        unit = bytes(rng.choice(b"abcXYZ_ ") for _ in range(rng.randrange(1, 9)))
        k = rng.randrange(64, 40_000)
        hay = unit * k
        needle = unit.swapcase() if rng.random() < 0.5 else unit
    elif cls == "absent":
        blob = rng.choice(blobs)
        size = rng.randrange(8_192, 65_536)
        off = rng.randrange(0, max(1, len(blob) - size))
        hay = blob[off:off + size]
        needle = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 17)))
        if needle in hay:
            needle = needle + b"\x00\xff"
    elif cls == "binary":
        hay = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 32_768)))
        needle = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 9)))
    elif cls == "tiny_fallback":
        hay = bytes(rng.choice(b"abcABC xyz_") for _ in range(rng.randrange(0, 8_192)))
        needle = bytes(rng.choice(b"abcABC xyz_") for _ in range(rng.randrange(1, 65)))
    elif cls == "long_needle":
        hay = bytes(rng.choice(b"abcdefABCDEF_ \n") for _ in range(rng.randrange(4_096, 65_536)))
        needle = bytes(rng.choice(b"abcdefABCDEF_ \n") for _ in range(rng.randrange(256, 4_097)))
    elif cls == "metachar":
        hay = bytes(rng.choice(b"a.b*c[d]e(f)\\g+?^$| ") for _ in range(rng.randrange(1, 32_768)))
        needle = bytes(rng.choice(b".*[]()\\+?^$|") for _ in range(rng.randrange(1, 9)))
    else:
        text = ("ÄÖÜ äöü ß İı ſΣσς " * rng.randrange(1, 2_000)).encode()
        hay = text[: rng.randrange(0, len(text) + 1)]
        needle = rng.choice(["ß".encode(), "İ".encode(), "ς".encode(), b"ss", b"i"])
    return cls, hay, needle


def median(xs):
    return statistics.median(xs)


def time_pair(hay, needle):
    reference.count(hay, needle)
    fast_count(hay, needle)
    base, fast = [], []
    for rnd in range(ROUNDS):
        if rnd % 2 == 0:
            t0 = time.perf_counter(); b = reference.count(hay, needle); base.append(time.perf_counter() - t0)
            t0 = time.perf_counter(); f = fast_count(hay, needle); fast.append(time.perf_counter() - t0)
        else:
            t0 = time.perf_counter(); f = fast_count(hay, needle); fast.append(time.perf_counter() - t0)
            t0 = time.perf_counter(); b = reference.count(hay, needle); base.append(time.perf_counter() - t0)
    return median(base), median(fast), b, f


def main():
    rng = random.Random(SEED)
    blobs = load_corpus()
    seen = set()
    records = []
    witnesses = []
    mismatches = []
    while len(records) < N_CASES:
        cls, hay, needle = make_case(rng, blobs)
        key = hashlib.sha256(hay + b"\x00" + needle).digest()
        if key in seen:
            continue
        seen.add(key)
        b, f, got_b, got_f = time_pair(hay, needle)
        if got_b != got_f:
            mismatches.append({"class": cls, "sha256": key.hex(), "got": [got_b, got_f]})
            continue
        record = {
            "class": cls,
            "haystack_bytes": len(hay),
            "needle_bytes": len(needle),
            "sha256": key.hex(),
            "reference_s": b,
            "foldscan_s": f,
            "ratio": b / f,
        }
        records.append(record)
        if b / f < 1.0 and len(hay) + len(needle) <= 131_072:
            witnesses.append((b / f, record, hay, needle))

    witnesses.sort(key=lambda w: w[0])
    top = []
    for ratio, record, hay, needle in witnesses[:8]:
        top.append({
            **record,
            "haystack_b64": base64.b64encode(hay).decode(),
            "needle_b64": base64.b64encode(needle).decode(),
        })

    by_class = {}
    for cls in CLASSES:
        ratios = [r["ratio"] for r in records if r["class"] == cls]
        if not ratios:
            continue
        by_class[cls] = {
            "cases": len(ratios),
            "min": min(ratios),
            "p05": sorted(ratios)[max(0, int(0.05 * (len(ratios) - 1)))],
            "median": statistics.median(ratios),
            "max": max(ratios),
            "below_1": sum(1 for r in ratios if r < 1.0),
            "below_095": sum(1 for r in ratios if r < 0.95),
        }

    all_ratios = [r["ratio"] for r in records]
    summary = {
        "seed": SEED,
        "cases": len(records),
        "unique_sha256": len(seen),
        "rounds_per_case": ROUNDS,
        "timer": "time.perf_counter",
        "mismatches": len(mismatches),
        "min_ratio": min(all_ratios),
        "p05_ratio": sorted(all_ratios)[int(0.05 * (len(all_ratios) - 1))],
        "median_ratio": statistics.median(all_ratios),
        "max_ratio": max(all_ratios),
        "below_1": sum(1 for r in all_ratios if r < 1.0),
        "below_095": sum(1 for r in all_ratios if r < 0.95),
        "by_class": by_class,
        "worst_witnesses": top,
        "command": "python3 benchmark/envelope.py",
    }
    (ROOT / "benchmark" / "envelope.json").write_text(json.dumps(summary, indent=2) + "\n")
    (ROOT / "benchmark" / "raw" / "envelope.json").write_text(
        json.dumps({"summary": {k: v for k, v in summary.items() if k != "worst_witnesses"},
                    "records": records}, indent=1) + "\n"
    )
    print(f"cases={len(records)} unique={len(seen)} mismatches={len(mismatches)}")
    print(f"envelope min={min(all_ratios):.3f} p05={summary['p05_ratio']:.3f} "
          f"median={summary['median_ratio']:.2f} max={summary['max_ratio']:.2f} "
          f"below_1={summary['below_1']}")
    for cls, data in by_class.items():
        print(f"  {cls:14} n={data['cases']:5d} min={data['min']:.3f} "
              f"median={data['median']:.2f} below_1={data['below_1']}")
    if mismatches:
        print("MISMATCHES:", mismatches[:3])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
