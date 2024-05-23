import random
import re

import pytest

from multiregex import AhocorasickError, RegexMatcher, generate_prematchers
from test_utils import assert_matches_equal


def test_basics():
    date_re = re.compile(r"\b2022-[0-1][0-9]-[0-3][0-9]\b")
    time_re = re.compile(r"\b[0-2][0-9]:[0-5][0-9]:[0-5][0-9]\b")
    matcher = RegexMatcher([date_re, time_re])
    assert not matcher.search("abc2022-01-01")
    matches = matcher.search("abc 2022-01-01 23:59:59")
    assert_matches_equal(
        matches,
        [
            (date_re, "2022-01-01"),
            (time_re, "23:59:59"),
        ],
    )


def test_unicode():
    matcher = RegexMatcher(["ä"])
    assert matcher.search("ä")


def test_search_match_fullmatch():
    test_re = re.compile("b")
    matcher = RegexMatcher([test_re])
    assert matcher.search("abc")
    assert not matcher.match("abc")
    assert matcher.match("b")
    assert not matcher.fullmatch("bb")
    assert matcher.fullmatch("b")


def test_ordered():
    patterns = [
        (re.compile(c), None if i % 2 == 0 else []) for i, c in enumerate("abcdef")
    ]  # type: ignore
    random.shuffle(patterns)
    matcher = RegexMatcher(patterns)
    matches = matcher.search("abcdefg")
    assert [p for p, _ in matches] == [p for p, _ in patterns]


@pytest.mark.parametrize(
    "pattern, prematcher",
    [
        ("a", {"a"}),
        ("[a]", {"a"}),
        ("a[0-9]b", {"a"}),
        ("a[0-9]+b", {"a"}),
        ("a[0-9]*b", {"a"}),
        ("a[0-9]?b", {"a"}),
        ("a[x+]b", {"a"}),
        ("aaa|bb", {"aaa", "bb"}),
        ("aaa|bb|c", {"aaa", "bb", "c"}),
        ("aa[a-z]aaa|bb|c", {"aaa", "bb", "c"}),
        ("aa|", None),
        ("(aaa|bb)", {"aaa", "bb"}),
        ("(aa|)", None),
        ("(aa|(bb|cc))", None),
    ],
)
def test_generate_prematchers(pattern, prematcher):
    try:
        assert generate_prematchers(re.compile(pattern)) == prematcher
    except ValueError:
        assert prematcher is None


@pytest.mark.parametrize(
    "prematchers",
    [
        [""],
        ["UPPER"],
        "abc",
    ],
)
def test_invalid_prematchers(prematchers):
    with pytest.raises((AhocorasickError, TypeError, ValueError)):
        RegexMatcher([(re.compile(""), prematchers)])


def test_false_positives_counter():
    matcher = RegexMatcher(["(a|a)a", "aa"], count_prematcher_false_positives=True)
    assert "(No data)" in matcher.format_prematcher_false_positives()
    matcher.match("a")
    matcher.match("aa")
    matcher.match("baa")
    # (a|a)a -> {"a"} prematches all 3 calls but matches only "aa".
    assert "0.67" in matcher.format_prematcher_false_positives()
    # aa -> {"aa"} doesn't prematch "a".
    assert "0.50" in matcher.format_prematcher_false_positives()
