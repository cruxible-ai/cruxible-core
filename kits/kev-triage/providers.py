"""Compatibility shim for KEV triage kit providers."""

from cruxible_kits.kev_triage import (
    load_fork_seed_data,
    load_public_kev_rows,
    load_software_inventory,
    match_software_to_products,
    normalize_fork_seed_tables,
    normalize_public_kev_reference,
)

__all__ = [
    "load_public_kev_rows",
    "normalize_public_kev_reference",
    "load_fork_seed_data",
    "normalize_fork_seed_tables",
    "load_software_inventory",
    "match_software_to_products",
]
