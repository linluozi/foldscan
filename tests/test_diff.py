"""Differential test: 18,000+ unique (haystack, needle) samples, byte-exact.

Samples are deduplicated by sha256(haystack || 0x00 || needle); the reported N
is the number of *independent* samples, not loop iterations.
"""

import hashlib
import random
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from foldscan import contains, count

TARGET = 18_000
SEED = 20261114
ALPHABETS = [
    bytes(range(256)),
    b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    b"abcABC0123_ \n\t.,;:()[]{}",
    b"ab",
    "äöüßİıſΣσς".encode(),
]


def ref_count(hay: bytes, needle: bytes) -> int:
    return len(re.findall(re.escape(needle), hay, re.IGNORECASE))


def make_sample(rng: random.Random):
    kind = rng.randrange(8)
    alpha = rng.choice(ALPHABETS)
    if kind == 0:
        hay = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 40)))
        needle = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 6)))
    elif kind == 1:
        hay = b""
        needle = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 4)))
    elif kind == 2:
        hay = bytes([rng.randrange(256)]) * rng.randrange(0, 30)
        needle = bytes([rng.choice(alpha)]) * rng.randrange(1, 5)
    elif kind == 3:
        hay = bytes(rng.choice(alpha) for _ in range(rng.randrange(0, 64)))
        needle = hay[rng.randrange(0, max(1, len(hay))):][: rng.randrange(0, 6)]
    elif kind == 4:
        hay = bytes(rng.choice(alpha) for _ in range(rng.randrange(0, 20)))
        needle = hay.upper()
    elif kind == 5:
        hay = rng.choice([b"\x00\xff\x00", bytes(range(256)), b"\xc3\x9f\xc3\x9f"])
        needle = bytes(rng.choice(alpha) for _ in range(rng.randrange(1, 7)))
    elif kind == 6:
        hay = bytes(rng.choice(alpha) for _ in range(rng.randrange(0, 8)))
        needle = bytes(rng.choice(alpha) for _ in range(rng.randrange(0, 40)))
    else:
        ned = bytearray(b"ab" * rng.randrange(0, 20))
        hay = bytes(rng.choice(alpha) for _ in range(rng.randrange(0, 32)))
        needle = bytes(ned)
    return hay, needle


def run_diff(target: int = TARGET):
    rng = random.Random(SEED)
    seen = set()
    samples = []
    attempts = 0
    while len(samples) < target and attempts < target * 20:
        attempts += 1
        hay, needle = make_sample(rng)
        key = hashlib.sha256(hay + b"\x00" + needle).digest()
        if key in seen:
            continue
        seen.add(key)
        samples.append((hay, needle))
    mismatches = []
    for hay, needle in samples:
        got = count(hay, needle)
        want = ref_count(hay, needle)
        got_c = contains(hay, needle)
        want_c = re.search(re.escape(needle), hay, re.IGNORECASE) is not None
        if got != want or got_c != want_c:
            mismatches.append(
                (hay.hex(), needle.hex(), got, want, got_c, want_c)
            )
    return len(samples), len(seen), attempts, mismatches


class TestDifferential(unittest.TestCase):
    def test_unique_samples(self):
        n, hashes, attempts, mismatches = run_diff()
        print(
            f"independent samples N={n} (unique sha256={hashes}), "
            f"attempts={attempts}, mismatches={len(mismatches)}"
        )
        self.assertGreaterEqual(n, TARGET)
        self.assertEqual(len(mismatches), 0, mismatches[:3])

    def test_edge_cases_explicit(self):
        cases = [
            (b"", b""),
            (b"a", b""),
            (b"", b"a"),
            (b"abc", b"abc"),
            (b"abc", b"ABC"),
            (b"\xff\xfe", b"\xfe"),
            (b"\x00" * 10, b"\x00\x00"),
            ("İıſΣς".encode(), b"i"),
            ("İıſΣς".encode(), "ς".encode()),
            (b"a" * 100, b"a" * 3),
        ]
        for hay, needle in cases:
            self.assertEqual(count(hay, needle), ref_count(hay, needle), (hay, needle))


if __name__ == "__main__":
    n, hashes, attempts, bad = run_diff()
    print(
        f"independent samples N={n} (unique sha256={hashes}), "
        f"attempts={attempts}, mismatches={len(bad)}"
    )
    raise SystemExit(0 if n >= TARGET and not bad else 1)
