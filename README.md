# esa-qa-mirror

**🔍 Search the corpus in your browser — no account needed: <https://gnosifex.github.io/esa-qa-mirror/>**

Mirrors the **final Q&As of the three European Supervisory Authorities** (EBA Single Rulebook Q&A, EIOPA Q&A, ESMA Q&A) into one normalized, greppable Markdown repository — one file per Q&A with uniform YAML frontmatter (authority, legal act, article, topic, status, dates, source URL).

**Why:** The three portals use different frontends, different formats and poor search. Supervisory interpretations that materially affect how an article must be read are effectively undiscoverable by web search. This tool turns the open, growing Q&A corpus into an enumerable local corpus you can search, diff and cite — and keeps it current via scheduled delta runs.

Out of the box it mirrors the **DORA** Q&As of all three authorities and the **CRD** Q&As of the EBA (banking-sector acts have no Joint Q&As — they live solely in the EBA Single Rulebook tool); any other legal act is a config-only change (see "Adding a new legal act"). Only **final** Q&As are mirrored — EIOPA/ESMA filter at listing level, EBA via the `require_status` post-filter.

## Quick start

```bash
pip install -r requirements.txt
python -m qa_mirror                 # full delta run per config.yaml
python -m qa_mirror --limit 5       # smoke test: max 5 records per authority
python -m qa_mirror --authority eba # one portal only
python -m qa_mirror.site            # rebuild the docs/ search index from data/
```

The search index (`docs/records-*.json`, `docs/manifest.json`) is a build artifact derived from `data/` — it is gitignored and generated at deploy time by the `pages` workflow, so the corpus lives in the repo exactly once.

Records land in `data/<legal-act-family>/<authority>-<qa-id>.md` (e.g. `data/dora/eba-2024-7089.md`) — grouped by legal act, with the basis act and its level-2 acts in one directory. `state.json` tracks content hashes so repeated runs only rewrite new or changed records (delta behaviour by default; `--full` rewrites everything). The `retrieved_at` timestamp is excluded from the change detection.

## Configuration

`config.yaml` holds the portal facet filters. The IDs are the portals' own facet values — filter manually in the browser and copy the values from the resulting URL:

- **EBA** `legal_act_ids`: values of `qa_legal_act[]` (e.g. `20` = DORA Regulation, `19` = DORA delegated/implementing acts).
- **EIOPA** `facets`: the `f[N]=` values (e.g. `regulation_reference%3A489` = DORA, `status%3AFinal`).
- **ESMA** `level1_ids`: values of `field_qa_level1_target_id` (e.g. `20010` = DORA).

## Using this mirror for research

**Without any account or tooling:** use the search page at **<https://gnosifex.github.io/esa-qa-mirror/>** — full-text search over all mirrored Q&As with act/authority filters, straight in the browser (static GitHub Pages site, rebuilt on every mirror run). Search state lives in the URL (`?q=…&act=…&auth=…`), so result views are shareable/bookmarkable; record sets are loaded per act family, so filtered searches stay fast as the corpus grows. Alternatively, **Code → Download ZIP** gives you the whole corpus for local searching.

With a (free) GitHub account, GitHub's code search also works:

- **Web search:** type your term in the repo's search box, or use the global search with `repo:gnosifex/esa-qa-mirror <term>` — e.g. `repo:gnosifex/esa-qa-mirror "critical or important function"`. Every hit is one Q&A file with question, answer, article and source link.
- **Filter by article/act:** search for frontmatter values, e.g. `repo:gnosifex/esa-qa-mirror "article: \"28\"" DORA`.
- **What's new:** the commit history of `data/` *is* the change log — each weekly bot commit shows exactly which Q&As were added or revised.

Locally it gets better: clone and `grep -rl 'subcontracting' data/dora/`, or open `data/` as an **Obsidian vault** — the frontmatter is deliberately single-line/Obsidian-compatible, so every record renders with filterable properties.

Always verify against the linked source before relying on a record (see the per-record disclaimer).

## Adding a new legal act

Three steps, config only:

1. **Find the facet IDs:** filter for the act manually in each portal's browser search and copy the ID from the resulting URL (EBA `qa_legal_act[]`, EIOPA `f[N]=regulation_reference:…`, ESMA `field_qa_level1_target_id`). Sectoral acts exist in one portal only — banking acts (CRD/CRR/PSD2…) solely at the EBA; only cross-sectoral acts (DORA, SFDR, PRIIPs, Securitisation…) are Joint ESAs Q&As across portals.
2. **Add the IDs** to the authority sections in `config.yaml` (plus `default_act_ref` where a portal exposes no legal-act string).
3. **Declare the act** under `acts:` in `config.yaml` (canonical `label` → target directory; for Joint acts also the register's `joint_id_format`). Without a label, records land in `data/unsorted/`.

Then run `python -m qa_mirror` once for the initial corpus.

## Scheduled runs

`.github/workflows/mirror.yml` runs a weekly delta and commits new/changed records. Enable it by pushing this repo to GitHub; adjust the cron as you like. Each run's diff **is** your "what's new" report. Any adapter error turns the run red (the successful part is still committed); the per-authority counts land in the job summary.

Each mirror run then calls `pages.yml`, which builds the search index from `data/` and deploys the search page as a GitHub Pages artifact (`pages.yml` also runs on relevant pushes to main). **One-time setup:** set the Pages source to "GitHub Actions" (repo Settings → Pages → Build and deployment → Source).

**Removed Q&As are never deleted, only marked:** when a complete, error-free listing pass no longer contains a known record, the run adds `x_delisted: "YYYY-MM-DD"` to its frontmatter (shown as a warning on the search page). Runs with `--limit` or with errors never mark anything. If the Q&A reappears at the portal, the record is rewritten and the marker cleared automatically.

**Plausibility brake:** if more than `max(5, 20%)` of an authority's known records vanish from the listing at once, that is almost certainly a broken listing filter (portals have been observed to silently ignore facet parameters after migrations), not mass withdrawal — the run refuses to mark anything for that authority and exits red instead. `--allow-mass-delisting` overrides after manual verification. The `probe` workflow (manual dispatch) shows what the portal actually serves the runner when diagnosing such failures.

## Record format

```markdown
---
authority: eba
qa_id: "2024_7089"
joint_id: ""                          # shared Joint-ESAs id where the portal exposes it
legal_act: "DORA"                     # canonical label (ACT_LABELS in common.py)
legal_act_ref: "(EU) 2022/2554"       # structured regulation reference
legal_act_raw: "Regulation (EU) No 2022/2554 (DORA Reg)"   # portal's verbatim string
article: "28"
topic: "ICT third-party risk management"
status: "Final Q&A"
date_submission_date: "20/05/2024"            # portal-verbatim
date_submission_date_iso: "2024-05-20"        # normalized twin, for sorting/filtering
date_final_publishing_date: "08/08/2025"
date_final_publishing_date_iso: "2025-08-08"
x_…: portal-specific extras, kept verbatim
x_delisted: "2026-07-08"              # only if the Q&A vanished from the portal listing
source_url: "https://…"
retrieved_at: "2026-07-08T12:34:56+00:00"   # UTC timestamp of the fetch
---

# EBA Q&A 2024_7089

## Question
…

## Answer
…

> **Disclaimer.** Unofficial, automatically generated mirror copy — no liability
> for accuracy/completeness; verify against the original before any use.
```

The first block of frontmatter keys (`authority` … `status`, `source_url`) is **uniform across all three authorities**; `legal_act`/`legal_act_ref` are normalized (portal strings differ wildly; ESMA exposes none — the configured `default_act_ref` fills it). Portal-specific fields are preserved verbatim under the `x_` prefix. **Privacy by default:** submitter identity fields published by the EBA portal (name of institution/submitter, country) are deliberately not mirrored.

## Caveats

- **Unofficial mirror.** The portal version always prevails; every record links its source. Q&A answers are generally not legally binding (for Level-1/2 questions answered by the European Commission they carry particular weight) — assess bindingness per record.
- **Scrapers break.** The adapters parse the current portal HTML (verified 2026-07-08). Frontend changes will break individual adapters; each adapter fails independently without stopping the others, and the CLI exit code/summary shows errors. Fixes are local to one small adapter file.
- **Be polite.** Requests are rate-limited (`delay_seconds`, default 1.5 s) and the User-Agent identifies the tool. Keep it that way.
- Content of the mirrored Q&As © the respective authorities (EBA/EIOPA/ESMA); reuse subject to their legal notices — [EBA legal notice](https://www.eba.europa.eu/legal-notice) · [EIOPA legal notice](https://www.eiopa.europa.eu/legal-notice_en) · [ESMA legal notice](https://www.esma.europa.eu/legal-notice). Every mirrored record carries its own disclaimer and source link. This repository's code is MIT-licensed.

## Layout

```
qa_mirror/              the tool (common.py + one adapter per authority + CLI)
config.yaml             which Q&A sets to mirror
data/<act-family>/      the mirrored records, authority in the filename (committed)
state.json              delta-run state (committed)
tests/                  pytest suite (fixture HTML per portal + unit tests)
docs/                   search page (index.html committed; JSON index generated at deploy)
.github/workflows/      weekly mirror run (mirror.yml), search-site deploy (pages.yml),
                        tests/lint (ci.yml)
```

## Joint Q&As, source of truth, deduplication

DORA Q&As are **Joint ESAs Q&As**: one shared corpus, answered jointly, hosted in the webtool of whichever authority received the question, indexed centrally in the [Joint Q&A Register](https://www.esma.europa.eu/joint-committee/joint-qas) (a PowerBI embed).

**The authority webtools are the source of truth, not the joint register.** This is a deliberate design decision, grounded in practice: the register is a secondary index that has been observed to carry broken/wrong links to EBA/EIOPA entries, while an explicit search in the authority's own portal returned the correct record. This tool therefore mirrors the webtools directly; the register is useful only as a manual completeness cross-check (deliberately not scraped — PowerBI backends are brittle to automate anyway).

Cross-portal duplicates **do occur** (e.g. joint Q&A DORA003 is published both as EIOPA "2734 - DORA003" and ESMA 2356). The mirror deliberately keeps every authority's own copy — each webtool is the source of truth for its records — and exposes the shared `joint_id` in the frontmatter (where a portal encodes it, currently EIOPA), normalized to the Joint Q&A Register's native format (e.g. `DORA003`), as the key for deduplication and register cross-checks.
