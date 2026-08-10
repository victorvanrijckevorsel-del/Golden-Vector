"""Design-token consistency guardrails (redesign plan sections 18.2.5-18.2.6, 20).

Locks the Phase 1 invariants:
- css/tokens.css is the ONLY first-party file with raw colour literals;
- every var(--x) reference resolves to a defined token (the --border/--paper
  class of silent debt can never return);
- workspace.css stays a pure ordered @import manifest;
- Python and first-party JavaScript renderers emit no raw colours;
- z-index values come from the documented token scale.

Intentional exceptions live in ALLOWED_* maps here — one documented place,
per plan section 20 — not scattered through the code.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC_DIR = Path("golden_vector/serve/static")
CSS_DIR = STATIC_DIR / "css"
SERVE_DIR = Path("golden_vector/serve")

# (?<!&) keeps HTML numeric entities like &#9632; from matching as hex colours.
COLOR_LITERAL = re.compile(r"(?<!&)#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")

# file name -> set of exact literals allowed there, with the reason documented.
ALLOWED_PY_COLOR_LITERALS: dict[str, set[str]] = {}
ALLOWED_JS_COLOR_LITERALS: dict[str, set[str]] = {}

EXPECTED_IMPORT_ORDER = (
    "css/tokens.css",
    "css/base.css",
    "css/shell.css",
    "css/components.css",
    "css/forms.css",
    "css/tables.css",
    "css/charts.css",
    "css/pages.css",
    "css/responsive.css",
)


def _strip_css_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _first_party_css_files() -> list[Path]:
    return sorted(CSS_DIR.glob("*.css"))


def test_workspace_css_is_a_pure_import_manifest():
    body = _strip_css_comments((STATIC_DIR / "workspace.css").read_text(encoding="utf-8"))
    statements = [line.strip() for line in body.splitlines() if line.strip()]
    assert statements, "workspace.css manifest is empty"
    for statement in statements:
        assert re.fullmatch(r'@import url\("css/[a-z-]+\.css"\);', statement), (
            "workspace.css may only contain @import statements, found: " + statement
        )


def test_import_manifest_covers_every_module_in_order():
    body = (STATIC_DIR / "workspace.css").read_text(encoding="utf-8")
    imports = re.findall(r'@import url\("([^"]+)"\);', body)
    assert tuple(imports) == EXPECTED_IMPORT_ORDER
    on_disk = {f"css/{path.name}" for path in _first_party_css_files()}
    assert on_disk == set(EXPECTED_IMPORT_ORDER), (
        "css/ modules and the manifest disagree: " + repr(on_disk ^ set(EXPECTED_IMPORT_ORDER))
    )


def test_every_css_custom_property_resolves():
    tokens = set(
        re.findall(r"(--[\w-]+)\s*:", _strip_css_comments((CSS_DIR / "tokens.css").read_text(encoding="utf-8")))
    )
    assert tokens, "tokens.css defines no custom properties"
    unresolved: list[str] = []
    for path in _first_party_css_files():
        body = _strip_css_comments(path.read_text(encoding="utf-8"))
        for used in re.findall(r"var\(\s*(--[\w-]+)", body):
            if used not in tokens:
                unresolved.append(f"{path.name}: var({used})")
    assert not unresolved, "Undefined custom properties (the --border/--paper bug class): " + ", ".join(unresolved)


def test_raw_colours_live_only_in_tokens_css():
    offenders: list[str] = []
    for path in _first_party_css_files():
        if path.name == "tokens.css":
            continue
        body = _strip_css_comments(path.read_text(encoding="utf-8"))
        for lineno, line in enumerate(body.splitlines(), start=1):
            if COLOR_LITERAL.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()[:80]}")
    manifest = _strip_css_comments((STATIC_DIR / "workspace.css").read_text(encoding="utf-8"))
    if COLOR_LITERAL.search(manifest):
        offenders.append("workspace.css: manifest must not contain colours")
    assert not offenders, "Raw colours outside css/tokens.css: " + "; ".join(offenders)


def test_python_renderers_emit_no_raw_colours():
    offenders: list[str] = []
    for module in sorted(SERVE_DIR.rglob("*.py")):
        source = module.read_text(encoding="utf-8")
        allowed = ALLOWED_PY_COLOR_LITERALS.get(module.name, set())
        for lineno, line in enumerate(source.splitlines(), start=1):
            match = COLOR_LITERAL.search(line)
            if match and match.group(0) not in allowed:
                offenders.append(f"{module.name}:{lineno}: {line.strip()[:80]}")
    assert not offenders, "Raw colours in serve Python (use semantic classes/tokens): " + "; ".join(offenders)


def test_first_party_js_emits_no_raw_colours():
    offenders: list[str] = []
    for script in sorted(STATIC_DIR.glob("*.js")):
        source = script.read_text(encoding="utf-8")
        allowed = ALLOWED_JS_COLOR_LITERALS.get(script.name, set())
        for lineno, line in enumerate(source.splitlines(), start=1):
            match = COLOR_LITERAL.search(line)
            if match and match.group(0) not in allowed:
                offenders.append(f"{script.name}:{lineno}: {line.strip()[:80]}")
    assert not offenders, "Raw colours in first-party JS: " + "; ".join(offenders)


def test_z_index_values_use_the_token_scale():
    offenders: list[str] = []
    for path in _first_party_css_files():
        if path.name == "tokens.css":
            continue
        body = _strip_css_comments(path.read_text(encoding="utf-8"))
        for lineno, line in enumerate(body.splitlines(), start=1):
            if re.search(r"z-index\s*:", line) and "var(" not in line:
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, "z-index outside the token scale: " + "; ".join(offenders)


def test_horizontal_scroll_is_owned_by_table_region_only():
    """GV-RD-P34-1: anonymous scroll containers are an accessibility defect —
    every declaration that enables horizontal scrolling must live in a rule
    whose EVERY comma-separated selector arm is/contains .table-region (the
    labelled, keyboard-focusable wrapper). Covers the `overflow` shorthand as
    well as `overflow-x`, so `overflow: auto` cannot slip through
    (GV-RD-FINAL-009)."""
    offenders: list[str] = []
    for path in _first_party_css_files():
        text = _strip_css_comments(path.read_text(encoding="utf-8"))
        for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", text):
            enables_scroll = bool(re.search(r"overflow-x\s*:\s*(auto|scroll)\b", body))
            for shorthand in re.findall(r"(?<![-\w])overflow\s*:([^;}]*)", body):
                if re.search(r"\b(auto|scroll)\b", shorthand):
                    enables_scroll = True
            if not enables_scroll:
                continue
            arms = [arm.strip() for arm in selector.split(",") if arm.strip()]
            for arm in arms:
                if ".table-region" not in arm:
                    offenders.append(f"{path.name}: {arm[:60]}")
    assert not offenders, "anonymous horizontal scroll containers: " + "; ".join(offenders)


def test_sticky_offsets_and_anchor_scroll_padding_come_from_tokens():
    """GV-RD-FINAL-003: the sticky app-header height, the sticky section-nav
    offset and the anchor landing offset are one set of tokens — no hardcoded
    twin may restate a header height, and anchors must clear both sticky bars."""
    bodies = {
        path.name: _strip_css_comments(path.read_text(encoding="utf-8"))
        for path in _first_party_css_files()
    }
    tokens_body = bodies["tokens.css"]
    header_tokens = {
        name: value.strip()
        for name, value in re.findall(
            r"(--app-header-height[\w-]*)\s*:\s*([^;]+);", tokens_body
        )
    }
    assert header_tokens, "no --app-header-height* token is defined"

    # scroll-padding-top must exist, and every occurrence must be token-driven.
    padding_decls = [
        (name, decl)
        for name, body in bodies.items()
        for decl in re.findall(r"scroll-padding-top\s*:([^;}]*)", body)
    ]
    assert padding_decls, "no scroll-padding-top: anchors land behind the sticky bars"
    assert all("var(--" in decl for _, decl in padding_decls), padding_decls

    # .section-nav top offsets are token references, never literals.
    nav_tops = [
        decl
        for body in bodies.values()
        for selector, rule in re.findall(r"([^{}]+)\{([^}]*)\}", body)
        if ".section-nav" in selector and "-link" not in selector
        for decl in re.findall(r"(?<![-\w])top\s*:([^;}]*)", rule)
    ]
    assert nav_tops, ".section-nav declares no sticky top offset"
    assert all("var(--" in decl for decl in nav_tops), nav_tops

    # Each header-height value appears once only: in its token definition.
    for token, value in header_tokens.items():
        # (?<![\d.]) so 0.74rem is not read as a twin of 4rem.
        value_re = re.compile(r"(?<![\d.])" + re.escape(value))
        twins = [
            f"{name}:{lineno}"
            for name, body in bodies.items()
            for lineno, line in enumerate(body.splitlines(), start=1)
            if value_re.search(line) and f"{token}:" not in line.replace(" ", "")
        ]
        assert not twins, f"hardcoded twin of {token} ({value}) at: {twins}"


# Class selectors with no literal emitter in first-party Python/JS. Each is
# either composed at runtime from data, generated by DataTables, or offered by a
# component contract ahead of its first call site -- NOT dead CSS.
ALLOWED_DYNAMIC_SELECTORS = {
    # DataTables generates its own control/sort markup at runtime.
    "dt-info", "dt-length", "dt-paging", "dt-search",
    "dt-orderable-asc", "dt-orderable-desc",
    # Correlation buckets composed as f"corr-{bucket}" in the serve layer.
    "corr-very-high", "corr-high", "corr-medium", "corr-low", "corr-unavailable",
    # Chart legend swatches composed as f"legend-swatch-{series_key}" (charts.py).
    "legend-swatch-gold", "legend-swatch-stock", "legend-swatch-context",
    "legend-swatch-gdx", "legend-swatch-gdxj", "legend-swatch-positive",
    "legend-swatch-negative", "legend-swatch-overlay-stock",
    "legend-swatch-overlay-gdx", "legend-swatch-overlay-gdxj",
    # Chart series classes composed from the same data-driven series keys.
    "series-gold", "series-stock", "series-gdx", "series-gdxj", "series-atm",
    "series-ivrv", "series-skew", "series-vol", "series-overlay-stock",
    "series-overlay-gdx", "series-overlay-gdxj",
    # Note status badges composed as f"note-{status.lower()}" (detail_forms.py).
    "note-open", "note-done", "note-watch",
    # notice() tone variants: composed at runtime as f"notice-{tone}" in
    # ui/status.py, so the literal class names never appear in source.
    "notice-success", "notice-info", "notice-danger", "notice-degraded",
    "notice-neutral",
}


def test_no_dead_first_party_selectors():
    """One direction only: every simple class selector in first-party CSS must
    appear as a whole token in the serve layer (Python or first-party JS) or be
    a documented dynamic source. Dead CSS is silent debt: it outlives its markup
    and misleads the next edit.

    This does NOT scan emitted markup for classes with no CSS owner — that
    opposite drift (GV-RD-FINAL-008) is not covered here. The match is
    word-boundary anchored so a longer unrelated token cannot count as an
    emitter; a mention in a comment or docstring still can."""
    selectors: set[str] = set()
    for path in _first_party_css_files():
        body = _strip_css_comments(path.read_text(encoding="utf-8"))
        for selector, _ in re.findall(r"([^{}]+)\{([^}]*)\}", body):
            if selector.strip().startswith("@"):
                continue
            selectors.update(re.findall(r"\.([A-Za-z][A-Za-z0-9_-]*)", selector))
    assert selectors, "no class selectors found in first-party CSS"
    haystack = "".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in sorted(Path("golden_vector/serve").rglob("*.py"))
        + sorted(STATIC_DIR.glob("*.js"))
    )
    emitted = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]*", haystack))
    dead = sorted(
        name
        for name in selectors
        if name not in emitted and name not in ALLOWED_DYNAMIC_SELECTORS
    )
    assert not dead, "CSS selectors with no emitter or documented dynamic source: " + ", ".join(dead)
