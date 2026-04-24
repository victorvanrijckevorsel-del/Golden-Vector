"""Screening-parameter overrides from the workspace Tool B view.

Emanuel (the user) can change gold price, screening thresholds, and
jurisdiction discounts from the Tool B view via URL query parameters.
When any overrides are present, the workspace calls
`compute_tool_b_in_memory` with an overridden AppConfig so the rendered
table reflects the scenario without ever touching YAML or parquet.

This module holds the URL-parsing + config-override logic in one place so
the WSGI routing layer stays thin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from golden_vector.contracts.config_models import (
    AppConfig,
    JurisdictionDiscounts,
    Layer1Thresholds,
    ScreeningParamsConfig,
    VerdictThresholds,
)


# URL param name -> field spec. Each spec knows how to coerce the raw
# string value and what target field to write into an override dict.
_FIELD_SPECS: dict[str, tuple[str, str, str]] = {
    # param, kind, unit
    "gold_price": ("gold_price_assumption", "float", "absolute"),
    "pe_target": ("strong_candidate_forward_pe_max", "float", "absolute"),
    "fcf_yield_target": ("fcf_yield_min", "float", "percent"),
    "aisc_target": ("aisc_max", "float", "absolute"),
    "margin_target": ("margin_min", "float", "percent"),
    "reserve_life_target": ("reserve_life_min", "float", "absolute"),
    "leverage_target": ("leverage_max", "float", "absolute"),
    "tier1_discount": ("tier_1", "float", "percent"),
    "tier2_discount": ("tier_2", "float", "percent"),
    "tier3_discount": ("tier_3", "float", "percent"),
}


@dataclass(frozen=True)
class ScreeningOverrides:
    """Structured view of the query-string overrides active on a request."""

    gold_price: float | None = None
    layer1: dict[str, float] = field(default_factory=dict)
    verdict: dict[str, float] = field(default_factory=dict)
    jurisdiction: dict[str, float] = field(default_factory=dict)

    def has_any(self) -> bool:
        return (
            self.gold_price is not None
            or bool(self.layer1)
            or bool(self.verdict)
            or bool(self.jurisdiction)
        )


class ScreeningOverrideError(ValueError):
    """Raised when a URL param fails validation."""


def parse_query_overrides(query: Mapping[str, list[str]]) -> ScreeningOverrides:
    """Parse URL query params into a ScreeningOverrides.

    Expects a mapping of param-name -> list-of-values (as produced by
    `urllib.parse.parse_qs`). Missing/blank values are ignored. Invalid
    values raise `ScreeningOverrideError` with a user-friendly message.
    """
    gold_price: float | None = None
    layer1: dict[str, float] = {}
    verdict: dict[str, float] = {}
    jurisdiction: dict[str, float] = {}

    for param_name, (target_field, _kind, unit) in _FIELD_SPECS.items():
        raw = query.get(param_name, [""])[0]
        raw = str(raw or "").strip()
        if not raw:
            continue
        try:
            numeric = float(raw)
        except ValueError as exc:
            raise ScreeningOverrideError(
                f"{param_name} must be a number (got {raw!r})"
            ) from exc
        if numeric < 0:
            raise ScreeningOverrideError(
                f"{param_name} must be non-negative (got {numeric})"
            )

        # Percent-style inputs: if the user typed "15" we interpret as 15%
        # and store as 0.15. If they typed "0.15" we honor that directly.
        # This matches how the YAML stores percent-valued thresholds.
        if unit == "percent":
            value = _percent_to_fraction(numeric, param_name)
        else:
            value = numeric

        if param_name == "gold_price":
            if value <= 0:
                raise ScreeningOverrideError("gold_price must be positive")
            gold_price = value
        elif target_field in {"aisc_max", "margin_min", "fcf_yield_min", "reserve_life_min", "leverage_max"}:
            if value <= 0:
                raise ScreeningOverrideError(f"{param_name} must be positive")
            layer1[target_field] = value
        elif target_field == "strong_candidate_forward_pe_max":
            if value <= 0:
                raise ScreeningOverrideError(f"{param_name} must be positive")
            verdict[target_field] = value
        elif target_field in {"tier_1", "tier_2", "tier_3"}:
            # Discount >= 100% collapses target P/E multiples to zero
            # (peer_pe * (1 - 1.0) = 0), which produces meaningless
            # zero/negative target prices across the board. Reject.
            #
            # Error message is explicit about the interpretation because
            # `1.0` (typed as a fraction) and `100` (typed as percent)
            # both land at `value = 1.0` after _percent_to_fraction. The
            # user needs to see what their input was coerced to.
            if value >= 1.0:
                raise ScreeningOverrideError(
                    f"{param_name} must be below 100% "
                    f"(got {numeric}, interpreted as {value * 100:.0f}%)"
                )
            jurisdiction[target_field] = value

    return ScreeningOverrides(
        gold_price=gold_price,
        layer1=layer1,
        verdict=verdict,
        jurisdiction=jurisdiction,
    )


def apply_overrides(app_config: AppConfig, overrides: ScreeningOverrides) -> AppConfig:
    """Return a new AppConfig with screening_params overlaid.

    The original config is unchanged (AppConfig is pydantic-immutable).
    Only the fields the overrides touch change; everything else passes
    through.
    """
    if not overrides.has_any():
        return app_config

    current_params = app_config.screening_params

    new_layer1 = _merge_model(
        current_params.layer1_thresholds,
        Layer1Thresholds,
        overrides.layer1,
    )
    new_verdict = _merge_model(
        current_params.verdict_thresholds,
        VerdictThresholds,
        overrides.verdict,
    )
    new_jurisdiction = _merge_model(
        current_params.jurisdiction_discounts,
        JurisdictionDiscounts,
        overrides.jurisdiction,
    )

    new_params = current_params.model_copy(
        update={
            "layer1_thresholds": new_layer1,
            "verdict_thresholds": new_verdict,
            "jurisdiction_discounts": new_jurisdiction,
        }
    )
    return app_config.model_copy(update={"screening_params": new_params})


def _merge_model(current, model_cls, override_fields: dict[str, float]):
    if not override_fields:
        return current
    return current.model_copy(update=override_fields)


def _percent_to_fraction(value: float, param_name: str) -> float:
    """Map user-typed percent inputs to internal fractions.

    Heuristic: values > 1 are treated as typed percents (e.g. "15" -> 0.15);
    values in [0, 1] are treated as already-fractional (e.g. "0.15" -> 0.15).
    Discount/threshold values in our domain are all < 1 as fractions and
    typically 0-100 as percents, so this disambiguation is safe.
    """
    if value > 1.0:
        return value / 100.0
    return value
