# Adaptation of the CPython test regex suite.

import re

import pytest

from multiregex import RegexMatcher, generate_prematcher

from . import cpython_test_re


def can_generate_prematcher(pattern):
    try:
        generate_prematcher(pattern)
        return True
    except ValueError:
        return False


cpython_tests = [
    test + ((None,) * (5 - len(test)))
    for test in cpython_test_re.tests
    if test[2] != cpython_test_re.SYNTAX_ERROR
    and can_generate_prematcher(re.compile(test[0]))
]


@pytest.mark.parametrize("pattern, s, outcome, expr, expected", cpython_tests)
def test_patterns(pattern, s, outcome, expr, expected):
    matcher = RegexMatcher([pattern])
    result = matcher.search(s)

    if outcome == cpython_test_re.FAIL:
        assert not result
        return

    assert result
    ((_, match),) = result
    vardict = {
        "found": match.group(0),
        "groups": match.group(),
        "flags": match.re.flags,
        "g1": "None",
        "g2": "None",
        "g3": "None",
        "g4": "None",
    }
    for (name, key) in [
        ("g1", 1),
        ("g2", 2),
        ("g3", 3),
        ("g4", 4),
    ] + [(g, g) for g in match.re.groupindex]:
        try:
            val = str(match.group(key))
        except IndexError:
            val = "None"
        vardict[name] = val
    assert eval(expr, vardict) == expected


# # Try the match with IGNORECASE enabled, and check that it
# # still succeeds.
# with self.subTest('case-insensitive match'):
#     obj = re.compile(pattern, re.IGNORECASE)
#     self.assertTrue(obj.search(s))

# # Try the match with UNICODE locale enabled, and check
# # that it still succeeds.
# with self.subTest('unicode-sensitive match'):
#     obj = re.compile(pattern, re.UNICODE)
#     self.assertTrue(obj.search(s))
