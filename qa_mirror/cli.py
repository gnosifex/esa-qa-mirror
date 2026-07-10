"""CLI: python -m qa_mirror [--authority ...] [--limit N] [--full]

Banking-scoped mirror. Discovery has two sources (see config.yaml):
- Joint ESAs Q&As (DORA) via the Joint Q&A Register — one query yields every
  joint Q&A with its receiving authority + a direct detail link.
- EBA Single Rulebook Q&As (banking-sector acts) via the EBA's own search.

Each discovered detail page is parsed by the receiving authority's adapter and
written as a normalized Markdown record under data/<act-family>/. Default run
is a delta; --full rewrites everything. Records that vanish from a complete,
error-free discovery pass are marked delisted (never deleted).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

from . import common, eba, eiopa, esma, register
from .common import Http, State, write_record

# Detail-page parsers, keyed by the register's "Receiving ESA".
ADAPTERS = {"eba": eba, "eiopa": eiopa, "esma": esma}


def _act_ref(raw: str) -> str:
    """The structured act reference (e.g. '2022/2554') inside a portal/register
    act string, or '' if none — used to tell a real act disagreement from mere
    wording differences ('DORA - Regulation (EU) 2022/2554' vs the reverse)."""
    m = common._ACT_REF_RE.search(raw or "")
    return (m.group(1) or m.group(2)) if m else ""


def _write_step_summary(totals: dict):
    """Mirror the run summary into the GitHub Actions job summary, if present."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "## Mirror run",
        "",
        "| authority | seen | checked | written | archived | delisted | errors |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for auth, t in totals.items():
        lines.append(
            f"| {auth} | {t['seen']} | {t['checked']} | {t['written']} "
            f"| {t['archived']} | {t['delisted']} | {t['errors']} |"
        )
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _write_run_manifest(root: Path, args, sel, totals, mode):
    """Append one JSON line per completed run to runs.jsonl — the committed,
    retention-free proof that a run happened even when nothing changed
    ("checked and unchanged" vs "never ran"). Skipped for --limit smoke runs."""
    line = {
        "ts": _now(),
        "mode": "sweep" if mode["sweep"] else "incremental",
        "authorities": sorted(sel),
        "full": bool(args.full),
        "totals": totals,
        "state_sha256": hashlib.sha256((root / "state.json").read_bytes()).hexdigest(),
    }
    with (root / "runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug_from_url(url: str) -> str:
    """State-key slug derived from a detail URL's tail — must agree with
    Record.slug() (verified against all mirrored records; a drift is
    self-correcting: the record merely looks new and gets fetched, and the
    post-fetch seen/verified bookkeeping uses the record's real key)."""
    return common.slug_of(url.rstrip("/").rsplit("/", 1)[-1].removesuffix("_en"))


def _run_mode(state, cfg, args) -> dict:
    """Decide what this run fetches. State-driven, not calendar-driven: a full
    sweep happens whenever the last completed one is too old (so a failed
    sweep retries on the next run), the verification queue picks the
    oldest-checked records first (so missed days heal themselves)."""
    inc = cfg.get("incremental") or {}
    now = datetime.now(timezone.utc)
    sweep_after = int(inc.get("sweep_after_days", 31))
    last_sweep = state.data.get("last_full_sweep", "")
    due = (not last_sweep
           or last_sweep < (now - timedelta(days=sweep_after)).date().isoformat())
    stale = now - timedelta(days=int(inc.get("verify_after_days", 7)))
    window = now - timedelta(days=int(inc.get("window_days", 14)))
    return {
        "sweep": bool(args.full or args.sweep or due),
        "stale_before": stale.isoformat(timespec="seconds"),
        "window_start": window.date().isoformat(),
        "budget": int(inc.get("daily_verify_budget", 600)),
    }


def _select(entries, state, mode):
    """Pick which enumerated records to fetch: everything on a sweep;
    otherwise new/reappearing records and recent publications (must-fetch),
    plus the oldest-verified records within the run's budget. Entries are
    (key, in_window, payload)."""
    must, rest = [], []
    for e in entries:
        h = state.data["records"].get(e[0])
        if (mode["sweep"] or h is None
                or h.startswith(common.DELISTED_HASH_PREFIX) or e[1]):
            must.append(e)
        else:
            rest.append(e)
    stale = sorted((e for e in rest
                    if state.verified_at(e[0]) <= mode["stale_before"]),
                   key=lambda e: (state.verified_at(e[0]), e[0]))
    take = stale[:max(0, mode["budget"])]
    mode["budget"] -= len(take)
    return must + take


def _fetch_first(adapter, http, urls):
    """Fetch the first URL that resolves. Alternates only exist for register
    rows with repaired links, where the first candidate is a guess — for
    ordinary rows the list has one entry and this is a plain fetch."""
    for u in urls[:-1]:
        try:
            return adapter.fetch_record(http, u)
        except Exception:
            continue
    return adapter.fetch_record(http, urls[-1])


def _write_delta(root, state, rec, args, totals, auth, tag):
    """Finalize timestamp + write the record only if new/changed. Returns True
    if it was written."""
    rec.retrieved_at = _now()
    totals[auth]["seen"] += 1
    if args.full or state.is_new_or_changed(rec):
        write_record(root, rec)
        state.remember(rec)
        totals[auth]["written"] += 1
        print(f"[{tag}] wrote {rec.slug()}")
        return True
    return False


def _mirror_joint(http, session, root, state, cfg, args, sel, totals, seen, complete,
                  mode):
    """Discover joint Q&As via the register; the register enumeration is always
    complete (presence, delisting), detail pages are fetched per _select."""
    for act_name, act in (cfg.get("joint_acts") or {}).items():
        statuses = set(act.get("statuses") or ["Final"])
        try:
            rows = register.discover(session, act["register_act"], statuses, sel)
        except register.RegisterError as exc:
            print(f"[register:{act_name}] DISCOVERY FAILED: {exc}", file=sys.stderr)
            for a in sel:  # cannot conclude anything is gone without the index
                complete[a] = False
                totals[a]["errors"] += 1
            continue
        entries = []
        for row in rows:
            auth = row["authority"]
            if not row["link"]:
                # register data-entry error that not even link synthesis could
                # fix — the record exists but is unreachable: fail visibly and
                # protect any previously mirrored copy from delisting.
                print(f"[{auth}:{act_name}] ERROR: register row "
                      f"{row['joint_id']} has no usable link — record "
                      "unreachable", file=sys.stderr)
                totals[auth]["errors"] += 1
                complete[auth] = False
                continue
            key = f"{auth}:{_slug_from_url(row['link'])}"
            seen[auth].add(key)
            in_window = (row.get("date_publication") or "") >= mode["window_start"]
            entries.append((key, in_window, row))
        n = 0
        for _, _, row in _select(entries, state, mode):
            if args.limit and n >= args.limit:
                break
            n += 1
            auth = row["authority"]
            tag = f"{auth}:{act_name}"
            try:
                rec = _fetch_first(ADAPTERS[auth], http,
                                   [row["link"], *row.get("link_alts", [])])
                # register metadata is authoritative for the shared/joint fields.
                # The legal act especially: a joint Q&A can straddle acts (e.g. a
                # DORA/MiCA VASP question), and the receiving portal may tag it by
                # the *other* act — but the register placed it in this joint act's
                # set, so its act string wins, keeping the record filed under the
                # act we discovered it for rather than in data/unsorted/.
                rec.joint_id = row["joint_id"] or rec.joint_id
                rec.status = row["status"] or rec.status
                if row["legal_act_raw"]:
                    portal_act = rec.legal_act_raw
                    rec.legal_act_raw = row["legal_act_raw"]
                    # When the portal names a *different* act than the register
                    # (verified live for ESMA 2364 / DORA138: register DORA, ESMA
                    # portal MiCA), keep the register's classification but record
                    # the portal's so the disagreement stays visible, not hidden.
                    # Mere wording differences (same ref) are not a disagreement.
                    if portal_act and _act_ref(portal_act) != _act_ref(row["legal_act_raw"]):
                        rec.extra["portal_legal_act"] = portal_act
                rec.article = rec.article or row["article"]
                rec.topic = rec.topic or row["topic"]
                if row["answered_by"]:
                    rec.extra["answered_by"] = row["answered_by"]
                if row["date_submission"]:
                    rec.dates.setdefault("submission_to_esas", row["date_submission"])
                if row["date_publication"]:
                    rec.dates.setdefault("publication_final_answer", row["date_publication"])
                rec.finalize({"default_act_ref": act.get("act_ref", "")})
                seen[auth].add(state.key(rec))  # real key, in case slug derivation drifted
                state.mark_verified(state.key(rec), _now())
                totals[auth]["checked"] += 1
                _write_delta(root, state, rec, args, totals, auth, tag)
            except Exception as exc:  # one bad detail page must not stop the run
                totals[auth]["errors"] += 1
                complete[auth] = False
                print(f"[{tag}] ERROR {row['link']}: {exc}", file=sys.stderr)
        if args.limit:  # a truncated pass is never a basis for delisting
            for a in sel:
                complete[a] = False


_EBA_PER_PAGE = 20  # listing page size of the EBA search (verified 2026-07-09)


def _mirror_eba(http, root, state, cfg, args, totals, seen, complete, mode):
    """EBA sectoral (banking) acts via the EBA's own search (finals tab).
    The listing enumeration is always complete (presence, counts, delisting);
    detail pages are fetched per _select."""
    params = cfg.get("eba") or {}
    if not params.get("legal_act_ids"):
        return
    req = str(params.get("require_status", "") or "")
    # Pre-flight: the portal's own count endpoint says how many finals exist —
    # the only independent completeness reference a first run has. Checks the
    # page budget up front (minute 1, not minute 50) and the discovery at the
    # end. Best-effort: an unavailable endpoint never blocks the run.
    expected = eba.expected_counts(http, params)
    if expected:
        pages = -(-expected.get("final", 0) // _EBA_PER_PAGE)
        max_pages = int(params.get("max_pages", 600))
        print(f"[eba] pre-flight: {expected} → ~{pages} listing pages "
              f"(max_pages={max_pages})")
        if pages > max_pages:
            print(f"[eba] ERROR: {expected.get('final', 0)} finals need ~{pages} "
                  f"listing pages > max_pages={max_pages} — raise eba.max_pages "
                  "in config.yaml", file=sys.stderr)
            totals["eba"]["errors"] += 1
            complete["eba"] = False
            return
    # Recently published finals (the "window") — catches revisions that bump
    # the publishing date on the day they appear. Best-effort: a broken date
    # facet only defers those to the verification queue (≤ verify_after_days).
    win = set()
    if not mode["sweep"] and not args.limit:
        try:
            win = {_slug_from_url(u) for u in eba.list_detail_urls(
                http, params, published_since=mode["window_start"])}
            if win:
                # A stale cache node can serve the windowed listing UNfiltered
                # (the known EBA disease) — every record would look freshly
                # published and the run would degenerate into an accidental
                # sweep. The count endpoint with the same date facet says how
                # many finals the window really holds; distrust a listing
                # that is implausibly larger.
                announced = eba.expected_counts(
                    http, params, published_since=mode["window_start"]
                ).get("final")
                if announced is not None and len(win) > announced * 1.5 + 3:
                    print(f"[eba] window listing implausible ({len(win)} slugs "
                          f"vs {announced} announced) — cache node ignored the "
                          "date facet; relying on the verification queue",
                          file=sys.stderr)
                    win = set()
        except Exception as exc:
            print(f"[eba] window listing failed ({exc}) — relying on the "
                  "verification queue", file=sys.stderr)
    entries = []
    listed = 0
    try:
        for url in eba.list_detail_urls(http, params):
            listed += 1
            slug = _slug_from_url(url)
            seen["eba"].add(f"eba:{slug}")
            entries.append((f"eba:{slug}", slug in win, url))
            if args.limit and listed >= args.limit:
                complete["eba"] = False
                break
    except Exception as exc:
        print(f"[eba] LISTING FAILED: {exc}", file=sys.stderr)
        totals["eba"]["errors"] += 1
        complete["eba"] = False
        return
    # A materially smaller discovery than announced means silent truncation
    # (stale cache nodes, broken pager) — fail closed rather than delist.
    if expected.get("final") and not args.limit and listed < expected["final"] * 0.95:
        print(f"[eba] ERROR: discovered {listed} of {expected['final']} announced "
              "finals — listing incomplete", file=sys.stderr)
        totals["eba"]["errors"] += 1
        complete["eba"] = False
    n = 0
    for _, _, url in _select(entries, state, mode):
        if args.limit and n >= args.limit:
            complete["eba"] = False
            break
        n += 1
        try:
            rec = eba.fetch_record(http, url).finalize(params)
            if req and req.lower() not in rec.status.lower():
                print(f"[eba] skip {rec.slug()} (status: {rec.status!r})")
                continue
            seen["eba"].add(state.key(rec))
            state.mark_verified(state.key(rec), _now())
            totals["eba"]["checked"] += 1
            _write_delta(root, state, rec, args, totals, "eba", "eba")
        except Exception as exc:
            totals["eba"]["errors"] += 1
            complete["eba"] = False
            print(f"[eba] ERROR {url}: {exc}", file=sys.stderr)


def _delist(http, root, state, cfg, args, totals, seen, complete, today):
    """Mark records of an authority that vanished from a complete, error-free
    discovery pass — never delete (a citation tool must not silently lose
    records). Missing EBA records are first resolved against the portal's
    archive tab: *archived after a review* (x_archived) is a different state
    than *vanished without trace* (x_delisted). A plausibility brake refuses
    mass delisting (a broken source); archive hits are positive evidence from
    the portal itself and bypass the brake."""
    for auth in ADAPTERS:
        if not complete[auth] or totals[auth]["errors"]:
            continue
        known = [
            k for k, h in state.data["records"].items()
            if k.startswith(f"{auth}:") and not h.startswith(common.DELISTED_HASH_PREFIX)
        ]
        missing = [k for k in known if k not in seen[auth]]
        if not missing:
            continue
        archived = set()
        if auth == "eba" and (cfg.get("eba") or {}).get("legal_act_ids"):
            try:
                slugs = eba.list_archive_slugs(http, cfg["eba"])
                archived = {k for k in missing if k.split(":", 1)[1] in slugs}
            except Exception as exc:
                # Unresolvable archive → cannot classify the missing records;
                # fail closed for this authority instead of guessing.
                print(f"[eba] ARCHIVE LOOKUP FAILED: {exc} — delisting skipped",
                      file=sys.stderr)
                totals[auth]["errors"] += 1
                continue
        for key in sorted(archived):
            path = common.mark_file_gone(root, key, today, "archived")
            if path:
                state.mark_delisted(key)  # same state marker: gone from finals
                totals[auth]["archived"] += 1
                print(f"[{auth}] archived {key} → marked {path.relative_to(root)}")
        rest = [k for k in missing if k not in archived]
        threshold = max(5, len(known) // 5)
        if len(rest) > threshold and not args.allow_mass_delisting:
            print(
                f"[{auth}] ERROR: implausible discovery — {len(rest)} of "
                f"{len(known)} known records missing; delisting skipped. "
                "Check the source; --allow-mass-delisting overrides.",
                file=sys.stderr,
            )
            totals[auth]["errors"] += 1
            continue
        for key in rest:
            path = common.mark_file_delisted(root, key, today)
            if path:
                state.mark_delisted(key)
                totals[auth]["delisted"] += 1
                print(f"[{auth}] delisted {key} → marked {path.relative_to(root)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qa_mirror")
    ap.add_argument("--authority", default="all", choices=["all", *ADAPTERS],
                    help="restrict to one receiving authority (default: all)")
    ap.add_argument("--limit", type=int, default=0, help="max records per source (0 = no limit)")
    ap.add_argument("--full", action="store_true", help="rewrite all records, not only new/changed")
    ap.add_argument("--sweep", action="store_true",
                    help="force a full content sweep (otherwise due-driven via "
                         "incremental.sweep_after_days)")
    ap.add_argument("--allow-mass-delisting", action="store_true",
                    help="permit delisting beyond the plausibility threshold")
    ap.add_argument("--root", default=".", help="repo root (default: cwd)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    cfg = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    # Acts declared in config extend/override the built-in label tables.
    for ref, spec in (cfg.get("acts") or {}).items():
        if spec.get("label"):
            common.ACT_LABELS[str(ref)] = str(spec["label"])
        if spec.get("joint_id_format"):
            common.JOINT_ID_FORMATS[str(spec.get("token", spec["label"]).upper())] = str(
                spec["joint_id_format"])

    http = Http(delay=float(cfg.get("delay_seconds", 1.5)))
    session = requests.Session()
    state = State(root / "state.json")
    today = datetime.now(timezone.utc).date().isoformat()

    sel = set(ADAPTERS) if args.authority == "all" else {args.authority}
    totals = {a: {"seen": 0, "written": 0, "checked": 0, "archived": 0,
                  "delisted": 0, "errors": 0} for a in ADAPTERS}
    seen = {a: set() for a in ADAPTERS}
    complete = {a: True for a in ADAPTERS}
    mode = _run_mode(state, cfg, args)
    print(f"mode: {'full sweep' if mode['sweep'] else 'incremental'} "
          f"(last full sweep: {state.data.get('last_full_sweep') or 'never'})")

    _mirror_joint(http, session, root, state, cfg, args, sel, totals, seen,
                  complete, mode)
    if "eba" in sel:
        _mirror_eba(http, root, state, cfg, args, totals, seen, complete, mode)
    else:
        complete["eba"] = False  # EBA sectoral not run → don't delist EBA
    if not args.limit:
        _delist(http, root, state, cfg, args, totals, seen, complete, today)

    ok = not any(t["errors"] for t in totals.values())
    if (mode["sweep"] and ok and not args.limit and args.authority == "all"):
        # only a green, unrestricted, all-authorities sweep counts as "the
        # whole corpus was verified in one pass" — anything less stays due
        state.data["last_full_sweep"] = today
    state.save()
    print("\nSummary:")
    for auth, t in totals.items():
        print(f"  {auth}: {t['seen']} seen, {t['checked']} checked, "
              f"{t['written']} written, {t['archived']} archived, "
              f"{t['delisted']} delisted, {t['errors']} errors")
    _write_step_summary(totals)
    if not args.limit:
        _write_run_manifest(root, args, sel, totals, mode)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
