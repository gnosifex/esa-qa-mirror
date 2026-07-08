from pathlib import Path
from types import SimpleNamespace

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


class FakeHttp:
    """Stands in for common.Http: serves canned HTML per URL, records calls."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.calls = []

    def get(self, url: str):
        self.calls.append(url)
        return SimpleNamespace(text=self.pages[url])


@pytest.fixture
def fixture_html():
    def load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return load
