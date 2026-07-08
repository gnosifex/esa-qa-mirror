from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

FIXTURES = Path(__file__).parent / "fixtures"


class FakeHttp:
    """Stands in for common.Http: serves canned pages per URL, records calls.
    Unknown URLs raise requests.HTTPError like a real 404 would."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.calls = []
        self.headers_sent = []

    def get(self, url: str, **kw):
        self.calls.append(url)
        self.headers_sent.append(kw.get("headers") or {})
        if url not in self.pages:
            raise requests.HTTPError(
                f"404 for {url}", response=SimpleNamespace(status_code=404)
            )
        body = self.pages[url]
        if isinstance(body, bytes):
            return SimpleNamespace(text=body.decode("utf-8", "replace"), content=body)
        return SimpleNamespace(text=body, content=body.encode("utf-8"))


@pytest.fixture
def fixture_html():
    def load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return load
