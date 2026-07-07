"""ESMA Q&A adapter.

Listing:  https://www.esma.europa.eu/esma-qa-search-page/final?field_qa_level1_target_id[0]=<id>&page=N   (page is 0-based)
Detail:   https://www.esma.europa.eu/publications-data/questions-answers/<id>
Detail markup: field divs (field--name-field-qa-*), Status inside div.additionalinfo,
question/answer inside <details> accordion blocks.
"""
from __future__ import annotations

import re

from .common import Http, Record, html_to_text, soup

BASE = "https://www.esma.europa.eu"


def list_detail_urls(http: Http, params: dict, max_pages: int = 100):
    seen = set()
    facets = "&".join(
        f"field_qa_level1_target_id%5B{i}%5D={a}"
        for i, a in enumerate(params.get("level1_ids", []))
    )
    for page in range(max_pages):
        url = f"{BASE}/esma-qa-search-page/final?{facets}&page={page}"
        html = http.get(url).text
        links = set(re.findall(r'href="(/publications-data/questions-answers/\d+)"', html))
        new = links - seen
        if not new:
            break
        seen |= new
        for link in sorted(new):
            yield BASE + link


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
    rec.legal_act_raw = _field(doc, "field-qa-legal-act") or _field(doc, "field-legal-act")
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
