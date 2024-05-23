# Test our simplistic Python parser benchmark example (2x speedup)
import re
from pathlib import Path

from multiregex import RegexMatcher
from test_utils import assert_matches_equal

# Simplistic Python parser
python_parser = {
    "function_definition": r"def\s+[\w]+\(.*\):",
    "class_definition": r"class\s+[\w]+(\(.+\))?:",
    "assignment": r"\w+\s*=\s*.+",
    "return_statement": r"return\s+.+",
    "raise_statement": r"raise\s+.+",
    "forloop": r"for\s+.+\s+in\s+.+:",
    "decorator": r"@.+",
    "import_statement": r"(from\s+.+\s+)?import\s+.+(\s+as\s+.+)?",
}


def test_python_parser():
    assert re.match(python_parser["function_definition"], "def foo():")
    assert re.match(python_parser["class_definition"], "class Foo:")
    assert re.match(python_parser["class_definition"], "class Foo(Bar):")
    assert re.match(python_parser["assignment"], "x = y()")
    assert re.match(python_parser["return_statement"], "return (x, y)")
    assert re.match(python_parser["raise_statement"], "raise from err")
    assert re.match(python_parser["forloop"], "for (_, (x, y)), in spam():")
    assert re.match(python_parser["decorator"], "@foo(x=1)")
    assert re.match(python_parser["import_statement"], "import x")
    assert re.match(python_parser["import_statement"], "from x import y as z")


def test_parse_myself():
    myself = Path(__file__).parents[1] / "multiregex" / "__init__.py"
    with myself.open() as f:
        myself_src = f.read().splitlines()
    slow_matcher = make_slow_matcher(python_parser.values())
    fast_matcher = RegexMatcher(python_parser.values())
    slow_results = map(slow_matcher, myself_src)
    fast_results = map(fast_matcher.search, myself_src)
    for slow_result, fast_result in zip(slow_results, fast_results):
        assert_matches_equal(slow_result, fast_result)


def make_slow_matcher(patterns):
    patterns = [re.compile(pat) for pat in patterns]
    return lambda s: [
        (pat, match)
        for pat, match in [(pat, pat.search(s)) for pat in patterns]
        if match is not None
    ]
