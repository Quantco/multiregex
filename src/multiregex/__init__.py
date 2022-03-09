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
import sre_constants
import sre_parse
from typing import (
    Dict,
    Iterable,
    List,
    Match,
    Optional,
    Pattern,
    Set,
    Tuple,
    TypeVar,
    Union,
    cast,
)

import ahocorasick
import pkg_resources

try:
    __version__ = pkg_resources.get_distribution(__name__).version
except Exception:
    __version__ = "unknown"


V = TypeVar("V")
PatternOrStr = Union[Pattern, str]


class RegexMatcher:
    def __init__(
        self,
        patterns: Iterable[
            Union[PatternOrStr, Tuple[PatternOrStr, Optional[Iterable[str]]]]
        ],
    ):
        """
        Parameters
        ----------
        patterns : list of patterns or (pattern, prematchers) tuples
            The patterns to match against. Patterns may either be instances of
            `re.Pattern` (results from `re.compile`) or strings.
            If given as list of `(pattern, prematchers)` tuples, `prematchers`
            are custom prematchers (iterables of strings) or `None` for automatic
            prematchers using `generate_prematchers`.
        """
        patterns = self._normalize_patterns(patterns)
        self.patterns = [
            (pattern, prematchers or self.generate_prematchers(pattern))
            for pattern, prematchers in patterns
        ]
        self._automaton = self._make_automaton()

    @classmethod
    def generate_prematchers(cls, pattern: Pattern) -> Set[str]:
        """Generate prematchers for the given pattern."""
        prematchers = generate_prematcher(pattern)
        for prematcher in prematchers:
            cls.validate_prematcher(prematcher)
        return prematchers

    @staticmethod
    def validate_prematcher(prematcher):
        if (
            not prematcher
            or not _isascii(prematcher)
            or any(map(str.isupper, prematcher))
        ):
            raise ValueError(
                "Prematcher {!r} must be non-empty, all-lowercase, all-ASCII".format(
                    prematcher
                )
            )

    @staticmethod
    def _normalize_patterns(patterns) -> List[Tuple[Pattern, Set[str]]]:
        """Normalize `patterns` param given to `__init__`."""
        if isinstance(patterns, str):
            raise TypeError(
                "Refusing to interpret {!r} as a list of patterns, pass a list of strings instead".format(
                    patterns
                )
            )
        patterns = list(patterns)
        if patterns and not isinstance(patterns[0], tuple):
            patterns = [(pattern, None) for pattern in patterns]
        patterns = [
            (re.compile(pattern), set(prematchers or ()))
            for pattern, prematchers in patterns
        ]
        return patterns

    def _make_automaton(self):
        """Create the pyahocorasick automaton."""
        pattern_candidates_by_prematchers = collections.defaultdict(set)
        for pattern, prematchers in self.patterns:
            for prematcher in prematchers:
                pattern_candidates_by_prematchers[prematcher].add(pattern)
        return _ahocorasick_make_automaton(pattern_candidates_by_prematchers)

    def match(self, s) -> Set[Tuple[Pattern, Match]]:
        """Quickly run `re.match` against `s` for all patterns."""
        return self._match(s, re.match, ordered=False)

    def match_ordered(self, s) -> List[Tuple[Pattern, Match]]:
        """Quickly run `re.match` against `s` for all patterns.

        Return results in the same order as `self.patterns` (potentially slower than `match`).
        """
        return self._match(s, re.match, ordered=True)

    def search(self, s) -> Set[Tuple[Pattern, Match]]:
        """Quickly run `re.match` against `s` for all patterns."""
        return self._match(s, re.search, ordered=False)

    def search_ordered(self, s) -> List[Tuple[Pattern, Match]]:
        """Quickly run `re.match` against `s` for all patterns.

        Return results in the same order as `self.patterns` (potentially slower than `search`).
        """
        return self._match(s, re.search, ordered=True)

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
        """Get a set of patterns that potentially match `s`."""
        s = to_lowercase_ascii(s)
        return set.union(
            set(), *(candidates for _, candidates in self._automaton.iter(s))
        )


def _isascii(s: str) -> bool:
    try:
        return s.isascii()
    except AttributeError:
        # Python < 3.7
        return not any(ord(c) & 0x80 for c in s)


def to_lowercase_ascii(s: str) -> str:
    return s.lower().encode("ascii", errors="ignore").decode()


def generate_prematcher(pattern: Pattern) -> Set[str]:
    """Generate a fallback/default prematchers for the given regex `pattern`.

    Currently the fallback prematcher is just the longest terminal text in the
    pattern, eg. "Fast(er)? regex(es| matching)" -> " regex". One level of
    alternatives with the "|" character is supported, ie. "(a|bb|ccc)" -> "ccc".
    """

    def _get_top_level_prematcher(sre_ast):
        return max(
            map(to_lowercase_ascii, _sre_find_terminals(sre_ast)), key=len, default=""
        )

    sre_ast = _simplify_sre_ast(sre_parse.parse(pattern.pattern))

    # Simple case: We find a top-level terminal string (eg. r"Fast(er)" -> "Fast").
    top_level_prematcher = _get_top_level_prematcher(sre_ast)
    if top_level_prematcher:
        return {top_level_prematcher}

    # Branch case: We find a first-level terminal string in a branch (eg. r"(abc|de)" -> "abc").
    # Each of the children must have a top-level simple prematcher. Nesting is not supported.
    sre_branches = (
        value[1] for type_, value in sre_ast if type_ == sre_constants.BRANCH
    )
    for children in sre_branches:
        simplified_children = map(_simplify_sre_ast, children)
        child_prematchers = set(map(_get_top_level_prematcher, simplified_children))
        print(child_prematchers)
        if all(child_prematchers):
            return child_prematchers

    raise ValueError("Could not generate prematchers for {!r}".format(pattern.pattern))


def _simplify_sre_ast(sre_ast):
    """Simplify an sre AST.

    - Transform pattern r"(...)" to r"...".
    """
    if len(sre_ast) == 1 and sre_ast[0][0] is sre_constants.SUBPATTERN:
        if len(sre_ast[0][1]) == 2:
            # Python < 3.6 has no subpattern flags support
            return sre_ast[0][1][1]
        else:
            _, add_flags, del_flags, p = sre_ast[0][1]
            if not add_flags and not del_flags:
                return p
    return sre_ast


def _sre_find_terminals(sre_ast):
    """Find all terminals (streaks of LITERALs) in an sre AST."""
    i = 0
    while i < len(sre_ast):
        chars = []
        while i < len(sre_ast) and sre_ast[i][0] is sre_constants.LITERAL:
            chars.append(cast(int, sre_ast[i][1]))
            i += 1
        yield "".join(map(chr, chars))
        i += 1


def _ahocorasick_make_automaton(words: Dict[str, V]) -> "ahocorasick.Automaton[V]":
    """Make an ahocorasick automaton from a dictionary of `needle -> value` items."""
    automaton = ahocorasick.Automaton()  # type: ahocorasick.Automaton[V]
    for word, value in words.items():
        _ahocorasick_ensure_successful(automaton.add_word(word, value))
    _ahocorasick_ensure_successful(automaton.make_automaton())
    return automaton


def _ahocorasick_ensure_successful(res):
    """pyahocorasick returns errors as bools."""
    if res is False:
        raise RuntimeError("Error performing ahocorasick call")
