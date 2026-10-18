"""Security and accessibility contracts for the home URL candidate preview."""

import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_JS = PROJECT_ROOT / "src/web/static/js/app.js"


def _run_node(script: str) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for URL input security tests")
    return subprocess.run(
        [node, "-e", script, str(APP_JS)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_url_extractor_normalizes_supported_urls_and_rejects_unsafe_protocols():
    script = r"""
const assert = require('node:assert/strict');
const {URLExtractor} = require(process.argv[1]);

const youtube = URLExtractor.extractAndRankURLs(
  'Watch https://www.youtube.com/watch?v=dQw4w9WgXcQ now',
);
assert.equal(youtube.length, 1);
assert.equal(youtube[0].url, 'https://www.youtube.com/watch?v=dQw4w9WgXcQ');
assert.equal(youtube[0].recommended, true);
assert.equal(Object.hasOwn(youtube[0], 'score'), false);

assert.equal(URLExtractor.cleanURL('javascript:alert(1)'), null);
assert.equal(URLExtractor.cleanURL('data:text/html,hello'), null);
assert.equal(URLExtractor.cleanURL('ftp://example.com/file'), null);

const hostile = 'https://example.com/x"><svg/onload=document.body.dataset.pwned=1>/z';
const normalized = URLExtractor.cleanURL(hostile);
assert.ok(normalized);
assert.equal(normalized.includes('<'), false);
assert.equal(normalized.includes('>'), false);
assert.equal(normalized.includes('"'), false);
assert.match(normalized, /%3Csvg/i);
"""
    result = _run_node(script)

    assert result.returncode == 0, result.stderr


def test_url_preview_uses_text_nodes_and_programmatic_radio_labels():
    script = r"""
const assert = require('node:assert/strict');
const {renderURLPreview} = require(process.argv[1]);

class FakeElement {
  constructor(tagName, ownerDocument) {
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.hidden = false;
    this.textContent = '';
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
}
class FakeDocument {
  createElement(tagName) { return new FakeElement(tagName, this); }
}

const fakeDocument = new FakeDocument();
const container = new FakeElement('div', fakeDocument);
const hostileText = 'https://example.com/x"><svg/onload=marker()>/z';
renderURLPreview(container, [{
  url: 'https://example.com/x%22%3E%3Csvg/onload=marker()%3E/z',
  display: hostileText,
  recommended: true,
}]);

function flatten(node) {
  return [node, ...node.children.flatMap(flatten)];
}
const nodes = flatten(container);
assert.deepEqual(
  [...new Set(nodes.map((node) => node.tagName))].sort(),
  ['DIV', 'INPUT', 'LABEL', 'SPAN'],
);
assert.equal(nodes.some((node) => node.tagName === 'SVG'), false);
assert.equal(nodes.some((node) => node.textContent === hostileText), true);

const input = nodes.find((node) => node.tagName === 'INPUT');
const label = nodes.find((node) => node.tagName === 'LABEL');
assert.equal(input.type, 'radio');
assert.equal(input.name, 'selected-url');
assert.equal(input.id, 'detected-url-0');
assert.equal(input.checked, true);
assert.equal(label.htmlFor, input.id);
assert.equal(nodes.some((node) => node.textContent === '推荐'), true);
assert.equal(nodes.some((node) => node.textContent.includes('评分')), false);
assert.equal(container.hidden, false);
"""
    result = _run_node(script)

    assert result.returncode == 0, result.stderr


def test_url_preview_source_has_no_user_controlled_inner_html_sink():
    source = APP_JS.read_text(encoding="utf-8")
    preview_start = source.index("function renderURLPreview(")
    preview_end = source.index("\nfunction bindURLSelection()", preview_start)
    preview_source = source[preview_start:preview_end]

    assert ".innerHTML" not in preview_source
    assert "textContent" in preview_source
    assert "replaceChildren" in preview_source
    assert "url-score" not in preview_source
