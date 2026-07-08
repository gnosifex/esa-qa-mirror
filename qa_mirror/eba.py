"""EBA Single Rulebook Q&A adapter.

Listing:  https://www.eba.europa.eu/single-rule-book-qa/search?qa_legal_act[]=<id>&page=N
Detail:   https://www.eba.europa.eu/single-rule-book-qa/qna/view/publicId/<YYYY_NNNN>
Detail markup: <dl class="metadata"> with <dt> label / <dd> value pairs
(Question ID, Legal act, Topic, Article, Question, Answer, Status, dates, ...).
"""
from __future__ import annotations

import re

from .common import Http, Record, html_to_text, iter_listing, soup

BASE = "https://www.eba.europa.eu"
KNOWN_LABELS = {
    "question id": "qa_id",
    "legal act": "legal_act_raw",
    "article": "article",
    "topic": "topic",
    "status": "status",
    "question": "question",
    "background on the question": "background",
    "answer": "answer",
    "final answer": "answer",
}

# Privacy by default for a public mirror: submitter identity adds no substantive
# value and is dropped even though the portal publishes it.
EXCLUDED_LABEL_PARTS = ("submitter", "name of institution", "country of incorporation")


def list_detail_urls(http: Http, params: dict, max_pages: int = 200):
    """Yield detail URLs for the configured legal-act filter, all pages."""
    q = "&".join(f"qa_legal_act%5B%5D={a}" for a in params.get("legal_act_ids", []))
    for link in iter_listing(
        http,
        lambda page: f"{BASE}/single-rule-book-qa/search?{q}&page={page}",
        r'href="(/single-rule-book-qa/qna/view/publicId/[^"]+)"',
        max_pages,
        "eba",
    ):
        yield BASE + link


def fetch_record(http: Http, url: str) -> Record:
    doc = soup(http.get(url).text)
    rec = Record(authority="eba", qa_id="", source_url=url)
    dl = doc.find("dl", class_="metadata")
    if not dl:
        rec.extra["parse_warning"] = "metadata dl not found"
        rec.qa_id = url.rsplit("/", 1)[-1]
        return rec
    for dt in dl.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue
        label = dt.get_text(" ", strip=True).lower()
        if any(part in label for part in EXCLUDED_LABEL_PARTS):
            continue
        value = html_to_text(dd)
        field = KNOWN_LABELS.get(label)
        if field:
            setattr(rec, field, value)
        elif label.startswith("date") or "date" in label:
            rec.dates[re.sub(r"[^a-z0-9]+", "_", label).strip("_")] = value
        else:
            rec.extra[re.sub(r"[^a-z0-9]+", "_", label).strip("_")] = value
    if not rec.qa_id:
        rec.qa_id = url.rsplit("/", 1)[-1]
    return rec
