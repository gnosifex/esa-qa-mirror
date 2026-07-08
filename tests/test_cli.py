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


def install(monkeypatch, rows, eba_listing=None):
    monkeypatch.setattr(cli.register, "discover", fake_discover(rows))
    for auth, mod in (("eiopa", eiopa), ("esma", esma), ("eba", eba)):
        monkeypatch.setattr(mod, "fetch_record", fetch_for(auth))
    if eba_listing is not None:
        monkeypatch.setattr(eba, "list_detail_urls",
                            lambda http, params, **kw: iter(eba_listing))


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


def test_authority_filter_restricts_rows(root, monkeypatch):
    install(monkeypatch, default_rows())
    assert run(root, "--authority", "esma") == 0
    assert (root / "data" / "dora" / "esma-2103.md").exists()
    assert not (root / "data" / "dora" / "eiopa-2622.md").exists()


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


def test_eba_sectoral_alongside_joint(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(
        JOINT_CFG + "eba:\n  legal_act_ids: [32]\n  default_act_ref: '2013/36'\n"
        "  require_status: Final\n", encoding="utf-8")
    listing = [f"{eba.BASE}/single-rule-book-qa/qna/view/publicId/2013_9"]

    # eba.fetch_record for the sectoral CRD record returns a CRD record
    def eba_fetch(http, url):
        return Record(authority="eba", qa_id="2013_9", source_url=url,
                      status="Final Q&A", legal_act_raw="Directive 2013/36/EU (CRD)",
                      question="Q", answer="A")
    install(monkeypatch, default_rows())
    monkeypatch.setattr(eba, "fetch_record", eba_fetch)
    monkeypatch.setattr(eba, "list_detail_urls",
                        lambda http, params, **kw: iter(listing))

    assert cli.main(["--root", str(tmp_path)]) == 0
    # joint EBA-less run still wrote EIOPA/ESMA joint records...
    assert (tmp_path / "data" / "dora" / "eiopa-2622.md").exists()
    # ...and the sectoral CRD record landed under its own family
    assert (tmp_path / "data" / "crd" / "eba-2013-9.md").exists()
