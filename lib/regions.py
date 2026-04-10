"""
Country → region map.

The destination country in this simulator is always inside the EU, so a flat
EU/Non-EU split would be a degenerate column. We instead break the EU into
its UN geoscheme sub-regions (Western / Northern / Southern / Eastern Europe)
which gives us a meaningful breakdown for analytics in the data hub.

Non-EU codes (e.g. when a future scenario emits a Swiss or UK destination)
return "Other" so the column never goes NULL.
"""
from __future__ import annotations

# UN geoscheme sub-regions for EU member states (M49 grouping).
# Using the EU-only subset because every destination in the simulator today
# is an EU member state.
_EU_SUBREGIONS: dict[str, frozenset[str]] = {
    "Western Europe":  frozenset({"AT", "BE", "DE", "FR", "IE", "LU", "NL"}),
    "Northern Europe": frozenset({"DK", "EE", "FI", "LT", "LV", "SE"}),
    "Southern Europe": frozenset({"CY", "ES", "GR", "HR", "IT", "MT", "PT", "SI"}),
    "Eastern Europe":  frozenset({"BG", "CZ", "HU", "PL", "RO", "SK"}),
}

# Inverted lookup: country_code → region_label, computed once at import time
# so country_region() is O(1).
_COUNTRY_TO_REGION: dict[str, str] = {
    code: region
    for region, codes in _EU_SUBREGIONS.items()
    for code in codes
}


def country_region(country_code: str | None) -> str:
    """
    Map an ISO-2 country code to its UN geoscheme sub-region label.

    Returns "Other" for unknown codes (including non-EU destinations and
    None / empty input). The function is the single source of truth for the
    sales_order_line_item.dest_country_region column.
    """
    if not country_code:
        return "Other"
    return _COUNTRY_TO_REGION.get(country_code.upper(), "Other")
