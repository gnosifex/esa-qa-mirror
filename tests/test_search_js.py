"""Unit-test the search page's query language (docs/index.html).

The pure search functions live between SEARCH CORE markers in the page's
inline script; this test extracts them verbatim and runs assertions under
node, so the deployed logic is what gets tested — no duplication.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

BEGIN = "// ---- SEARCH CORE"
END = "// ---- END SEARCH CORE"

ASSERTIONS = r"""
const assert = require('assert');
const hay = s => s.toLowerCase().replace(/\s+/g, ' ');
const H = hay('The register of information must list every ICT third-party\n' +
              'arrangement under Article 28 of Regulation (EU) 2022/2554.');
const m = q => matches(H, parseQuery(q));

// bare words AND-combine; each matches at word start only
assert(m('register information'));
assert(!m('register outsourcing'));
assert(!m('cat'));                    // no hit via appli"cat"ion-style substrings
assert(m('art. 28'));                 // "art." → word prefix of "Article"
assert(m('regulation 2022/2554'));

// stopwords are ignored outside phrases (they'd match every record)
assert(m('of the'));                  // stopword-only query = no filter
assert(!parseQuery('of the').length);

// quoted phrase = exact contiguous match, whitespace-tolerant
assert(m('"register of information"'));
// typographic quotes (macOS/iOS auto-substitution) work like ASCII quotes
assert(m('„register of information“'));   // German „…“
assert(m('“register of information”'));   // English “…”
assert.deepStrictEqual(parseQuery('„register of information“'),
                       parseQuery('"register of information"'));
assert(m('"ict third-party arrangement"'));
assert(!matches(hay('information about the register'),
                parseQuery('"register of information"')));

// OR / AND keywords, any case
assert(m('subcontracting OR "register of information"'));
assert(!m('subcontracting or outsourcing'));
assert(m('ict AND arrangement'));

// /regex/, invalid patterns fall back to a literal match
assert(m('/third-?party/'));
assert(!m('/fourth-?party/'));
assert(!m('/(unclosed/'));            // invalid regex → literal "(unclosed"

// highlighting: one combined regex, stopwords never highlighted
assert(highlightRe(parseQuery('of the')) === null);
const hre = highlightRe(parseQuery('"register of information" 28'));
const marked = 'register of information ... 28'.replace(hre, x => '[' + x + ']');
assert.strictEqual(marked, '[register of information] ... [28]');

console.log('search core: all assertions passed');
"""


def test_search_core(tmp_path):
    html = (Path(__file__).resolve().parents[1] / "docs" / "index.html").read_text("utf-8")
    core = html[html.index(BEGIN):html.index(END)]
    script = tmp_path / "search_core_test.js"
    script.write_text(core + ASSERTIONS, encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
