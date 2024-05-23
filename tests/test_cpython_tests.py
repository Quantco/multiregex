# Adaptation of the CPython test regex suite.

import re

import pytest

from multiregex import RegexMatcher, generate_prematchers
from test_utils import assert_matches_equal, cpython_test_re


def can_generate_prematchers(pattern):
    try:
        generate_prematchers(pattern)
        return True
    except ValueError:
        return False


cpython_tests = [
    test + ((None,) * (5 - len(test)))
    for test in cpython_test_re.tests
    if test[2] != cpython_test_re.SYNTAX_ERROR
    and can_generate_prematchers(re.compile(test[0]))
]


@pytest.mark.parametrize("pattern, s, outcome, expr, expected", cpython_tests)
@pytest.mark.parametrize("flags", [0, re.ASCII, re.IGNORECASE, re.UNICODE])
def test_patterns(pattern, s, outcome, expr, expected, flags):
    matcher = RegexMatcher([re.compile(pattern, flags)])
    result = matcher.search(s)
    result_no_prematchers = matcher.search(s, enable_prematchers=False)
    assert_matches_equal(result, result_no_prematchers)
    if outcome == cpython_test_re.FAIL:
        assert not result
    else:
        ((_, match),) = result
        assert eval_test_expr(match, expr) == expected


def eval_test_expr(match, expr):
    from typing import Any  # noqa

    vardict = {
        "found": match.group(0),
        "groups": match.group(),
        "flags": match.re.flags,
    }
    numbered_groups = [(f"g{i}", i) for i in range(100)]  # type: Any
    named_groups = [(g, g) for g in match.re.groupindex]  # type: Any
    for name, key in numbered_groups + named_groups:
        try:
            val = str(match.group(key))
        except IndexError:
            val = "Error"
        vardict[name] = val
    return eval(expr, vardict)
