"""Build the static search site (docs/) from data/ — served via GitHub Pages.

Usage: python -m qa_mirror.site [--root .]
Writes docs/records-<act-family>.json (one per data/ subdirectory) plus
docs/manifest.json (families, counts, acts, authorities) so the search page
only loads the record sets a query actually needs. docs/index.html is a
static file committed alongside.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

# First ---…--- pair only: a "---" inside the body (ESMA answers separate
# accordion parts with it) must not shift the frontmatter boundary.
_FM_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)
_Q_RE = re.compile(r"## Question\n(.*?)\n## (?:Background|Answer)", re.S)
_B_RE = re.compile(r"## Background\n(.*?)\n## Answer", re.S)
# The answer ends at the disclaimer separator, not at any "---" — multi-part
# ESMA answers contain "---" between accordion blocks.
_A_RE = re.compile(r"## Answer\n(.*?)(?:\n---\n\n> \*\*Disclaimer\.\*\*|\Z)", re.S)


def build(root: Path) -> int:
    by_family: dict[str, list[dict]] = {}
    for f in sorted((root / "data").rglob("*.md")):
        text = f.read_text(encoding="utf-8")
        m = _FM_RE.match(text)
        if not m:
            continue
        fm = yaml.safe_load(m.group(1)) or {}
        body = m.group(2)
        q = _Q_RE.search(body)
        b = _B_RE.search(body)
        a = _A_RE.search(body)
        by_family.setdefault(f.parent.name, []).append({
            "authority": fm.get("authority", ""),
            "qa_id": fm.get("qa_id", ""),
            "joint_id": fm.get("joint_id", ""),
            "legal_act": fm.get("legal_act", ""),
            "article": fm.get("article", ""),
            "topic": fm.get("topic", ""),
            "status": fm.get("status", ""),
            "delisted": fm.get("x_delisted", ""),
            "source_url": fm.get("source_url", ""),
            "file": str(f.relative_to(root)),
            "question": (q.group(1).strip() if q else ""),
            "background": (b.group(1).strip() if b else ""),
            "answer": (a.group(1).strip() if a else ""),
        })
    docs = root / "docs"
    docs.mkdir(exist_ok=True)
    for old in docs.glob("records*.json"):  # drop stale per-family files
        old.unlink()
    manifest = {}
    total = 0
    for family, records in sorted(by_family.items()):
        out = docs / f"records-{family}.json"
        out.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        manifest[family] = {
            "file": out.name,
            "count": len(records),
            "acts": sorted({r["legal_act"] for r in records if r["legal_act"]}),
            "authorities": sorted({r["authority"] for r in records if r["authority"]}),
        }
        total += len(records)
        print(f"site: {len(records)} records → {out}")
    (docs / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"site: {total} records total, manifest → {docs / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    raise SystemExit(build(Path(ap.parse_args().root).resolve()))
