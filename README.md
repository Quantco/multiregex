# multiregex

[![CI](https://github.com/Quantco/multiregex/actions/workflows/ci.yml/badge.svg)](https://github.com/Quantco/multiregex/actions/workflows/ci.yml)
[![Documentation](https://img.shields.io/badge/docs-latest-success?style=plastic)](https://docs.dev.quantco.cloud/qc-github-artifacts/Quantco/multiregex/latest/index.html)

Quickly match many regexes against a string. Provides 2-10x speedups over naïve regex matching.

## Installation

You can install the package in development mode using:

```bash
git clone git@github.com:quantco/multiregex.git
cd multiregex

# create and activate a fresh environment named multiregex
# see environment.yml for details
mamba env create
conda activate multiregex

pre-commit install
pip install --no-build-isolation -e .
```


## Usage

```py
import multiregex

# Create matcher from multiple regexes.
my_patterns = [r"\w+@\w+\.com", r"\w\.com"]
matcher = multiregex.RegexMatcher(my_patterns)

# Run `re.search` for all regexes.
# Returns a set of matches as (re.Pattern, re.Match) tuples.
matcher.search("john.doe@example.com")
# => [(re.compile('\\w+@\\w+\\.com'), <re.Match ... 'doe@example.com'>),
#     (re.compile('\\w+\\.com'), <re.Match ... 'example.com'>)]

# Same as above, but with `re.match`.
matcher.match(...)
# Same as above, but with `re.fullmatch`.
matcher.fullmatch(...)
```

### Custom prematchers

To be able to quickly match many regexes against a string, `multiregex` uses
"prematchers" under the hood. Prematchers are lists of non-regex strings of which
at least one can be assumed to be present in the haystack if the corresponding regex matches.
As an example, a valid prematcher of `r"\w+\.com"` could be `[".com"]` and a valid
prematcher of `r"(B|b)anana"` could be `["B", "b"]` or `["anana"]`.

You will likely have to provide your own prematchers for all but the simplest
regex patterns:

```py
multiregex.RegexMatcher([r"\d+"])
# => ValueError: Could not generate prematcher : '\\d+'
```

To provide custom prematchers, pass `(pattern, prematchers)` tuples:

```py
multiregex.RegexMatcher([(r"\d+", map(str, range(10)))])
```

To use a mixture of automatic and custom prematchers, pass `prematchers=None`:

```py
matcher = multiregex.RegexMatcher([(r"\d+", map(str, range(10))), (r"\w+\.com", None)])
matcher.patterns
# => [(re.compile('\\d+'), ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']),
#     (re.compile('\\w+\\.com'), ['com'])]
```

### Disabling prematchers

To disable prematching for certain pattern entirely (ie., always run the regex
without first running any prematchers), pass an empty list of prematchers:

```py
multiregex.RegexMatcher([(r"super complicated regex", [])])
```
