"""Shared model-state banner rendering for workspace screens."""

from __future__ import annotations

from html import escape

from golden_vector.app.model_state import summarize_model_state_manifest


def render_model_state_banner(payload: dict[str, object] | None) -> str:
    """Render a model-build banner ONLY when the build needs attention.

    When the build is complete there is nothing for the user to act on, so we
    render nothing — the big "Model Build Complete" panel was pure provenance
    clutter at the top of every page, and the per-page cards already carry the
    refresh/freshness detail. We still surface a loud warning when the model
    state is degraded so a broken build can't pass silently.
    """

    if payload is not None and str(payload.get("state") or "").lower() == "complete":
        return ""
    lines = summarize_model_state_manifest(payload)
    return (
        "<div class=\"flash\">"
        "<p><strong>Model build state needs attention.</strong></p>"
        + "".join(f"<p>{escape(line)}</p>" for line in lines)
        + "</div>"
    )
