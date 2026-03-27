"""Deterministic provider helpers used by bundled demo configs."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from cruxible_core.provider.types import ProviderContext


def load_public_kev_rows(
    _input_payload: dict[str, Any], context: ProviderContext,
) -> dict[str, Any]:
    """Load and normalize public KEV reference rows from a hashed data bundle.

    Reads KEV CSV, EPSS/NVD CSV, and NVD CPE JSON. Joins on CVE ID,
    extracts CPE-based product identity and version ranges, and emits
    one row per (CVE, CPE product) pair.
    """
    if context.artifact is None or context.artifact.local_path is None:
        raise ValueError("load_public_kev_rows requires a local artifact bundle")
    bundle_root = Path(context.artifact.local_path)

    # Load sources
    kev_rows = _load_csv_rows(
        bundle_root / "known_exploited_vulnerabilities.csv",
    )
    enriched_by_cve = {
        row.get("CVE", "").strip(): row
        for row in _load_csv_rows(bundle_root / "epss_kev_nvd.csv")
        if row.get("CVE", "").strip()
    }
    nvd_cpe_by_cve = _load_nvd_cpe_data(
        bundle_root / "nvd_kev_cves.json",
    )

    items: list[dict[str, Any]] = []
    for kev_row in kev_rows:
        cve_id = kev_row.get("cveID", "").strip()
        if not cve_id:
            continue
        enriched = enriched_by_cve.get(cve_id, {})
        cpe_products = nvd_cpe_by_cve.get(cve_id, [])

        # Base vulnerability fields shared across all product rows
        vuln_base = {
            "cve_id": cve_id,
            "description": _first_non_empty(
                kev_row.get("shortDescription"),
                enriched.get("Description"),
            ),
            "cvss_score": _parse_float(enriched.get("CVSS3")),
            "epss_score": _parse_float(enriched.get("EPSS")),
            "kev_due_date": _first_non_empty(kev_row.get("dueDate")),
            "known_ransomware_use": _first_non_empty(
                kev_row.get("knownRansomwareCampaignUse"),
            ),
        }

        if cpe_products:
            # Emit one row per (CVE, CPE product) pair
            for product in cpe_products:
                items.append({
                    **vuln_base,
                    **product,
                })
        else:
            # Fallback: no CPE data, use KEV/EPSS names
            vendor_name = _first_non_empty(
                kev_row.get("vendorProject"), enriched.get("Vendor"),
            )
            product_name = _first_non_empty(
                kev_row.get("product"), enriched.get("Product"),
            )
            vendor_id = _slugify(vendor_name or "unknown-vendor")
            items.append({
                **vuln_base,
                "vendor_id": vendor_id,
                "vendor_name": vendor_name or "Unknown Vendor",
                "product_id": _slugify(
                    f"{vendor_id}__{product_name or 'unknown-product'}",
                ),
                "product_name": product_name or "Unknown Product",
                "cpe_vendor": None,
                "cpe_product": None,
                "cpe_part": None,
                "affected_versions": [],
                "fixed_version": None,
            })

    return {"items": items}


# ---------------------------------------------------------------------------
# NVD CPE parsing
# ---------------------------------------------------------------------------


def _load_nvd_cpe_data(
    path: Path,
) -> dict[str, list[dict[str, Any]]]:
    """Parse NVD CVE JSON and extract CPE product + version data.

    Returns a dict keyed by CVE ID, where each value is a list of
    product dicts (one per distinct CPE product affected by the CVE).
    Each product dict contains identity fields and an aggregated
    affected_versions list.
    """
    if not path.exists():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, list[dict[str, Any]]] = {}

    for entry in raw:
        cve = entry.get("cve", {})
        cve_id = cve.get("id", "")
        if not cve_id:
            continue

        # Collect version ranges grouped by (cpe_vendor, cpe_product)
        product_versions: dict[
            tuple[str, str, str], list[dict[str, Any]]
        ] = defaultdict(list)

        for config in cve.get("configurations", []):
            for node in config.get("nodes", []):
                for match in node.get("cpeMatch", []):
                    if not match.get("vulnerable", False):
                        continue
                    parsed = _parse_cpe_criteria(match.get("criteria", ""))
                    if parsed is None:
                        continue
                    cpe_part, cpe_vendor, cpe_product = parsed
                    version_range = _extract_version_range(match)
                    key = (cpe_part, cpe_vendor, cpe_product)
                    # Always register the product key so CPE identity is
                    # preserved even when all version ranges are filtered.
                    if key not in product_versions:
                        product_versions[key] = []
                    if version_range is not None:
                        product_versions[key].append(version_range)

        if not product_versions:
            continue

        products: list[dict[str, Any]] = []
        for (cpe_part, cpe_vendor, cpe_product), versions in (
            product_versions.items()
        ):
            # Derive stable IDs from CPE strings
            vendor_id = _slugify(cpe_vendor)
            product_id = _slugify(f"{cpe_vendor}__{cpe_product}")

            # Determine a summary fixed_version from the version ranges
            fixed = _pick_latest_fixed_version(versions)

            products.append({
                "vendor_id": vendor_id,
                "vendor_name": _humanize(cpe_vendor),
                "product_id": product_id,
                "product_name": _humanize(cpe_product),
                "cpe_vendor": cpe_vendor,
                "cpe_product": cpe_product,
                "cpe_part": cpe_part,
                "affected_versions": versions,
                "fixed_version": fixed,
            })

        result[cve_id] = products

    return result


def _parse_cpe_criteria(criteria: str) -> tuple[str, str, str] | None:
    """Extract (part, vendor, product) from a CPE 2.3 URI string."""
    # cpe:2.3:a:craftcms:craft_cms:*:*:*:*:*:*:*:*
    parts = criteria.split(":")
    if len(parts) < 5 or parts[0] != "cpe" or parts[1] != "2.3":
        return None
    return parts[2], parts[3], parts[4]


def _extract_specific_version(criteria: str) -> str | None:
    """Extract a specific version from a CPE 2.3 URI when present.

    The version field is the 6th colon-separated component (index 5).
    Returns None if the version is a wildcard (*) or missing.
    """
    parts = criteria.split(":")
    if len(parts) < 6:
        return None
    version = parts[5]
    if version in ("*", "-", ""):
        return None
    return version


def _extract_version_range(match: dict[str, Any]) -> dict[str, Any] | None:
    """Build a version range dict from a CPE match entry.

    Returns None when the match has no version bounds and no specific
    version — these are "all versions" matches that carry no useful
    range information.
    """
    version_range: dict[str, Any] = {}
    for field in (
        "versionStartIncluding",
        "versionStartExcluding",
        "versionEndIncluding",
        "versionEndExcluding",
    ):
        value = match.get(field)
        if value is not None:
            # Convert camelCase to snake_case for config consistency
            snake = re.sub(r"([A-Z])", r"_\1", field).lower()
            version_range[snake] = value

    # If no range fields, check for a specific version in the CPE string
    if not version_range:
        specific = _extract_specific_version(match.get("criteria", ""))
        if specific:
            version_range["version_exact"] = specific
        else:
            return None

    # Derive fixed_version from end boundary
    end_excl = match.get("versionEndExcluding")
    if end_excl:
        version_range["fixed_version"] = end_excl

    return version_range


def _pick_latest_fixed_version(
    versions: list[dict[str, Any]],
) -> str | None:
    """Pick the highest fixed_version from a list of version ranges."""
    fixed_versions = [
        v["fixed_version"] for v in versions if v.get("fixed_version")
    ]
    if not fixed_versions:
        return None
    # Simple lexicographic max — good enough for semver-ish strings
    return max(fixed_versions)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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
    normalized = value.lower().replace("+", "plus")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return slug or "unknown"


def _humanize(value: str) -> str:
    """Turn a CPE-style identifier into a readable name."""
    return value.replace("_", " ").replace("-", " ").title()
