// Thin client for Backend-V2 C&T Risk Management REST + SSE.
//
// Backend lives at VITE_API_BASE_URL (defaults to http://localhost:8505,
// matching lib/config.py:API_PORT in the EU Custom Data Hub repo).
// CORS is open on the backend (allow_origins=["*"]).

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8505";

// ── Backend "hydrated case" shape ───────────────────────────────────────────
// Mirrors the SELECT in lib/database.py:get_case_hydrated. Snake_case kept.
export interface BackendCase {
  Case_ID: string;
  Sales_Order_Business_Key: string;
  Status: string;
  VAT_Problem_Type: string | null;
  Recommended_Product_Value: number | null;
  Recommended_VAT_Product_Category: string | null;
  Recommended_VAT_Rate: number | null;
  Recommended_VAT_Fee: number | null;
  AI_Analysis: string | null;
  AI_Confidence: number | null;
  VAT_Gap_Fee: number | null;
  Evaluation_by: string | null;
  Proposed_Action_Tax: string | null;
  Proposed_Action_Customs: string | null;
  Communication: Array<{ date: string; from: string; action: string; message: string }>;
  Additional_Evidence: string | null;
  Update_time: string;
  Updated_by: string;
  Created_time: string | null;
  // From Sales_Order
  Sales_Order_ID: string | null;
  HS_Product_Category: string | null;
  Product_Description: string | null;
  Product_Value: number | null;
  VAT_Rate: number | null;
  VAT_Fee: number | null;
  Seller_Name: string | null;
  Country_Origin: string | null;
  Country_Destination: string | null;
  // From Sales_Order_Risk
  Sales_Order_Risk_ID: string | null;
  Risk_Type: string | null;
  Overall_Risk_Score: number | null;
  Overall_Risk_Level: string | null;
  Seller_Risk_Score: number | null;
  Country_Risk_Score: number | null;
  Product_Category_Risk_Score: number | null;
  Manufacturer_Risk_Score: number | null;
  Confidence_Score: number | null;
  Proposed_Risk_Action: string | null;
  Overall_Risk_Description: string | null;
  // Case-level overall risk (averaged across orders)
  Overall_Case_Risk_Score: number | null;
  Overall_Case_Risk_Level: string | null;
  // Per-engine risk scores (0-1, averaged across orders in the case)
  Engine_VAT_Ratio: number | null;
  Engine_ML_Watchlist: number | null;
  Engine_IE_Seller_Watchlist: number | null;
  Engine_Description_Vagueness: number | null;
  // Slide-1 customs + tax recommendations computed at read time by the
  // backend (lib/database.py:_compute_customs_recommendation and
  // _compute_tax_recommendation). Unified across list and detail views
  // on both authorities — frontend must NOT recompute these rules.
  AI_Suggested_Customs_Action: string | null;
  AI_Customs_Analysis: string | null;
  AI_Suggested_Tax_Action: string | null;
  AI_Tax_Analysis: string | null;
  // Persisted legislation references cited by the VAT Fraud Detection
  // agent, in the same order the agent emitted them. Parsed from JSON
  // by the backend hydrator (lib/database.py:_hydrate_row), so it's
  // already an array here rather than a string.
  AI_Legislation_Refs: Array<{
    ref?: string;
    source?: string;
    section?: string;
    url?: string;
    page?: number | string | null;
    paragraph?: string | null;
  }> | null;
  // All orders in this case (populated by backend)
  transaction_count: number | null;
  orders: Array<{
    Sales_Order_ID: string;
    Sales_Order_Business_Key: string;
    HS_Product_Category: string | null;
    VAT_Subcategory_Code: string | null;
    Product_Description: string | null;
    Product_Value: number | null;
    VAT_Rate: number | null;
    VAT_Fee: number | null;
    Seller_Name: string | null;
    Country_Origin: string | null;
    Country_Destination: string | null;
    Overall_Risk_Score: number | null;
    Overall_Risk_Level: string | null;
  }> | null;
}

export async function fetchCases(): Promise<BackendCase[]> {
  const r = await fetch(`${BASE}/api/rg/cases`);
  if (!r.ok) throw new Error(`fetchCases: HTTP ${r.status}`);
  const data = await r.json();
  return (data.items ?? []) as BackendCase[];
}

export async function fetchCase(caseId: string): Promise<BackendCase | null> {
  const r = await fetch(`${BASE}/api/rg/cases/${caseId}`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`fetchCase: HTTP ${r.status}`);
  return (await r.json()) as BackendCase;
}

export type CaseStreamEvent =
  | { event: "new_case"; case: BackendCase }
  | { event: "case_updated"; action: string; case: BackendCase | null }
  | { event: "cases_reset" }
  | { event: "reset" };

export function subscribeCases(
  onEvent: (ev: CaseStreamEvent) => void,
  onOpen?: () => void,
): () => void {
  const es = new EventSource(`${BASE}/api/rg/cases/stream`);
  es.onopen = () => {
    // Fires on the initial connection AND on every auto-reconnect
    // (e.g. after the backend restarts or the network blips). The
    // consumer should re-fetch the case list here to stay in sync
    // with whatever the backend looks like now — EventSource by
    // itself does NOT replay missed events.
    onOpen?.();
  };
  es.onmessage = (m) => {
    try {
      const parsed = JSON.parse(m.data) as CaseStreamEvent;
      onEvent(parsed);
    } catch {
      /* ignore malformed event */
    }
  };
  es.onerror = () => {
    // EventSource auto-reconnects; nothing to do here — onOpen will
    // fire again once the connection is back and will trigger a
    // re-fetch via the consumer.
  };
  return () => es.close();
}

// ── Officer action POSTs ────────────────────────────────────────────────────
// Listeners notified when the backend returns 404 on a case-scoped action —
// the frontend's case list is out of sync with the DB (typical after a
// backend restart / re-seed). backendCaseStore subscribes and forces a
// full re-fetch so stale Case_IDs disappear from the UI instead of
// silently producing more 404s on every action.
const _staleCaseListeners = new Set<() => void>();
export function onStaleCaseDetected(cb: () => void): () => void {
  _staleCaseListeners.add(cb);
  return () => _staleCaseListeners.delete(cb);
}

async function post(path: string, body: unknown): Promise<void> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    if (r.status === 404 && path.startsWith("/api/rg/cases/")) {
      // The backend doesn't have this case — almost always because the
      // tab's cached case list predates a backend restart / re-seed.
      // Signal the store so it re-syncs before the user clicks again.
      _staleCaseListeners.forEach((cb) => { try { cb(); } catch { /**/ } });
      throw new Error(
        `Case not found on backend (404). The case list was out of date — `
        + `it has been refreshed. Please retry.`,
      );
    }
    throw new Error(`POST ${path}: HTTP ${r.status}`);
  }
}

export const customsAction = (caseId: string, body: {
  action: "tax_review" | "retainment" | "release" | "input_requested";
  comment?: string;
  officer?: string;
}) => post(`/api/rg/cases/${caseId}/customs-action`, body);

export const taxAction = (caseId: string, body: {
  action: "risk_confirmed" | "no_limited_risk" | "input_requested";
  comment?: string;
  officer?: string;
  vat_category?: string;
}) => post(`/api/rg/cases/${caseId}/tax-action`, body);

export const addCommunication = (caseId: string, body: {
  from: string; action: string; message: string;
}) => post(`/api/rg/cases/${caseId}/communication`, body);

export interface PreviousCase {
  Case_ID: string;
  Status: string;
  VAT_Problem_Type: string | null;
  Overall_Case_Risk_Score: number | null;
  Overall_Case_Risk_Level: string | null;
  Seller_Name: string | null;
  Country_Origin: string | null;
  Country_Destination: string | null;
  HS_Product_Category: string | null;
  Product_Description: string | null;
  Proposed_Action_Customs: string | null;
  order_count: number;
}

export interface CorrelatedCase {
  Case_ID: string;
  Status: string;
  VAT_Problem_Type: string | null;
  Overall_Case_Risk_Score: number | null;
  Overall_Case_Risk_Level: string | null;
  Seller_Name: string | null;
  Country_Origin: string | null;
  Country_Destination: string | null;
  HS_Product_Category: string | null;
  Product_Description: string | null;
  order_count: number;
}

export type AgentProposal = {
  action: string;   // role-specific action id (risk_confirmed, retainment, …)
  comment: string;  // short justification text the LLM wrote
};

export type AgentMode = "advisor" | "action";

export type AgentAnswer = {
  answer: string;
  proposal: AgentProposal | null;
  mode: AgentMode;
};

export async function askCaseAgent(
  caseId: string,
  question: string,
  role: "customs" | "tax" = "customs",
  mode?: AgentMode,
): Promise<AgentAnswer> {
  const r = await fetch(`${BASE}/api/rg/cases/${caseId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, role, ...(mode ? { mode } : {}) }),
  });
  if (!r.ok) {
    if (r.status === 404) {
      // Stale case — the tab's cached Case_ID predates a backend
      // restart / re-seed, or the case was archived. Self-heal by
      // re-fetching so the UI drops the dead case, and tell the user
      // without leaking "404" at them.
      _staleCaseListeners.forEach((cb) => { try { cb(); } catch { /**/ } });
      return {
        answer: "This case is no longer on the backend — the list has been "
              + "refreshed. Please reopen the case from the list if it still "
              + "exists and try again.",
        proposal: null,
        mode: "advisor",
      };
    }
    return {
      answer: `Error contacting AI assistant (HTTP ${r.status}).`,
      proposal: null,
      mode: "advisor",
    };
  }
  const data = await r.json();
  return {
    answer:   data.answer   ?? "No response.",
    proposal: data.proposal ?? null,
    mode:     (data.mode === "action" ? "action" : "advisor") as AgentMode,
  };
}

export async function fetchPreviousCases(caseId: string): Promise<PreviousCase[]> {
  const r = await fetch(`${BASE}/api/rg/cases/${caseId}/previous`);
  if (!r.ok) return [];
  const data = await r.json();
  return data.items ?? [];
}

export async function fetchCorrelatedCases(caseId: string): Promise<CorrelatedCase[]> {
  const r = await fetch(`${BASE}/api/rg/cases/${caseId}/correlated`);
  if (!r.ok) return [];
  const data = await r.json();
  return data.items ?? [];
}

// ── Reference data (lookups for dropdowns / categories) ─────────────────────
export interface VatCategory    { label: string; rate: number; description: string | null }
export interface VatSubcategory { code: string; name: string }
export interface RiskLevel      { name: string; display_color: string | null }
export interface EuRegion       { country_code: string; country_name: string | null; region: string }
export interface SuspicionType  { name: string; description: string | null; icon: string | null; color: string | null }
export interface StatusRef      { name: string; description: string | null }
export interface ActionRef      { code: string; label: string; description: string | null }
export interface RiskSignal     { key: string; label: string; description: string | null }
export interface RiskThresholds { release: number; retain: number }

export interface ReferenceBundle {
  vat_categories:        VatCategory[];
  // parent-category label → list of child subcategories
  vat_subcategories:     Record<string, VatSubcategory[]>;
  // destination country → subcategory code → VAT rate (fraction).
  // Only exceptions to the country standard are present.
  vat_rates_by_country:  Record<string, Record<string, number>>;
  // Per-destination standard VAT rate (fraction) — fallback when a
  // specific (country, subcategory) isn't in vat_rates_by_country.
  country_standard_rate: Record<string, number>;
  risk_levels:           RiskLevel[];
  regions:               EuRegion[];
  suspicion_types:       SuspicionType[];
  case_statuses:         StatusRef[];
  sales_order_statuses:  StatusRef[];
  customs_actions:       ActionRef[];
  tax_actions:           ActionRef[];
  risk_engine_signals:   RiskSignal[];
  risk_thresholds:       RiskThresholds;
}

export async function fetchReference(): Promise<ReferenceBundle> {
  const r = await fetch(`${BASE}/api/reference`);
  if (!r.ok) throw new Error(`fetchReference: HTTP ${r.status}`);
  return (await r.json()) as ReferenceBundle;
}
