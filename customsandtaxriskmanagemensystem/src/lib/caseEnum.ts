// Single source of truth for Customs / Tax action enums.
//
// The backend seeds the canonical labels into `customs_actions` and
// `tax_actions` (see lib/database.py:_SEED_*_ACTIONS), exposed via
// /api/reference and consumed by referenceStore. At runtime we read
// the labels from there; the tables below are only the compile-time
// types and a hardcoded fallback (kept in sync with the backend seed
// so the UI renders sensibly before the reference fetch lands).
//
// Terminology:
// - `code` is the wire identifier sent in POST bodies (e.g. "retainment").
// - `label` is the user-facing string shown in the UI (e.g. "Recommend Control").
// Any file that needs to bridge the two should import from here rather
// than re-expressing the mapping inline.

import { getCustomsActions, getTaxActions } from "./referenceStore";

// ── Wire codes ──────────────────────────────────────────────────────────────

export type CustomsActionCode = "retainment" | "release" | "tax_review" | "input_requested";
export type TaxActionCode     = "risk_confirmed" | "no_limited_risk";

// ── Canonical labels (fallback if referenceStore hasn't loaded yet) ─────────

export type CustomsActionLabel =
  | "Recommend Control"
  | "Recommend Release"
  | "Submit for Tax Review"
  | "Request Input from Deemed Importer";

export type TaxActionLabel = "Confirm Risk" | "No/Limited Risk";

export const CUSTOMS_ACTION_LABELS: Record<CustomsActionCode, CustomsActionLabel> = {
  retainment:       "Recommend Control",
  release:          "Recommend Release",
  tax_review:       "Submit for Tax Review",
  input_requested:  "Request Input from Deemed Importer",
};

export const TAX_ACTION_LABELS: Record<TaxActionCode, TaxActionLabel> = {
  risk_confirmed:  "Confirm Risk",
  no_limited_risk: "No/Limited Risk",
};

// Reverse — label → code. Built at module load so lookup is O(1).
const CUSTOMS_CODE_BY_LABEL: Record<string, CustomsActionCode> = Object.fromEntries(
  (Object.entries(CUSTOMS_ACTION_LABELS) as [CustomsActionCode, string][])
    .map(([code, label]) => [label, code]),
) as Record<string, CustomsActionCode>;

const TAX_CODE_BY_LABEL: Record<string, TaxActionCode> = Object.fromEntries(
  (Object.entries(TAX_ACTION_LABELS) as [TaxActionCode, string][])
    .map(([code, label]) => [label, code]),
) as Record<string, TaxActionCode>;

// ── Lookups ────────────────────────────────────────────────────────────────

/**
 * Turn a wire-code (or an already-labelled string) into a user-facing
 * label. Prefers the backend-served label (via referenceStore) over
 * the fallback table so relabels in lib/database.py:_SEED_*_ACTIONS
 * propagate without FE changes. Returns the input verbatim if it
 * doesn't match any known code.
 */
export function actionLabelOf(code: string): string {
  const custom = [...getCustomsActions(), ...getTaxActions()].find((a) => a.code === code);
  if (custom) return custom.label;
  if (code in CUSTOMS_ACTION_LABELS) return CUSTOMS_ACTION_LABELS[code as CustomsActionCode];
  if (code in TAX_ACTION_LABELS)     return TAX_ACTION_LABELS[code as TaxActionCode];
  return code;
}

export function customsCodeFor(label: string): CustomsActionCode | undefined {
  return CUSTOMS_CODE_BY_LABEL[label];
}

export function taxCodeFor(label: string): TaxActionCode | undefined {
  return TAX_CODE_BY_LABEL[label];
}

// ── Allowed-set helpers (for select-value guarding) ────────────────────────

export const VALID_CUSTOMS_LABELS: ReadonlySet<string> = new Set(
  Object.values(CUSTOMS_ACTION_LABELS),
);

export const VALID_TAX_LABELS: ReadonlySet<string> = new Set(
  Object.values(TAX_ACTION_LABELS),
);
