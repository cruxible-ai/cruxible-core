"""Compatibility shim for KEV demo providers."""

from cruxible_core.demo_providers.kev_triage import (
    load_fork_seed_data,
    load_public_kev_rows,
    load_reference_product_catalog,
    load_software_inventory,
    match_software_to_products,
)

__all__ = [
    "load_public_kev_rows",
    "load_fork_seed_data",
    "load_reference_product_catalog",
    "load_software_inventory",
    "match_software_to_products",
]
