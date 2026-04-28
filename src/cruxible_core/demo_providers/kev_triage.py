"""Deterministic provider helpers used by the KEV demo configs."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, cast

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

    return _build_public_kev_rows(kev_rows, enriched_by_cve, nvd_cpe_by_cve)


def normalize_public_kev_reference(
    input_payload: dict[str, Any],
    _context: ProviderContext,
) -> dict[str, Any]:
    """Normalize parsed public KEV tables into reference graph rows."""
    kev_rows = _parsed_table_rows(input_payload, "known_exploited_vulnerabilities")
    enriched_by_cve = {
        str(row.get("cve", "")).strip(): row
        for row in _parsed_table_rows(input_payload, "epss_kev_nvd")
        if str(row.get("cve", "")).strip()
    }
    nvd_cpe_by_cve = _parse_nvd_cpe_rows(_parsed_table_rows(input_payload, "nvd_kev_cves"))
    return _build_public_kev_rows(kev_rows, enriched_by_cve, nvd_cpe_by_cve)


def _build_public_kev_rows(
    kev_rows: list[dict[str, Any]],
    enriched_by_cve: dict[str, dict[str, Any]],
    nvd_cpe_by_cve: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for kev_row in kev_rows:
        cve_id = _first_non_empty(
            kev_row.get("cveID"),
            kev_row.get("cve_id"),
            kev_row.get("cveid"),
        )
        if not cve_id:
            continue
        enriched = enriched_by_cve.get(cve_id, {})
        cpe_products = nvd_cpe_by_cve.get(cve_id, [])

        vuln_base = {
            "cve_id": cve_id,
            "description": _first_non_empty(
                kev_row.get("shortDescription"),
                kev_row.get("short_description"),
                kev_row.get("shortdescription"),
                enriched.get("Description"),
                enriched.get("description"),
            ),
            "cvss_score": _parse_float(
                _first_non_empty(enriched.get("CVSS3"), enriched.get("cvss3"))
            ),
            "epss_score": _parse_float(
                _first_non_empty(enriched.get("EPSS"), enriched.get("epss"))
            ),
            "kev_due_date": _first_non_empty(
                kev_row.get("dueDate"),
                kev_row.get("due_date"),
                kev_row.get("duedate"),
            ),
            "known_ransomware_use": _first_non_empty(
                kev_row.get("knownRansomwareCampaignUse"),
                kev_row.get("known_ransomware_campaign_use"),
                kev_row.get("knownransomwarecampaignuse"),
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
            kev_row.get("vendor_project"),
            kev_row.get("vendorproject"),
            enriched.get("Vendor"),
            enriched.get("vendor"),
        )
        product_name = _first_non_empty(
            kev_row.get("product"),
            enriched.get("Product"),
            enriched.get("product"),
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
    tables = {
        key: _load_csv_rows(bundle_root / filename)
        for key, filename in _FORK_SEED_FILES.items()
    }
    return _build_fork_seed_data(tables)


def normalize_fork_seed_tables(
    input_payload: dict[str, Any],
    _context: ProviderContext,
) -> dict[str, Any]:
    """Normalize parsed fork seed tables into deterministic internal graph rows."""
    tables = {
        table_name: _parsed_table_rows(input_payload, table_name)
        for table_name in _FORK_SEED_FILES
    }
    return _build_fork_seed_data(tables)


def _build_fork_seed_data(tables: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    payload = {key: [dict(row) for row in rows] for key, rows in tables.items()}
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


def match_software_to_products(
    input_payload: dict[str, Any],
    _context: ProviderContext,
) -> dict[str, Any]:
    """Match software inventory rows to reference products deterministically."""
    inventory_items = _require_items(input_payload, "inventory_items")
    reference_products = [
        product
        for raw_product in _require_items(input_payload, "reference_products")
        if (product := _normalize_reference_product(raw_product)) is not None
    ]

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


def _normalize_reference_product(product: dict[str, Any]) -> dict[str, Any] | None:
    if "properties" not in product:
        product_id = _first_non_empty(product.get("product_id"))
        if not product_id:
            return None
        return {
            "product_id": product_id,
            "product_name": _first_non_empty(product.get("product_name")) or "",
            "vendor_id": _first_non_empty(product.get("vendor_id")) or "",
            "vendor_name": _first_non_empty(product.get("vendor_name")) or "",
            "cpe_vendor": _first_non_empty(product.get("cpe_vendor")) or "",
            "cpe_product": _first_non_empty(product.get("cpe_product")) or "",
            "cpe_part": _first_non_empty(product.get("cpe_part")) or "",
        }

    properties = product.get("properties")
    if not isinstance(properties, dict):
        return None

    product_id = _first_non_empty(product.get("entity_id"), properties.get("product_id"))
    if not product_id:
        return None

    vendor_name = _first_non_empty(properties.get("vendor_name")) or ""
    cpe_vendor = _first_non_empty(properties.get("cpe_vendor")) or ""
    return {
        "product_id": product_id,
        "product_name": _first_non_empty(properties.get("product_name")) or "",
        "vendor_id": _first_non_empty(properties.get("vendor_id")) or "",
        "vendor_name": vendor_name,
        "cpe_vendor": cpe_vendor,
        "cpe_product": _first_non_empty(properties.get("cpe_product")) or "",
        "cpe_part": _first_non_empty(properties.get("cpe_part")) or "",
    }


def assess_asset_affected(
    input_payload: dict[str, Any],
    _context: ProviderContext,
) -> dict[str, Any]:
    """Join approved asset-product edges to vulnerability-product edges."""
    asset_product_edges = _require_items(input_payload, "asset_product_edges")
    vulnerability_product_edges = _require_items(input_payload, "vulnerability_product_edges")

    vulnerability_edges_by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in vulnerability_product_edges:
        product_id = _edge_to_id(edge)
        if product_id:
            vulnerability_edges_by_product[product_id].append(edge)

    rows_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in asset_product_edges:
        asset_id = _edge_from_id(edge)
        product_id = _edge_to_id(edge)
        properties = _edge_properties(edge)
        if not asset_id or not product_id:
            continue

        installed_version = _first_non_empty(properties.get("installed_version")) or ""
        source = _first_non_empty(properties.get("evidence_source")) or "asset_runs_product"
        for vulnerability_edge in vulnerability_edges_by_product.get(product_id, []):
            cve_id = _edge_from_id(vulnerability_edge)
            if not cve_id:
                continue
            vulnerability_properties = _edge_properties(vulnerability_edge)
            verdict, rationale = _assess_version_membership(
                installed_version,
                vulnerability_properties.get("affected_versions"),
                vulnerability_properties.get("fixed_version"),
            )
            if verdict == "contradict":
                continue

            row = {
                "asset_id": asset_id,
                "cve_id": cve_id,
                "product_id": product_id,
                "installed_version": installed_version,
                "source": source,
                "rationale": rationale,
                "verdict": verdict,
            }
            key = (asset_id, cve_id)
            current = rows_by_pair.get(key)
            if current is None or _verdict_rank(verdict) > _verdict_rank(current["verdict"]):
                rows_by_pair[key] = row

    return {"items": [rows_by_pair[key] for key in sorted(rows_by_pair)]}


def assess_asset_exposure(
    input_payload: dict[str, Any],
    _context: ProviderContext,
) -> dict[str, Any]:
    """Assess which affected assets are materially exposed."""
    affected_edges = _require_items(input_payload, "affected_edges")
    assets = _require_items(input_payload, "assets")
    asset_control_edges = _require_items(input_payload, "asset_control_edges")
    controls = _require_items(input_payload, "controls")

    assets_by_id = {_entity_id(entity): _entity_properties(entity) for entity in assets}
    controls_by_id = {_entity_id(entity): _entity_properties(entity) for entity in controls}
    active_controls_by_asset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in asset_control_edges:
        asset_id = _edge_from_id(edge)
        control_id = _edge_to_id(edge)
        if not asset_id or not control_id:
            continue
        control = controls_by_id.get(control_id)
        if control is None or _first_non_empty(control.get("status")) != "active":
            continue
        active_controls_by_asset[asset_id].append(control)

    rows_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in affected_edges:
        asset_id = _edge_from_id(edge)
        cve_id = _edge_to_id(edge)
        if not asset_id or not cve_id:
            continue

        asset = assets_by_id.get(asset_id, {})
        active_controls = active_controls_by_asset.get(asset_id, [])
        exploitability_verdict = _derive_exploitability_verdict(asset)
        if exploitability_verdict == "contradict":
            continue

        control_verdict = "support" if not active_controls else "unsure"
        priority = _derive_exposure_priority(asset, exploitability_verdict, control_verdict)
        due_by = _priority_due_by(priority)
        rationale = _build_exposure_rationale(asset, active_controls, exploitability_verdict)
        rows_by_pair[(asset_id, cve_id)] = {
            "asset_id": asset_id,
            "cve_id": cve_id,
            "priority": priority,
            "due_by": due_by,
            "rationale": rationale,
            "exploitability_verdict": exploitability_verdict,
            "control_verdict": control_verdict,
        }

    return {"items": [rows_by_pair[key] for key in sorted(rows_by_pair)]}


def assess_service_impact(
    input_payload: dict[str, Any],
    _context: ProviderContext,
) -> dict[str, Any]:
    """Roll exposed asset-vulnerability pairs up to service impact judgments."""
    exposure_edges = _require_items(input_payload, "exposure_edges")
    service_asset_edges = _require_items(input_payload, "service_asset_edges")
    services = _require_items(input_payload, "services")

    services_by_id = {_entity_id(entity): _entity_properties(entity) for entity in services}
    service_ids_by_asset: dict[str, list[str]] = defaultdict(list)
    for edge in service_asset_edges:
        service_id = _edge_from_id(edge)
        asset_id = _edge_to_id(edge)
        if service_id and asset_id:
            service_ids_by_asset[asset_id].append(service_id)

    impacted_assets_by_pair: dict[tuple[str, str], set[str]] = defaultdict(set)
    for edge in exposure_edges:
        asset_id = _edge_from_id(edge)
        cve_id = _edge_to_id(edge)
        if not asset_id or not cve_id:
            continue
        for service_id in service_ids_by_asset.get(asset_id, []):
            impacted_assets_by_pair[(service_id, cve_id)].add(asset_id)

    items: list[dict[str, Any]] = []
    for (service_id, cve_id), asset_ids in sorted(impacted_assets_by_pair.items()):
        service = services_by_id.get(service_id, {})
        blast_radius = _derive_blast_radius(
            _first_non_empty(service.get("tier")) or "",
            len(asset_ids),
        )
        items.append(
            {
                "service_id": service_id,
                "cve_id": cve_id,
                "blast_radius": blast_radius,
                "rationale": (
                    f"Service depends on {len(asset_ids)} exposed asset(s): "
                    f"{', '.join(sorted(asset_ids))}"
                ),
                "verdict": "support",
            }
        )

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


def _edge_from_id(edge: dict[str, Any]) -> str:
    return _first_non_empty(edge.get("from_id")) or ""


def _edge_to_id(edge: dict[str, Any]) -> str:
    return _first_non_empty(edge.get("to_id")) or ""


def _edge_properties(edge: dict[str, Any]) -> dict[str, Any]:
    properties = edge.get("properties")
    return properties if isinstance(properties, dict) else {}


def _entity_id(entity: dict[str, Any]) -> str:
    return _first_non_empty(entity.get("entity_id")) or ""


def _entity_properties(entity: dict[str, Any]) -> dict[str, Any]:
    properties = entity.get("properties")
    return properties if isinstance(properties, dict) else {}


def _verdict_rank(verdict: str) -> int:
    return {"support": 2, "unsure": 1, "contradict": 0}.get(verdict, -1)


def _assess_version_membership(
    installed_version: str,
    affected_versions: Any,
    fixed_version: Any,
) -> tuple[str, str]:
    if not installed_version:
        return "unsure", "Installed version is missing"

    ranges = affected_versions if isinstance(affected_versions, list) else []
    comparable_range_seen = False
    for range_spec in ranges:
        if not isinstance(range_spec, dict):
            continue
        membership = _version_in_range(installed_version, range_spec)
        if membership is None:
            continue
        comparable_range_seen = True
        if membership:
            return "support", _build_range_rationale(installed_version, range_spec)

    fixed = _first_non_empty(fixed_version)
    fixed_comparison = _compare_versions(installed_version, fixed) if fixed else None
    if comparable_range_seen:
        if fixed and fixed_comparison is not None and fixed_comparison >= 0:
            return (
                "contradict",
                f"Installed version {installed_version} is at or beyond fixed {fixed}",
            )
        return "contradict", f"Installed version {installed_version} is outside the affected range"

    if fixed and fixed_comparison is not None:
        if fixed_comparison < 0:
            return "support", f"Installed version {installed_version} is earlier than fixed {fixed}"
        return "contradict", f"Installed version {installed_version} is at or beyond fixed {fixed}"

    return (
        "unsure",
        f"Could not compare installed version {installed_version} to the reference data",
    )


def _build_range_rationale(installed_version: str, range_spec: dict[str, Any]) -> str:
    clauses: list[str] = [f"Installed version {installed_version} fits the affected range"]
    for field in (
        "version_start_including",
        "version_start_excluding",
        "version_end_including",
        "version_end_excluding",
        "version_exact",
        "fixed_version",
    ):
        value = _first_non_empty(range_spec.get(field))
        if value:
            clauses.append(f"{field}={value}")
    return "; ".join(clauses)


def _version_in_range(installed_version: str, range_spec: dict[str, Any]) -> bool | None:
    exact_version = _first_non_empty(range_spec.get("version_exact"))
    if exact_version:
        comparison = _compare_versions(installed_version, exact_version)
        return None if comparison is None else comparison == 0

    comparable = False
    predicates: tuple[tuple[str, Callable[[int], bool]], ...] = (
        ("version_start_including", lambda value: value >= 0),
        ("version_start_excluding", lambda value: value > 0),
        ("version_end_including", lambda value: value <= 0),
        ("version_end_excluding", lambda value: value < 0),
    )
    for field, predicate in predicates:
        bound = _first_non_empty(range_spec.get(field))
        if not bound:
            continue
        comparison = _compare_versions(installed_version, bound)
        if comparison is None:
            return None
        comparable = True
        if not predicate(comparison):
            return False

    if not comparable:
        return None
    return True


def _compare_versions(left: Any, right: Any) -> int | None:
    left_tokens = _tokenize_version(left)
    right_tokens = _tokenize_version(right)
    if not left_tokens or not right_tokens:
        return None

    max_length = max(len(left_tokens), len(right_tokens))
    for index in range(max_length):
        if index >= len(left_tokens):
            return -1
        if index >= len(right_tokens):
            return 1
        left_token = left_tokens[index]
        right_token = right_tokens[index]
        if left_token == right_token:
            continue
        if isinstance(left_token, int) and isinstance(right_token, int):
            return -1 if left_token < right_token else 1
        return -1 if str(left_token) < str(right_token) else 1

    return 0


def _tokenize_version(value: Any) -> list[int | str]:
    text = _first_non_empty(value)
    if text is None:
        return []
    parts = re.findall(r"[a-z]+|\d+", text.lower())
    tokens: list[int | str] = []
    for part in parts:
        if part.isdigit():
            tokens.append(int(part))
        else:
            tokens.append(part)
    return tokens


def _derive_exploitability_verdict(asset: dict[str, Any]) -> str:
    internet_exposed = asset.get("internet_exposed")
    environment = _first_non_empty(asset.get("environment")) or ""
    criticality = _first_non_empty(asset.get("criticality")) or ""
    if internet_exposed is True:
        return "support"
    if environment == "production" and criticality in {"critical", "high"}:
        return "unsure"
    if environment == "production":
        return "unsure"
    return "contradict"


def _derive_exposure_priority(
    asset: dict[str, Any],
    exploitability_verdict: str,
    control_verdict: str,
) -> str:
    criticality = _first_non_empty(asset.get("criticality")) or ""
    if exploitability_verdict == "support" and control_verdict == "support":
        return "urgent" if criticality == "critical" else "high"
    if criticality in {"critical", "high"}:
        return "high"
    return "medium"


def _priority_due_by(priority: str) -> str:
    return {
        "urgent": "24h",
        "high": "72h",
        "medium": "7d",
    }.get(priority, "14d")


def _build_exposure_rationale(
    asset: dict[str, Any],
    active_controls: list[dict[str, Any]],
    exploitability_verdict: str,
) -> str:
    hostname = _first_non_empty(asset.get("hostname")) or "asset"
    environment = _first_non_empty(asset.get("environment")) or "unknown"
    exposure_clause = (
        "internet-facing"
        if asset.get("internet_exposed") is True
        else f"{environment} asset with {exploitability_verdict} exploitability"
    )
    if not active_controls:
        return f"{hostname} is {exposure_clause} and has no active compensating controls"
    control_names = ", ".join(
        sorted(
            _first_non_empty(control.get("name")) or "unknown control"
            for control in active_controls
        )
    )
    return f"{hostname} is {exposure_clause}; active controls require review: {control_names}"


def _derive_blast_radius(tier: str, exposed_asset_count: int) -> str:
    normalized = tier.lower()
    if normalized == "tier-1":
        return "critical" if exposed_asset_count > 1 else "high"
    if normalized == "tier-2":
        return "high" if exposed_asset_count > 1 else "medium"
    return "medium" if exposed_asset_count > 1 else "low"


# ---------------------------------------------------------------------------
# NVD CPE parsing
# ---------------------------------------------------------------------------


def _load_nvd_cpe_data(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Parse NVD CVE JSON and extract CPE product + version data."""
    if not path.exists():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return {}
    return _parse_nvd_cpe_rows(raw)


def _parse_nvd_cpe_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}

    for entry in rows:
        cve = entry.get("cve", {})
        if not isinstance(cve, dict):
            continue
        cve_id = cve.get("id", "")
        if not cve_id:
            continue

        product_versions: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        configurations = entry.get("configurations")
        if not isinstance(configurations, list):
            configurations = cve.get("configurations", [])
        for config in configurations:
            if not isinstance(config, dict):
                continue
            for node in config.get("nodes", []):
                if not isinstance(node, dict):
                    continue
                for match in node.get("cpeMatch", []):
                    if not isinstance(match, dict):
                        continue
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
    return cast(str, max(fixed_versions))


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


def _parsed_table_rows(input_payload: dict[str, Any], table_name: str) -> list[dict[str, Any]]:
    tables = input_payload.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("Expected input.tables to be a mapping")
    table = tables.get(table_name)
    if not isinstance(table, dict):
        raise ValueError(f"Expected parsed table '{table_name}'")
    rows = table.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"Expected parsed table '{table_name}' to contain rows")
    return [_strip_provider_metadata(row) for row in rows if isinstance(row, dict)]


def _strip_provider_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if not key.startswith("_")}


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
