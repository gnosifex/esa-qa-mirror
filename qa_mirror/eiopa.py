"""EIOPA Q&A adapter.

Listing:  official full-database XLSX export (deterministic, complete):
          https://www.eiopa.europa.eu/sites/default/files/export_qa/eiopa-qa.xlsx
Detail:   https://www.eiopa.europa.eu/qa-regulation/questions-and-answers-database/<slug>_en
Detail markup: <p>Label: <b>value</b></p> metadata block; Question /
Background of the question / EIOPA answer under h2 headings.

Why the XLSX instead of the HTML search (established live 2026-07-08 after
EIOPA's portal migration): the search endpoint is served by cache nodes that
non-deterministically ignore the query string — the same facet URL returns
correctly filtered results or an unfiltered default listing depending on the
node hit (one such response mass-corrupted the corpus before the plausibility
brake existed). The export is byte-stable across nodes and regions. Detail
pages have been deterministic throughout.

Detail slugs are derived from the export's Question ID (pathauto-style, with
observed irregularities like 3308-dora221 vs 3476-dora-280), so several
candidates are tried; the resolving fetch is cached for fetch_record.
"""
from __future__ import annotations

import io
import re
import sys

from .common import Http, Record, format_joint_id, html_to_text, soup

BASE = "https://www.eiopa.europa.eu"
EXPORT_URL = f"{BASE}/sites/default/files/export_qa/eiopa-qa.xlsx"
LABELS = {
    "question id": "qa_id",
    "regulation reference": "legal_act_raw",
    "article": "article",
    "topic": "topic",
    "status": "status",
}

# detail pages fetched during slug resolution, keyed by URL — fetch_record
# consumes them so each page is downloaded once
_page_cache: dict[str, str] = {}


def _slug_candidates(qid: str) -> list[str]:
    """Candidate URL slugs for a Question ID like "Dora 262 - 3419",
    "3308 - DORA221" or plain "3374"."""
    nums = re.findall(r"\d+", qid)
    page_id = max(nums, key=len) if nums else ""
    m = re.search(r"([A-Za-z]{3,10})[\s-]*0*(\d{1,4})", qid)
    slug_full = re.sub(r"[^a-z0-9]+", "-", qid.lower()).strip("-")
    cands = []
    if page_id and m and m.group(2).lstrip("0") != page_id:
        token, num = m.group(1).lower(), m.group(2)
        cands += [f"{page_id}-{token}{num}", f"{page_id}-{token}-{num}"]
    if slug_full:
        cands.append(slug_full)
    if page_id:
        cands.append(page_id)
    return list(dict.fromkeys(cands))


def _resolve_detail_url(http: Http, qid: str) -> str | None:
    for slug in _slug_candidates(qid):
        url = f"{BASE}/qa-regulation/questions-and-answers-database/{slug}_en"
        try:
            html = http.get(url).text
        except Exception:
            continue
        _page_cache[url] = html
        return url
    return None


def list_detail_urls(http: Http, params: dict, max_pages: int = 0):
    import openpyxl  # heavier import, keep local to the one place that needs it

    wb = openpyxl.load_workbook(io.BytesIO(http.get(EXPORT_URL).content), read_only=True)
    rows = wb.worksheets[0].iter_rows(values_only=True)
    header = [str(c or "").strip().lower() for c in next(rows)]
    qid_col = header.index("question id")
    ref_col = header.index("regulation reference")
    ref_filter = str(params.get("require_act_ref", "") or "")
    for row in rows:
        qid = str(row[qid_col] or "").strip()
        ref = str(row[ref_col] or "")
        if not qid or (ref_filter and ref_filter not in ref):
            continue
        url = _resolve_detail_url(http, qid)
        if url:
            yield url
        else:
            # not fatal by itself — pre-migration entries in the export have no
            # live page; anything previously mirrored is caught by delisting
            print(f"[eiopa] WARNING: no detail page found for {qid!r}", file=sys.stderr)


def fetch_record(http: Http, url: str) -> Record:
    html = _page_cache.pop(url, None)
    if html is None:
        html = http.get(url).text
    doc = soup(html)
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
    # DORA Q&As are Joint ESAs Q&As with a shared ID across the three portals;
    # EIOPA encodes it in its own ID in several formats: "DORA 137 - 3195",
    # "2787 - DORA 011", post-migration "3308 - DORA221". Normalized to the
    # Joint Q&A Register's native format per act (see common.JOINT_ID_FORMATS).
    m = re.search(r"([A-Za-z]{3,10})[\s_-]*0*(\d{1,4})", rec.qa_id)
    if m:
        rec.joint_id = format_joint_id(m.group(1), int(m.group(2)))
    return rec
