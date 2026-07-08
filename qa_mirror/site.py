"""Build the static search site (docs/) from data/ — served via GitHub Pages.

Usage: python -m qa_mirror.site [--root .]
Writes docs/records.json; docs/index.html is a static file committed alongside.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml


def build(root: Path) -> int:
    records = []
    for f in sorted((root / "data").rglob("*.md")):
        text = f.read_text(encoding="utf-8")
        parts = text.split("---")
        if len(parts) < 3:
            continue
        fm = yaml.safe_load(parts[1]) or {}
        body = "---".join(parts[2:])
        q = re.search(r"## Question\n(.*?)\n## (?:Background|Answer)", body, re.S)
        b = re.search(r"## Background\n(.*?)\n## Answer", body, re.S)
        a = re.search(r"## Answer\n(.*?)(?:\n---\n|$)", body, re.S)
        records.append({
            "authority": fm.get("authority", ""),
            "qa_id": fm.get("qa_id", ""),
            "joint_id": fm.get("joint_id", ""),
            "legal_act": fm.get("legal_act", ""),
            "article": fm.get("article", ""),
            "topic": fm.get("topic", ""),
            "status": fm.get("status", ""),
            "source_url": fm.get("source_url", ""),
            "file": str(f.relative_to(root)),
            "question": (q.group(1).strip() if q else ""),
            "background": (b.group(1).strip() if b else ""),
            "answer": (a.group(1).strip() if a else ""),
        })
    out = root / "docs" / "records.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    print(f"site: {len(records)} records → {out}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    raise SystemExit(build(Path(ap.parse_args().root).resolve()))
