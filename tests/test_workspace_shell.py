"""Semantic shell, grouped navigation, drawer, and palette-contrast guardrails
(redesign plan sections 8, 9.2, 14, 18.2 items 2-3).

Node is REQUIRED for the runtime drawer test — per the Codex decision
(2026-08-10), required JavaScript coverage must not silently skip.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from golden_vector.serve.page_shell import _NAV_LINKS, _page_shell
from golden_vector.serve.workspace import create_workspace_app
from tests.helpers import build_test_paths, call_wsgi_app
from tests.test_workspace_app import _repo_app_config

EXPECTED_NAV = (
    ("candidate_finder", "/", "Candidate Finder"),
    ("tool_a", "/tool-a", "Gold Sensitivity"),
    ("tool_b", "/tool-b", "Corporate Finance"),
    ("tool_c", "/tool-c", "Gold Downside"),
    ("tool_d", "/tool-d", "Corporate Resilience"),
    ("option_trading", "/option-trading", "Option Trading"),
    ("portfolio", "/portfolio", "Portfolio"),
    ("lab", "/lab", "Lab"),
    ("scorecard", "/scorecard", "Scorecard"),
)


def _shell_app(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    return create_workspace_app(paths, app_config=_repo_app_config(), tool_b_tickers=["NEM"])


def test_nav_link_contract_is_preserved():
    """Nav ids, hrefs, and labels are a preserved contract (only grouping changed)."""
    assert _NAV_LINKS == EXPECTED_NAV


def test_shell_renders_landmarks_skip_link_and_grouped_nav():
    html = _page_shell("T", "<h1>Body</h1>", active_nav="tool_a")
    assert '<a class="skip-link" href="#main-content">Skip to main content</a>' in html
    assert '<aside class="app-sidebar" id="app-sidebar">' in html
    assert '<nav class="app-nav" id="app-nav" aria-label="Primary">' in html
    assert '<main id="main-content" tabindex="-1">' in html
    for group in ("Discover", "Analyse", "Manage", "Research"):
        assert f'<p class="nav-group-label">{group}</p>' in html
    assert '<span class="app-wordmark">Golden Vector</span>' in html
    assert '<span class="app-descriptor">Gold-equities research</span>' in html
    assert '<button class="nav-toggle" type="button" aria-expanded="false" aria-controls="app-nav">' in html
    assert 'data-page="tool_a"' in html
    for _nav_id, href, label in EXPECTED_NAV:
        assert f'href="{href}">{label}</a>' in html


def test_shell_marks_exactly_one_nav_entry_current():
    html = _page_shell("T", "x", active_nav="tool_b")
    assert html.count('aria-current="page"') == 1
    assert 'aria-current="page" href="/tool-b"' in html


def test_error_shell_renders_nav_with_no_current_item(tmp_path):
    """Documented intentional change (plan 15.11): error pages highlight nothing."""
    app = _shell_app(tmp_path)
    response = call_wsgi_app(app, method="GET", path="/combined")
    body = response["body"]
    assert response["status"].startswith("404")
    assert 'aria-current' not in body
    assert 'data-page="error"' in body
    # Navigation stays fully usable from error pages.
    for _nav_id, href, label in EXPECTED_NAV:
        assert f'href="{href}">{label}</a>' in body


def test_shell_asset_is_served_and_loaded(tmp_path):
    app = _shell_app(tmp_path)
    asset = call_wsgi_app(app, method="GET", path="/static/workspace-shell.js")
    assert asset["status"].startswith("200")
    assert "application/javascript" in asset["headers"].get("Content-Type", "")
    page = call_wsgi_app(app, method="GET", path="/scorecard")
    assert '<script src="/static/workspace-shell.js" defer></script>' in page["body"]


def test_all_first_party_js_passes_node_check():
    static_dir = Path("golden_vector/serve/static")
    scripts = sorted(static_dir.glob("*.js"))
    assert scripts, "no first-party scripts found"
    for script in scripts:
        result = subprocess.run(
            ["node", "--check", str(script)], check=False, capture_output=True, text=True
        )
        assert result.returncode == 0, f"{script.name}: {result.stderr}"


def test_drawer_runtime_open_close_focus_and_trap():
    script = r"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class El {
  constructor(name) {
    this.name = name;
    this.attrs = {};
    this.listeners = {};
    this.hidden = false;
    this._links = [];
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  hasAttribute(k) { return k in this.attrs; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(n, f) { this.listeners[n] = f; }
  focus() { doc.activeElement = this; }
  querySelector(sel) { return sel === "a" ? (this._links[0] || null) : null; }
  querySelectorAll(sel) { return sel === "a" ? this._links : []; }
}

const toggle = new El("button");
const frame = new El("div");
const sidebar = new El("aside");
const backdrop = new El("div");
backdrop.hidden = true;
const link1 = new El("a");
const link2 = new El("a");
link1.closest = (s) => (s === "a" ? link1 : null);
link2.closest = (s) => (s === "a" ? link2 : null);
sidebar._links = [link1, link2];

var doc = {
  readyState: "complete",
  activeElement: null,
  listeners: {},
  querySelector(sel) {
    return { ".nav-toggle": toggle, ".app-frame": frame, ".nav-backdrop": backdrop }[sel] || null;
  },
  getElementById(id) { return id === "app-sidebar" ? sidebar : null; },
  addEventListener(n, f) { this.listeners[n] = f; },
};

vm.runInNewContext(
  fs.readFileSync("golden_vector/serve/static/workspace-shell.js", "utf8"),
  { document: doc, window: {}, console }
);

// Open: state, aria, backdrop, focus moves into the menu.
toggle.listeners.click();
assert.ok(frame.hasAttribute("data-nav-open"));
assert.equal(toggle.attrs["aria-expanded"], "true");
assert.equal(backdrop.hidden, false);
assert.equal(doc.activeElement, link1);

// Escape closes and returns focus to the trigger.
doc.listeners.keydown({ key: "Escape" });
assert.ok(!frame.hasAttribute("data-nav-open"));
assert.equal(toggle.attrs["aria-expanded"], "false");
assert.equal(backdrop.hidden, true);
assert.equal(doc.activeElement, toggle);

// Backdrop click closes.
toggle.listeners.click();
backdrop.listeners.click();
assert.ok(!frame.hasAttribute("data-nav-open"));

// Navigating via a link closes WITHOUT stealing focus back to the trigger.
toggle.listeners.click();
doc.activeElement = link1;
sidebar.listeners.click({ target: link1 });
assert.ok(!frame.hasAttribute("data-nav-open"));
assert.equal(doc.activeElement, link1);

// Tab wraps from the last link to the first while open (focus trap).
toggle.listeners.click();
doc.activeElement = link2;
let prevented = false;
sidebar.listeners.keydown({ key: "Tab", shiftKey: false, preventDefault() { prevented = true; } });
assert.ok(prevented);
assert.equal(doc.activeElement, link1);
"""
    result = subprocess.run(
        ["node", "-e", script], check=False, cwd=Path.cwd(), text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------- contrast

_TOKEN_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")


def _resolved_tokens() -> dict[str, str]:
    text = Path("golden_vector/serve/static/css/tokens.css").read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    raw = {name: value.strip() for name, value in _TOKEN_RE.findall(text)}

    def resolve(value: str, depth: int = 0) -> str:
        match = re.fullmatch(r"var\((--[\w-]+)\)", value.strip())
        if match and depth < 10:
            return resolve(raw[match.group(1)], depth + 1)
        return value.strip()

    return {name: resolve(value) for name, value in raw.items()}


def _luminance(hex_value: str) -> float:
    value = hex_value.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))

    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _ratio(fg: str, bg: str) -> float:
    l1, l2 = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def test_dark_palette_meets_wcag_contrast():
    """Plan 9.2: token contrast is verified, not guessed. AA normal text = 4.5:1."""
    tokens = _resolved_tokens()
    pairs = [
        # (foreground, background, minimum)
        ("--color-text-primary", "--color-surface-1", 4.5),
        ("--color-text-primary", "--color-surface-2", 4.5),
        ("--color-text-secondary", "--color-surface-1", 4.5),
        ("--color-text-muted", "--color-surface-1", 4.5),
        ("--color-text-secondary", "--color-shell", 4.5),
        ("--color-brand-ink", "--color-brand-gold", 4.5),
        ("--color-brand-gold", "--color-shell", 4.5),
        ("--color-brand-gold", "--accent-soft", 4.5),
        ("--link", "--color-surface-1", 4.5),
        ("--color-warning", "--color-surface-1", 4.5),
        ("--color-positive", "--color-surface-1", 4.5),
        ("--color-negative", "--color-surface-1", 4.5),
        ("--color-verified", "--color-surface-1", 4.5),
        ("--color-text-primary", "--selected-bg", 4.5),
        ("--tint-green-ink", "--tint-green", 4.5),
        ("--tint-amber-ink", "--tint-amber", 4.5),
        ("--tint-red-ink", "--tint-red", 4.5),
        ("--tint-gray-ink", "--tint-gray", 4.5),
        ("--verdict-supported-ink", "--verdict-supported-bg", 4.5),
        ("--verdict-not-supported-ink", "--verdict-not-supported-bg", 4.5),
        ("--verdict-partial-ink", "--verdict-partial-bg", 4.5),
        ("--verdict-accruing-ink", "--verdict-accruing-bg", 4.5),
        # Focus ring against both shell and surface (non-text: 3.0).
        ("--color-focus", "--color-surface-1", 3.0),
        ("--color-focus", "--color-shell", 3.0),
    ]
    failures = []
    for fg, bg, minimum in pairs:
        ratio = _ratio(tokens[fg], tokens[bg])
        if ratio < minimum:
            failures.append(f"{fg} on {bg}: {ratio:.2f} < {minimum}")
    assert not failures, "Contrast failures: " + "; ".join(failures)
