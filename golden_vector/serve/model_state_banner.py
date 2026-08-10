"""Shared model-state banner rendering for workspace screens."""

from __future__ import annotations

from html import escape

from golden_vector.app.model_state import (
    summarize_model_state_manifest,
    summarize_option_freshness,
)
from golden_vector.serve.ui.status import notice


def render_option_freshness_box(
    payload: dict[str, object] | None,
    *,
    only_when_stale: bool = False,
) -> str:
    """Render the option-data freshness box from the model-state manifest.

    The backend (manifest freshness domain) owns the status and the message;
    this renderer never computes market hours or freshness itself. One renderer
    serves the Option Trading overview, the ticker option lens, and Candidate
    Finder so the wording can never diverge.
    """

    freshness = summarize_option_freshness(payload)
    if freshness is None:
        return ""
    status = str(freshness["status"])
    if only_when_stale and status == "OK":
        return ""
    message = str(freshness.get("message") or "")
    if status == "OK":
        return (
            "<p class=\"hint option-freshness option-freshness-ok\">"
            f"{escape(message)}</p>"
        )
    if status == "CARRIED_FORWARD":
        label = "Stored option snapshot"
    elif status == "MISALIGNED":
        label = "Option data misaligned"
    else:
        label = "Option data unavailable"
    return notice(
        "warning",
        f"<p><strong>{escape(label)}.</strong> {escape(message)}</p>",
        extra_classes="option-freshness option-freshness-stale",
    )


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
    return notice(
        "danger",
        "<p><strong>Model build state needs attention.</strong></p>"
        + "".join(f"<p>{escape(line)}</p>" for line in lines),
    )
