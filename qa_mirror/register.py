"""Joint Q&A Register — the canonical discovery source for Joint ESAs Q&As.

DORA Q&As are *Joint* ESAs Q&As: one shared corpus answered jointly and indexed
centrally in the Joint Q&A Register, embedded as a PowerBI report at
<https://www.esma.europa.eu/joint-committee/joint-qas>. This module queries that
report's public backend directly and returns, in one request, every Joint Q&A
with its receiving authority, the authority's native detail-page ID, a direct
link to the answer, status, legal act and metadata.

That replaces the per-portal DORA discovery — ESMA's cache-flaky search, EIOPA's
stale XLSX export — with a single authoritative source: take the rows for the
wanted act, and fetch each linked detail page for content. Verified live
2026-07-08: the register is queryable with only the report's public resource key
and was fresher than the EIOPA export (publication dates to 2026-06 vs 2026-04).
Sectoral acts (e.g. EBA-only CRD) are *not* Joint Q&As and keep their own
per-authority discovery; the register covers cross-sectoral joint acts only.

PowerBI protocol (reverse-engineered — undocumented, may change):
- Resource key + cluster come from the embed URL's `r` token; the metadata
  endpoint yields the modelId/dbName/reportId, `conceptualschema` the tables and
  columns, and `querydata` the rows in PowerBI's compressed "dsr" shape
  (per-row repeat/null bitmasks + per-column value dictionaries).
"""
from __future__ import annotations

import datetime
import sys
import time

import requests

from .common import USER_AGENT

# From the embed URL app.powerbi.com/view?r=<base64 {"k":key,"t":tenant,"c":9}>.
# Cluster c=9 resolves to the west-europe backend (verified; other clusters 401).
RESOURCE_KEY = "e190a6e7-a75d-4543-b3e3-5d1a328e663e"
PBI_HOST = "wabi-west-europe-d-primary-api.analysis.windows.net"
_EPOCH = datetime.date(1970, 1, 1)


class RegisterError(RuntimeError):
    """The register could not be queried or parsed — discovery must fail closed
    rather than proceed on a partial/garbled list."""


# PowerBI's public backend spuriously rejects otherwise-valid requests in
# bursts — the conceptualschema call was seen 400ing for tens of seconds on one
# run, then answering 200 on the first try minutes later (identical request).
# The bursts outlast a short retry, so retry generously with capped backoff to
# ride them out; 400/429/5xx and network errors are all treated as transient.
_RETRYABLE_STATUS = (400, 408, 429, 500, 502, 503, 504)
_RETRIES = 6
_BACKOFF_CAP = 30


def _backoff(attempt: int) -> int:
    return min(_BACKOFF_CAP, 3 * 2**attempt)


def _pbi(session: requests.Session, path: str, payload=None):
    url = f"https://{PBI_HOST}{path}"
    headers = {"X-PowerBI-ResourceKey": RESOURCE_KEY, "User-Agent": USER_AGENT}
    for attempt in range(_RETRIES + 1):
        try:
            if payload is None:
                resp = session.get(url, headers=headers, timeout=60)
            else:
                resp = session.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code in _RETRYABLE_STATUS and attempt < _RETRIES:
                wait = _backoff(attempt)
                print(f"[register] {resp.status_code} for {path} — retrying in "
                      f"{wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()  # requests transparently gunzips
        except (requests.RequestException, ValueError) as exc:
            if attempt >= _RETRIES:
                raise RegisterError(f"PowerBI {path} failed: {exc}") from exc
            wait = _backoff(attempt)
            print(f"[register] {type(exc).__name__} for {path} — retrying in "
                  f"{wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RegisterError(f"PowerBI {path} failed after {_RETRIES} retries")


def _find(cols: list[str], *needles: str) -> int:
    """Index of the column whose (case-insensitive) name contains all needles.
    Names carry stray spaces upstream ('Subject matter  '), so match loosely."""
    for i, c in enumerate(cols):
        cl = c.lower()
        if all(n.lower() in cl for n in needles):
            return i
    raise RegisterError(f"register column not found: {needles}")


def _decode_dsr(ds: dict) -> tuple[list[str], list[list]]:
    """Decode PowerBI's compressed data-shape result into (column names, rows).

    Row 0 carries the 'S' descriptor (column order + per-column value-dict name
    'DN'). Each data row lists in 'C' only the cells that are neither repeated
    from the previous row ('R' bitmask) nor null ('Ø' bitmask); dict-encoded
    cells are integer indices into ValueDicts[DN].
    """
    vdicts = ds.get("ValueDicts", {})
    raw = ds.get("PH", [{}])[0].get("DM0", [])
    if not raw or "S" not in raw[0]:
        raise RegisterError("unexpected querydata shape (no descriptor)")
    descr = raw[0]["S"]
    dict_of = [c.get("DN") for c in descr]
    n = len(descr)
    prev: list = [None] * n
    rows: list[list] = []
    for r in raw:
        cells = r.get("C", [])
        repeat = r.get("R", 0)
        null = r.get("Ø", 0)
        ci = 0
        row: list = [None] * n
        for col in range(n):
            if repeat & (1 << col):
                row[col] = prev[col]
            elif null & (1 << col):
                row[col] = None
            else:
                v = cells[ci]
                ci += 1
                if dict_of[col] is not None and isinstance(v, int):
                    v = vdicts[dict_of[col]][v]
                row[col] = v
        prev = row
        rows.append(row)
    return descr, rows


def _date(ms) -> str:
    """PowerBI epoch-millis → ISO date, or '' when absent."""
    if not isinstance(ms, (int, float)):
        return ""
    return (_EPOCH + datetime.timedelta(milliseconds=ms)).isoformat()


def fetch_rows(session: requests.Session | None = None) -> list[dict]:
    """Return every Joint Q&A in the register as a dict of normalized fields.

    Fields: joint_id, authority (eba|eiopa|esma, lowercased 'Receiving ESA'),
    native_id, link, status, legal_act_raw, article, topic, subject,
    answered_by, date_submission, date_publication.
    """
    own = session is None
    session = session or requests.Session()
    try:
        meta = _pbi(session, f"/public/reports/{RESOURCE_KEY}/modelsAndExploration"
                             "?preferReadOnlySession=true")
        model = meta["models"][0]
        model_id, dbname = model["id"], model.get("dbName")
        report_id = (meta.get("exploration") or {}).get("report", {}).get("objectId")

        cs = _pbi(session, "/public/reports/conceptualschema",
                  {"userPreferredLocale": "en-US", "models": [model_id]})
        entities = cs["schemas"][0]["schema"]["Entities"]
        # the data table is the entity with the most columns (the date-dimension
        # helper tables have only 7)
        entity = max(entities, key=lambda e: len(e.get("Properties", [])))
        tname = entity["Name"]
        cols = [p["Name"] for p in entity["Properties"]]

        selects = [{"Column": {"Expression": {"SourceRef": {"Source": "t"}},
                               "Property": c}, "Name": f"t.{c}"} for c in cols]
        body = {"version": "1.0.0", "queries": [{
            "Query": {"Commands": [{"SemanticQueryDataShapeCommand": {
                "Query": {"Version": 2,
                          "From": [{"Name": "t", "Entity": tname, "Type": 0}],
                          "Select": selects},
                "Binding": {"Primary": {"Groupings": [
                                {"Projections": list(range(len(cols)))}]},
                            "DataReduction": {"DataVolume": 4,
                                              "Primary": {"Window": {"Count": 30000}}},
                            "Version": 1}}}]},
            "QueryId": "",
            "ApplicationContext": {"DatasetId": dbname,
                                   "Sources": [{"ReportId": report_id}]}}],
            "cancelQueries": [], "modelId": model_id}
        res = _pbi(session, "/public/reports/querydata?synchronous=true", body)
    finally:
        if own:
            session.close()

    try:
        ds = res["results"][0]["result"]["data"]["dsr"]["DS"][0]
    except (KeyError, IndexError) as exc:
        raise RegisterError(f"querydata missing result set: {exc}") from exc
    _descr, rows = _decode_dsr(ds)

    c_joint = _find(cols, "joint", "id")
    c_esa = _find(cols, "receiving esa")
    c_native = _find(cols, "id at the esa")
    c_sub = _find(cols, "submission")
    c_pub = _find(cols, "publication")
    c_status = _find(cols, "status")
    c_act = _find(cols, "legal act")
    c_article = _find(cols, "article")
    c_topic = _find(cols, "topic")
    c_link = _find(cols, "link to the answer")
    c_answered = _find(cols, "answered by")

    out = []
    for r in rows:
        esa = str(r[c_esa] or "").strip().lower()
        out.append({
            "joint_id": str(r[c_joint] or "").strip(),
            "authority": esa,
            "native_id": str(r[c_native] or "").strip(),
            "link": str(r[c_link] or "").strip(),
            "status": str(r[c_status] or "").strip(),
            "legal_act_raw": str(r[c_act] or "").strip(),
            "article": str(r[c_article] or "").strip(),
            "topic": str(r[c_topic] or "").strip(),
            "answered_by": str(r[c_answered] or "").strip(),
            "date_submission": _date(r[c_sub]),
            "date_publication": _date(r[c_pub]),
        })
    return out


def discover(session, act_substr: str, statuses, authorities) -> list[dict]:
    """Register rows for one act, restricted to the wanted statuses and to rows
    that carry a usable http(s) link to a known authority. `act_substr` matches
    the register's 'Legal act' (e.g. 'DORA'); `statuses` is a set of accepted
    Status values (e.g. {'Final'}); `authorities` is the set of adapter keys we
    can fetch (eba/eiopa/esma)."""
    rows = fetch_rows(session)
    want_status = {s.lower() for s in statuses}
    picked = []
    for row in rows:
        if act_substr.lower() not in row["legal_act_raw"].lower():
            continue
        if want_status and row["status"].lower() not in want_status:
            continue
        if row["authority"] not in authorities:
            continue
        if not row["link"].startswith("http"):
            continue
        picked.append(row)
    return picked
