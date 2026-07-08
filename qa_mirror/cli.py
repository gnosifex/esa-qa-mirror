"""CLI: python -m qa_mirror [--authority all|eba|eiopa|esma] [--limit N] [--full]

Reads config.yaml (per-authority filters), fetches listings + detail pages,
writes normalized Markdown records to data/<authority>/, tracks state.json.
Default run is a delta: unchanged records are skipped when writing.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import common, eba, eiopa, esma
from .common import Http, State, write_record

ADAPTERS = {"eba": eba, "eiopa": eiopa, "esma": esma}


def _write_step_summary(totals: dict):
    """Mirror the run summary into the GitHub Actions job summary, if present."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "## Mirror run",
        "",
        "| authority | seen | written | delisted | errors |",
        "|---|---:|---:|---:|---:|",
    ]
    for auth, t in totals.items():
        lines.append(
            f"| {auth} | {t['seen']} | {t['written']} | {t['delisted']} | {t['errors']} |"
        )
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qa_mirror")
    ap.add_argument("--authority", default="all", choices=["all", *ADAPTERS])
    ap.add_argument("--limit", type=int, default=0, help="max records per authority (0 = no limit)")
    ap.add_argument("--full", action="store_true", help="rewrite all records, not only new/changed")
    ap.add_argument(
        "--allow-mass-delisting",
        action="store_true",
        help="permit marking more than the plausibility threshold of an authority's records as delisted",
    )
    ap.add_argument("--root", default=".", help="repo root (default: cwd)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    cfg = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    # Acts declared in config extend/override the built-in tables, so adding a
    # new legal act never requires a code change.
    for ref, spec in (cfg.get("acts") or {}).items():
        if spec.get("label"):
            common.ACT_LABELS[str(ref)] = str(spec["label"])
        if spec.get("joint_id_format"):
            common.JOINT_ID_FORMATS[str(spec.get("token", spec["label"]).upper())] = str(
                spec["joint_id_format"]
            )
    http = Http(delay=float(cfg.get("delay_seconds", 1.5)))
    state = State(root / "state.json")

    authorities = list(ADAPTERS) if args.authority == "all" else [args.authority]
    today = datetime.now(timezone.utc).date().isoformat()
    totals = {}
    for auth in authorities:
        mod = ADAPTERS[auth]
        params = cfg.get(auth, {}) or {}
        written = errors = delisted = n = 0
        seen_keys = set()
        listing_ok = True
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
                    req_ref = str(params.get("require_act_ref", "") or "")
                    if req_ref and rec.legal_act_ref != f"(EU) {req_ref}":
                        print(f"[{auth}] skip {rec.slug()} (act: {rec.legal_act_raw!r})")
                        continue
                    seen_keys.add(state.key(rec))
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
            listing_ok = False

        # Known records that no longer appear in the listing are marked (never
        # deleted — a citation tool must not silently lose records). Only safe
        # to conclude "gone" from a complete, error-free pass: --limit truncates
        # the listing, and a fetch error hides that record's key from seen_keys.
        if listing_ok and errors == 0 and not args.limit:
            known = sorted(
                k for k in state.data["records"] if k.startswith(f"{auth}:")
            )
            missing = [k for k in known if k not in seen_keys]
            # Plausibility brake: losing a large share of the corpus at once
            # means a broken listing filter, not mass withdrawal (seen live:
            # a portal migration made the facet params no-ops and one run
            # "delisted" every known record). Refuse and go red instead.
            threshold = max(5, len(known) // 5)
            if len(missing) > threshold and not args.allow_mass_delisting:
                print(
                    f"[{auth}] ERROR: implausible listing — {len(missing)} of "
                    f"{len(known)} known records missing; delisting skipped. "
                    "Check the portal/facets; --allow-mass-delisting overrides.",
                    file=sys.stderr,
                )
                errors += 1
            else:
                for key in missing:
                    path = common.mark_file_delisted(root, key, today)
                    if path:
                        state.mark_delisted(key)
                        delisted += 1
                        print(f"[{auth}] delisted {key} → marked {path.relative_to(root)}")
        totals[auth] = {"seen": n, "written": written, "errors": errors, "delisted": delisted}

    state.save()
    print("\nSummary:")
    for auth, t in totals.items():
        print(
            f"  {auth}: {t['seen']} seen, {t['written']} written, "
            f"{t['delisted']} delisted, {t['errors']} errors"
        )
    _write_step_summary(totals)
    # Any error → non-zero: a partially successful run must not look green, or
    # a permanently broken adapter would go unnoticed while the others still
    # write. Partial results are committed anyway (workflow decouples the steps).
    return 1 if any(t["errors"] for t in totals.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
