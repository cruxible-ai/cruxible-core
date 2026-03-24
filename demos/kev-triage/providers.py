"""Deterministic provider helpers used by bundled demo configs."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from cruxible_core.provider.types import ProviderContext


def load_public_kev_rows(
    _input_payload: dict[str, Any], context: ProviderContext,
) -> dict[str, Any]:
    """Load and normalize public KEV reference rows from a hashed data bundle."""
    if context.artifact is None or context.artifact.local_path is None:
        raise ValueError("load_public_kev_rows requires a local artifact bundle")
    bundle_root = Path(context.artifact.local_path)
    kev_rows = _load_csv_rows(bundle_root / "known_exploited_vulnerabilities.csv")
    enriched_by_cve = {
        row.get("CVE", "").strip(): row
        for row in _load_csv_rows(bundle_root / "epss_kev_nvd.csv")
        if row.get("CVE", "").strip()
    }

    items: list[dict[str, Any]] = []
    for kev_row in kev_rows:
        cve_id = kev_row.get("cveID", "").strip()
        if not cve_id:
            continue
        enriched = enriched_by_cve.get(cve_id, {})
        vendor_name = _first_non_empty(kev_row.get("vendorProject"), enriched.get("Vendor"))
        product_name = _first_non_empty(kev_row.get("product"), enriched.get("Product"))
        vendor_id = _slugify(vendor_name or "unknown-vendor")
        product_id = _slugify(f"{vendor_id}__{product_name or 'unknown-product'}")
        items.append(
            {
                "vendor_id": vendor_id,
                "vendor_name": vendor_name or "Unknown Vendor",
                "product_id": product_id,
                "product_name": product_name or "Unknown Product",
                "cve_id": cve_id,
                "description": _first_non_empty(
                    kev_row.get("shortDescription"),
                    enriched.get("Description"),
                ),
                "cvss_score": _parse_float(enriched.get("CVSS3")),
                "epss_score": _parse_float(enriched.get("EPSS")),
                "kev_due_date": _first_non_empty(kev_row.get("dueDate")),
                "known_ransomware_use": _first_non_empty(
                    kev_row.get("knownRansomwareCampaignUse")
                ),
                "published_at": None,
                "affected_version_range": None,
                "fixed_version": None,
                "cpe": None,
                "product_family": None,
            }
        )
    return {"items": items}


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _parse_float(value: Any) -> float | None:
    text = _first_non_empty(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "unknown"
