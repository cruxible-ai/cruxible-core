"""Deterministic provider helpers used by the KEV demo configs."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from cruxible_core.provider.types import ProviderContext

_FORK_SEED_FILES = {
    "assets": "assets.csv",
    "business_services": "business_services.csv",
    "owners": "owners.csv",
    "compensating_controls": "compensating_controls.csv",
    "exceptions": "exceptions.csv",
    "patch_windows": "patch_windows.csv",
    "service_depends_on_asset": "service_depends_on_asset.csv",
    "asset_owned_by": "asset_owned_by.csv",
    "asset_has_control": "asset_has_control.csv",
    "asset_has_exception": "asset_has_exception.csv",
    "asset_patch_window": "asset_patch_window.csv",
}
_GENERIC_TOKENS = {
    "corp",
    "corporation",
    "co",
    "company",
    "foundation",
    "group",
    "inc",
    "llc",
    "ltd",
    "project",
}


def load_public_kev_rows(
    _input_payload: dict[str, Any],
    context: ProviderContext,
) -> dict[str, Any]:
    """Load and normalize public KEV reference rows from a hashed data bundle."""
    bundle_root = _require_artifact_root(context, "load_public_kev_rows")

    kev_rows = _load_csv_rows(bundle_root / "known_exploited_vulnerabilities.csv")
    enriched_by_cve = {
        row.get("CVE", "").strip(): row
        for row in _load_csv_rows(bundle_root / "epss_kev_nvd.csv")
        if row.get("CVE", "").strip()
    }
    nvd_cpe_by_cve = _load_nvd_cpe_data(bundle_root / "nvd_kev_cves.json")

    items: list[dict[str, Any]] = []
    for kev_row in kev_rows:
        cve_id = kev_row.get("cveID", "").strip()
        if not cve_id:
            continue
        enriched = enriched_by_cve.get(cve_id, {})
        cpe_products = nvd_cpe_by_cve.get(cve_id, [])

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
            for product in cpe_products:
                items.append({
                    **vuln_base,
                    **product,
                })
            continue

        vendor_name = _first_non_empty(
            kev_row.get("vendorProject"),
            enriched.get("Vendor"),
        )
        product_name = _first_non_empty(
            kev_row.get("product"),
            enriched.get("Product"),
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


def load_fork_seed_data(
    _input_payload: dict[str, Any],
    context: ProviderContext,
) -> dict[str, Any]:
    """Load deterministic fork entity and relationship rows from the seed bundle."""
    bundle_root = _require_artifact_root(context, "load_fork_seed_data")
    payload = {
        key: _load_csv_rows(bundle_root / filename)
        for key, filename in _FORK_SEED_FILES.items()
    }

    for row in payload["assets"]:
        row["internet_exposed"] = _parse_bool(row.get("internet_exposed"))

    return payload


def load_software_inventory(
    _input_payload: dict[str, Any],
    context: ProviderContext,
) -> dict[str, Any]:
    """Load raw software inventory rows from the seed bundle."""
    bundle_root = _require_artifact_root(context, "load_software_inventory")
    return {"items": _load_csv_rows(bundle_root / "software_inventory.csv")}


def load_reference_product_catalog(
    _input_payload: dict[str, Any],
    context: ProviderContext,
) -> dict[str, Any]:
    """Load a unique reference product catalog from the public artifact bundle."""
    bundle_root = _require_artifact_root(context, "load_reference_product_catalog")
    products_by_id: dict[str, dict[str, Any]] = {}

    for product_rows in _load_nvd_cpe_data(bundle_root / "nvd_kev_cves.json").values():
        for product in product_rows:
            product_id = str(product["product_id"])
            current = products_by_id.get(product_id)
            candidate = {
                "product_id": product_id,
                "product_name": product["product_name"],
                "vendor_id": product["vendor_id"],
                "vendor_name": product["vendor_name"],
                "cpe_vendor": product["cpe_vendor"],
                "cpe_product": product["cpe_product"],
                "cpe_part": product["cpe_part"],
            }
            if current is None or _catalog_row_completeness(candidate) > _catalog_row_completeness(
                current
            ):
                products_by_id[product_id] = candidate

    items = [products_by_id[key] for key in sorted(products_by_id)]
    return {"items": items}


def match_software_to_products(
    input_payload: dict[str, Any],
    _context: ProviderContext,
) -> dict[str, Any]:
    """Match software inventory rows to reference products deterministically."""
    inventory_items = _require_items(input_payload, "inventory_items")
    reference_products = _require_items(input_payload, "reference_products")

    best_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for item in inventory_items:
        best_product: dict[str, Any] | None = None
        best_score = 0.0
        for product in reference_products:
            score = _score_product_match(item, product)
            if score > best_score:
                best_product = product
                best_score = score

        if best_product is None or best_score < 0.5:
            continue

        pair = (str(item.get("asset_id", "")), str(best_product.get("product_id", "")))
        if not all(pair):
            continue

        row = {
            "asset_id": pair[0],
            "product_id": pair[1],
            "installed_version": _first_non_empty(item.get("version")) or "",
            "evidence_source": _first_non_empty(item.get("evidence_source")) or "",
            "match_confidence": round(best_score, 4),
            "verdict": _score_to_verdict(best_score),
            "_last_seen": _first_non_empty(item.get("last_seen")) or "",
        }

        current = best_by_pair.get(pair)
        if current is None or _match_row_sort_key(row) > _match_row_sort_key(current):
            best_by_pair[pair] = row

    items = []
    for pair in sorted(best_by_pair):
        row = dict(best_by_pair[pair])
        row.pop("_last_seen", None)
        items.append(row)
    return {"items": items}


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------


def _score_product_match(inventory_row: dict[str, Any], product_row: dict[str, Any]) -> float:
    inventory_name = _normalize_name(inventory_row.get("software_name"))
    inventory_vendor = _normalize_vendor(inventory_row.get("vendor"))
    if not inventory_name:
        return 0.0

    vendor_candidates = [
        _normalize_vendor(product_row.get("vendor_name")),
        _normalize_vendor(product_row.get("cpe_vendor")),
    ]
    vendor_candidates = [candidate for candidate in vendor_candidates if candidate]
    vendor_strength = 0.0
    if inventory_vendor:
        vendor_strength = max(
            (_text_similarity(inventory_vendor, candidate) for candidate in vendor_candidates),
            default=0.0,
        )
        if vendor_strength < 0.4:
            return 0.0
    else:
        vendor_strength = 1.0

    reference_names = [
        _normalize_name(product_row.get("product_name")),
        _normalize_name(product_row.get("cpe_product")),
    ]
    name_strength = max(
        (_text_similarity(inventory_name, candidate) for candidate in reference_names if candidate),
        default=0.0,
    )
    if name_strength < 0.45:
        return 0.0

    score = 0.6 * name_strength + 0.4 * vendor_strength
    if any(
        _is_contained_name(inventory_name, candidate)
        for candidate in reference_names
        if candidate
    ):
        score = max(score, 0.85 if vendor_strength >= 0.8 else 0.75)
    if any(inventory_name == candidate for candidate in reference_names if candidate):
        score = max(score, 0.95)
    return min(score, 0.99)


def _normalize_vendor(value: Any) -> str:
    return _normalize_text(value, drop_generic=True)


def _normalize_name(value: Any) -> str:
    return _normalize_text(value, drop_generic=False)


def _normalize_text(value: Any, *, drop_generic: bool) -> str:
    text = _first_non_empty(value)
    if text is None:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    if not normalized:
        return ""
    tokens = [token for token in normalized.split() if token]
    if drop_generic:
        tokens = [token for token in tokens if token not in _GENERIC_TOKENS]
    return " ".join(tokens)


def _text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0

    left_tokens = set(left.split())
    right_tokens = set(right.split())
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))
    sequence = SequenceMatcher(None, left, right).ratio()
    if left_tokens <= right_tokens or right_tokens <= left_tokens:
        return max(overlap, sequence, 0.92)
    return max(overlap, sequence)


def _is_contained_name(left: str, right: str) -> bool:
    return bool(left and right and (left in right or right in left))


def _score_to_verdict(score: float) -> str:
    if score >= 0.8:
        return "support"
    if score >= 0.5:
        return "unsure"
    return "contradict"


def _match_row_sort_key(row: dict[str, Any]) -> tuple[float, str, str]:
    return (
        float(row.get("match_confidence", 0.0)),
        str(row.get("_last_seen", "")),
        str(row.get("installed_version", "")),
    )


def _catalog_row_completeness(row: dict[str, Any]) -> int:
    return sum(
        bool(row.get(key))
        for key in ("vendor_name", "cpe_vendor", "cpe_product", "cpe_part")
    )


# ---------------------------------------------------------------------------
# NVD CPE parsing
# ---------------------------------------------------------------------------


def _load_nvd_cpe_data(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Parse NVD CVE JSON and extract CPE product + version data."""
    if not path.exists():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, list[dict[str, Any]]] = {}

    for entry in raw:
        cve = entry.get("cve", {})
        cve_id = cve.get("id", "")
        if not cve_id:
            continue

        product_versions: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
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
                    if key not in product_versions:
                        product_versions[key] = []
                    if version_range is not None:
                        product_versions[key].append(version_range)

        if not product_versions:
            continue

        products: list[dict[str, Any]] = []
        for (cpe_part, cpe_vendor, cpe_product), versions in product_versions.items():
            vendor_id = _slugify(cpe_vendor)
            product_id = _slugify(f"{cpe_vendor}__{cpe_product}")
            products.append({
                "vendor_id": vendor_id,
                "vendor_name": _humanize(cpe_vendor),
                "product_id": product_id,
                "product_name": _humanize(cpe_product),
                "cpe_vendor": cpe_vendor,
                "cpe_product": cpe_product,
                "cpe_part": cpe_part,
                "affected_versions": versions,
                "fixed_version": _pick_latest_fixed_version(versions),
            })

        result[cve_id] = products

    return result


def _parse_cpe_criteria(criteria: str) -> tuple[str, str, str] | None:
    parts = criteria.split(":")
    if len(parts) < 5 or parts[0] != "cpe" or parts[1] != "2.3":
        return None
    return parts[2], parts[3], parts[4]


def _extract_specific_version(criteria: str) -> str | None:
    parts = criteria.split(":")
    if len(parts) < 6:
        return None
    version = parts[5]
    if version in ("*", "-", ""):
        return None
    return version


def _extract_version_range(match: dict[str, Any]) -> dict[str, Any] | None:
    version_range: dict[str, Any] = {}
    for field in (
        "versionStartIncluding",
        "versionStartExcluding",
        "versionEndIncluding",
        "versionEndExcluding",
    ):
        value = match.get(field)
        if value is not None:
            version_range[re.sub(r"([A-Z])", r"_\1", field).lower()] = value

    if not version_range:
        specific = _extract_specific_version(match.get("criteria", ""))
        if specific:
            version_range["version_exact"] = specific
        else:
            return None

    end_excl = match.get("versionEndExcluding")
    if end_excl:
        version_range["fixed_version"] = end_excl
    return version_range


def _pick_latest_fixed_version(versions: list[dict[str, Any]]) -> str | None:
    fixed_versions = [value["fixed_version"] for value in versions if value.get("fixed_version")]
    if not fixed_versions:
        return None
    return max(fixed_versions)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _require_artifact_root(context: ProviderContext, provider_name: str) -> Path:
    if context.artifact is None or context.artifact.local_path is None:
        raise ValueError(f"{provider_name} requires a local artifact bundle")
    return Path(context.artifact.local_path)


def _require_items(input_payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = input_payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Expected '{key}' to be a list of objects")
    return value


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _parse_bool(value: Any) -> bool | None:
    text = _first_non_empty(value)
    if text is None:
        return None
    lowered = text.lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    return None


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
    return value.replace("_", " ").replace("-", " ").title()
