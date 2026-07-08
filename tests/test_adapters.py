from qa_mirror import eba, eiopa, esma

from conftest import FakeHttp


# --- EBA (sectoral banking discovery + detail parse) --------------------------

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


# --- EIOPA (detail parse for register-discovered joint Q&As) -------------------

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


# --- ESMA (detail parse for register-discovered joint Q&As) -------------------

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
