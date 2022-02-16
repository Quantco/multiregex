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

    @staticmethod
    def generate_prematchers(pattern: Pattern) -> Set[str]:
        """Generate prematchers for the given pattern."""
        prematcher = generate_prematcher(pattern)
        return {prematcher}

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
        s = s.lower().encode("ascii", errors="ignore").decode()
        return set.union(
            set(), *(candidates for _, candidates in self._automaton.iter(s))
        )


def generate_prematcher(pattern: Pattern, placeholder="\x01") -> str:
    """Generate a fallback/default prematcher for the given regex `pattern`."""

    def err(reason):
        return ValueError(
            "Could not generate prematcher {}: {!r}".format(reason, pattern.pattern)
        )

    pat = pattern.pattern
    if pattern.flags & re.VERBOSE:
        raise err(" for verbose pattern")
    if placeholder in pat:
        raise err(" for pattern containing placeholder{!r}".format(placeholder))
    if re.search(r"\\[0-7]{3}", pat):
        raise err(" containing octal escape")
    if re.search(r"\\x", pat):
        raise err(r" containing \x.. escape")
    # Strip any leading and trailing modifiers.
    # Eg. "\bfoo(\s)*(?:ue|\u00fc)xy" -> "foo(\s)*(?:ue|\u00fc)xy"
    modifiers1 = ("^", "$")
    modifiers2 = (r"\b", r"\B")
    while pat.startswith(modifiers2):
        pat = pat[2:]
    while pat.startswith(modifiers1):
        pat = pat[1:]
    while pat.endswith(modifiers2):
        pat = pat[:-2]
    while pat.endswith(modifiers1):
        pat = pat[:-1]
    # Some safe cleanup.
    # Eg. "fo[o](\s)*(?:ue|\u00fc)xy" -> "foo(?:ue|\u00fc)xy"
    # Note: This is incorrect within [...], eg. for "[(\s)]"
    pat = re.sub(r"\((.)\)", r"\1", pat)
    pat = re.sub(r"\\s\*?|\\.", placeholder, pat)
    if "[" not in pat:  # These replacements are generally not safe within [...]
        # Replace "X+" with "X" + placeholder
        pat = re.sub(r"(\w)\+", r"\1" + placeholder, pat)
        # Replace "X?" with placeholder.
        pat = re.sub(r"\w\?", placeholder, pat)
    elif not re.search(r"\[[^\]]*\[", pat):  # Don't replace [...] inside other [...]
        # Replace "[X]" with "X"
        pat = re.sub(r"\[(.)\]", r"\1", pat)
        # Replace character ranges with placeholder.
        pat = re.sub(r"\[[^\]]+\][\+\?\*]?", placeholder, pat)
    # Replace simple alternatives "(a|b)" or "(?:a|b)"
    # with placeholder. Only replace if it's the only alternative in the pattern.
    # Eg. "foo_(?:ue|\u00fc)xy" -> "foo__xy"
    if pat.count("(") == 1:
        pat = re.sub(r"\((?:\?:)?[^(]+\)", placeholder, pat)
    # Select longest safe substring. If it is empty, None is returned below.
    # Eg. "foo___xy" -> "foo" (where _ = placeholder)
    pat = max(pat.split(placeholder), key=len)
    # Remove any non-ASCII characters. Fast patterns will match against ASCII
    # characters only (the same thing is done in the generated code).
    pat = pat.encode("ascii", "ignore").decode()
    # If any special regex characters are left in the pattern, refuse to generate
    # a prematcher.
    if pat and re.search(r"[^a-z\s0-9:/-]", pat) is None:
        return pat
    raise err("")


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
