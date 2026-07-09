import pytest

from qa_mirror import cli, eba, eiopa, esma, register
from qa_mirror.common import Record, State


def row(joint, auth, native, status="Final",
        act="DORA - Regulation (EU) 2022/2554"):
    return {
        "joint_id": joint, "authority": auth, "native_id": native,
        "link": f"https://portal/{auth}/{native}", "status": status,
        "legal_act_raw": act, "article": "1", "topic": "t",
        "answered_by": "Joint ESAs", "date_submission": "2024-01-01",
        "date_publication": "2025-01-01",
    }


def fake_discover(rows):
    """Mirror register.discover's filtering over a canned row list."""
    def discover(session, act_substr, statuses, authorities):
        return [r for r in rows
                if act_substr.lower() in r["legal_act_raw"].lower()
                and r["status"] in statuses
                and r["authority"] in authorities
                and r["link"].startswith("http")]
    return discover


def fetch_for(auth):
    def fetch(http, url):
        nid = url.rstrip("/").rsplit("/", 1)[-1]
        return Record(authority=auth, qa_id=nid, source_url=url,
                      question="Q?", answer="A.")
    return fetch


def install(monkeypatch, rows, eba_listing=None, eba_counts=None, eba_archive=None):
    monkeypatch.setattr(cli.register, "discover", fake_discover(rows))
    for auth, mod in (("eiopa", eiopa), ("esma", esma), ("eba", eba)):
        monkeypatch.setattr(mod, "fetch_record", fetch_for(auth))
    if eba_listing is not None:
        monkeypatch.setattr(eba, "list_detail_urls",
                            lambda http, params, **kw: iter(eba_listing))
    # never let unit tests hit the live count/archive endpoints
    monkeypatch.setattr(eba, "expected_counts",
                        lambda http, params: dict(eba_counts or {}))
    monkeypatch.setattr(eba, "list_archive_slugs",
                        lambda http, params: set(eba_archive or ()))


JOINT_CFG = (
    "delay_seconds: 0\n"
    "joint_acts:\n"
    "  DORA:\n"
    "    register_act: DORA\n"
    "    act_ref: '2022/2554'\n"
    "    statuses: [Final]\n"
)


@pytest.fixture
def root(tmp_path):
    (tmp_path / "config.yaml").write_text(JOINT_CFG, encoding="utf-8")
    return tmp_path


def run(root, *argv):
    return cli.main(["--root", str(root), *argv])


def default_rows():
    return [
        row("DORA001", "eiopa", "2622"),
        row("DORA003", "eiopa", "2734"),
        row("DORA050", "esma", "2103"),
        row("DORA002", "eiopa", "2673", status="Rejected"),  # filtered out
    ]


def test_joint_discovery_writes_then_delta(root, monkeypatch):
    install(monkeypatch, default_rows())
    assert run(root) == 0
    # three Final DORA rows written; the Rejected one skipped
    assert (root / "data" / "dora" / "eiopa-2622.md").exists()
    assert (root / "data" / "dora" / "eiopa-2734.md").exists()
    assert (root / "data" / "dora" / "esma-2103.md").exists()
    assert not (root / "data" / "dora" / "eiopa-2673.md").exists()
    # register metadata landed on the record
    text = (root / "data" / "dora" / "eiopa-2622.md").read_text()
    assert 'joint_id: "DORA001"' in text
    assert 'legal_act: "DORA"' in text
    # second run: nothing changed
    assert run(root) == 0
    state = State(root / "state.json")
    assert state.data["records"]["eiopa:2622"]  # remembered


def test_register_act_wins_for_cross_act_joint_record(root, monkeypatch):
    # A joint DORA row whose ESMA detail page tags the act as "MiCA" (a real
    # DORA/MiCA VASP crossover) must still file under DORA — the register, not
    # the receiving portal, classifies the joint act.
    rows = [row("DORA138", "esma", "2364",
                act="DORA - Regulation (EU) 2022/2554")]
    monkeypatch.setattr(cli.register, "discover", fake_discover(rows))

    def esma_fetch(http, url):
        return Record(authority="esma", qa_id="2364", source_url=url,
                      legal_act_raw="MiCA", question="Q", answer="A")
    monkeypatch.setattr(esma, "fetch_record", esma_fetch)

    assert run(root) == 0
    doc = root / "data" / "dora" / "esma-2364.md"
    assert doc.exists()
    assert not (root / "data" / "unsorted" / "esma-2364.md").exists()
    # the portal's differing act classification is kept visible, not hidden
    text = doc.read_text()
    assert 'legal_act: "DORA"' in text
    assert 'x_portal_legal_act: "MiCA"' in text


def test_matching_act_wording_is_not_flagged_as_disagreement(root, monkeypatch):
    # portal and register describe the same act with different word order — must
    # NOT be recorded as a disagreement
    rows = [row("DORA003", "esma", "2356",
                act="DORA - Regulation (EU) 2022/2554")]
    monkeypatch.setattr(cli.register, "discover", fake_discover(rows))

    def esma_fetch(http, url):
        return Record(authority="esma", qa_id="2356", source_url=url,
                      legal_act_raw="Regulation (EU) 2022/2554 - DORA",
                      question="Q", answer="A")
    monkeypatch.setattr(esma, "fetch_record", esma_fetch)

    assert run(root) == 0
    text = (root / "data" / "dora" / "esma-2356.md").read_text()
    assert "x_portal_legal_act" not in text


def test_authority_filter_restricts_rows(root, monkeypatch):
    install(monkeypatch, default_rows())
    assert run(root, "--authority", "esma") == 0
    assert (root / "data" / "dora" / "esma-2103.md").exists()
    assert not (root / "data" / "dora" / "eiopa-2622.md").exists()


def test_repaired_link_falls_through_to_working_alternate(root, monkeypatch):
    # a repaired register row carries guessed candidates; the first one 404s,
    # the alternate resolves — the record must be mirrored from the alternate
    r = dict(row("DORA001", "eiopa", "2622"),
             link="https://portal/eiopa/2622-dora001",
             link_alts=["https://portal/eiopa/dora001-2622"])
    monkeypatch.setattr(cli.register, "discover",
                        lambda session, act, statuses, auths: [r])

    def fetch(http, url):
        if url.endswith("2622-dora001"):
            raise RuntimeError("404")
        return Record(authority="eiopa", qa_id="2622", source_url=url,
                      question="Q", answer="A")
    monkeypatch.setattr(eiopa, "fetch_record", fetch)

    assert run(root) == 0
    text = (root / "data" / "dora" / "eiopa-2622.md").read_text()
    assert "dora001-2622" in text  # the alternate is the recorded source


def test_unusable_register_link_is_error_and_suppresses_delisting(root, monkeypatch):
    install(monkeypatch, default_rows())
    run(root)  # mirrors eiopa 2622 with a working link
    # next pass: the same row's link cell is broken beyond repair (link="")
    rows = default_rows()
    rows[0] = dict(rows[0], link="")
    monkeypatch.setattr(cli.register, "discover",
                        lambda session, act, statuses, auths:
                        [r for r in rows if r["status"] == "Final"])
    assert run(root) == 1  # red: a wanted register row is unreachable
    # the previously mirrored copy is protected from delisting
    assert "x_delisted" not in (root / "data" / "dora" / "eiopa-2622.md").read_text()


def test_register_failure_is_error_and_suppresses_delisting(root, monkeypatch):
    # first, a good run to populate state
    install(monkeypatch, default_rows())
    run(root)
    # now the register query fails wholesale
    def boom(session, act, statuses, authorities):
        raise register.RegisterError("powerbi down")
    monkeypatch.setattr(cli.register, "discover", boom)
    assert run(root) == 1  # red
    # nothing delisted despite the records being "unseen" this run
    assert "x_delisted" not in (root / "data" / "dora" / "eiopa-2622.md").read_text()


def test_delisting_marks_vanished_joint_record(root, monkeypatch):
    rows = [row("DORA00%d" % i, "eiopa", str(2600 + i)) for i in range(8)]
    install(monkeypatch, rows)
    run(root)
    # one row disappears from the register (well under the brake threshold)
    install(monkeypatch, rows[:-1])
    assert run(root) == 0
    gone = root / "data" / "dora" / f"eiopa-{2600 + 7}.md"
    assert "x_delisted:" in gone.read_text()
    assert "x_delisted" not in (root / "data" / "dora" / "eiopa-2600.md").read_text()


def test_mass_delisting_brake(root, monkeypatch):
    rows = [row("DORA00%d" % i, "eiopa", str(2600 + i)) for i in range(8)]
    install(monkeypatch, rows)
    run(root)
    install(monkeypatch, [])  # everything vanished at once → implausible
    assert run(root) == 1
    assert "x_delisted" not in (root / "data" / "dora" / "eiopa-2600.md").read_text()
    assert run(root, "--allow-mass-delisting") == 0
    assert "x_delisted:" in (root / "data" / "dora" / "eiopa-2600.md").read_text()


EBA_CFG = (JOINT_CFG + "eba:\n  legal_act_ids: [32]\n  default_act_ref: '2013/36'\n"
           "  require_status: Final\n")


def eba_listing(*qa_ids):
    return [f"{eba.BASE}/single-rule-book-qa/qna/view/publicId/{q}" for q in qa_ids]


def eba_fetch_final(http, url):
    nid = url.rstrip("/").rsplit("/", 1)[-1]
    return Record(authority="eba", qa_id=nid, source_url=url,
                  status="Final Q&A", legal_act_raw="Directive 2013/36/EU (CRD)",
                  question="Q", answer="A")


def test_eba_sectoral_alongside_joint(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(EBA_CFG, encoding="utf-8")
    install(monkeypatch, default_rows(), eba_listing=eba_listing("2013_9"))
    monkeypatch.setattr(eba, "fetch_record", eba_fetch_final)

    assert cli.main(["--root", str(tmp_path)]) == 0
    # joint EBA-less run still wrote EIOPA/ESMA joint records...
    assert (tmp_path / "data" / "dora" / "eiopa-2622.md").exists()
    # ...and the sectoral CRD record landed under its own family
    assert (tmp_path / "data" / "crd" / "eba-2013-9.md").exists()


def test_eba_missing_records_split_into_archived_and_delisted(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(EBA_CFG, encoding="utf-8")
    install(monkeypatch, [], eba_listing=eba_listing("2013_1", "2013_2", "2013_3"))
    monkeypatch.setattr(eba, "fetch_record", eba_fetch_final)
    assert cli.main(["--root", str(tmp_path)]) == 0
    # next pass: 2013_2 moved to the archive tab, 2013_3 vanished entirely
    install(monkeypatch, [], eba_listing=eba_listing("2013_1"),
            eba_archive={"2013-2"})
    monkeypatch.setattr(eba, "fetch_record", eba_fetch_final)
    assert cli.main(["--root", str(tmp_path)]) == 0
    crd = tmp_path / "data" / "crd"
    assert "x_archived:" in (crd / "eba-2013-2.md").read_text()
    assert "x_delisted" not in (crd / "eba-2013-2.md").read_text()
    assert "x_delisted:" in (crd / "eba-2013-3.md").read_text()
    assert "x_" not in (crd / "eba-2013-1.md").read_text().split("---")[1]


def test_eba_archive_lookup_failure_fails_closed(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(EBA_CFG, encoding="utf-8")
    install(monkeypatch, [], eba_listing=eba_listing("2013_1", "2013_2"))
    monkeypatch.setattr(eba, "fetch_record", eba_fetch_final)
    assert cli.main(["--root", str(tmp_path)]) == 0

    install(monkeypatch, [], eba_listing=eba_listing("2013_1"))
    monkeypatch.setattr(eba, "fetch_record", eba_fetch_final)
    def boom(http, params):
        raise RuntimeError("archive tab unreachable")
    monkeypatch.setattr(eba, "list_archive_slugs", boom)
    assert cli.main(["--root", str(tmp_path)]) == 1  # red
    # unable to classify → nothing marked at all
    assert "x_" not in (tmp_path / "data" / "crd" / "eba-2013-2.md")\
        .read_text().split("---")[1]


def test_eba_preflight_aborts_when_page_budget_too_small(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(EBA_CFG + "  max_pages: 2\n",
                                          encoding="utf-8")
    def never(http, params, **kw):
        raise AssertionError("listing must not be walked when pre-flight fails")
    install(monkeypatch, default_rows(), eba_counts={"final": 100})
    monkeypatch.setattr(eba, "list_detail_urls", never)
    assert cli.main(["--root", str(tmp_path)]) == 1  # 100/20 = 5 pages > 2


def test_eba_incomplete_discovery_vs_announced_count_is_error(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(EBA_CFG, encoding="utf-8")
    # portal announces 10 finals, the listing serves only 1 → silent truncation
    install(monkeypatch, default_rows(), eba_listing=eba_listing("2013_1"),
            eba_counts={"final": 10})
    monkeypatch.setattr(eba, "fetch_record", eba_fetch_final)
    assert cli.main(["--root", str(tmp_path)]) == 1
    # the fetched record itself is still written (partial results are kept)
    assert (tmp_path / "data" / "crd" / "eba-2013-1.md").exists()


def test_run_manifest_written_for_full_runs_only(root, monkeypatch):
    install(monkeypatch, default_rows())
    assert run(root) == 0
    lines = (root / "runs.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    import json
    entry = json.loads(lines[0])
    assert entry["totals"]["eiopa"]["written"] == 2
    assert len(entry["state_sha256"]) == 64
    assert entry["ts"]
    # a --limit smoke run must not pollute the audit trail
    run(root, "--limit", "1")
    assert len((root / "runs.jsonl").read_text().strip().splitlines()) == 1
    # the next full run appends
    run(root)
    assert len((root / "runs.jsonl").read_text().strip().splitlines()) == 2
