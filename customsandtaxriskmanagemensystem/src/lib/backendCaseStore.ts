// Bridge between Backend-V2 (REST + SSE) and the frontend Case model.
//
// Fetches cases from the backend, maps BackendCase → Case (with nested
// orders), and keeps them in sync via SSE. The existing caseStore.ts
// continues to manage localStorage UI state (status overrides, snapshots,
// activities) on top of the backend-sourced data.

import {
  fetchCases,
  subscribeCases,
  onStaleCaseDetected,
  type BackendCase,
} from "./apiClient";
import { regionForCountry } from "./referenceStore";
import type { Case, Order, CaseStatus, AISuggestedAction } from "./caseData";

let _backendCases: Map<string, BackendCase> = new Map();
let _started = false;
let _connected = false;  // true once initial fetch succeeds (even if 0 cases)
let _unsubscribe: (() => void) | null = null;

function notify(): void {
  window.dispatchEvent(new Event("case-store-updated"));
}

function upsert(c: BackendCase): void {
  if (!c?.Case_ID) return;
  _backendCases.set(c.Case_ID, c);
}

// ── Bootstrap ──────────────────────────────────────────────────────────────

export async function startBackendCaseStore(): Promise<void> {
  if (_started) return;
  _started = true;
  // Helper used for the bootstrap AND for SSE (re)connects. Always
  // replaces the map contents so the tab can never drift from the
  // backend — e.g. after uvicorn restarts or a re-seed happens while
  // this tab stays open.
  const refetch = async (label: string) => {
    try {
      const list = await fetchCases();
      _backendCases.clear();
      list.forEach(upsert);
      _connected = true;
      notify();
      console.log(`[backendCaseStore] ${label}: ${list.length} cases from backend`);
    } catch (err) {
      console.error(`[backendCaseStore] ${label} failed`, err);
      _connected = false;
    }
  };

  await refetch("initial fetch");

  _unsubscribe = subscribeCases(
    (ev) => {
      if (ev.event === "new_case" || ev.event === "case_updated") {
        if (ev.case) {
          upsert(ev.case);
          notify();
        }
      } else if (ev.event === "cases_reset" || ev.event === "reset") {
        _backendCases.clear();
        _connected = true;
        // Clear the localStorage UI state keys the live caseStore uses
        // so the frontend fully resets. (The long legacy list from
        // taxReviewStore was dropped when that store was deleted.)
        [
          "case-statuses", "case-actions", "case-closed-dates",
          "case-snapshots", "case-store-reset-v5",
        ].forEach((k) => localStorage.removeItem(k));
        notify();
      }
    },
    // onOpen — fires on initial connection AND on every auto-reconnect.
    // The initial open right after the bootstrap refetch is redundant
    // but harmless; subsequent opens catch backend restarts and any
    // state drift we missed while the SSE was disconnected.
    () => { void refetch("SSE (re)connect refetch"); },
  );

  // Self-heal on 404: if any officer action POSTs against a Case_ID the
  // backend doesn't have, the apiClient fires this callback before
  // throwing — we clear the stale map and re-pull from the backend so
  // the user's next click targets a real case.
  onStaleCaseDetected(() => {
    console.warn("[backendCaseStore] stale case detected — refetching");
    void refetch("stale-case 404 refetch");
  });
}

export function stopBackendCaseStore(): void {
  _unsubscribe?.();
  _unsubscribe = null;
  _started = false;
  _backendCases.clear();
}

// ── Accessors ──────────────────────────────────────────────────────────────

export function isBackendConnected(): boolean {
  return _connected;
}

export function hasBackendCases(): boolean {
  return _backendCases.size > 0;
}

export function getBackendCase(caseId: string): BackendCase | undefined {
  return _backendCases.get(caseId);
}

// ── Mapping: BackendCase → frontend Case ───────────────────────────────────

// Backend score → level fallback. Used when BackendCase.Overall_Case_Risk_Level
// is missing or not one of High/Medium/Low. The AI's own classifier
// (api.py:case_risk_level) only emits Medium/High for live amber cases,
// but a Low can legitimately appear on officer-overridden snapshots or
// legacy/historical cases — so the fallback keeps all three tiers.
function riskLevelOf(score: number | null): "High" | "Medium" | "Low" {
  const s = (score ?? 0) * 100;
  if (s >= 65) return "High";
  if (s >= 40) return "Medium";
  return "Low";
}

function aiSuggestedAction(bc: BackendCase): AISuggestedAction {
  // Prefer the backend slide-1 recommendation (same rule applied in
  // list and detail views); fall back to legacy score bands only if
  // the backend field is missing (e.g. older API build, or a seed
  // case predating the hydration update).
  const backend = bc.AI_Suggested_Customs_Action;
  if (backend === "Recommend Control"
   || backend === "Submit for Tax Review"
   || backend === "Request Input from Third Party"
   || backend === "Recommend Release") {
    return backend;
  }
  const s = ((bc.Overall_Case_Risk_Score ?? bc.Overall_Risk_Score ?? 0)) * 100;
  if (s >= 85) return "Recommend Control";
  if (s >= 70) return "Submit for Tax Review";
  if (s >= 55) return "Request Input from Third Party";
  return "Recommend Release";
}

function statusMapping(backendStatus: string): CaseStatus {
  const s = backendStatus ?? "";
  const sl = s.toLowerCase();
  // Exact matches first (backend uses these exact strings)
  if (s === "New") return "New";
  if (s === "Under Review by Customs") return "Under Review by Customs";
  if (s === "AI Investigation in Progress") return "AI Investigation in Progress";
  if (s === "Under Review by Tax") return "Under Review by Tax";
  if (s === "Reviewed by Tax") return "Reviewed by Tax";
  if (s === "Requested Input by Deemed Importer") return "Requested Input by Deemed Importer";
  if (s === "Closed") return "Closed";
  // Fallback fuzzy match. "Reviewed by Tax" is handled above — the
  // fuzzy "contains tax" rule would otherwise misclassify it into the
  // Tax queue even though the case is back in Customs.
  if (sl.includes("tax") || sl.includes("ai_invest")) return "Under Review by Tax";
  if (sl.includes("customs") || sl.includes("review")) return "Under Review by Customs";
  if (sl.includes("closed") || sl.includes("released") || sl.includes("retained")) return "Closed";
  if (sl.includes("input") || sl.includes("requested")) return "Requested Input by Deemed Importer";
  if (sl.includes("new") || s === "") return "New";
  return "Under Review by Customs";
}

function dateOnly(iso: string | null | undefined): string {
  if (!iso) return new Date().toISOString().split("T")[0];
  const i = iso.indexOf("T");
  return i > 0 ? iso.slice(0, i) : iso.slice(0, 10);
}

export function backendCaseToCase(bc: BackendCase): Case {
  const caseScore = bc.Overall_Case_Risk_Score ?? bc.Overall_Risk_Score ?? 0;

  // Map all orders from the backend (or fall back to the single joined order)
  const backendOrders = bc.orders ?? [];
  const orders: Order[] = backendOrders.length > 0
    ? backendOrders.map((o, i) => ({
        id: o.Sales_Order_ID ?? `${bc.Case_ID}-${i}`,
        salesOrderId: o.Sales_Order_Business_Key ?? "",
        productDescription: o.Product_Description ?? "Unknown product",
        itemValue: o.Product_Value ?? 0,
        riskScore: Math.round((o.Overall_Risk_Score ?? 0) * 100),
        date: dateOnly(bc.Created_time ?? bc.Update_time),
        vatPercent: Math.round((o.VAT_Rate ?? 0) * 100),
        vatValue: o.VAT_Fee ?? 0,
        vatSubcategoryCode: o.VAT_Subcategory_Code ?? null,
      }))
    : [{
        id: bc.Sales_Order_ID ?? bc.Sales_Order_Business_Key,
        salesOrderId: bc.Sales_Order_Business_Key,
        productDescription: bc.Product_Description ?? "Unknown product",
        itemValue: bc.Product_Value ?? 0,
        riskScore: Math.round((bc.Overall_Risk_Score ?? 0) * 100),
        date: dateOnly(bc.Created_time ?? bc.Update_time),
        vatPercent: Math.round((bc.VAT_Rate ?? 0) * 100),
        vatValue: bc.VAT_Fee ?? 0,
      }];

  const backendLevel = bc.Overall_Case_Risk_Level;
  const riskLevel: "High" | "Medium" | "Low" =
    backendLevel === "High" || backendLevel === "Medium" || backendLevel === "Low"
      ? backendLevel
      : riskLevelOf(caseScore);

  // Build case name from unique product descriptions
  const descriptions = [...new Set(orders.map(o => o.productDescription.split("—")[0].trim()))];
  const caseName = descriptions.length > 0
    ? `${descriptions.slice(0, 2).join(", ")}${descriptions.length > 2 ? " +" + (descriptions.length - 2) : ""} — ${bc.Seller_Name ?? "Unknown"}`
    : `Case ${bc.Case_ID}`;

  return {
    id: bc.Case_ID,
    caseName,
    orders,
    seller: bc.Seller_Name ?? "Unknown",
    declaredCategory: bc.HS_Product_Category ?? "Unclassified",
    aiSuggestedCategory: bc.Recommended_VAT_Product_Category ?? bc.HS_Product_Category ?? "",
    countryOfOrigin: bc.Country_Origin ?? "",
    countryOfDestination: bc.Country_Destination ?? "IE",
    riskScore: Math.round(caseScore * 100),
    riskLevel,
    status: statusMapping(bc.Status),
    aiSuggestedAction: aiSuggestedAction(bc),
    engineVatRatio: bc.Engine_VAT_Ratio ?? 0,
    engineMlWatchlist: bc.Engine_ML_Watchlist ?? 0,
    engineIeSellerWatchlist: bc.Engine_IE_Seller_Watchlist ?? 0,
    engineDescriptionVagueness: bc.Engine_Description_Vagueness ?? 0,
    aiAnalysis: bc.AI_Analysis,
    aiLegislationRefs: bc.AI_Legislation_Refs ?? null,
    aiCustomsAnalysis: bc.AI_Customs_Analysis ?? null,
    aiSuggestedTaxAction:
      bc.AI_Suggested_Tax_Action === "Confirm Risk"
      || bc.AI_Suggested_Tax_Action === "No/Limited Risk"
      || bc.AI_Suggested_Tax_Action === "AI Uncertain"
        ? bc.AI_Suggested_Tax_Action
        : null,
    aiTaxAnalysis: bc.AI_Tax_Analysis ?? null,
    communication: bc.Communication ?? [],
  };
}

// ── Get all cases as frontend Case[] ───────────────────────────────────────

// This frontend represents the Irish customs & tax authority. Non-IE cases
// are still received via SSE and remain in the store (so deep-links via
// getBackendCase still resolve), but they are hidden from list views.
// Replace with a per-authority context when other countries are added.
const AUTHORITY_COUNTRY = "IE";

export function getAllBackendCases(): Case[] {
  return [..._backendCases.values()]
    .filter((c) => c.Country_Destination === AUTHORITY_COUNTRY)
    .sort((a, b) =>
      (a.Created_time ?? a.Update_time ?? "")
        .localeCompare(b.Created_time ?? b.Update_time ?? "")
    )
    .map(backendCaseToCase);
}
