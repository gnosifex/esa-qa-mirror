"""Shared plumbing: polite HTTP, HTML→text, record normalization, state."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "esa-qa-mirror/0.1 (+https://github.com/gnosifex/esa-qa-mirror; "
    "public Q&A archival tool; contact via repo issues)"
)
DEFAULT_DELAY = 1.5  # seconds between requests — be polite


class Http:
    # Transient failures (throttling, flaky origins, network blips) are retried
    # here centrally with growing backoff so adapters only ever see hard
    # errors. 4xx other than 429 (e.g. 404) raise immediately — they are
    # signal, not noise.
    RETRYABLE = (429, 500, 502, 503, 504)

    def __init__(self, delay: float = DEFAULT_DELAY, retries: int = 3):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.delay = delay
        self.retries = retries
        self._last = 0.0

    def get(self, url: str, **kw) -> requests.Response:
        for attempt in range(self.retries + 1):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self.session.get(url, timeout=60, **kw)
                self._last = time.monotonic()
                if resp.status_code in self.RETRYABLE and attempt < self.retries:
                    backoff = min(
                        300, int(resp.headers.get("Retry-After") or 0) or 15 * 2**attempt
                    )
                    print(
                        f"[http] {resp.status_code} for {url} — retrying in {backoff}s",
                        file=sys.stderr,
                    )
                    time.sleep(backoff)
                    continue
                resp.raise_for_status()
                return resp
            except requests.HTTPError:
                raise
            except requests.RequestException as exc:
                self._last = time.monotonic()
                if attempt >= self.retries:
                    raise
                backoff = 15 * 2**attempt
                print(
                    f"[http] {type(exc).__name__} for {url} — retrying in {backoff}s",
                    file=sys.stderr,
                )
                time.sleep(backoff)
        raise RuntimeError("unreachable")


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


_BLOCK_TAGS = ["p", "li", "h2", "h3", "h4", "td"]


def html_to_text(node) -> str:
    """Element → readable plain text with paragraph breaks preserved."""
    if node is None:
        return ""
    if isinstance(node, str):
        node = soup(node)
    for br in node.find_all("br"):
        br.replace_with("\n")
    parts = []
    blocks = node.find_all(_BLOCK_TAGS) or [node]
    # find_all returns nested blocks (<li><p>…</p></li>, <td><p>…</p></td>) as
    # parent AND child; emitting both duplicates the text. Keep only blocks with
    # no ancestor in the result. Compare by identity — bs4's == compares content,
    # which would false-match equal tags elsewhere in the document.
    block_ids = {id(b) for b in blocks}
    for b in blocks:
        if any(id(a) in block_ids for a in b.parents):
            continue
        t = re.sub(r"\s+", " ", b.get_text(" ", strip=True))
        if t:
            prefix = "- " if b.name == "li" else ""
            parts.append(prefix + t)
    if not parts:
        t = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
        return t
    return "\n\n".join(parts)


def iter_listing(http: Http, page_url, href_re: str, max_pages: int, tag: str):
    """Yield detail-page links from a 0-based paginated listing, in page order.

    Stops after two consecutive pages with no *new* links. A single barren page
    — whether it carries no links at all (a transient empty response mid-listing)
    or only already-seen ones (pinned/duplicate entries) — must not silently cut
    off the rest of the corpus, so both cases are treated the same and only a
    second consecutive one ends the walk. Warns when max_pages is exhausted,
    since that also means possible truncation.
    """
    seen = set()
    stale = 0
    for page in range(max_pages):
        html = http.get(page_url(page)).text
        links = set(re.findall(href_re, html))
        new = links - seen
        if not new:
            stale += 1
            if stale >= 2:
                return
            continue
        stale = 0
        seen |= new
        yield from sorted(new)
    print(
        f"[{tag}] WARNING: pagination stopped at max_pages={max_pages} — "
        "listing may be truncated",
        file=sys.stderr,
    )


# Canonical labels per act reference — extend as you add acts to config.yaml.
ACT_LABELS = {
    "2022/2554": "DORA",
    "2022/2556": "DORA-Amending-Directive",
    "2024/1772": "DORA-RTS-Incident-Classification",
    "2024/1773": "DORA-RTS-TPPol",
    "2024/1774": "DORA-RTS-RMF",
    "2024/2956": "DORA-ITS-Register-of-Information",
    "2025/301": "DORA-RTS-Incident-Reporting",
    "2025/302": "DORA-ITS-Incident-Reporting",
    "2025/532": "DORA-RTS-Subcontracting",
    "2025/1190": "DORA-RTS-TLPT",
    "2013/36": "CRD",
    "575/2013": "CRR",
    "2015/2366": "PSD2",
}

# Matches both naming styles: regulations "(EU) No 575/2013" / "(EU) 2022/2554"
# and directives "2013/36/EU" (number before the EU suffix).
_ACT_REF_RE = re.compile(
    r"\((?:EU|EG|EC)\)\s*(?:No\.?\s*)?(\d{1,4}/\d{1,4})"
    r"|(\d{4}/\d{1,4})(?=/(?:EU|EG|EC)\b)"
)

# Portal date styles seen so far: EBA "20/05/2024", ESMA/EIOPA "06 Dec 2024".
_DATE_FORMATS = ("%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d.%m.%Y")


def iso_date(value: str) -> str:
    """Portal-verbatim date string → ISO "YYYY-MM-DD", or "" if unparseable."""
    v = (value or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


# Joint-Q&A-Register ID formats differ per legal act (DORA pads to three digits:
# DORA003). Add act-specific rules here when mirroring further acts; the fallback
# keeps the number unpadded.
JOINT_ID_FORMATS = {"DORA": "{token}{num:03d}"}


def format_joint_id(token: str, num: int) -> str:
    token = token.upper()
    fmt = JOINT_ID_FORMATS.get(token, "{token}{num}")
    return fmt.format(token=token, num=num)


@dataclass
class Record:
    """Normalized Q&A record — one file per record under data/<authority>/."""

    authority: str          # eba | eiopa | esma
    qa_id: str              # portal-native ID, e.g. 2024_7089 / DORA 137 - 3195 / 2356
    source_url: str
    joint_id: str = ""      # shared Joint-ESAs-Q&A id where the portal exposes it
    legal_act: str = ""     # canonical label (see ACT_LABELS), set by finalize()
    legal_act_ref: str = "" # regulation reference, e.g. "(EU) 2022/2554"
    legal_act_raw: str = "" # portal's verbatim legal-act string
    article: str = ""
    topic: str = ""
    status: str = ""
    dates: dict = field(default_factory=dict)   # submission/publication/... as found
    retrieved_at: str = ""                       # UTC timestamp of this fetch
    question: str = ""
    background: str = ""                         # e.g. EBA "Background on the question"
    answer: str = ""
    extra: dict = field(default_factory=dict)   # any further portal fields, verbatim

    def act_family(self) -> str:
        """Directory grouping: the level-1 family of the canonical label
        (DORA-RTS-RMF → dora), so a basis act and its level-2 acts stay together."""
        base = (self.legal_act or "").split("-")[0].strip().lower()
        return re.sub(r"[^a-z0-9]+", "-", base) or "unsorted"

    def finalize(self, params: dict) -> "Record":
        """Derive the structured legal-act fields from the portal string, falling
        back to the authority's configured default (portals differ wildly here —
        ESMA e.g. exposes no legal-act field on the detail page at all)."""
        m = _ACT_REF_RE.search(self.legal_act_raw or "")
        if m:
            ref = m.group(1) or m.group(2)
        elif not self.legal_act_raw:
            ref = str(params.get("default_act_ref", "") or "")
        else:
            # A present-but-unparseable act string means a foreign or unknown
            # act — mislabeling it with the configured default would smuggle
            # out-of-scope records into the act's directory (seen live when a
            # broken portal facet returned Solvency-II Q&As on a DORA filter).
            ref = ""
        if ref:
            self.legal_act_ref = f"(EU) {ref}"
            self.legal_act = ACT_LABELS.get(ref, self.legal_act or "")
        return self

    def slug(self) -> str:
        s = re.sub(r"[^A-Za-z0-9]+", "-", self.qa_id).strip("-").lower()
        return s or hashlib.sha1(self.source_url.encode()).hexdigest()[:12]

    def to_markdown(self) -> str:
        def y(v: str) -> str:
            # Single-line double-quoted YAML scalar: escape backslash/quote and
            # encode line breaks as \n — multi-line quoted scalars are valid YAML
            # but break simple frontmatter parsers (e.g. Obsidian).
            s = str(v).replace("\\", "\\\\").replace('"', '\\"')
            s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
            return '"' + s + '"'

        fm = [
            "---",
            f"authority: {self.authority}",
            f"qa_id: {y(self.qa_id)}",
            f"joint_id: {y(self.joint_id)}",
            f"legal_act: {y(self.legal_act)}",
            f"legal_act_ref: {y(self.legal_act_ref)}",
            f"legal_act_raw: {y(self.legal_act_raw)}",
            f"article: {y(self.article)}",
            f"topic: {y(self.topic)}",
            f"status: {y(self.status)}",
        ]
        for k, v in sorted(self.dates.items()):
            fm.append(f"date_{k}: {y(v)}")
            # Portal-verbatim value plus a normalized twin for sorting/filtering
            # (Obsidian properties, search page). Raw value always kept.
            if iso_date(v):
                fm.append(f"date_{k}_iso: {y(iso_date(v))}")
        for k, v in sorted(self.extra.items()):
            fm.append(f"x_{k}: {y(v)}")
        fm += [
            f"source_url: {y(self.source_url)}",
            f"retrieved_at: {y(self.retrieved_at)}",
            "---",
            "",
        ]
        body = [
            f"# {self.authority.upper()} Q&A {self.qa_id}",
            "",
            "## Question",
            "",
            self.question or "*(not captured)*",
            "",
        ]
        if self.background:
            body += ["## Background", "", self.background, ""]
        body += [
            "## Answer",
            "",
            self.answer or "*(not captured)*",
            "",
            "---",
            "",
            "> **Disclaimer.** Unofficial, automatically generated mirror copy — "
            "no guarantee and no liability is accepted for accuracy, completeness "
            "or timeliness; conversion errors are possible. Before any use or "
            f"reliance, verify against the original: <{self.source_url}> — "
            "the authority's portal version prevails. Content © the respective "
            "authority; reuse subject to its legal notice.",
            "",
        ]
        return "\n".join(fm + body)

    def content_hash(self) -> str:
        # retrieved_at is excluded: a fresh fetch of unchanged content must not
        # count as a change, or every delta run would rewrite every record.
        md = re.sub(r"^retrieved_at: .*\n", "", self.to_markdown(), flags=re.M)
        return hashlib.sha256(md.encode()).hexdigest()[:16]


# state.json hash values get this prefix when the record vanished from the
# portal listing: it can never equal a real content hash, so a reappearing
# record is always treated as changed and rewritten (clearing the marker).
DELISTED_HASH_PREFIX = "delisted:"


class State:
    """Tracks known records for delta runs (state.json at repo root)."""

    def __init__(self, path: Path):
        self.path = path
        self.root = path.parent
        self.data = {"records": {}}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    def key(self, rec: Record) -> str:
        return f"{rec.authority}:{rec.slug()}"

    def is_new_or_changed(self, rec: Record) -> bool:
        if self.data["records"].get(self.key(rec)) != rec.content_hash():
            return True
        # A matching hash alone is not enough: if the file was deleted from
        # data/, the record must be rewritten even though nothing changed.
        return not record_path(self.root, rec).exists()

    def remember(self, rec: Record):
        self.data["records"][self.key(rec)] = rec.content_hash()

    def mark_delisted(self, key: str):
        cur = self.data["records"].get(key, "")
        if not cur.startswith(DELISTED_HASH_PREFIX):
            self.data["records"][key] = DELISTED_HASH_PREFIX + cur

    def save(self):
        self.path.write_text(
            json.dumps(self.data, indent=1, sort_keys=True), encoding="utf-8"
        )


def record_path(root: Path, rec: Record) -> Path:
    # Grouped by legal-act family, authority in the filename:
    # data/dora/eba-2024-7089.md
    return root / "data" / rec.act_family() / f"{rec.authority}-{rec.slug()}.md"


def write_record(root: Path, rec: Record) -> Path:
    out = record_path(root, rec)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rec.to_markdown(), encoding="utf-8")
    return out


def mark_file_delisted(root: Path, key: str, date_iso: str) -> Path | None:
    """Flag the record file for state key "authority:slug" as no longer listed.

    The file is kept (a citation tool must not silently lose records) and gets
    an `x_delisted: "YYYY-MM-DD"` frontmatter field instead. Returns the file
    path if it was newly marked, None if already marked or not found.
    """
    authority, slug = key.split(":", 1)
    for f in sorted((root / "data").glob(f"*/{authority}-{slug}.md")):
        text = f.read_text(encoding="utf-8")
        if re.search(r"^x_delisted: ", text, flags=re.M):
            return None
        new = re.sub(
            r"^source_url: ",
            f'x_delisted: "{date_iso}"\nsource_url: ',
            text,
            count=1,
            flags=re.M,
        )
        if new == text:
            return None
        f.write_text(new, encoding="utf-8")
        return f
    return None
