"""Reference implementation: the obvious ``re``-based byte search."""

from __future__ import annotations

import re

_CACHE: dict[bytes, re.Pattern[bytes]] = {}


def _pattern(needle: bytes) -> re.Pattern[bytes]:
    pattern = _CACHE.get(needle)
    if pattern is None:
        pattern = re.compile(re.escape(needle), re.IGNORECASE)
        _CACHE[needle] = pattern
    return pattern


def count(haystack: bytes, needle: bytes, *, ignore_case: bool = True) -> int:
    if not ignore_case:
        return haystack.count(needle)
    return len(_pattern(needle).findall(haystack))


def contains(haystack: bytes, needle: bytes, *, ignore_case: bool = True) -> bool:
    if not ignore_case:
        return haystack.find(needle) >= 0
    return _pattern(needle).search(haystack) is not None
