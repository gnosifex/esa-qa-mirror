"""EBA Single Rulebook Q&A adapter.

Listing:  https://www.eba.europa.eu/single-rule-book-qa/search?qa_legal_act[]=<id>&page=N
          /search is the *finals* tab; the status tabs are sibling paths
          (/under-review, /rejected, /archive, /all — verified 2026-07-09).
Counts:   /qa-search-count?<same facets> answers the per-tab totals as Drupal
          AJAX commands when called with X-Requested-With: XMLHttpRequest —
          the pre-flight completeness reference for a run.
Detail:   https://www.eba.europa.eu/single-rule-book-qa/qna/view/publicId/<YYYY_NNNN>
Detail markup: <dl class="metadata"> with <dt> label / <dd> value pairs
(Question ID, Legal act, Topic, Article, Question, Answer, Status, dates, ...).
"""
from __future__ import annotations

import json
import re
import sys

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


_DETAIL_HREF_RE = r'href="(/single-rule-book-qa/qna/view/publicId/[^"]+)"'
_COUNT_RE = re.compile(r"#view-count-(\w+)")


def _act_query(params: dict) -> str:
    return "&".join(f"qa_legal_act%5B%5D={a}" for a in params.get("legal_act_ids", []))


def _facet_date(iso: str) -> str:
    """The search form's date fields use the portal's display format
    (DD/MM/YYYY), URL-encoded."""
    y, m, d = iso.split("-")
    return f"{d}%2F{m}%2F{y}"


def list_detail_urls(http: Http, params: dict, max_pages: int = 0,
                     published_since: str = ""):
    """Yield detail URLs for the configured legal-act filter, all pages.
    /search lists final Q&As only (the other statuses live on sibling tabs).
    published_since (ISO date) narrows the listing to Q&As whose final answer
    was published on/after that date — the incremental runs' window."""
    q = _act_query(params)
    if published_since:
        q += f"&qa_final_publishing_date_start={_facet_date(published_since)}"
    for link in iter_listing(
        http,
        lambda page: f"{BASE}/single-rule-book-qa/search?{q}&page={page}",
        _DETAIL_HREF_RE,
        max_pages or int(params.get("max_pages", 600)),
        "eba",
    ):
        yield BASE + link


def list_archive_slugs(http: Http, params: dict) -> set[str]:
    """Record slugs (e.g. "2017-3613") currently on the archive tab for the
    configured acts — Q&As the EBA moved there after a review. Used to tell
    *archived* apart from *vanished without trace* when a record disappears
    from the finals listing."""
    q = _act_query(params)
    slugs = set()
    for link in iter_listing(
        http,
        lambda page: f"{BASE}/single-rule-book-qa/archive?{q}&page={page}",
        _DETAIL_HREF_RE,
        int(params.get("max_pages", 600)),
        "eba-archive",
    ):
        qa_id = link.rstrip("/").rsplit("/", 1)[-1]
        slugs.add(re.sub(r"[^A-Za-z0-9]+", "-", qa_id).strip("-").lower())
    return slugs


def expected_counts(http: Http, params: dict) -> dict[str, int]:
    """Per-status-tab totals for the configured acts, from the portal's own
    count endpoint — e.g. {"final": 96, "review": 3, "rejected": 71,
    "archive": 115}. Empty dict when the endpoint is unavailable or changes
    shape (callers must treat the pre-flight as best-effort, never fatal)."""
    try:
        resp = http.get(
            f"{BASE}/qa-search-count?{_act_query(params)}",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        counts = {}
        for cmd in json.loads(resp.text):
            m = _COUNT_RE.search(str(cmd.get("selector", "")))
            n = re.search(r"\d+", str(cmd.get("data", "")))
            if m and n:
                counts[m.group(1)] = int(n.group(0))
        return counts
    except Exception as exc:  # fail open: the check must not break the run
        print(f"[eba] count endpoint unavailable ({exc}) — continuing without",
              file=sys.stderr)
        return {}


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
