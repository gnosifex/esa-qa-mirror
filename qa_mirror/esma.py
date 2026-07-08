"""ESMA Q&A detail-page parser.

Detail:   https://www.esma.europa.eu/publications-data/questions-answers/<id>
Detail markup: field divs (field--name-field-qa-*), Status inside
div.additionalinfo, question/answer inside <details> accordion blocks.

Discovery of ESMA-received Joint Q&As is the Joint Q&A Register's job (see
qa_mirror/register.py) — this module only turns a known detail URL into a
Record. ESMA's own facet search was retired: it sat behind a cache that
non-deterministically served unfiltered results, which repeatedly corrupted
the corpus. The detail pages themselves have been reliable throughout.
"""
from __future__ import annotations

import re

from .common import Http, Record, html_to_text, soup

BASE = "https://www.esma.europa.eu"


def _field(doc, name: str) -> str:
    node = doc.find(class_=re.compile(rf"field--name-{name}\b"))
    if not node:
        return ""
    item = node.find(class_="field__item") or node
    return html_to_text(item)


def fetch_record(http: Http, url: str) -> Record:
    doc = soup(http.get(url).text)
    rec = Record(authority="esma", qa_id=url.rsplit("/", 1)[-1], source_url=url)
    rec.topic = _field(doc, "field-qa-subject-matter")
    # Since the 2026 migration the level-1 act is exposed as field-qa-level1
    # (e.g. "Regulation (EU) 2022/2554 - The Digital Operational Resilience
    # Act (DORA)") — the old field names are kept as fallbacks.
    rec.legal_act_raw = (
        _field(doc, "field-qa-level1")
        or _field(doc, "field-qa-legal-act")
        or _field(doc, "field-legal-act")
    )
    rec.article = _field(doc, "field-qa-article") or _field(doc, "field-article")
    info = doc.find("div", class_="additionalinfo")
    if info:
        for div in info.find_all("div", recursive=False):
            text = div.get_text(" ", strip=True)
            if text.lower().startswith("status"):
                rec.status = text.split(":", 1)[-1].strip()
            elif "date" in text.lower() and ":" in text:
                k, v = text.split(":", 1)
                rec.dates[re.sub(r"[^a-z0-9]+", "_", k.lower()).strip("_")] = v.strip()
    # Question/answer live in <details> accordion blocks.
    blocks = doc.find_all("details")
    texts = [html_to_text(b) for b in blocks if html_to_text(b)]
    if texts:
        rec.question = texts[0]
        if len(texts) > 1:
            rec.answer = "\n\n---\n\n".join(texts[1:])
    if not rec.question:
        main = doc.find(class_=re.compile("question__content")) or doc.find("article")
        rec.question = html_to_text(main) if main else ""
        rec.extra["parse_warning"] = "accordion not found; captured page body"
    return rec
