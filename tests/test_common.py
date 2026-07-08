import pytest

from qa_mirror.common import (
    DELISTED_HASH_PREFIX,
    Record,
    State,
    format_joint_id,
    html_to_text,
    iso_date,
    iter_listing,
    mark_file_delisted,
    record_path,
    write_record,
)

from conftest import FakeHttp


# --- html_to_text -----------------------------------------------------------

def test_nested_li_p_not_duplicated():
    assert html_to_text("<ul><li><p>Text</p></li></ul>") == "- Text"


def test_nested_td_p_not_duplicated():
    html = "<table><tr><td><p>A</p><p>B</p></td><td>C</td></tr></table>"
    assert html_to_text(html) == "A B\n\nC"


def test_flat_paragraphs_keep_breaks():
    assert html_to_text("<p>A</p><p>B</p>") == "A\n\nB"


def test_equal_but_distinct_blocks_are_kept():
    # Dedup must compare node identity, not content — bs4's == is content-based.
    assert html_to_text("<p>Same</p><p>Same</p>") == "Same\n\nSame"


def test_list_after_paragraph():
    html = "<p>Intro:</p><ul><li><p>one</p></li><li><p>two</p></li></ul>"
    assert html_to_text(html) == "Intro:\n\n- one\n\n- two"


def test_no_blocks_falls_back_to_plain_text():
    assert html_to_text("<span>just text</span>") == "just text"


# --- iso_date ---------------------------------------------------------------

def test_iso_date_formats():
    assert iso_date("20/05/2024") == "2024-05-20"   # EBA
    assert iso_date("06 Dec 2024") == "2024-12-06"  # ESMA/EIOPA
    assert iso_date("2024-05-20") == "2024-05-20"
    assert iso_date("") == ""
    assert iso_date("sometime in 2024") == ""


# --- legal-act reference / joint id -----------------------------------------

def test_finalize_no_default_fallback_for_unparseable_act_string():
    # present-but-unparseable act string = foreign/unknown act — the default
    # must not mislabel it (broken portal facets returned Solvency-II records
    # on a DORA filter and they masqueraded as DORA via the fallback)
    r = Record(authority="eiopa", qa_id="x", source_url="u",
               legal_act_raw="Risk-Free Interest Rate - General questions").finalize(
        {"default_act_ref": "2022/2554"})
    assert (r.legal_act_ref, r.legal_act) == ("", "")


def test_finalize_regulation_and_directive_styles():
    r = Record(authority="eba", qa_id="x", source_url="u",
               legal_act_raw="Regulation (EU) No 575/2013 (CRR)").finalize({})
    assert (r.legal_act_ref, r.legal_act) == ("(EU) 575/2013", "CRR")
    r = Record(authority="eba", qa_id="x", source_url="u",
               legal_act_raw="Directive 2013/36/EU (CRD)").finalize({})
    assert (r.legal_act_ref, r.legal_act) == ("(EU) 2013/36", "CRD")
    r = Record(authority="esma", qa_id="x", source_url="u").finalize(
        {"default_act_ref": "2022/2554"})
    assert (r.legal_act_ref, r.legal_act) == ("(EU) 2022/2554", "DORA")


def test_format_joint_id():
    assert format_joint_id("dora", 3) == "DORA003"
    assert format_joint_id("DORA", 137) == "DORA137"
    assert format_joint_id("XYZ", 12) == "XYZ12"  # unknown act: unpadded fallback


# --- Record markdown / hashing ----------------------------------------------

def make_record(**kw):
    base = dict(
        authority="eba", qa_id="2024_1", source_url="https://example.org/1",
        legal_act="DORA", question="Q?", answer="A.",
        dates={"submission_date": "20/05/2024"},
    )
    base.update(kw)
    return Record(**base)


def test_to_markdown_emits_iso_date_twin():
    md = make_record().to_markdown()
    assert 'date_submission_date: "20/05/2024"' in md
    assert 'date_submission_date_iso: "2024-05-20"' in md


def test_to_markdown_skips_iso_twin_for_unparseable_dates():
    md = make_record(dates={"published": "unknown"}).to_markdown()
    assert 'date_published: "unknown"' in md
    assert "date_published_iso" not in md


def test_content_hash_ignores_retrieved_at_only():
    a = make_record(retrieved_at="2026-01-01T00:00:00+00:00")
    b = make_record(retrieved_at="2026-07-08T12:00:00+00:00")
    assert a.content_hash() == b.content_hash()
    assert a.content_hash() != make_record(answer="Changed.").content_hash()


# --- State ------------------------------------------------------------------

def test_state_detects_missing_file(tmp_path):
    state = State(tmp_path / "state.json")
    rec = make_record()
    assert state.is_new_or_changed(rec)
    write_record(tmp_path, rec)
    state.remember(rec)
    assert not state.is_new_or_changed(rec)
    # deleting the file must force a rewrite even though the hash still matches
    record_path(tmp_path, rec).unlink()
    assert state.is_new_or_changed(rec)


def test_state_delisted_sentinel_forces_rewrite_and_is_stable(tmp_path):
    state = State(tmp_path / "state.json")
    rec = make_record()
    write_record(tmp_path, rec)
    state.remember(rec)
    key = state.key(rec)
    state.mark_delisted(key)
    assert state.data["records"][key].startswith(DELISTED_HASH_PREFIX)
    assert state.is_new_or_changed(rec)  # reappearing record gets rewritten
    state.mark_delisted(key)  # marking twice must not stack prefixes
    assert not state.data["records"][key].startswith(DELISTED_HASH_PREFIX * 2)


def test_mark_file_delisted(tmp_path):
    rec = make_record()
    path = write_record(tmp_path, rec)
    state = State(tmp_path / "state.json")
    marked = mark_file_delisted(tmp_path, state.key(rec), "2026-07-08")
    assert marked == path
    text = path.read_text(encoding="utf-8")
    assert 'x_delisted: "2026-07-08"\nsource_url:' in text
    # already marked → no second marker, reported as not-newly-marked
    assert mark_file_delisted(tmp_path, state.key(rec), "2026-07-09") is None
    assert path.read_text(encoding="utf-8").count("x_delisted") == 1


# --- Http retries -------------------------------------------------------------

class _Resp:
    def __init__(self, code):
        self.status_code = code
        self.headers = {}

    def raise_for_status(self):
        import requests
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


def make_http(responses, monkeypatch):
    from qa_mirror import common as c
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    h = c.Http(delay=0, retries=2)
    calls = []

    class Sess:
        def get(self, url, **kw):
            calls.append(url)
            return _Resp(responses[min(len(calls), len(responses)) - 1])

    h.session = Sess()
    return h, calls


def test_http_retries_transient_errors(monkeypatch):
    h, calls = make_http([503, 429, 200], monkeypatch)
    assert h.get("u").status_code == 200
    assert len(calls) == 3


def test_http_gives_up_after_retries(monkeypatch):
    import requests
    h, calls = make_http([503, 503, 503], monkeypatch)
    with pytest.raises(requests.HTTPError):
        h.get("u")
    assert len(calls) == 3  # retries=2 → 3 attempts, then the 503 raises


def test_http_does_not_retry_hard_404(monkeypatch):
    import requests
    h, calls = make_http([404], monkeypatch)
    with pytest.raises(requests.HTTPError):
        h.get("u")
    assert len(calls) == 1


# --- iter_listing -----------------------------------------------------------

LINK = 'href="/qa/{}"'


def page(*ids):
    return " ".join(LINK.format(i) for i in ids)


def test_iter_listing_survives_one_stale_page():
    http = FakeHttp({0: page("a", "b"), 1: page("a"), 2: page("c"), 3: ""})
    got = list(iter_listing(http, lambda p: p, r'href="(/qa/[^"]+)"', 10, "t"))
    assert got == ["/qa/a", "/qa/b", "/qa/c"]


def test_iter_listing_stops_after_two_stale_pages():
    http = FakeHttp({0: page("a"), 1: page("a"), 2: page("a"), 3: page("b")})
    got = list(iter_listing(http, lambda p: p, r'href="(/qa/[^"]+)"', 10, "t"))
    assert got == ["/qa/a"]
    assert http.calls == [0, 1, 2]


def test_iter_listing_stops_on_page_without_links():
    http = FakeHttp({0: page("a"), 1: "<html>no results</html>"})
    got = list(iter_listing(http, lambda p: p, r'href="(/qa/[^"]+)"', 10, "t"))
    assert got == ["/qa/a"]


def test_iter_listing_warns_when_max_pages_reached(capsys):
    http = FakeHttp({0: page("a"), 1: page("b")})
    got = list(iter_listing(http, lambda p: p, r'href="(/qa/[^"]+)"', 2, "t"))
    assert got == ["/qa/a", "/qa/b"]
    assert "max_pages=2" in capsys.readouterr().err
