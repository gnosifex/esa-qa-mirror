from types import SimpleNamespace

import pytest

from qa_mirror import cli
from qa_mirror.common import Record, State


def make_adapter(records, listing_error=None):
    """Fake adapter module: yields one URL per record, serves records by URL."""
    by_url = {r.source_url: r for r in records}

    def list_detail_urls(http, params):
        if listing_error:
            raise listing_error
        yield from by_url

    def fetch_record(http, url):
        rec = by_url[url]
        # fetch_record constructs a fresh Record; emulate that so mutation
        # (retrieved_at) does not leak between runs
        return Record(**{**rec.__dict__})

    return SimpleNamespace(list_detail_urls=list_detail_urls, fetch_record=fetch_record)


def rec(authority, qa_id, **kw):
    base = dict(
        authority=authority, qa_id=qa_id,
        source_url=f"https://example.org/{authority}/{qa_id}",
        legal_act="DORA", question="Q?", answer="A.", status="Final Q&A",
    )
    base.update(kw)
    return Record(**base)


@pytest.fixture
def root(tmp_path):
    (tmp_path / "config.yaml").write_text("delay_seconds: 0\nacts: {}\n", encoding="utf-8")
    return tmp_path


def run(root, adapters, *argv):
    cli.ADAPTERS.clear()
    cli.ADAPTERS.update(adapters)
    return cli.main(["--root", str(root), *argv])


@pytest.fixture(autouse=True)
def restore_adapters():
    saved = dict(cli.ADAPTERS)
    yield
    cli.ADAPTERS.clear()
    cli.ADAPTERS.update(saved)


def test_partial_failure_exits_nonzero(root, capsys):
    adapters = {
        "good": make_adapter([rec("good", "1")]),
        "bad": make_adapter([], listing_error=RuntimeError("portal down")),
    }
    assert run(root, adapters) == 1
    assert (root / "data" / "dora" / "good-1.md").exists()  # partial results kept
    assert "LISTING FAILED" in capsys.readouterr().err


def test_clean_run_exits_zero(root):
    assert run(root, {"good": make_adapter([rec("good", "1")])}) == 0


def test_delisting_marks_missing_records(root):
    r1, r2 = rec("good", "1"), rec("good", "2")
    assert run(root, {"good": make_adapter([r1, r2])}) == 0
    # next run: record 2 vanished from the listing
    assert run(root, {"good": make_adapter([r1])}) == 0
    kept = (root / "data" / "dora" / "good-1.md").read_text(encoding="utf-8")
    gone = (root / "data" / "dora" / "good-2.md").read_text(encoding="utf-8")
    assert "x_delisted" not in kept
    assert "x_delisted:" in gone  # marked, never deleted
    state = State(root / "state.json")
    assert state.data["records"]["good:2"].startswith("delisted:")
    # a third identical run must not re-mark or grow the marker
    assert run(root, {"good": make_adapter([r1])}) == 0
    assert gone == (root / "data" / "dora" / "good-2.md").read_text(encoding="utf-8")


def test_no_delisting_on_limited_or_failing_runs(root):
    r1, r2 = rec("good", "1"), rec("good", "2")
    run(root, {"good": make_adapter([r1, r2])})

    run(root, {"good": make_adapter([r1])}, "--limit", "1")  # truncated listing
    assert "x_delisted" not in (root / "data" / "dora" / "good-2.md").read_text(
        encoding="utf-8")

    run(root, {"good": make_adapter([], listing_error=RuntimeError("down"))})
    assert "x_delisted" not in (root / "data" / "dora" / "good-2.md").read_text(
        encoding="utf-8")


def test_deleted_file_is_restored_despite_matching_hash(root):
    r1 = rec("good", "1")
    run(root, {"good": make_adapter([r1])})
    (root / "data" / "dora" / "good-1.md").unlink()
    run(root, {"good": make_adapter([r1])})
    assert (root / "data" / "dora" / "good-1.md").exists()


def test_github_step_summary(root, monkeypatch, tmp_path):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    run(root, {"good": make_adapter([rec("good", "1")])})
    text = summary.read_text(encoding="utf-8")
    assert "| authority | seen | written | delisted | errors |" in text
    assert "| good | 1 | 1 | 0 | 0 |" in text


def test_require_status_skips_and_delists(root):
    (root / "config.yaml").write_text(
        "delay_seconds: 0\nacts: {}\ngood:\n  require_status: Final\n",
        encoding="utf-8",
    )
    final, draft = rec("good", "1"), rec("good", "2", status="Under review")
    run(root, {"good": make_adapter([final, draft])})
    assert (root / "data" / "dora" / "good-1.md").exists()
    assert not (root / "data" / "dora" / "good-2.md").exists()


def test_mass_delisting_is_refused_and_reported(root, capsys):
    recs = [rec("good", str(i)) for i in range(8)]
    assert run(root, {"good": make_adapter(recs)}) == 0
    # broken listing filter: suddenly no known record is listed
    assert run(root, {"good": make_adapter([])}) == 1
    assert "implausible listing" in capsys.readouterr().err
    for i in range(8):
        assert "x_delisted" not in (root / "data" / "dora" / f"good-{i}.md").read_text(
            encoding="utf-8")
    # explicit override marks them and exits clean
    assert run(root, {"good": make_adapter([])}, "--allow-mass-delisting") == 0
    for i in range(8):
        assert "x_delisted" in (root / "data" / "dora" / f"good-{i}.md").read_text(
            encoding="utf-8")
    # already-delisted keys must not keep tripping the brake on later runs
    # (post-migration corpora would otherwise stay red forever)
    assert run(root, {"good": make_adapter([])}) == 0


def test_single_delisting_passes_the_plausibility_brake(root):
    recs = [rec("good", str(i)) for i in range(6)]
    run(root, {"good": make_adapter(recs)})
    assert run(root, {"good": make_adapter(recs[1:])}) == 0
    assert "x_delisted" in (root / "data" / "dora" / "good-0.md").read_text(encoding="utf-8")
    assert "x_delisted" not in (root / "data" / "dora" / "good-1.md").read_text(encoding="utf-8")


def test_require_act_ref_skips_foreign_records(root):
    (root / "config.yaml").write_text(
        "delay_seconds: 0\nacts: {}\ngood:\n  require_act_ref: \"2022/2554\"\n",
        encoding="utf-8",
    )
    dora = rec("good", "1", legal_act_raw="Regulation (EU) 2022/2554 (DORA)")
    foreign = rec("good", "2", legal_act_raw="(EU) 2023/894 - some Solvency II ITS")
    unparseable = rec("good", "3", legal_act_raw="Risk-Free Interest Rate")
    assert run(root, {"good": make_adapter([dora, foreign, unparseable])}) == 0
    assert (root / "data" / "dora" / "good-1.md").exists()
    assert not list((root / "data").glob("*/good-2.md"))
    assert not list((root / "data").glob("*/good-3.md"))


def test_delisting_needs_prior_state(root, tmp_path):
    # a record written earlier whose status left the mirrored set gets marked
    r1, r2 = rec("good", "1"), rec("good", "2")
    run(root, {"good": make_adapter([r1, r2])})
    (root / "config.yaml").write_text(
        "delay_seconds: 0\nacts: {}\ngood:\n  require_status: Final\n",
        encoding="utf-8",
    )
    r2_review = rec("good", "2", status="Under review")
    run(root, {"good": make_adapter([r1, r2_review])})
    assert "x_delisted:" in (root / "data" / "dora" / "good-2.md").read_text(
        encoding="utf-8")
