import datetime

import pytest
import requests

from qa_mirror import register


def _ms(y, m, d):
    return (datetime.date(y, m, d) - datetime.date(1970, 1, 1)).days * 86400000


# Column order for the synthetic Q&A table (subset the adapter actually reads).
COLS = [
    "joint Q&A ID", "Receiving ESA", "Q&A ID at the ESA that received it",
    "Date of submission to the ESAs", "Date of publication of the final answer",
    "Status", "Legal act", "Article", "Topic",
    "Link to the answer (for final Q&As)", "Answered by",
]
VALUE_DICTS = {
    "D0": ["DORA001", "DORA002"],
    "D1": ["EIOPA", "ESMA"],
    "D2": ["2622", "2103"],
    "D3": ["Final", "Rejected"],
    "D4": ["DORA - Regulation (EU) 2022/2554"],
    "D5": ["3(60)", "N/A"],
    "D6": ["ICT risk"],
    "D7": ["https://www.eiopa.europa.eu/qa-regulation/questions-and-answers-database/dora001-2622_en",
           "https://www.esma.europa.eu/publications-data/questions-answers/2103"],
    "D8": ["European Commission", ""],
}
# PowerBI attaches the 'S' descriptor to the FIRST data row (it carries both S
# and C). dict-encoded columns carry DN; the two date columns are literals.
_DESCR = [
    {"N": "G0", "DN": "D0"}, {"N": "G1", "DN": "D1"}, {"N": "G2", "DN": "D2"},
    {"N": "G3"}, {"N": "G4"},
    {"N": "G5", "DN": "D3"}, {"N": "G6", "DN": "D4"}, {"N": "G7", "DN": "D5"},
    {"N": "G8", "DN": "D6"}, {"N": "G9", "DN": "D7"}, {"N": "G10", "DN": "D8"},
]
# row A carries the descriptor + all cells present (DORA001, EIOPA, Final).
# row B (DORA002, ESMA, Rejected) repeats the Legal act (col 6) and nulls
# Answered by (col 10) — exercises the R and Ø bitmasks. Its Status cell (col 5)
# is 1 -> D3[1] = "Rejected".
_ROW_A = {"S": _DESCR,
          "C": [0, 0, 0, _ms(2023, 1, 27), _ms(2025, 4, 1), 0, 0, 0, 0, 0, 0]}
_ROW_B = {"C": [1, 1, 1, _ms(2024, 6, 1), _ms(2026, 6, 1), 1, 1, 0, 1],
          "R": 1 << 6, "Ø": 1 << 10}
DSR = {"results": [{"result": {"data": {"dsr": {"DS": [{
    "ValueDicts": VALUE_DICTS, "PH": [{"DM0": [_ROW_A, _ROW_B]}]}]}}}}]}

META = {"models": [{"id": 1, "dbName": "db"}],
        "exploration": {"report": {"objectId": "rep"}}}
CS = {"schemas": [{"schema": {"Entities": [
    {"Name": "DateTableTemplate", "Properties": [{"Name": "Date"}, {"Name": "Year"}]},
    {"Name": "Q&A", "Properties": [{"Name": c} for c in COLS]},
]}}]}


def _fake_pbi(session, path, payload=None):
    if "modelsAndExploration" in path:
        return META
    if "conceptualschema" in path:
        return CS
    if "querydata" in path:
        return DSR
    raise AssertionError(path)


def test_fetch_rows_decodes_and_normalizes(monkeypatch):
    monkeypatch.setattr(register, "_pbi", _fake_pbi)
    rows = register.fetch_rows(session=object())
    assert len(rows) == 2
    a, b = rows
    assert a == {
        "joint_id": "DORA001", "authority": "eiopa", "native_id": "2622",
        "link": "https://www.eiopa.europa.eu/qa-regulation/questions-and-answers-database/dora001-2622_en",
        "status": "Final", "legal_act_raw": "DORA - Regulation (EU) 2022/2554",
        "article": "3(60)", "topic": "ICT risk", "answered_by": "European Commission",
        "date_submission": "2023-01-27", "date_publication": "2025-04-01",
    }
    # row B: Legal act repeated from A (R bitmask), Answered by nulled (Ø)
    assert b["joint_id"] == "DORA002"
    assert b["authority"] == "esma"
    assert b["native_id"] == "2103"
    assert b["legal_act_raw"] == "DORA - Regulation (EU) 2022/2554"  # repeated
    assert b["article"] == "N/A"
    assert b["answered_by"] == ""  # nulled
    assert b["date_publication"] == "2026-06-01"
    assert b["link"].endswith("/questions-answers/2103")


def test_discover_filters_act_status_authority_and_link(monkeypatch):
    monkeypatch.setattr(register, "_pbi", _fake_pbi)
    # both rows are DORA; only row A is Final
    picked = register.discover(object(), "DORA", {"Final"}, {"eba", "eiopa", "esma"})
    assert [r["joint_id"] for r in picked] == ["DORA001"]

    # accepting Rejected too brings row B back
    picked = register.discover(object(), "DORA", {"Final", "Rejected"},
                               {"eba", "eiopa", "esma"})
    assert {r["joint_id"] for r in picked} == {"DORA001", "DORA002"}

    # restricting authorities drops EIOPA row A
    picked = register.discover(object(), "DORA", {"Final", "Rejected"}, {"esma"})
    assert [r["joint_id"] for r in picked] == ["DORA002"]

    # a non-matching act yields nothing
    assert register.discover(object(), "MiCA", {"Final"}, {"esma"}) == []


class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self._body


def test_pbi_retries_transient_status_then_succeeds(monkeypatch):
    # PowerBI 400s the first call, then serves the same request fine — the client
    # must retry rather than fail the whole discovery (the live 2026-07-08 case).
    slept, seq = [], [_Resp(400), _Resp(200, {"ok": True})]
    monkeypatch.setattr(register.time, "sleep", slept.append)

    class Sess:
        def get(self, url, headers=None, timeout=None):
            return seq.pop(0)

    out = register._pbi(Sess(), "/public/reports/x")
    assert out == {"ok": True}
    assert slept  # it backed off at least once


def test_pbi_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(register.time, "sleep", lambda s: None)

    class Sess:
        def get(self, url, headers=None, timeout=None):
            return _Resp(503)

    with pytest.raises(register.RegisterError):
        register._pbi(Sess(), "/public/reports/x")


def test_discover_skips_rows_without_http_link(monkeypatch):
    def pbi_norows(session, path, payload=None):
        if "querydata" in path:
            d = {"results": [{"result": {"data": {"dsr": {"DS": [{
                "ValueDicts": {**VALUE_DICTS, "D7": ["rejected", "n/a"]},
                "PH": [{"DM0": [_ROW_A, _ROW_B]}]}]}}}}]}
            return d
        return _fake_pbi(session, path, payload)
    monkeypatch.setattr(register, "_pbi", pbi_norows)
    # links are now non-URLs ("rejected"/"n/a") → nothing discoverable
    assert register.discover(object(), "DORA", {"Final", "Rejected"},
                             {"eba", "eiopa", "esma"}) == []
