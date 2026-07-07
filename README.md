# esa-qa-mirror

Mirrors the **final Q&As of the three European Supervisory Authorities** (EBA Single Rulebook Q&A, EIOPA Q&A, ESMA Q&A) into one normalized, greppable Markdown repository — one file per Q&A with uniform YAML frontmatter (authority, legal act, article, topic, status, dates, source URL).

**Why:** The three portals use different frontends, different formats and poor search. Supervisory interpretations that materially affect how an article must be read are effectively undiscoverable by web search. This tool turns the open, growing Q&A corpus into an enumerable local corpus you can search, diff and cite — and keeps it current via scheduled delta runs.

Out of the box it mirrors the **DORA** Q&As of all three authorities and the **CRD** Q&As of the EBA (banking-sector acts have no Joint Q&As — they live solely in the EBA Single Rulebook tool); any other legal act is a one-line config change (facet IDs documented in `config.yaml`). Only **final** Q&As are mirrored — EIOPA/ESMA filter at listing level, EBA via the `require_status` post-filter.

## Quick start

```bash
pip install -r requirements.txt
python -m qa_mirror                 # full delta run per config.yaml
python -m qa_mirror --limit 5       # smoke test: max 5 records per authority
python -m qa_mirror --authority eba # one portal only
```

Records land in `data/<legal-act-family>/<authority>-<qa-id>.md` (e.g. `data/dora/eba-2024-7089.md`) — grouped by legal act, with the basis act and its level-2 acts in one directory. `state.json` tracks content hashes so repeated runs only rewrite new or changed records (delta behaviour by default; `--full` rewrites everything). The `retrieved_at` timestamp is excluded from the change detection.

## Configuration

`config.yaml` holds the portal facet filters. The IDs are the portals' own facet values — filter manually in the browser and copy the values from the resulting URL:

- **EBA** `legal_act_ids`: values of `qa_legal_act[]` (e.g. `20` = DORA Regulation, `19` = DORA delegated/implementing acts).
- **EIOPA** `facets`: the `f[N]=` values (e.g. `regulation_reference%3A489` = DORA, `status%3AFinal`).
- **ESMA** `level1_ids`: values of `field_qa_level1_target_id` (e.g. `20010` = DORA).

## Scheduled runs

`.github/workflows/mirror.yml` runs a weekly delta and commits new/changed records. Enable it by pushing this repo to GitHub; adjust the cron as you like. Each run's diff **is** your "what's new" report.

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
date_submission_date: "20/05/2024"
date_final_publishing_date: "08/08/2025"
x_…: portal-specific extras, kept verbatim
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
.github/workflows/      weekly mirror run
```

## Joint Q&As, source of truth, deduplication

DORA Q&As are **Joint ESAs Q&As**: one shared corpus, answered jointly, hosted in the webtool of whichever authority received the question, indexed centrally in the [Joint Q&A Register](https://www.esma.europa.eu/joint-committee/joint-qas) (a PowerBI embed).

**The authority webtools are the source of truth, not the joint register.** This is a deliberate design decision, grounded in practice: the register is a secondary index that has been observed to carry broken/wrong links to EBA/EIOPA entries, while an explicit search in the authority's own portal returned the correct record. This tool therefore mirrors the webtools directly; the register is useful only as a manual completeness cross-check (deliberately not scraped — PowerBI backends are brittle to automate anyway).

Cross-portal duplicates **do occur** (e.g. joint Q&A DORA003 is published both as EIOPA "2734 - DORA003" and ESMA 2356). The mirror deliberately keeps every authority's own copy — each webtool is the source of truth for its records — and exposes the shared `joint_id` in the frontmatter (where a portal encodes it, currently EIOPA), normalized to the Joint Q&A Register's native format (e.g. `DORA003`), as the key for deduplication and register cross-checks.
