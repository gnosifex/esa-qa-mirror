"""CLI: python -m qa_mirror [--authority all|eba|eiopa|esma] [--limit N] [--full]

Reads config.yaml (per-authority filters), fetches listings + detail pages,
writes normalized Markdown records to data/<authority>/, tracks state.json.
Default run is a delta: unchanged records are skipped when writing.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import eba, eiopa, esma
from .common import Http, State, write_record

ADAPTERS = {"eba": eba, "eiopa": eiopa, "esma": esma}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qa_mirror")
    ap.add_argument("--authority", default="all", choices=["all", *ADAPTERS])
    ap.add_argument("--limit", type=int, default=0, help="max records per authority (0 = no limit)")
    ap.add_argument("--full", action="store_true", help="rewrite all records, not only new/changed")
    ap.add_argument("--root", default=".", help="repo root (default: cwd)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    cfg = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    http = Http(delay=float(cfg.get("delay_seconds", 1.5)))
    state = State(root / "state.json")

    authorities = list(ADAPTERS) if args.authority == "all" else [args.authority]
    totals = {}
    for auth in authorities:
        mod = ADAPTERS[auth]
        params = cfg.get(auth, {}) or {}
        written = errors = n = 0
        try:
            for url in mod.list_detail_urls(http, params):
                if args.limit and n >= args.limit:
                    break
                n += 1
                try:
                    rec = mod.fetch_record(http, url).finalize(params)
                    req = str(params.get("require_status", "") or "")
                    if req and req.lower() not in rec.status.lower():
                        print(f"[{auth}] skip {rec.slug()} (status: {rec.status!r})")
                        continue
                    rec.retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    if args.full or state.is_new_or_changed(rec):
                        write_record(root, rec)
                        state.remember(rec)
                        written += 1
                        print(f"[{auth}] wrote {rec.slug()}")
                except Exception as exc:  # one bad record must not stop the run
                    errors += 1
                    print(f"[{auth}] ERROR {url}: {exc}", file=sys.stderr)
        except Exception as exc:  # one broken portal must not stop the others
            print(f"[{auth}] LISTING FAILED: {exc}", file=sys.stderr)
            errors += 1
        totals[auth] = (n, written, errors)

    state.save()
    print("\nSummary:")
    for auth, (n, written, errors) in totals.items():
        print(f"  {auth}: {n} seen, {written} written, {errors} errors")
    return 1 if any(e for _, _, e in totals.values()) and not any(
        w for _, w, _ in totals.values()
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
