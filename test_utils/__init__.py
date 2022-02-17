def assert_matches_equal(a, b):
    def _normalize(pattern_match):
        pattern, match = pattern_match
        return (pattern, match if isinstance(match, str) else match.group())

    a = type(a)(map(_normalize, a))
    b = type(b)(map(_normalize, b))
    assert a == b
