# esa-qa-mirror

**🔍 Search the corpus in your browser — no account needed: <https://gnosifex.github.io/esa-qa-mirror/>**

Mirrors the supervisory **Q&As relevant to banking regulation** into one normalized, greppable Markdown repository — one file per Q&A with uniform YAML frontmatter (authority, legal act, article, topic, status, dates, source URL).

Two bodies of Q&As matter for a credit institution, and this tool covers both:

- **Joint ESAs Q&As** — cross-sectoral acts answered jointly by EBA/EIOPA/ESMA. **DORA** is the one that binds banks today. These are discovered through the [Joint Q&A Register](https://www.esma.europa.eu/joint-committee/joint-qas), then fetched from whichever authority's webtool received the question.
- **EBA Single Rulebook Q&As** — the banking-sector acts that live solely at the EBA: **CRD** out of the box, with **CRR / PSD2 / BRRD / MiCAR** a one-line config change.

**Why:** the authorities publish these Q&As as individual web pages made for interactive reading — three webtools, three formats. What's missing is the corpus **as data**: everything in one grip, normalized and machine-readable. These supervisory interpretations materially affect how an article must be read, and having all of them enumerable in one repository makes them not just searchable, diffable and citable, but directly usable as an **LLM-ready knowledge base** — feed `data/` to an AI assistant for retrieval, cross-cutting analysis or drafting support. That is what this mirror provides: one Markdown file per Q&A with uniform frontmatter, kept current via scheduled delta runs. Only **final** Q&As are mirrored.

## Quick start

```bash
pip install -r requirements.txt
python -m qa_mirror --limit 5       # smoke test: max 5 records per source
python -m qa_mirror                 # full delta run per config.yaml (first run mirrors everything — takes a while)
python -m qa_mirror --authority eba # one receiving authority only
python -m qa_mirror.site            # rebuild the docs/ search index from data/
```

The search index (`docs/records-*.json`, `docs/manifest.json`) is a build artifact derived from `data/` — it is gitignored and generated at deploy time by the `pages` workflow, so the corpus lives in the repo exactly once.

Records land in `data/<legal-act-family>/<authority>-<qa-id>.md` (e.g. `data/dora/eba-2024-7089.md`) — grouped by legal act, with the basis act and its level-2 acts in one directory. `state.json` tracks content hashes so repeated runs only rewrite new or changed records (delta behaviour by default; `--full` rewrites everything). The `retrieved_at` timestamp is excluded from the change detection.

## How discovery works

Two sources, one per kind of act (see `config.yaml`):

- **Joint acts (DORA) → the Joint Q&A Register.** One query to the register's PowerBI backend returns *every* joint Q&A with its receiving authority, the authority's native detail-page id, a direct link to the answer, status, legal act and metadata. The mirror takes the rows for the wanted act and status, then fetches each linked detail page for its content. This is what makes the joint corpus *complete*: the register lists Q&As regardless of who drafted the answer (including EU-Commission-answered finals), which a per-portal search misses.
- **Sectoral banking acts (CRD…) → the EBA's own search.** These are not Joint Q&As and have no register entry, so the EBA Single Rulebook search is paged through directly, filtered to finals.

Each discovered detail page is parsed by the receiving authority's adapter (`qa_mirror/eba.py`, `eiopa.py`, `esma.py`) into a uniform `Record`. The register supplies the authoritative shared fields (joint id, status, legal act, dates); the detail page supplies question, background and answer.

## Configuration

`config.yaml` declares the two discovery sources:

```yaml
joint_acts:
  DORA:
    register_act: "DORA"      # matches the register's "Legal act" by substring
    act_ref: "2022/2554"      # fills legal_act_ref where a portal exposes none
    statuses: ["Final", "Revised"]   # register Status values to mirror

eba:
  legal_act_ids: [32]         # 32 = CRD; qa_legal_act[] facet values
  default_act_ref: "2013/36"
  require_status: "Final"     # safety net — /search is the finals tab already
  max_pages: 600              # listing-page budget (20 Q&As per page)
```

The EBA `legal_act_ids` are the portal's own `qa_legal_act[]` facet values — filter manually in the browser and copy the value from the resulting URL. Common banking acts: `32` = CRD · `33` = CRR · `38` = PSD2 · `31` = BRRD · `18` = MiCAR. **Caution:** CRR alone is a very large, multi-year corpus — expect a long first run.

## Using this mirror for research

**Without any account or tooling:** use the search page at **<https://gnosifex.github.io/esa-qa-mirror/>** — full-text search over all mirrored Q&As with act (multi-select), authority and publication-date-range filters, straight in the browser (static GitHub Pages site, rebuilt on every mirror run). Words match at word start (`art. 28` finds Article 28), `"…"` searches an exact phrase, `OR`/`AND` combine terms, `/…/` is a regex, and results list the newest answers first with their publication date. Search state lives in the URL (`?q=…&act=…&auth=…&from=…&to=…`), so result views are shareable/bookmarkable; record sets are loaded per act family, so act-filtered searches only download the records they need. Alternatively, **Code → Download ZIP** gives you the whole corpus for local searching.

With a (free) GitHub account, GitHub's code search also works:

- **Web search:** type your term in the repo's search box, or use the global search with `repo:gnosifex/esa-qa-mirror <term>` — e.g. `repo:gnosifex/esa-qa-mirror "critical or important function"`. Every hit is one Q&A file with question, answer, article and source link.
- **Filter by article/act:** search for frontmatter values, e.g. `repo:gnosifex/esa-qa-mirror "article: \"28\"" DORA`.
- **What's new:** the commit history of `data/` *is* the change log — each bot commit shows exactly which Q&As were added or revised.

Locally it gets better: clone and `grep -rl 'subcontracting' data/dora/`, open `data/` as an **Obsidian vault** — the frontmatter is deliberately single-line/Obsidian-compatible, so every record renders with filterable properties — or point an **LLM / AI agent** at `data/`: one file per Q&A with uniform frontmatter is trivially easy for machines to enumerate, filter and quote.

Always verify against the linked source before relying on a record (see the per-record disclaimer).

## Adding a legal act

- **Another joint act** (SFDR, PRIIPs, Securitisation… — any cross-sectoral act in the register): add an entry under `joint_acts` with its `register_act` substring and `act_ref`. If you want a canonical directory label and joint-id normalization, also declare it under `acts:` (canonical `label` → target directory; for joint acts the register's `joint_id_format`). Without a label, records land in `data/unsorted/`.
- **Another sectoral banking act** (CRR, PSD2…): add its `qa_legal_act[]` id to `eba.legal_act_ids`, and declare the act under `acts:` for its directory label.

Then run `python -m qa_mirror` once for the initial corpus.

## Scheduled runs

`.github/workflows/mirror.yml` runs a daily delta and commits new/changed records (the run is idempotent — the daily cadence just caps worst-case latency at ~a day, whatever weekday an authority publishes on). Each run's diff **is** your "what's new" report. Any adapter error — or a failed register query — turns the run red (the successful part is still committed); the per-source counts land in the job summary.

**Every full run appends one JSON line to `runs.jsonl`** (UTC timestamp, per-source counts, SHA-256 over `state.json`) and commits it — so *"checked and unchanged"* is distinguishable from *"never ran"* in the git history itself, independent of GitHub's log retention. `--limit` smoke runs don't write it.

**Pre-flight completeness check (EBA):** before fetching anything, the run asks the portal's own count endpoint how many final Q&As exist for the configured acts, aborts red in minute one if the listing-page budget (`eba.max_pages`) can't cover them, logs the expected fetch time — and fails red if discovery ends materially below the announced count (silent truncation). Listing pages that come back empty are retried once with a cache-buster: the portals intermittently serve listings as JS-only shells from stale cache nodes.

Each mirror run then calls `pages.yml`, which builds the search index from `data/` and deploys the search page as a GitHub Pages artifact (`pages.yml` also runs on relevant pushes to main). **One-time setup:** set the Pages source to "GitHub Actions" (repo Settings → Pages → Build and deployment → Source).

**Removed Q&As are never deleted, only marked:** when a complete, error-free discovery pass no longer contains a known record, the run resolves EBA records against the portal's **archive tab** first — *archived after a review* gets `x_archived: "YYYY-MM-DD"`, *vanished without trace* gets `x_delisted: "YYYY-MM-DD"` (both shown as warnings on the search page). Runs with `--limit` or with errors never mark anything. If the Q&A reappears, the record is rewritten and the marker cleared automatically. On the register side, `statuses: ["Final", "Revised"]` keeps a Q&A discovered when its final answer is revised — the revised content is mirrored instead of the record being mis-marked as delisted.

**Plausibility brake:** if more than `max(5, 20%)` of a source's known records vanish at once, that is almost certainly a broken query (the register or a portal silently ignoring a filter), not mass withdrawal — the run refuses to mark anything for that authority and exits red instead. `--allow-mass-delisting` overrides after manual verification. The `probe` workflow (manual dispatch) shows what the sources actually serve the runner when diagnosing such failures.

## Record format

```markdown
---
authority: eba
qa_id: "2024_7089"
joint_id: ""                          # shared Joint-ESAs id (from the register / portal)
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
x_delisted: "2026-07-08"              # only if the Q&A vanished from discovery
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

The first block of frontmatter keys (`authority` … `status`, `source_url`) is **uniform across every record**; `legal_act`/`legal_act_ref` are normalized (portal strings differ wildly; ESMA exposes none — the configured `act_ref`/`default_act_ref` fills it). Portal-specific fields are preserved verbatim under the `x_` prefix. **Privacy by default:** submitter identity fields published by the EBA portal (name of institution/submitter, country) are deliberately not mirrored.

## Caveats

- **Unofficial mirror.** The portal version always prevails; every record links its source. Q&A answers are generally not legally binding (for Level-1/2 questions answered by the European Commission they carry particular weight) — assess bindingness per record.
- **Answers speak as of their publication date.** They interpret the legal acts in force at that time, and the authorities do not systematically revisit published Q&As after subsequent changes to the underlying legislation — check whether the cited provisions have since been amended. The publication date is on every record and search result.
- **Scrapers break.** The adapters parse the current portal HTML, and the register client reverse-engineers PowerBI's undocumented backend (both verified 2026-07-08). Frontend/backend changes will break the affected piece; each detail fetch fails independently without stopping the others, a failed register query fails closed (no delisting), and the CLI exit code/summary shows errors. Fixes are local to one small module.
- **Be polite.** Requests are rate-limited (`delay_seconds`, default 1.5 s) and the User-Agent identifies the tool. Keep it that way.
- Content of the mirrored Q&As © the respective authorities (EBA/EIOPA/ESMA); reuse subject to their legal notices — [EBA legal notice](https://www.eba.europa.eu/legal-notice) · [EIOPA legal notice](https://www.eiopa.europa.eu/legal-notice_en) · [ESMA legal notice](https://www.esma.europa.eu/legal-notice). Every mirrored record carries its own disclaimer and source link. This repository's code is MIT-licensed.

## Layout

```
qa_mirror/              the tool: common.py, register.py (joint discovery),
                        one adapter per authority (eba/eiopa/esma), CLI
config.yaml             which Q&A sets to mirror
data/<act-family>/      the mirrored records, authority in the filename (committed)
state.json              delta-run state (committed)
runs.jsonl              one JSON line per full mirror run — the audit trail (committed)
tests/                  pytest suite (fixture HTML per portal + unit tests)
docs/                   search page (index.html committed; JSON index generated at deploy)
.github/workflows/      daily mirror run (mirror.yml), search-site deploy (pages.yml),
                        tests/lint (ci.yml), network probe (probe.yml)
```

## Joint Q&As, the register, and deduplication

DORA Q&As are **Joint ESAs Q&As**: one shared corpus, answered jointly, hosted in the webtool of whichever authority received the question, indexed centrally in the [Joint Q&A Register](https://www.esma.europa.eu/joint-committee/joint-qas) (a PowerBI embed).

**The register is the discovery index; the authority webtools are the source of truth for content.** The mirror reads the register to learn *which* joint Q&As exist and where each one lives, then fetches the answer from the receiving authority's own detail page. This split is deliberate: the register gives completeness (it lists every joint Q&A, including EU-Commission-answered finals a per-portal search would miss) while the webtool gives the authoritative, full-text answer. A register row whose link doesn't resolve to a fetchable detail page is skipped rather than trusted blindly.

Cross-portal duplicates **do occur** (e.g. joint Q&A DORA003 is published both as EIOPA "2734 - DORA003" and ESMA 2356). The mirror keeps every authority's own copy — each webtool is the source of truth for its records — and exposes the shared `joint_id` in the frontmatter (from the register, normalized to its native format, e.g. `DORA003`) as the key for deduplication and cross-checks.

Occasionally the register and the receiving portal **classify the same document under different acts** — e.g. DORA138 / ESMA 2364, which the register lists under DORA (applicability of DORA to certain crypto VASPs) while ESMA's own page tags it MiCA. The register's classification wins for filing (it decides the joint set the Q&A belongs to), but the portal's differing act is preserved in `x_portal_legal_act:` so the disagreement stays visible rather than hidden.
