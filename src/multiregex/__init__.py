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

try:
    sre_constants = re._constants  # type: ignore
    sre_parse = re._parser  # type: ignore
except AttributeError:
    import sre_constants
    import sre_parse
from typing import (
    Dict,
    Iterable,
    List,
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
Prematchers = Set[str]
FalsePositivesCounter = Dict[str, int]


class AhocorasickError(Exception):
    pass


class RegexMatcher:
    def __init__(
        self,
        patterns: Iterable[
            Union[PatternOrStr, Tuple[PatternOrStr, Optional[Iterable[str]]]]
        ],
        count_prematcher_false_positives=False,
    ):
        """
        Parameters
        ----------
        patterns : list of patterns or (pattern, prematchers) tuples
            The patterns to match against. Patterns may either be instances of
            `re.Pattern` (results from `re.compile`) or strings.
            If given as list of `(pattern, prematchers)` tuples, `prematchers`
            are custom prematchers (iterables of strings) or `None` for automatic
            prematchers using `generate_prematchers`. To disable prematchers for
            a specific pattern (ie., always run the "slow" matcher without any
            prematching), use a `(pattern, []`) tuple.
        count_prematcher_false_positives : bool, default: False
            If true, enable "profiling" to check the effectiveness of prematchers on
            the input strings given to ``search``, ``match``, and ``fullmatch``.
            Use ``format_prematcher_false_positives`` to retrieve the profile.
        """
        patterns = self._normalize_patterns(patterns)
        patterns = self._generate_missing_prematchers(patterns)
        self.patterns = [pattern for pattern, _ in patterns]
        self.prematchers = dict(patterns)
        self.patterns_without_prematchers = {
            pattern for pattern, prematchers in patterns if not prematchers
        }
        self.automaton = self._make_automaton(patterns)

        self.count_prematcher_false_positives = count_prematcher_false_positives
        if count_prematcher_false_positives:
            self.prematcher_false_positives = {
                pattern: {"positives": 0, "false_positives": 0}
                for pattern in self.patterns
            }

    @classmethod
    def generate_prematchers(cls, pattern: Pattern) -> Prematchers:
        """Generate prematchers for the given pattern."""
        return generate_prematchers(pattern)

    @staticmethod
    def _normalize_patterns(patterns):
        """Normalize `patterns` param given to `__init__`."""

        def safe_set(iterable):
            if isinstance(iterable, str):
                raise TypeError(
                    "Refusing to interpret {!r} as a list of patterns, pass a list of strings instead".format(
                        iterable
                    )
                )
            else:
                return set(iterable)

        patterns = list(patterns)
        if patterns and not isinstance(patterns[0], tuple):
            return [(re.compile(pattern), None) for pattern in patterns]
        else:
            return [
                (
                    re.compile(pattern),
                    None if prematchers is None else safe_set(prematchers),
                )
                for pattern, prematchers in patterns
            ]

    def _generate_missing_prematchers(self, patterns):
        patterns = [
            (
                pattern,
                self.generate_prematchers(pattern)
                if prematchers is None
                else prematchers,
            )
            for pattern, prematchers in patterns
        ]
        for _, prematchers in patterns:
            for prematcher in prematchers:
                validate_prematcher(prematcher)
        return patterns

    @staticmethod
    def _make_automaton(prematchers):
        """Create the pyahocorasick automaton."""
        pattern_candidates_by_prematchers = collections.defaultdict(set)
        for pattern, prematchers_ in prematchers:
            for prematcher in prematchers_:
                pattern_candidates_by_prematchers[prematcher].add(pattern)
        return _ahocorasick_make_automaton(pattern_candidates_by_prematchers)

    def run(self, match_func, s, enable_prematchers=True):
        """Quickly run `match_func` against `s` for all patterns.

        Parameters
        ----------
        match_func : Callable[str] -> Match
            The base matching function, eg. `re.search`.
        s : str
            The string to match against.
        enable_prematchers : bool (default True)
            If false, do not use prematchers; use `match_func` only.
        """
        candidates = self.patterns
        if enable_prematchers:
            candidates_set = self.get_pattern_candidates(s)
            candidates = [p for p in candidates if p in candidates_set]

        # Inlined versions for match_func = re.match/search, up to 30% faster.
        if match_func is re.search:
            re_results = [(pattern, pattern.search(s)) for pattern in candidates]
        elif match_func is re.match:
            re_results = [(pattern, pattern.match(s)) for pattern in candidates]
        elif match_func is re.fullmatch:
            re_results = [(pattern, pattern.fullmatch(s)) for pattern in candidates]
        else:
            re_results = [(pattern, match_func(pattern, s)) for pattern in candidates]
        if self.count_prematcher_false_positives:
            for pattern, match in re_results:
                self.prematcher_false_positives[pattern]["positives"] += 1
                if match is None:
                    self.prematcher_false_positives[pattern]["false_positives"] += 1

        return [(pattern, match) for pattern, match in re_results if match is not None]

    """Alias for ``run(re.search, ...)``."""
    search = functools.partialmethod(run, re.search)

    """Alias for ``run(re.match, ...)``."""
    match = functools.partialmethod(run, re.match)

    """Alias for ``run(re.fullmatch, ...)``."""
    fullmatch = functools.partialmethod(run, re.fullmatch)

    def get_pattern_candidates(self, s: str) -> Set[Pattern]:
        """Get a set of patterns that potentially match `s`."""
        s = to_lowercase_ascii(s)
        return self.patterns_without_prematchers.union(
            *(candidates for _, candidates in self.automaton.iter(s))
        )

    def get_prematcher_false_positives(
        self,
    ) -> List[Tuple[Pattern, FalsePositivesCounter]]:
        if not self.count_prematcher_false_positives:
            raise RuntimeError("Prematcher profiling not enabled")
        return sorted(
            (
                (pattern, fp_counter)
                for pattern, fp_counter in self.prematcher_false_positives.items()
                if fp_counter["false_positives"]
            ),
            key=lambda x: -x[1]["false_positives"],
        )

    def format_prematcher_false_positives(self, worst_n: Optional[int] = None) -> str:
        output = [
            "FP count | FP rate | Pattern / Prematchers",
            "---------+---------+----------------------",
        ]
        fp_data = self.get_prematcher_false_positives()[:worst_n]
        if fp_data:
            for pattern, fp_counter in fp_data:
                output.append(
                    "{:>8d} |    {:.2f} | {} / {}".format(
                        fp_counter["false_positives"],
                        fp_counter["false_positives"] / fp_counter["positives"],
                        pattern.pattern,
                        self.prematchers[pattern],
                    )
                )
        else:
            output.append("(No data)")
        return "\n".join(output)


def _isascii(s: str) -> bool:
    try:
        return s.isascii()
    except AttributeError:
        # Python < 3.7
        return not any(ord(c) & 0x80 for c in s)


def to_lowercase_ascii(s: str) -> str:
    return s.lower().encode("ascii", errors="ignore").decode()


def validate_prematcher(prematcher: str) -> None:
    if not prematcher or any(map(str.isupper, prematcher)):
        raise ValueError(
            "Prematcher {!r} must be non-empty, all-lowercase, all-ASCII".format(
                prematcher
            )
        )


def generate_prematchers(pattern: Pattern) -> Prematchers:
    """Generate fallback/default prematchers for the given regex `pattern`.

    Currently the fallback prematcher is just the set of longest terminal texts
    in the pattern, eg. "Fast(er)? regex(es| matching)" -> {" regex"}. One level of
    branches with the "|" character is supported, ie. "(a|bb|ccc)" -> {"ccc", "a", "bb"}.
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

    # Branch case: We find a first-level terminal string in a branch (eg. r"(abc|de)" -> {"abc", "de"}).
    # Each of the children must have a top-level simple prematcher. Nesting is not supported.
    sre_branches = (
        value[1] for type_, value in sre_ast if type_ == sre_constants.BRANCH
    )
    for children in sre_branches:
        simplified_children = map(_simplify_sre_ast, children)
        child_prematchers = set(map(_get_top_level_prematcher, simplified_children))
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
        raise AhocorasickError("Error performing ahocorasick call")
