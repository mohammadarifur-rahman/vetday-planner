from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_html():
    def _load(name: str) -> str:
        return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")

    return _load
