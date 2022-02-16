r"""Speed up regex matching with non-regex substring "prematchers", similar to Bloom filters.

For each regex pattern we use a list of simple (non-regex) substring prematchers.
When evaluating regex patterns on a string, we use the prematchers to restrict
the set of regex patterns to be run. Hence, the prematchers _must_ match each string
unless it's impossible for the corresponding regex to match, similar to Bloom filters.

Examples:
    r"\bfoo\b"          -> ["foo"]
    r"(foo|bar) \s*"    -> ["foo ", "bar "]
    r"Gemäß Richtlinie" -> ["gem richtlinie"]
    # Prematchers are all-lowercase and non-ASCII characters are ignored

Prematchers are attempted to be automatically generated from the regexes, see
`RegexMatcher.generate_prematchers`.  You must provide a handcrafted list of
prematchers for regexes that this fails for.  You may also override the
automatically generated prematchers.
"""

import collections
import functools
import re
from typing import Dict, Iterable, List, Optional, Pattern, Set, Tuple, TypeVar, Union

import ahocorasick
import pkg_resources

try:
    __version__ = pkg_resources.get_distribution(__name__).version
except Exception:
    __version__ = "unknown"


V = TypeVar("V")
PatternOrStr = Union[Pattern, str]


class RegexMatcher:
    patterns: List[Tuple[Pattern, Set[str]]]

    def __init__(
        self,
        patterns: Iterable[
            Union[PatternOrStr, Tuple[PatternOrStr, Optional[Iterable[str]]]]
        ],
    ):
        patterns = self._normalize_patterns(patterns)
        self.patterns = [
            (pattern, prematchers or self.generate_prematchers(pattern))
            for pattern, prematchers in patterns
        ]
        self._automaton = self._make_automaton()

    @staticmethod
    def generate_prematchers(pattern: Pattern) -> Set[str]:
        prematcher = generate_prematcher(pattern.pattern)
        return {prematcher}

    @staticmethod
    def _normalize_patterns(patterns) -> List[Tuple[Pattern, Set[str]]]:
        if isinstance(patterns, str):
            raise TypeError(
                f"Refusing to interpret {patterns!r} as a list of patterns, pass a list of strings instead"
            )
        patterns = list(patterns)
        if patterns and not isinstance(patterns[0], tuple):
            patterns = [(pattern, None) for pattern in patterns]
        patterns = [
            (re.compile(pattern), set(prematchers or ())) for pattern, prematchers in patterns
        ]
        return patterns

    def _make_automaton(self):
        pattern_candidates_by_prematchers = collections.defaultdict(set)
        for pattern, prematchers in self.patterns:
            for prematcher in prematchers:
                pattern_candidates_by_prematchers[prematcher].add(pattern)
        return _ahocorasick_make_automaton(pattern_candidates_by_prematchers)

    def match(self, s):
        return self._match(s, re.Pattern.match, ordered=False)

    def match_ordered(self, s):
        return self._match(s, re.Pattern.match, ordered=True)

    def search(self, s):
        return self._match(s, re.Pattern.search, ordered=False)

    def search_ordered(self, s):
        return self._match(s, re.Pattern.search, ordered=True)

    def _match(self, s, match_method, ordered):
        candidates = list(self.get_pattern_candidates(s))
        if ordered:
            candidates = [
                pattern for pattern, _ in self.patterns if pattern in candidates
            ]
        match_method = functools.partial(match_method, string=s)
        matches = [
            (pattern, match)
            for pattern, match in zip(candidates, map(match_method, candidates))
            if match is not None
        ]
        if ordered:
            return matches
        else:
            return set(matches)

    def get_pattern_candidates(self, s: str) -> Set[Pattern]:
        s = s.lower().encode("ascii", errors="ignore").decode()
        return set.union(
            set(), *(candidates for _, candidates in self._automaton.iter(s))
        )


def generate_prematcher(pattern: str) -> str:
    """Generate a fallback/default prematcher for the given regex `pattern`."""
    pattern_backup = pattern
    # We use _ as placeholder below.
    assert "_" not in pattern
    # Strip any leading and trailing \b.
    # Eg. "\bfoo(\s)*(?:ue|\u00fc)xy" -> "foo(\s)*(?:ue|\u00fc)xy"
    while pattern.startswith(r"\b"):
        pattern = pattern[2:]
    while pattern.endswith(r"\b"):
        pattern = pattern[:-2]
    # Some safe cleanup.
    # Eg. "foo(\s)*(?:ue|\u00fc)xy" -> "foo(?:ue|\u00fc)xy"
    pattern = (
        pattern.lower()
        .replace(r"(\s)", r"\s")
        .replace(r"\s*", r"_")
        .replace(r"\s", r"_")
        .replace(r"\.", r"_")
    )
    # Replace character ranges with placeholder.
    pattern = re.sub(r"\[[^\]]+\]", "_", pattern)
    # Common special case: Replace simple alternatives "(a|b)" or "(?:a|b)"
    # with placeholder. Only replace if it's the only alternative in the pattern.
    # Eg. "foo_(?:ue|\u00fc)xy" -> "foo__xy"
    if pattern.count("(") == 1:
        pattern = re.sub(r"\((?:\?:)?[^(]+\)", "_", pattern)
    # Select longest safe substring. If it is empty, None is returned below.
    # Eg. "foo___xy" -> "foo".
    pattern = max(pattern.split("_"), key=len)
    # Remove any non-ASCII characters. Fast patterns will match against ASCII
    # characters only (the same thing is done in the generated code).
    pattern = pattern.encode("ascii", "ignore").decode()
    # If any special regex characters are left in the pattern, refuse to generate
    # a prematcher.
    if not pattern or re.search(r"[^a-z\s0-9:/-]", pattern) is not None:
        raise ValueError(f"Could not generate prematcher for {pattern_backup!r}")
    return pattern


def _ahocorasick_make_automaton(words: Dict[str, V]) -> "ahocorasick.Automaton[V]":
    """Make an ahocorasick automaton from a dictionary of `needle -> value` items."""
    automaton: ahocorasick.Automaton[V] = ahocorasick.Automaton()
    for word, value in words.items():
        _ahocorasick_ensure_successful(automaton.add_word(word, value))
    _ahocorasick_ensure_successful(automaton.make_automaton())
    return automaton


def _ahocorasick_ensure_successful(res):
    if res is False:
        raise RuntimeError("Error performing ahocorasick call")
