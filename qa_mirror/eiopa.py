"""EIOPA Q&A adapter.

Listing:  https://www.eiopa.europa.eu/search-qas_en?f[0]=regulation_reference:<id>&f[1]=status:Final&page=N
Detail:   https://www.eiopa.europa.eu/qa-regulation/questions-and-answers-database/<slug>_en
Detail markup: <p>Label: <b>value</b></p> metadata block; question/answer in ecl-card blocks.
"""
from __future__ import annotations

import re

from .common import Http, Record, format_joint_id, html_to_text, soup

BASE = "https://www.eiopa.europa.eu"
LABELS = {
    "question id": "qa_id",
    "regulation reference": "legal_act_raw",
    "article": "article",
    "topic": "topic",
    "status": "status",
}


def list_detail_urls(http: Http, params: dict, max_pages: int = 100):
    seen = set()
    facets = "&".join(
        f"f%5B{i}%5D={f}" for i, f in enumerate(params.get("facets", []))
    )
    for page in range(max_pages):
        url = f"{BASE}/search-qas_en?{facets}&page={page}"
        html = http.get(url).text
        links = set(
            re.findall(r'href="(/qa-regulation/questions-and-answers-database/[^"]+)"', html)
        )
        new = links - seen
        if not new:
            break
        seen |= new
        for link in sorted(new):
            yield BASE + link


def fetch_record(http: Http, url: str) -> Record:
    doc = soup(http.get(url).text)
    rec = Record(authority="eiopa", qa_id="", source_url=url)
    article_node = doc.find("article") or doc
    for p in article_node.find_all("p"):
        b = p.find("b")
        if not b:
            continue
        label = p.get_text(" ", strip=True).split(":")[0].strip().lower()
        value = b.get_text(" ", strip=True)
        field = LABELS.get(label)
        if field:
            setattr(rec, field, value)
        elif "date" in label:
            rec.dates[re.sub(r"[^a-z0-9]+", "_", label).strip("_")] = value
    # Question sits in an ecl-card headed "Question"; the answer under its own
    # heading (e.g. "EIOPA answer") elsewhere in the article. Parse by headings:
    # section = heading's following siblings up to the next heading, falling back
    # to the heading's parent block (card case) when the siblings carry no text.
    for heading in article_node.find_all(re.compile("^h[1-6]$")):
        title = heading.get_text(" ", strip=True).lower()
        if "question" not in title and "answer" not in title:
            continue
        parts = []
        for sib in heading.next_siblings:
            if getattr(sib, "name", None) and re.match(r"^h[1-6]$", sib.name):
                break
            if getattr(sib, "name", None):
                t = html_to_text(sib)
                if t:
                    parts.append(t)
        body = "\n\n".join(parts)
        if not body and heading.parent is not None:
            body = html_to_text(heading.parent)
            body = re.sub(rf"^{re.escape(heading.get_text(' ', strip=True))}\s*", "", body).strip()
        if "answer" in title and not rec.answer:
            rec.answer = body
        elif "question" in title and not rec.question:
            rec.question = body
    if not rec.qa_id:
        rec.qa_id = url.rstrip("/").rsplit("/", 1)[-1].removesuffix("_en")
    # DORA Q&As are Joint ESAs Q&As with a shared ID across the three portals;
    # EIOPA encodes it in its own ID in two formats: "DORA 137 - 3195" and
    # "2787 - DORA 011". Normalized to the Joint Q&A Register's native format
    # per act (see common.JOINT_ID_FORMATS): DORA137 → DORA137, DORA 011 → DORA011.
    m = re.search(r"([A-Za-z]{3,10})[\s_-]*0*(\d{1,4})", rec.qa_id)
    if m:
        rec.joint_id = format_joint_id(m.group(1), int(m.group(2)))
    return rec
