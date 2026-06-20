"""Tests for the shared serve URL builder (Claude↔Codex shared infra)."""

from __future__ import annotations

from golden_vector.serve.url_helpers import build_page_url


def test_build_page_url_sets_and_preserves_other_params():
    url = build_page_url(
        "/ticker/NEM",
        {"window": "12m", "lens": "gold"},
        set_params={"fundamentals_source": "yahoo"},
    )
    # Existing params preserved; new one added.
    assert url.startswith("/ticker/NEM?")
    assert "window=12m" in url
    assert "lens=gold" in url
    assert "fundamentals_source=yahoo" in url


def test_build_page_url_replaces_existing_key():
    url = build_page_url("/tool-a", {"window": "12m"}, set_params={"window": "3y"})
    assert url == "/tool-a?window=3y"


def test_build_page_url_none_deletes_key():
    url = build_page_url(
        "/finder",
        {"window": "6m", "show": "6m,3y"},
        set_params={"show": None},
    )
    assert "show=" not in url
    assert "window=6m" in url


def test_build_page_url_empty_returns_bare_path():
    assert build_page_url("/tool-b", {}, set_params={}) == "/tool-b"
    # Deleting the only param leaves a bare path (no trailing '?').
    assert build_page_url("/tool-b", {"x": "1"}, set_params={"x": None}) == "/tool-b"


def test_build_page_url_url_encodes_values():
    url = build_page_url("/finder", {}, set_params={"search": "a b&c"})
    # Space and ampersand must be percent-encoded so the query stays well-formed.
    assert "a+b%26c" in url
    assert "&c" not in url.split("?", 1)[1].replace("%26", "")


def test_build_page_url_preserves_order_of_current_then_new():
    url = build_page_url(
        "/p", {"a": "1", "b": "2"}, set_params={"c": "3"}
    )
    assert url == "/p?a=1&b=2&c=3"
