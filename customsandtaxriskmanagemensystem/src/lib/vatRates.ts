// VAT category / rate helpers sourced from the backend reference
// store (vat_categories seeded in lib/database.py:_SEED_VAT_CATEGORIES).
// Single entry point so neither CaseReview nor the VAT panel has to
// re-express the "UPPERCASE parent categories and their Irish rates"
// table that lived on the frontend previously.

import { getVatCategories } from "./referenceStore";

export function vatRatesByCategory(): Record<string, number> {
  const out: Record<string, number> = {};
  for (const c of getVatCategories()) out[c.label] = c.rate;
  return out;
}

export function vatCategoryOptions(): { label: string; value: string; rate: number }[] {
  return getVatCategories().map((c) => ({
    label: c.label,
    value: c.label,
    rate: c.rate,
  }));
}
