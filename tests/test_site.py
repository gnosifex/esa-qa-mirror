import json

from qa_mirror import site
from qa_mirror.common import Record, State, mark_file_delisted, write_record


def rec(authority, qa_id, legal_act, **kw):
    base = dict(
        authority=authority, qa_id=qa_id, legal_act=legal_act,
        source_url=f"https://example.org/{authority}/{qa_id}",
        question="What is asked?", answer="What is answered.",
        status="Final Q&A", retrieved_at="2026-07-08T00:00:00+00:00",
    )
    base.update(kw)
    return Record(**base)


def test_build_splits_per_family_and_writes_manifest(tmp_path):
    write_record(tmp_path, rec("eba", "2024_1", "DORA",
                               dates={"final_publishing_date": "08/08/2025"}))
    write_record(tmp_path, rec("esma", "2356", "DORA-RTS-RMF"))
    write_record(tmp_path, rec("eba", "2013_2", "CRD"))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "records.json").write_text("[]")  # stale monolith

    assert site.build(tmp_path) == 0

    manifest = json.loads((tmp_path / "docs" / "manifest.json").read_text("utf-8"))
    assert set(manifest) == {"dora", "crd"}
    assert manifest["dora"]["count"] == 2
    assert manifest["dora"]["acts"] == ["DORA", "DORA-RTS-RMF"]
    assert manifest["dora"]["authorities"] == ["eba", "esma"]
    assert manifest["crd"]["file"] == "records-crd.json"
    assert not (tmp_path / "docs" / "records.json").exists()  # stale file removed

    dora = json.loads((tmp_path / "docs" / "records-dora.json").read_text("utf-8"))
    r = next(x for x in dora if x["qa_id"] == "2024_1")
    assert r["question"] == "What is asked?"
    assert r["answer"] == "What is answered."
    assert r["date"] == "2025-08-08"  # normalized publication date, for sorting
    assert next(x for x in dora if x["qa_id"] == "2356")["date"] == ""
    assert r["file"] == "data/dora/eba-2024_1.md".replace("2024_1", "2024-1")


def test_build_keeps_separator_inside_multipart_answers(tmp_path):
    # ESMA joins accordion parts with "---"; extraction must not stop there
    write_record(tmp_path, rec(
        "esma", "42", "DORA",
        answer="Part one.\n\n---\n\nPart two.",
        background="Some background.",
    ))
    site.build(tmp_path)
    (r,) = json.loads((tmp_path / "docs" / "records-dora.json").read_text("utf-8"))
    assert r["answer"] == "Part one.\n\n---\n\nPart two."
    assert r["background"] == "Some background."
    assert "Disclaimer" not in r["answer"]


def test_build_exposes_delisted_flag(tmp_path):
    r = rec("eba", "2024_9", "DORA")
    write_record(tmp_path, r)
    mark_file_delisted(tmp_path, State(tmp_path / "state.json").key(r), "2026-07-08")
    site.build(tmp_path)
    (out,) = json.loads((tmp_path / "docs" / "records-dora.json").read_text("utf-8"))
    assert out["delisted"] == "2026-07-08"
