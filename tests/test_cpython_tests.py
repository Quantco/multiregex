# Adaptation of the CPython test regex suite.

import re

import pytest

from multiregex import RegexMatcher, generate_prematcher
from tests import cpython_test_re


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
@pytest.mark.parametrize("flags", [0, re.ASCII, re.IGNORECASE, re.UNICODE])
def test_patterns(pattern, s, outcome, expr, expected, flags):
    matcher = RegexMatcher([re.compile(pattern, flags)])
    result = matcher.search(s)
    if outcome == cpython_test_re.FAIL:
        assert not result
    else:
        ((_, match),) = result
        assert eval_test_expr(match, expr) == expected


def eval_test_expr(match, expr):
    from typing import Any

    vardict = {
        "found": match.group(0),
        "groups": match.group(),
        "flags": match.re.flags,
    }
    numbered_groups = [("g{}".format(i), i) for i in range(100)]  # type: Any
    named_groups = [(g, g) for g in match.re.groupindex]  # type: Any
    for (name, key) in numbered_groups + named_groups:
        try:
            val = str(match.group(key))
        except IndexError:
            val = "Error"
        vardict[name] = val
    return eval(expr, vardict)
