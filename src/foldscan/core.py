"""Core primitives for exact case-insensitive byte search.

The reference semantics are exactly those of::

    len(re.findall(re.escape(needle), haystack, re.IGNORECASE))

For ``bytes`` patterns CPython applies ASCII-only case folding.  ``bytes.lower``
is also ASCII-only and length preserving, so lowering both sides and using
``bytes.count`` yields the same non-overlapping leftmost match count.  This
module exploits that equivalence and dispatches around the cases where the
copy cannot pay for itself.
"""

from __future__ import annotations

import re
from functools import lru_cache

#: Buffers below this size use the reference scanner: the fold copy costs a
#: fixed allocation that cannot be amortised over a few kilobytes.
SMALL_BUFFER = 8192

@lru_cache(maxsize=4096)
def _fold_needle(value: bytes) -> bytes:
    """Fold a needle; bounded LRU because needles repeat across calls."""
    return value.lower()


@lru_cache(maxsize=4096)
def _reference_pattern(needle: bytes) -> re.Pattern[bytes]:
    return re.compile(re.escape(needle), re.IGNORECASE)


def _fold(haystack: bytes) -> bytes:
    """Fold a haystack *without* caching it: buffers must not be retained."""
    return haystack.lower()


def _case_invariant(needle: bytes) -> bool:
    """True when no byte in *needle* has an ASCII case partner."""
    return needle.lower() == needle.upper()


def _worth_folding(haystack: bytes, needle: bytes) -> bool:
    """Cheap guard for the regime where ``re``'s literal fastscan wins.

    Measured on the adversarial envelope: needles that are not ASCII, or that
    do not start with an ASCII letter/digit/underscore, make ``bytes.count``
    slower than the reference's first-byte fastscan.  Real text tokens start
    with a word byte, so the guard keeps the documented win and refuses the
    regime where the copy scan loses.
    """
    if not needle.isascii():
        return False
    head = needle[:1]
    return bool(head.isalnum() or head == b"_")


def _as_bytes(value, name: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    raise TypeError(f"{name} must be bytes-like, got {type(value).__name__}")


def count(haystack, needle, *, ignore_case: bool = True) -> int:
    """Count non-overlapping occurrences of *needle* in *haystack*."""
    hay = _as_bytes(haystack, "haystack")
    pin = _as_bytes(needle, "needle")
    if not ignore_case:
        return hay.count(pin)
    if not pin:
        return len(hay) + 1
    if len(hay) < SMALL_BUFFER:
        return len(_reference_pattern(pin).findall(hay))
    if len(pin) > len(hay):
        return 0
    if not _worth_folding(hay, pin):
        return len(_reference_pattern(pin).findall(hay))
    if _case_invariant(pin):
        return hay.count(pin)
    if len(pin) == len(hay):
        return int(_fold(hay) == _fold(pin))
    return _fold(hay).count(_fold(pin))


def contains(haystack, needle, *, ignore_case: bool = True) -> bool:
    """Return True when *needle* occurs in *haystack*."""
    hay = _as_bytes(haystack, "haystack")
    pin = _as_bytes(needle, "needle")
    if not ignore_case:
        return hay.find(pin) >= 0
    if not pin:
        return True
    if len(hay) < SMALL_BUFFER:
        return _reference_pattern(pin).search(hay) is not None
    if len(pin) > len(hay):
        return False
    if not _worth_folding(hay, pin):
        return _reference_pattern(pin).search(hay) is not None
    if _case_invariant(pin):
        return hay.find(pin) >= 0
    return _fold(hay).find(_fold(pin)) >= 0


def count_many(haystack, needles, *, ignore_case: bool = True) -> dict[bytes, int]:
    """Count several needles, folding the haystack at most once."""
    hay = _as_bytes(haystack, "haystack")
    pins = [_as_bytes(n, "needle") for n in needles]
    if not ignore_case or len(hay) < SMALL_BUFFER or not any(
        pin and not _case_invariant(pin) for pin in pins
    ):
        return {pin: count(hay, pin, ignore_case=ignore_case) for pin in pins}
    low = _fold(hay)
    out: dict[bytes, int] = {}
    for pin in pins:
        if not pin:
            out[pin] = len(hay) + 1
        elif len(pin) > len(hay):
            out[pin] = 0
        elif _case_invariant(pin):
            out[pin] = hay.count(pin)
        else:
            out[pin] = low.count(_fold(pin))
    return out


def reference_count(haystack, needle, *, ignore_case: bool = True) -> int:
    """The reference scanner, exposed as the predictable escape hatch."""
    hay = _as_bytes(haystack, "haystack")
    pin = _as_bytes(needle, "needle")
    if not ignore_case:
        return hay.count(pin)
    return len(_reference_pattern(pin).findall(hay))


__all__ = [
    "count",
    "contains",
    "count_many",
    "reference_count",
    "SMALL_BUFFER",
]
