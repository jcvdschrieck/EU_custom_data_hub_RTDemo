// Shared case state management using localStorage
// Tracks case status changes, actions, and movement between dashboards

import { type CaseStatus, type ActionTaken, type Case, type ActivityEntry, getInitialActivitiesForCase } from "./caseData";

const CASE_STATUS_KEY = "case-statuses";
const CASE_ACTION_KEY = "case-actions";
const CASE_CLOSED_KEY = "case-closed-dates";
const CASE_SNAPSHOT_KEY = "case-snapshots";

export interface StoredCaseSnapshot {
  caseData: Case;
  activities: ActivityEntry[];
  riskSaved: boolean;
  // Free-text justification the officer typed in the Save-Risk dialog.
  // Surfaced back into the AI Risk Summary as an appended paragraph so
  // the narrative explains WHY the override differs from the AI's
  // initial score.
  riskSaveNote?: string;
  vatSaved?: boolean;
  vatCategory?: string;
  updatedAt: string;
}

// One-time reset
(() => {
  const RESET_KEY = "case-store-reset-v5";
  if (!localStorage.getItem(RESET_KEY)) {
    localStorage.removeItem(CASE_STATUS_KEY);
    localStorage.removeItem(CASE_ACTION_KEY);
    localStorage.removeItem(CASE_CLOSED_KEY);
    localStorage.removeItem(CASE_SNAPSHOT_KEY);
    localStorage.setItem(RESET_KEY, "done");
  }
})();

export function getCaseStatuses(): Record<string, CaseStatus> {
  try {
    const data = localStorage.getItem(CASE_STATUS_KEY);
    return data ? JSON.parse(data) : {};
  } catch {
    return {};
  }
}

export function setCaseStatus(id: string, status: CaseStatus): void {
  const statuses = getCaseStatuses();
  statuses[id] = status;
  localStorage.setItem(CASE_STATUS_KEY, JSON.stringify(statuses));
  window.dispatchEvent(new Event("case-store-updated"));
}

export function getCaseActions(): Record<string, ActionTaken> {
  try {
    const data = localStorage.getItem(CASE_ACTION_KEY);
    return data ? JSON.parse(data) : {};
  } catch {
    return {};
  }
}

export function setCaseAction(id: string, action: ActionTaken): void {
  const actions = getCaseActions();
  actions[id] = action;
  localStorage.setItem(CASE_ACTION_KEY, JSON.stringify(actions));
  window.dispatchEvent(new Event("case-store-updated"));
}

export function getCaseClosedDates(): Record<string, string> {
  try {
    const data = localStorage.getItem(CASE_CLOSED_KEY);
    return data ? JSON.parse(data) : {};
  } catch {
    return {};
  }
}

export function setCaseClosedDate(id: string, date: string): void {
  const dates = getCaseClosedDates();
  dates[id] = date;
  localStorage.setItem(CASE_CLOSED_KEY, JSON.stringify(dates));
  window.dispatchEvent(new Event("case-store-updated"));
}

export function getCaseSnapshots(): Record<string, StoredCaseSnapshot> {
  try {
    const data = localStorage.getItem(CASE_SNAPSHOT_KEY);
    return data ? JSON.parse(data) : {};
  } catch {
    return {};
  }
}

export function getCaseSnapshot(id: string): StoredCaseSnapshot | undefined {
  return getCaseSnapshots()[id];
}

export function setCaseSnapshot(snapshot: StoredCaseSnapshot): void {
  const snapshots = getCaseSnapshots();
  snapshots[snapshot.caseData.id] = snapshot;
  localStorage.setItem(CASE_SNAPSHOT_KEY, JSON.stringify(snapshots));
  window.dispatchEvent(new Event("case-store-updated"));
}

export function getCaseWithSnapshot(baseCase: Case): Case {
  const snap = getCaseSnapshot(baseCase.id);
  if (!snap) return baseCase;
  // Merge: keep backend-sourced live data (orders, engine scores)
  // and — importantly — the AI-computed riskScore. The officer's
  // saved adjustment is a LEVEL-only override: we overlay riskLevel
  // from the snapshot when riskSaved, but riskScore stays the AI's
  // ground truth. The snapshot still stores a numeric `caseData.riskScore`
  // so the Save-Risk slider can remember where the officer left it,
  // but it never replaces the displayed case score.
  const useSavedRisk = snap.riskSaved === true;
  return {
    ...baseCase,
    riskScore:   baseCase.riskScore,
    riskLevel:   useSavedRisk ? snap.caseData.riskLevel : baseCase.riskLevel,
    actionTaken: snap.caseData.actionTaken ?? baseCase.actionTaken,
    closedDate:  snap.caseData.closedDate  ?? baseCase.closedDate,
    notes:       snap.caseData.notes       ?? baseCase.notes,
  };
}

// Close a case (set status, action, and date)
export function closeCase(id: string, action: ActionTaken): void {
  setCaseStatus(id, "Closed");
  setCaseAction(id, action);
  setCaseClosedDate(id, new Date().toISOString().split("T")[0]);
}

// Submit for tax review
export function submitForTaxReview(id: string): void {
  setCaseStatus(id, "Under Review by Tax");
  setCaseAction(id, "Submitted for Tax Review");
}

// Send case back to customs after tax review (NOT closed) — marks as "Reviewed by Tax"
export function returnToCustomsFromTax(id: string): void {
  setCaseStatus(id, "Reviewed by Tax");
}

// Move case to "Requested Input by Deemed Importer" status (visible in Customs ongoing dashboard)
export function requestThirdPartyInput(id: string): void {
  setCaseStatus(id, "Requested Input by Deemed Importer");
  setCaseAction(id, "Input Requested");
}

// Get effective status for a case (localStorage override or original)
export function getEffectiveCaseStatus(id: string, originalStatus: CaseStatus): CaseStatus {
  // Backend AI investigation status always takes priority — the agent
  // is actively processing and the frontend shouldn't override this.
  if (originalStatus === "AI Investigation in Progress") return originalStatus;
  const overrides = getCaseStatuses();
  return overrides[id] || originalStatus;
}

// Get effective action taken
export function getEffectiveCaseAction(id: string, originalAction?: ActionTaken): ActionTaken | undefined {
  const overrides = getCaseActions();
  return overrides[id] || originalAction;
}

// Append activities to an existing snapshot (or create one from a base case if needed).
export function appendActivities(
  baseCase: Case,
  newEntries: ActivityEntry[],
  patch?: Partial<Case>,
): void {
  const existing = getCaseSnapshot(baseCase.id);
  const baseActivities = existing?.activities ?? getInitialActivitiesForCase(baseCase);
  const mergedCase: Case = { ...(existing?.caseData ?? baseCase), ...patch };
  const mergedActivities = [...baseActivities, ...newEntries];
  setCaseSnapshot({
    caseData: mergedCase,
    activities: mergedActivities,
    riskSaved: existing?.riskSaved ?? false,
    vatSaved: existing?.vatSaved ?? false,
    vatCategory: existing?.vatCategory ?? "",
    updatedAt: new Date().toISOString(),
  });
}

// Build a timestamp string in "YYYY-MM-DD HH:mm" format
export function nowTimestamp(): string {
  return new Date()
    .toLocaleString("sv-SE", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    })
    .replace("T", " ");
}
