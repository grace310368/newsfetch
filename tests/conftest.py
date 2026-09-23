import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from newsfetch import db  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
