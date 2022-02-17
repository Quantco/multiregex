import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).parents[1]))


pytest.register_assert_rewrite("test_utils")
