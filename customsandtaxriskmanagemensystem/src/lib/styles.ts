// Centralised style maps for case-status badges and risk-level badges.
// Replaces the drift that used to exist across CustomsAuthority,
// TaxAuthority, CaseReview, and ClosedCases.
//
// Keys are the canonical status / risk-level strings emitted by the
// backend reference tables (case_statuses, risk_levels). Add a new
// backend row and the lookup falls back to a neutral muted style until
// you extend the map here — no more broken silent "no badge style"
// rendering when a new status appears.

export const statusStyles: Record<string, string> = {
  New: "bg-muted text-muted-foreground",
  "Under Review by Customs": "bg-primary/15 text-primary",
  "Under Review by Tax": "bg-yellow-500/15 text-yellow-600",
  "AI Investigation in Progress": "bg-purple-500/15 text-purple-600 border-purple-500/30",
  "Reviewed by Tax": "bg-muted text-muted-foreground",
  "Requested Input by Deemed Importer": "bg-warning/15 text-warning",
  Closed: "bg-success/10 text-success",
};

export const riskLevelStyles: Record<string, string> = {
  Critical: "bg-destructive/15 text-destructive border-destructive/30",
  High: "bg-risk-high/15 text-risk-high border-risk-high/30",
  Medium: "bg-warning/10 text-warning",
  Low: "bg-success/10 text-success",
};

// Fallback neutral style for unknown keys — lets new backend-added
// statuses / risk levels render safely until the map is updated.
const NEUTRAL_BADGE = "bg-muted text-muted-foreground";

export function statusStyle(status: string | undefined | null): string {
  if (!status) return NEUTRAL_BADGE;
  return statusStyles[status] ?? NEUTRAL_BADGE;
}

export function riskLevelStyle(level: string | undefined | null): string {
  if (!level) return NEUTRAL_BADGE;
  return riskLevelStyles[level] ?? NEUTRAL_BADGE;
}
