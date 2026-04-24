// Reference / lookup data hydrated once at app startup from
// GET /api/reference. Replaces previously-hardcoded constants in
// TaxReviewDialog (vat categories), CategoryBreakdown (suspicion types),
// caseStore (region mapping), and various risk-level strings.
//
// Synchronous getters; if the fetch hasn't completed yet, returns sensible
// fallbacks so the UI never crashes.

import {
  fetchReference,
  type ReferenceBundle,
  type VatCategory,
  type VatSubcategory,
  type RiskLevel,
  type EuRegion,
  type SuspicionType,
  type StatusRef,
  type ActionRef,
  type RiskSignal,
  type RiskThresholds,
} from "./apiClient";

let _data: ReferenceBundle = {
  vat_categories:       [],
  vat_subcategories:    {},
  vat_rates_by_country:  {},
  country_standard_rate: {},
  risk_levels:          [],
  regions:              [],
  suspicion_types:      [],
  case_statuses:        [],
  sales_order_statuses: [],
  customs_actions:      [],
  tax_actions:          [],
  risk_engine_signals:  [],
  risk_thresholds:      { release: 0, retain: 0 },
};
let _loaded = false;
let _started = false;

export async function startReferenceStore(): Promise<void> {
  if (_started) return;
  _started = true;
  try {
    _data = await fetchReference();
    _loaded = true;
    window.dispatchEvent(new Event("reference-loaded"));
  } catch (err) {
    console.error("[referenceStore] fetch failed — falling back to empty lookups", err);
  }
}

export const isReferenceLoaded = (): boolean => _loaded;

export const getVatCategories      = (): VatCategory[]   => _data.vat_categories;
// Subcategories for a given parent label; empty list if unknown.
export const getVatSubcategories = (category: string): VatSubcategory[] =>
  _data.vat_subcategories[category] ?? [];

/**
 * Expected VAT rate (as a fraction, e.g. 0.23) for a given destination
 * and subcategory code. Prefers the specific (country, sub) entry in
 * vat_rates_by_country; otherwise falls back to the destination's
 * standard rate. Returns undefined if the destination is unknown.
 */
export function expectedVatRateFor(
  destination: string | null | undefined,
  subcategoryCode: string | null | undefined,
): number | undefined {
  if (!destination) return undefined;
  if (subcategoryCode) {
    const specific = _data.vat_rates_by_country[destination]?.[subcategoryCode];
    if (specific !== undefined) return specific;
  }
  return _data.country_standard_rate[destination];
}

/** Destination country's standard VAT rate (fraction), or undefined if unknown. */
export const getCountryStandardRate = (destination: string | null | undefined): number | undefined =>
  destination ? _data.country_standard_rate[destination] : undefined;
export const getRiskLevels         = (): RiskLevel[]     => _data.risk_levels;
export const getRegions            = (): EuRegion[]      => _data.regions;
export const getSuspicionTypes     = (): SuspicionType[] => _data.suspicion_types;
export const getCaseStatusList     = (): StatusRef[]     => _data.case_statuses;
export const getSalesOrderStatuses = (): StatusRef[]     => _data.sales_order_statuses;
export const getCustomsActions     = (): ActionRef[]     => _data.customs_actions;
export const getTaxActions         = (): ActionRef[]     => _data.tax_actions;
export const getRiskEngineSignals  = (): RiskSignal[]    => _data.risk_engine_signals;
export const getRiskThresholds     = (): RiskThresholds  => _data.risk_thresholds;

// Convenience: map ISO country code → region label. Falls back to the
// country code itself when the lookup misses.
export function regionForCountry(country: string | null | undefined): string {
  if (!country) return "Unknown";
  const code = country.toUpperCase();
  const hit = _data.regions.find((r) => r.country_code === code);
  return hit?.region ?? code;
}
