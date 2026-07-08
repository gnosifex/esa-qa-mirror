from qa_mirror import eba, eiopa, esma

from conftest import FakeHttp


# --- EBA ----------------------------------------------------------------------

def test_eba_fetch_record(fixture_html):
    url = f"{eba.BASE}/single-rule-book-qa/qna/view/publicId/2024_7242"
    rec = eba.fetch_record(FakeHttp({url: fixture_html("eba_detail.html")}), url)
    rec.finalize({})
    assert rec.qa_id == "2024_7242"
    assert rec.legal_act == "CRD"
    assert rec.legal_act_ref == "(EU) 2013/36"
    assert rec.article == "134"
    assert rec.topic == "Supervisory reporting"
    assert rec.status == "Final Q&A"
    assert rec.dates == {
        "submission_date": "20/05/2024",
        "final_publishing_date": "08/08/2025",
    }
    assert rec.question == "Does the SyRB apply on a consolidated basis?"
    # the regression this suite exists for: nested li>p / td>p must not duplicate
    assert rec.background == (
        "Bank A has the following exposures:\n\n"
        "- through branches and direct lending: 100 EUR\n\n"
        "- through subsidiary B: 500 EUR"
    )
    assert rec.answer == "Yes.\n\nCell one\n\nCell two"
    # submitter identity is dropped by design
    assert "Should Be Dropped" not in rec.to_markdown()


def test_eba_listing_pagination():
    q = "qa_legal_act%5B%5D=32"
    detail = "/single-rule-book-qa/qna/view/publicId/2024_{}"

    def page_url(p):
        return f"{eba.BASE}/single-rule-book-qa/search?{q}&page={p}"

    http = FakeHttp({
        page_url(0): f'<a href="{detail.format(1)}">x</a> <a href="{detail.format(2)}">y</a>',
        page_url(1): "<html>empty</html>",
    })
    urls = list(eba.list_detail_urls(http, {"legal_act_ids": [32]}))
    assert urls == [eba.BASE + detail.format(1), eba.BASE + detail.format(2)]


# --- EIOPA ----------------------------------------------------------------------

def make_export_xlsx(rows):
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Question ID", "Submitted on", "Answered on", "Regulation Reference",
               "QA Topic", "Article", "Template", "Question",
               "Background of the question", "EIOPA Answer"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_eiopa_listing_from_xlsx_export(fixture_html):
    xlsx = make_export_xlsx([
        # post-migration ID style; slug uses the compact form (3308-dora221)
        ["3308 - DORA221", "2025-03-28", "2025-04-01",
         "(EU) 2022/2554 - Digital Operational Resilience Act (DORA)",
         "t", "3", "", "q", "", "a"],
        # hyphenated slug variant (first candidate 404s, second resolves)
        ["3476 - DORA-280", "2025-05-01", "2025-05-02",
         "(EU) 2022/2554 - Digital Operational Resilience Act (DORA)",
         "t", "5", "", "q", "", "a"],
        # foreign act — filtered out by require_act_ref, never fetched
        ["3374", "2025-06-26", "2025-07-01",
         "(EU) No 2015/35 - supplementing Dir 2009/138/EC (SII)",
         "t", "15", "", "q", "", "a"],
        # pre-migration entry whose page is gone — warned about, skipped
        ["2787 - DORA 011", "2024-12-06", "2024-12-07",
         "(EU) 2022/2554 - Digital Operational Resilience Act (DORA)",
         "t", "30", "", "q", "", "a"],
    ])
    detail = f"{eiopa.BASE}/qa-regulation/questions-and-answers-database"
    http = FakeHttp({
        eiopa.EXPORT_URL: xlsx,
        f"{detail}/3308-dora221_en": fixture_html("eiopa_detail.html"),
        f"{detail}/3476-dora-280_en": fixture_html("eiopa_detail.html"),
    })
    urls = list(eiopa.list_detail_urls(http, {"require_act_ref": "2022/2554"}))
    assert urls == [f"{detail}/3308-dora221_en", f"{detail}/3476-dora-280_en"]
    assert not any("3374" in u for u in http.calls)  # foreign act never fetched
    # resolution cached the pages: fetch_record must not re-download
    n_calls = len(http.calls)
    rec = eiopa.fetch_record(http, urls[0])
    assert rec.qa_id == "2787 - DORA 011"  # from the fixture's metadata
    assert len(http.calls) == n_calls


def test_eiopa_slug_candidates():
    assert eiopa._slug_candidates("3308 - DORA221")[0] == "3308-dora221"
    assert "3476-dora-280" in eiopa._slug_candidates("3476 - DORA-280")
    assert eiopa._slug_candidates("Dora 262 - 3419")[0] == "3419-dora262"
    assert eiopa._slug_candidates("3374") == ["3374"]


def test_eiopa_fetch_record(fixture_html):
    url = f"{eiopa.BASE}/qa-regulation/questions-and-answers-database/2787_en"
    rec = eiopa.fetch_record(FakeHttp({url: fixture_html("eiopa_detail.html")}), url)
    rec.finalize({"default_act_ref": "2022/2554"})
    assert rec.qa_id == "2787 - DORA 011"
    assert rec.joint_id == "DORA011"  # register format: three-digit padding
    assert rec.legal_act == "DORA"
    assert rec.article == "30"
    assert rec.status == "Final"
    assert rec.dates == {"date_of_submission": "06 Dec 2024"}
    assert rec.question == "Does subcontracting of ICT services require notification?"
    # "Background of the question" contains the word "question" — it must land
    # in background, not overwrite or shadow the question section
    assert rec.background == "Our provider subcontracts data storage."
    assert rec.answer == "It depends on the contractual arrangement.\n\n- Point one applies."


def test_eiopa_joint_id_formats(fixture_html):
    # ID styles seen across portal generations: "DORA 137 - 3195",
    # "2787 - DORA 011", and post-migration "3308 - DORA221"
    url = f"{eiopa.BASE}/qa-regulation/questions-and-answers-database/3195_en"
    for portal_id, expected in [
        ("DORA 137 - 3195", "DORA137"),
        ("3308 - DORA221", "DORA221"),
    ]:
        html = fixture_html("eiopa_detail.html").replace("2787 - DORA 011", portal_id)
        rec = eiopa.fetch_record(FakeHttp({url: html}), url)
        assert rec.joint_id == expected, portal_id
    # a purely numeric ID must not yield a bogus joint id
    html = fixture_html("eiopa_detail.html").replace("2787 - DORA 011", "3195")
    rec = eiopa.fetch_record(FakeHttp({url: html}), url)
    assert rec.joint_id == ""


# --- ESMA ----------------------------------------------------------------------

def esma_listing_base():
    return (
        f"{esma.BASE}/esma-qa-search-page/final?field_qa_serial_value="
        "&combine_keywords_qa_search=&field_qa_level1_target_id%5B0%5D=20010"
        "&created%5Bmin%5D=&created%5Bmax%5D="
    )


FACET_ECHO = "field_qa_level1_target_id%5B0%5D=20010"


def test_esma_listing_follows_only_advertised_pager_links():
    base = esma_listing_base()
    detail = '/publications-data/questions-answers/{}'
    # page 0 advertises page 1; page 1 advertises page 0 back. A page=2 URL
    # exists on the portal but serves an unfiltered default listing — the
    # adapter must never request pages the pager does not advertise.
    page0 = (f'<a href="{detail.format(2646)}">x</a>'
             f'<a href="?{FACET_ECHO}&amp;page=1">2</a>')
    page1 = (f'<a href="{detail.format(2103)}">y</a>'
             f'<a href="?{FACET_ECHO}&amp;page=0">1</a>')
    http = FakeHttp({base: page0, f"{base}&page=1": page1})
    urls = list(esma.list_detail_urls(http, {"level1_ids": [20010]}))
    assert urls == [esma.BASE + detail.format(2646), esma.BASE + detail.format(2103)]
    assert http.calls == [base, f"{base}&page=1"]  # nothing beyond the pager
    # every listing request must carry the cache-bypass cookie
    assert all("Cookie" in h for h in http.headers_sent)


def test_esma_listing_single_page():
    base = esma_listing_base()
    http = FakeHttp({base: f'<a href="/publications-data/questions-answers/2356">x</a>'
                           f'<a href="?{FACET_ECHO}">self</a>'})
    urls = list(esma.list_detail_urls(http, {"level1_ids": [20010]}))
    assert urls == [f"{esma.BASE}/publications-data/questions-answers/2356"]


class FlakyHttp:
    """Serves a sequence of responses per URL — for cache-flakiness tests."""

    def __init__(self, sequences: dict):
        self.sequences = {k: list(v) for k, v in sequences.items()}
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(url)
        seq = self.sequences[url]
        from types import SimpleNamespace
        return SimpleNamespace(text=seq.pop(0) if len(seq) > 1 else seq[0])


def test_esma_listing_retries_unfiltered_cache_responses(monkeypatch):
    from qa_mirror import common
    monkeypatch.setattr(common.time, "sleep", lambda s: None)
    base = esma_listing_base()
    junk = '<a href="/publications-data/questions-answers/2856">junk</a>'
    good = (f'<a href="/publications-data/questions-answers/2646">x</a>'
            f'<a href="?{FACET_ECHO}">self</a>')
    http = FlakyHttp({base: [junk, junk, good]})
    urls = list(esma.list_detail_urls(http, {"level1_ids": [20010]}))
    # junk responses are never yielded; the retry eventually got the real page
    assert urls == [f"{esma.BASE}/publications-data/questions-answers/2646"]


def test_esma_listing_fails_closed_on_persistent_unfiltered_responses(monkeypatch):
    import pytest as _pytest

    from qa_mirror import common
    monkeypatch.setattr(common.time, "sleep", lambda s: None)
    base = esma_listing_base()
    junk = '<a href="/publications-data/questions-answers/2856">junk</a>'
    http = FlakyHttp({base: [junk]})
    with _pytest.raises(RuntimeError, match="unfiltered"):
        list(esma.list_detail_urls(http, {"level1_ids": [20010]}))


def test_esma_fetch_record(fixture_html):
    url = f"{esma.BASE}/publications-data/questions-answers/2356"
    rec = esma.fetch_record(FakeHttp({url: fixture_html("esma_detail.html")}), url)
    rec.finalize({})  # no default needed: the act comes from field-qa-level1
    assert rec.qa_id == "2356"
    assert rec.legal_act_raw.startswith("Regulation (EU) 2022/2554")
    assert rec.legal_act == "DORA"
    assert rec.legal_act_ref == "(EU) 2022/2554"
    assert rec.topic == "Incident reporting"
    assert rec.status == "Answered"
    assert rec.dates == {"answer_publication_date": "12 Apr 2024"}
    assert rec.question == "What counts as a major incident?"
    # multi-part accordion answers are joined with a --- separator
    assert rec.answer == "Answer text one.\n\n---\n\nAnswer text two."
