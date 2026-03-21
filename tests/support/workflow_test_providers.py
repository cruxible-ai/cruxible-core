"""Provider callables used by workflow tests."""

from __future__ import annotations

from typing import Any

from cruxible_core.provider.types import ProviderContext


def lift_predictor(input_payload: dict[str, Any], context: ProviderContext) -> dict[str, Any]:
    """Return a deterministic forecast payload."""
    base = 0.10 if context.deterministic else 0.08
    return {
        "predicted_lift_pct": round(base + 0.01 * len(input_payload.get("sku", "")), 4),
        "confidence_lower": 0.05,
        "confidence_upper": 0.25,
        "model_version": context.provider_version,
    }


def margin_calculator(input_payload: dict[str, Any], context: ProviderContext) -> dict[str, Any]:
    """Convert lift into a simple expected margin result."""
    lift = float(input_payload["predicted_lift_pct"])
    return {
        "expected_margin_pct": round(lift / 2, 4),
        "decision": "approve" if lift >= 0.10 else "review",
        "calculator_version": context.provider_version,
    }


def campaign_recommendations(
    input_payload: dict[str, Any], _context: ProviderContext
) -> dict[str, Any]:
    """Return a deterministic relationship-group proposal payload."""
    region = input_payload["region"]
    members = [
        {
            "from_type": "Campaign",
            "from_id": input_payload["campaign_id"],
            "to_type": "Product",
            "to_id": "SKU-123",
            "signals": [{"integration": "catalog", "signal": "support", "evidence": region}],
            "properties": {"reason": f"{region} bestseller"},
        },
        {
            "from_type": "Campaign",
            "from_id": input_payload["campaign_id"],
            "to_type": "Product",
            "to_id": "SKU-456",
            "signals": [{"integration": "catalog", "signal": "support", "evidence": region}],
            "properties": {"reason": f"{region} fallback"},
        },
    ]
    return {
        "members": members,
        "thesis_text": "Recommend products for regional campaign",
        "thesis_facts": {"campaign_id": input_payload["campaign_id"], "region": region},
        "analysis_state": {"source": "campaign_recommendations"},
        "integrations_used": ["catalog"],
        "suggested_priority": "high",
    }


def broken_provider(_input_payload: dict[str, Any], _context: ProviderContext) -> dict[str, Any]:
    """Return an invalid output shape for contract failure tests."""
    return {"unexpected": "value"}
