import random
import re

from multiregex import RegexMatcher


def assert_matches(a, b):
    def _normalize(pattern_match):
        pattern, match = pattern_match
        return (pattern, match if isinstance(match, str) else match.group())

    a = type(a)(map(_normalize, a))
    b = type(b)(map(_normalize, b))
    assert a == b


def test_basics():
    date_re = re.compile(r"\b2022-[0-1][0-9]-[0-3][0-9]\b")
    time_re = re.compile(r"\b[0-2][0-9]:[0-5][0-9]:[0-5][0-9]\b")
    matcher = RegexMatcher([date_re, time_re])
    assert not matcher.search("abc2022-01-01")
    matches = matcher.search("abc 2022-01-01 23:59:59")
    assert_matches(
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
