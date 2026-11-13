import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from foldscan import SMALL_BUFFER, contains, count, count_many


def ref_count(haystack: bytes, needle: bytes) -> int:
    return len(re.findall(re.escape(needle), haystack, re.IGNORECASE))


class TestCount(unittest.TestCase):
    def test_ascii_case_folding(self):
        self.assertEqual(count(b"aBcABCabc", b"abc"), 3)
        self.assertEqual(count(b"aBcABCabc", b"AbC"), 3)
        self.assertEqual(count(b"aBcABCabc", b"abc", ignore_case=False), 1)

    def test_no_match_and_empty_needle(self):
        self.assertEqual(count(b"hello", b"xyz"), 0)
        self.assertEqual(count(b"hello", b""), 6)
        self.assertEqual(count(b"", b""), 1)
        self.assertEqual(ref_count(b"", b""), 1)

    def test_needle_longer_than_haystack(self):
        self.assertEqual(count(b"ab", b"abcdef"), 0)
        self.assertEqual(count(b"", b"a"), 0)

    def test_equal_length(self):
        self.assertEqual(count(b"AbC", b"aBc"), 1)
        self.assertEqual(count(b"AbC", b"aBd"), 0)

    def test_non_ascii_bytes_are_literal(self):
        hay = "STRASSE".encode() + bytes([0xC3, 0x9F])
        self.assertEqual(count(hay, bytes([0xC3, 0x9F])), 1)
        self.assertEqual(count(hay, "ß".encode()), 1)
        # bytes.IGNORECASE is ASCII-only: C3 9F must not fold to "ss".
        self.assertEqual(count(hay, b"ss"), 1)

    def test_regex_metacharacters(self):
        for needle in (b".", b"*", b"(", b"[a-z]", b"\\"):
            hay = b"x" + needle + b"y" + needle.upper()
            self.assertEqual(count(hay, needle), ref_count(hay, needle), needle)

    def test_high_bit_dense(self):
        hay = bytes(range(256)) * 8
        for needle in (b"\x00\xff", b"\xfe", b"\x80\x81"):
            self.assertEqual(count(hay, needle), ref_count(hay, needle))

    def test_dispatch_branches(self):
        hay = b"self " * 2000  # > SMALL_BUFFER
        self.assertGreater(len(hay), SMALL_BUFFER)
        self.assertEqual(count(hay, b"SELF"), 2000)
        self.assertEqual(count(hay, b"self"), 2000)
        small = b"SELF self"
        self.assertLess(len(small), SMALL_BUFFER)
        self.assertEqual(count(small, b"Self"), ref_count(small, b"Self"))

    def test_bytearray_and_memoryview(self):
        self.assertEqual(count(bytearray(b"AbC"), b"abc"), 1)
        self.assertEqual(count(memoryview(b"AbC"), b"abc"), 1)

    def test_type_error(self):
        with self.assertRaises(TypeError):
            count("text", b"a")
        with self.assertRaises(TypeError):
            count(b"text", "a")


class TestContains(unittest.TestCase):
    def test_contains(self):
        self.assertTrue(contains(b"xxAbCxx", b"abc"))
        self.assertFalse(contains(b"xxxxx", b"abc"))
        self.assertTrue(contains(b"anything", b""))
        self.assertFalse(contains(b"", b"a"))
        self.assertTrue(contains(b"x" * 10000 + b"NeEdLe", b"needle"))

    def test_contains_matches_reference(self):
        cases = [
            (b"", b"a"),
            (b"a", b"A"),
            (b"AbCdEf", b"cDe"),
            (bytes(range(256)) * 40, b"\xde\xad"),
        ]
        for hay, needle in cases:
            expected = re.search(re.escape(needle), hay, re.IGNORECASE) is not None
            self.assertEqual(contains(hay, needle), expected)


class TestCountMany(unittest.TestCase):
    def test_matches_individual_counts(self):
        hay = (b"def f(self): return None  # IMPORT self\n" * 400)
        needles = [b"self", b"None", b"import", b"def ", b"missing", b""]
        got = count_many(hay, needles)
        for needle in needles:
            self.assertEqual(got[needle], count(hay, needle), needle)

    def test_small_and_case_sensitive(self):
        small = b"AbC abc"
        self.assertEqual(count_many(small, [b"abc"]), {b"abc": 2})
        self.assertEqual(
            count_many(b"AbC abc", [b"abc"], ignore_case=False), {b"abc": 1}
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
