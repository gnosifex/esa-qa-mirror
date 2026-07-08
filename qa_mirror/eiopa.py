"""EIOPA Q&A detail-page parser.

Detail:   https://www.eiopa.europa.eu/qa-regulation/questions-and-answers-database/<slug>_en
Detail markup: <p>Label: <b>value</b></p> metadata block; Question /
Background of the question / EIOPA answer under h2 headings.

Discovery of EIOPA-received Joint Q&As is the Joint Q&A Register's job (see
qa_mirror/register.py) — this module only turns a known detail URL into a
Record. EIOPA's XLSX export was retired as a discovery source: it lagged the
register by weeks, and reconstructing detail-page slugs from it was brittle.
The register supplies the exact detail link directly.
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
    # heading (e.g. "EIOPA answer") elsewhere in the article; since the 2026
    # portal migration there is also a "Background of the question" heading.
    # Parse by headings: section = heading's following siblings up to the next
    # heading, falling back to the heading's parent block (card case) when the
    # siblings carry no text.
    for heading in article_node.find_all(re.compile("^h[1-6]$")):
        title = heading.get_text(" ", strip=True).lower()
        if not any(w in title for w in ("question", "answer", "background")):
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
        body = re.sub(
            r"^(?:eiopa\s+answer|answer|background of the question|background|question)\b[\s:]*",
            "", body, flags=re.I,
        )
        # "background" first: its heading contains the word "question" too
        if "background" in title and not rec.background:
            rec.background = body
        elif "answer" in title and not rec.answer:
            rec.answer = body
        elif "question" in title and not rec.question:
            rec.question = body
    if not rec.qa_id:
        rec.qa_id = url.rstrip("/").rsplit("/", 1)[-1].removesuffix("_en")
    # EIOPA encodes the shared Joint-Q&A id in its own ID in several formats:
    # "DORA 137 - 3195", "2787 - DORA 011", post-migration "3308 - DORA221".
    # (The register supplies it directly too; this is the fallback.)
    m = re.search(r"([A-Za-z]{3,10})[\s_-]*0*(\d{1,4})", rec.qa_id)
    if m:
        rec.joint_id = format_joint_id(m.group(1), int(m.group(2)))
    return rec
