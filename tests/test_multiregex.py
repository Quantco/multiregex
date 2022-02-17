import random
import re

import pytest

from multiregex import RegexMatcher, generate_prematcher
from test_utils import assert_matches_equal


def test_basics():
    date_re = re.compile(r"\b2022-[0-1][0-9]-[0-3][0-9]\b")
    time_re = re.compile(r"\b[0-2][0-9]:[0-5][0-9]:[0-5][0-9]\b")
    matcher = RegexMatcher([date_re, time_re])
    assert not matcher.search("abc2022-01-01")
    matches = matcher.search("abc 2022-01-01 23:59:59")
    assert_matches_equal(
        matches,
        {
            (date_re, "2022-01-01"),
            (time_re, "23:59:59"),
        },
    )


def test_match_method():
    test_re = re.compile("b")
    matcher = RegexMatcher([test_re])
    assert matcher.search("abc")
    assert not matcher.match("abc")
    assert matcher.match("b")


def test_ordered():
    patterns = [re.compile(c) for c in "abcdef"]
    random.shuffle(patterns)
    matcher = RegexMatcher(patterns)
    matches = matcher.search_ordered("abcdef")
    assert [p for p, _ in matches] == patterns


@pytest.mark.parametrize(
    "pattern, prematcher",
    [
        ("a", "a"),
        ("[a]", "a"),
        ("a[0-9]b", "a"),
        ("a[0-9]+b", "a"),
        ("a[0-9]*b", "a"),
        ("a[0-9]?b", "a"),
        ("a[x+]b", "a"),
    ],
)
def test_generate_prematcher(pattern, prematcher):
    try:
        assert generate_prematcher(re.compile(pattern)) == prematcher
    except ValueError:
        assert prematcher is None
