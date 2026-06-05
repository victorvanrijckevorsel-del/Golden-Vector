"""Shared model-state banner rendering for workspace screens."""

from __future__ import annotations

from html import escape

from golden_vector.app.model_state import summarize_model_state_manifest


def render_model_state_banner(payload: dict[str, object] | None) -> str:
    """Render a compact complete/incomplete model-build signal."""

    lines = summarize_model_state_manifest(payload)
    if payload is not None and str(payload.get("state") or "").lower() == "complete":
        return (
            "<div class=\"panel\">"
            "<h2>Model Build Complete</h2>"
            + "".join(f"<p>{escape(line)}</p>" for line in lines[1:])
            + "</div>"
        )
    return (
        "<div class=\"flash\">"
        "<p><strong>Model build state needs attention.</strong></p>"
        + "".join(f"<p>{escape(line)}</p>" for line in lines)
        + "</div>"
    )
