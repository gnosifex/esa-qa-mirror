"""python -m qa_mirror.retry_plan — authorities a retry run should repeat.

The mirror workflow runs every authority nightly and schedules retry runs at
other times of day. A retry repeats only the authorities whose most recent
run (per runs.jsonl) ended with errors — so a source that is blocked at one
time of day gets probed at another, without re-running the healthy ones.
Prints the authorities space-separated (empty: nothing to retry).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def failed_authorities(runs_path: Path) -> list[str]:
    latest = {}  # authority -> its error count in the latest run covering it
    if runs_path.exists():
        for line in runs_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            totals = entry.get("totals") or {}
            for auth in entry.get("authorities") or []:
                if auth in totals:
                    latest[auth] = int(totals[auth].get("errors", 0))
    return sorted(a for a, errors in latest.items() if errors)


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]) if args else Path("runs.jsonl")
    print(" ".join(failed_authorities(path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
