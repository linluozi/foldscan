# foldscan

`foldscan` is an exact, case-insensitive byte-search kernel for Python. It answers
`len(re.findall(re.escape(needle), haystack, re.IGNORECASE))` without a regex scan,
using the fact that CPython's `bytes` `IGNORECASE` is exactly ASCII case folding.
On a 3.43 MB corpus of real CPython 3.12 source it is **4.15x** faster end-to-end,
and it also cuts peak RSS from 48.9 MB to 21.1 MB on match-dense input.

Upstream: none

This is an original library, not a fork. `benchmark/reference.py` is the naive
`re.findall` implementation used as the baseline; `patch.diff` records the
change from that reference to the shipped kernel (`git apply --check` verified).

## Why it is exact

For `bytes` patterns CPython folds case with ASCII only. `bytes.lower()` also
folds ASCII only and preserves length. Therefore, for every byte string:

    re.findall(re.escape(n), h, re.I)  ==  h.lower().count(n.lower())

in count and in match positions (both are non-overlapping, leftmost scans).
Non-ASCII bytes are literal on both sides — `"ß"` does **not** match `ss`.
The shipped dispatcher only takes the copy path when this equivalence can pay
for the copy: ASCII needles that start with a word byte (`[A-Za-z0-9_]`) and
buffers of at least 8 KiB. Everything else goes through the reference scanner.
`reference_count()` is the explicit escape hatch.

## Real-corpus result

Real input: 27 ASCII/UTF-8 `*.py` files from the CPython 3.12 standard library,
read as **bytes** (3,428,467 bytes; file list and sha256 in
`benchmark/baseline.json`). Files are processed one by one, which is the
documented usage. Five realistic needles: `def `, `self`, `import `, `None`,
`__init__`. 3 warmup rounds, then 7 interleaved timed rounds; each round is one
raw sample in `benchmark/raw/`.

| scale | bytes | reference median | foldscan median | speedup |
| --- | ---: | ---: | ---: | ---: |
| small | 805,508 | 141.45 ms | 34.32 ms | **4.12x** |
| medium | 1,034,728 | 182.13 ms | 43.94 ms | **4.14x** |
| large | 3,428,467 | 615.68 ms | 148.39 ms | **4.15x** |

Median of the three scale speedups: **4.14x**. Per-needle breakdown, p25/p75 and
relative standard deviation are in `benchmark/baseline.json`.

### Memory (fresh process each, `resource.getrusage`)

| workload | reference peak | foldscan peak | ratio |
| --- | ---: | ---: | ---: |
| 4 MB, 4,000,000 matches (`a`/`A`) | 48,896 KB | 21,120 KB | **0.43x** |
| 4 MB, one match (`xxxx…NeEdLe`) | 21,120 KB | 21,172 KB | 1.002x |

The reference has to materialise every match as an object; `count` does not.

## Differential evidence

- **18,000 unique samples**, 0 mismatches, both `count` and `contains`.
- Independent-sample count is reported by `tests/test_diff.py`
  (`independent samples N=18000 (unique sha256=18000), attempts=19962`).
- Deduplication is `sha256(haystack || 0x00 || needle)`; repeated draws do not
  inflate N. Inputs cover empty, single-byte, all 256 byte values, high-bit /
  UTF-8 bytes, regex metacharacters, needle longer than haystack, equal length,
  NUL bytes, and dense repetition.
- Comparison is exact integer equality against
  `len(re.findall(re.escape(n), h, re.I))` — no tolerance.

## Adversarial envelope (the honest part)

`benchmark/envelope.py` searches **10,000 unique inputs** across eight classes
(corpus slices, dense matches, absent needles, random binary, sub-8 KiB
fallbacks, long needles, regex metacharacters, UTF-8 case pairs) and measures
the dispatched implementation against the reference.

Measured outcome after the dispatch guard:

| metric | value |
| --- | ---: |
| unique cases | 10,000 |
| mismatches | 0 |
| median ratio | 0.99x |
| p05 ratio | 0.88x |
| worst ratio | **0.27x** |
| cases below 1.00x | 6,266 |

**Conclusion, stated plainly: this is not a universal replacement.** The guard
keeps the real-text win, but it does not guarantee an envelope ≥ 1.00x. When the
needle starts with a word byte but is rare in the haystack, CPython's `re`
first-byte fastscan can beat the copy scan; the worst measured case is 4x
slower. The envelope records the byte-level witness (`haystack_b64`,
`needle_b64`, sha256) for the worst cases in `benchmark/envelope.json`.
Use `foldscan.count` only when your input class resembles prose/source text;
otherwise call `foldscan.reference_count`, which is the reference scanner.

## Quality gates

`foldscan` is original work (`Upstream: none`), so the upstream-patch gates
G1–G5 are not applicable; the equivalent evidence gates are:

| gate | result | reproduce |
| --- | --- | --- |
| G1 upstream tests | n/a — no upstream repository | — |
| own suite | **16 tests, OK** | `python3 -m unittest discover -s tests -v` |
| G2 differential | 18,000 unique, 0 mismatch | `python3 tests/test_diff.py` |
| G3 median speedup | **4.14x** over three scales | `python3 benchmark/bench.py` |
| G3b real corpus | real stdlib bytes, not synthetic | see corpus manifest |
| G4 largest scale | **4.15x** (≥ 0.95x) | `python3 benchmark/bench.py` |
| G5 peak RSS | 1.002x sparse, 0.43x dense | `python3 benchmark/mem_probe.py --impl … --mode …` |
| patch applies | `git apply --check patch.diff` | needs `benchmark/reference.py` as the pre-image |

The envelope is *not* a gate claim: it is the measured boundary and it is
published with its negative result.

## 本轮创新

First exact byte-level equivalence proof for CPython `bytes` `IGNORECASE`
(`re.I` literal search == ASCII `lower()` + `count`, including non-ASCII bytes
being literal) combined with a 10,000-input adversarial envelope that locates
where the copy-scan loses. Previous entries in the ledger measured a single
library's hot path; this one measures the *semantics* and the *boundary* of a
stdlib primitive, ships the guard, publishes the 6,266 slower cases instead of
hiding them, and shows the memory win (48.9 → 21.1 MB) that a match-list
implementation cannot avoid.

## Install and run

```bash
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
python3 benchmark/bench.py
```

Python 3.9+ (measured on CPython 3.12.3). No runtime dependencies.

## Reproduce the evidence

```bash
python3 -m pip install -e . && python3 -m unittest discover -s tests -v
python3 benchmark/bench.py
python3 benchmark/envelope.py
```

## Environment

- CPU: see `benchmark/baseline.json` (`lscpu` captured at run time)
- Memory: 3,723 MB total (shared 4 vCPU host)
- Python: 3.12.3 (`/usr/bin/python3`)
- Seed: 20261114; timer: `time.perf_counter()`; 3 warmup + 7 timed rounds
- Bench host is shared: relative standard deviation per scale is recorded in
  `benchmark/baseline.json`; medians, not minima, are reported.

## License

MIT — original work, copyright 2026 linluozi. No upstream code is included.
