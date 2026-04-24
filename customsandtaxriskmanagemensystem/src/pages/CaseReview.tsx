import { useParams, useNavigate } from "react-router-dom";
import { useEffect, useState, useMemo, useRef } from "react";
import type { Order } from "@/lib/caseData";
import { customsAction, taxAction, addCommunication, fetchPreviousCases, fetchCorrelatedCases, askCaseAgent, type PreviousCase, type CorrelatedCase } from "@/lib/apiClient";
import { statusStyles, riskLevelStyles } from "@/lib/styles";
import { getRiskEngineSignals } from "@/lib/referenceStore";
import { vatRatesByCategory } from "@/lib/vatRates";
import { VATAssessmentSection } from "@/components/case/VATAssessmentSection";
import {
  actionLabelOf,
  CUSTOMS_ACTION_LABELS,
  TAX_ACTION_LABELS,
  VALID_CUSTOMS_LABELS,
  VALID_TAX_LABELS,
} from "@/lib/caseEnum";

// Risk-signal display names — single source of truth. Canonical values
// live in the backend risk_engine_signals table and are fetched at
// startup into referenceStore. We fall back to hardcoded names (kept
// in sync with the backend seed) so the UI renders sensibly even when
// the reference fetch hasn't completed yet.
// Normalise AI-summary text: the rule-built summaries concatenate
// rationale fragments from different sources (backend + FE override
// sentences + signal breakdowns), so they occasionally end up with
// ".." or stray spaces before punctuation. This helper collapses the
// common cases so the rendered text reads cleanly.
function cleanupText(s: string | null | undefined): string {
  if (!s) return "";
  return s
    // "..", "..." → "."
    .replace(/\.{2,}/g, ".")
    // ". ." → "."
    .replace(/\.\s*\./g, ".")
    // ",," → ","
    .replace(/,\s*,/g, ",")
    // space before punctuation
    .replace(/\s+([.,;:!?])/g, "$1")
    // collapse multiple spaces
    .replace(/ {2,}/g, " ")
    .trim();
}

const SIGNAL_LABEL_FALLBACK: Record<string, string> = {
  vat_ratio:             "Product Category - VAT Rate Consistency",
  watchlist:             "VAT Product Category Misclassification",
  ireland_watchlist:     "IE Seller Risk",
  description_vagueness: "Vague Description",
};
function signalLabel(key: string): string {
  const hit = getRiskEngineSignals().find((s) => s.key === key);
  return hit?.label ?? SIGNAL_LABEL_FALLBACK[key] ?? key;
}
import {
  getLiveCases, getLiveClosedCases,
  getInitialActivitiesForCase,
  type Case,
  type ActivityEntry,
  type AISuggestedAction,
} from "@/lib/caseData";
import { useCaseTab } from "@/pages/CustomsLayout";
import { useTaxCaseTab } from "@/pages/TaxLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Slider } from "@/components/ui/slider";
import {
  ArrowLeft,
  AlertTriangle,
  Save,
  MessageSquarePlus,
  Bot,
  Sparkles,
  XCircle,
  CheckCircle2,
  FileSearch,
  UserRound,
  Gauge,
  RefreshCw,
  FolderOpen,
  ClipboardPenLine,
  HelpCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/use-toast";
import {
  closeCase,
  submitForTaxReview as submitCaseForTaxReview,
  setCaseStatus as persistCaseStatus,
  setCaseAction,
  returnToCustomsFromTax,
  requestThirdPartyInput,
  getEffectiveCaseStatus,
  getEffectiveCaseAction,
  getCaseSnapshot,
  getCaseWithSnapshot,
  setCaseSnapshot,
  appendActivities,
  nowTimestamp,
} from "@/lib/caseStore";


// Reduce a list of order product descriptions to a single base-product label
// (AI summary of core meaning), e.g. "iPhone 13", "Samsung Galaxy S24" -> "Smartphone".
function getBaseProductFromOrders(orders: { productDescription: string }[]): string {
  const text = orders.map((o) => o.productDescription.toLowerCase()).join(" ");
  const map: { match: RegExp; label: string }[] = [
    { match: /airpod|earbud|earphone/, label: "Wireless Earbuds" },
    { match: /headphone/, label: "Headphones" },
    { match: /iphone|galaxy|pixel|smartphone|mobile phone/, label: "Smartphone" },
    { match: /macbook|laptop|notebook/, label: "Laptop" },
    { match: /ipad|learning tablet|kids tablet/, label: "Tablet" },
    { match: /e-ink|course reader|e-reader|ereader|kindle/, label: "E-Reader" },
    { match: /apple watch|smart watch|smartwatch/, label: "Smartwatch" },
    { match: /fitness tracker|activity band|fitness band/, label: "Fitness Tracker" },
    { match: /drone|aerial/, label: "Drone Camera" },
    { match: /action camera|gopro/, label: "Action Camera" },
    { match: /dslr|mirrorless|camcorder/, label: "Camera" },
    { match: /tv|television/, label: "Television" },
    { match: /monitor|display/, label: "Monitor" },
    { match: /power bank/, label: "Power Bank" },
    { match: /charger|adapter/, label: "Charger" },
    { match: /cable/, label: "Cable" },
    { match: /vacuum/, label: "Vacuum Cleaner" },
    { match: /led face mask/, label: "LED Face Mask" },
    { match: /hair (curl|straight|dry)/, label: "Hair Styling Tool" },
    { match: /electric toothbrush/, label: "Electric Toothbrush" },
    { match: /coding robot|robot kit/, label: "Coding Robot Kit" },
    { match: /brain game|memory training|logic puzzle/, label: "Electronic Game Console" },
    { match: /barbie|doll/, label: "Doll" },
    { match: /lego|building block/, label: "Building Blocks" },
    { match: /puzzle/, label: "Puzzle" },
    { match: /smart speaker|voice assistant/, label: "Smart Speaker" },
    { match: /shoe|sneaker|boot|footwear/, label: "Footwear" },
    { match: /shirt|jacket|trouser|dress|clothing|apparel|hoodie/, label: "Apparel" },
    { match: /bag|backpack|handbag|wallet/, label: "Bag / Accessory" },
    { match: /textbook|psychology|course book/, label: "Textbook" },
    { match: /book|magazine/, label: "Printed Material" },
    { match: /supplement|vitamin/, label: "Supplement" },
    { match: /cosmetic|skincare|makeup/, label: "Cosmetic Product" },
    { match: /furniture|chair|table|sofa|desk/, label: "Furniture" },
    { match: /drill|hammer|wrench|screwdriver/, label: "Hand Tool" },
  ];
  for (const { match, label } of map) {
    if (match.test(text)) return label;
  }
  // Fallback: first word of first description, capitalised.
  const first = orders[0]?.productDescription.split("—")[0].trim().split(" ")[0] ?? "Item";
  return first.charAt(0).toUpperCase() + first.slice(1).toLowerCase();
}

type OfficerRiskLevel = "High" | "Medium" | "Low";



// Customs / Tax officer action lists — derived from caseEnum.ts
// (the single source of truth bridging wire codes ↔ labels). Tax
// deliberately excludes "Request Input from Deemed Importer": that
// action is Customs-only.
const customsActions = Object.values(CUSTOMS_ACTION_LABELS) as AISuggestedAction[];
const taxActions     = Object.values(TAX_ACTION_LABELS);

export default function CaseReview() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { toast } = useToast();

  // Determine if viewing as tax authority based on URL
  const isTaxView = window.location.pathname.startsWith("/tax-authority");

  const customsTab = useCaseTab();
  const taxTab = useTaxCaseTab();
  const { openTab } = isTaxView ? taxTab : customsTab;
  const { closeTab } = isTaxView ? taxTab : customsTab;

  // Re-render when backend pushes case updates (SSE)
  const [, forceUpdate] = useState(0);
  useEffect(() => {
    const handler = () => forceUpdate(v => v + 1);
    window.addEventListener("case-store-updated", handler);
    window.addEventListener("tax-review-updated", handler);
    return () => {
      window.removeEventListener("case-store-updated", handler);
      window.removeEventListener("tax-review-updated", handler);
    };
  }, []);

  const allCases = [...getLiveCases(), ...getLiveClosedCases()];
  const baseCaseData = allCases.find((c) => c.id === id);
  const storedSnapshot = baseCaseData ? getCaseSnapshot(baseCaseData.id) : undefined;
  const caseData: Case | undefined = baseCaseData ? getCaseWithSnapshot(baseCaseData) : undefined;

  // Track case status — sync from backend when it changes
  const backendStatus = caseData?.status ?? "New";
  const [caseStatus, setCaseStatus] = useState(backendStatus);
  useEffect(() => {
    setCaseStatus(backendStatus);
  }, [backendStatus]);
  const [riskSaved, setRiskSaved] = useState(storedSnapshot?.riskSaved ?? false);
  const [vatSaved, setVatSaved] = useState(storedSnapshot?.vatSaved ?? false);
  const [vatCategory, setVatCategory] = useState<string>(storedSnapshot?.vatCategory ?? "");
  // The officer's adjustment is a LEVEL override stored as a label.
  // null = no override picked yet. The AI's numeric riskScore stays
  // untouched everywhere; only the level can diverge from the AI.
  const [adjustedRiskLevel, setAdjustedRiskLevel] = useState<OfficerRiskLevel | null>(
    storedSnapshot?.riskSaved
      ? (storedSnapshot.caseData.riskLevel as OfficerRiskLevel)
      : null
  );
  const [selectedAction, setSelectedAction] = useState<string>("");
  const [activities, setActivities] = useState<ActivityEntry[]>(storedSnapshot?.activities ?? []);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [showApplyDialog, setShowApplyDialog] = useState(false);
  const [showRuleDialog, setShowRuleDialog] = useState(false);
  const [showAddNoteDialog, setShowAddNoteDialog] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [saveNoteText, setSaveNoteText] = useState("");
  const [applyNoteText, setApplyNoteText] = useState("");
  const [backendPrevCases, setBackendPrevCases] = useState<PreviousCase[]>([]);
  const [backendCorrelatedCases, setBackendCorrelatedCases] = useState<CorrelatedCase[]>([]);
  const [chatMessages, setChatMessages] = useState<Array<{
    role: "user" | "assistant";
    text: string;
    // Agentic proposal attached to an assistant message — renders as an
    // Apply/Cancel card under the bubble. `applied` flips to true after
    // the officer presses Apply so the buttons disable and the card
    // freezes with its final state.
    proposal?: {
      action: string;
      comment: string;
      applied?: "pending" | "applying" | "done" | "cancelled";
    };
  }>>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  // Latest unresolved proposal from the Tax agent. Held here (not on a
  // message) so the NEXT user reply can be interpreted as a
  // confirmation/cancellation of THIS proposal — the whole "click
  // Apply" UX is gone; the officer confirms by typing "yes" / "no" in
  // the chat. Null when no proposal is pending.
  const [pendingProposal, setPendingProposal] = useState<{
    action: string;
    comment: string;
  } | null>(null);
  const [createRule, setCreateRule] = useState(false);
  const [informMemberStates, setInformMemberStates] = useState(false);
  const [selectedCorrelations, setSelectedCorrelations] = useState<string[]>([]);
  const [actionApplied, setActionApplied] = useState(false);

  useEffect(() => {
    if (caseData) {
      // Read the effective status BEFORE calling openTab — the base
      // caseData.status is the stale backend value, so it would file a
      // locally-closed case under "Ongoing Cases" in the sidebar until
      // a page refresh. Using effectiveStatus fixes that.
      const effectiveStatus = getEffectiveCaseStatus(caseData.id, caseData.status);
      openTab(caseData.id, caseData.id, effectiveStatus === "Closed");
      setAdjustedRiskLevel(
        storedSnapshot?.riskSaved
          ? (storedSnapshot.caseData.riskLevel as OfficerRiskLevel)
          : null
      );
      setRiskSaved(storedSnapshot?.riskSaved ?? false);
      setVatSaved(storedSnapshot?.vatSaved ?? false);
      setVatCategory(storedSnapshot?.vatCategory ?? "");

      // Fetch previous and correlated cases from backend
      fetchPreviousCases(caseData.id).then(setBackendPrevCases).catch(() => {});
      fetchCorrelatedCases(caseData.id).then(setBackendCorrelatedCases).catch(() => {});

      // Prefilled "Recommended action to Case". Guard: only seat a
      // value the officer's Select will actually render as a SelectItem
      // (VALID_*_LABELS comes from caseEnum.ts — same canonical set
      // the backend serves). Otherwise fall back to empty so the
      // dropdown shows its placeholder and the officer has to choose.
      const safeSet = (v: string | undefined | null, allowed: ReadonlySet<string>) =>
        setSelectedAction(v && allowed.has(v) ? v : "");
      if (isTaxView) {
        safeSet(caseData.aiSuggestedTaxAction ?? undefined, VALID_TAX_LABELS);
      } else {
        // Reviewed-by-Tax cases: prefer the customs action the Tax
        // verdict mapped to (persisted via setCaseAction). Note the
        // "Submit for Tax Review" SelectItem is hidden when status is
        // Reviewed-by-Tax, so filter it out of the allowed set here
        // rather than seating an option the Select won't render.
        const reviewedByTaxAction = effectiveStatus === "Reviewed by Tax"
          ? getEffectiveCaseAction(caseData.id, undefined)
          : undefined;
        const allowed = effectiveStatus === "Reviewed by Tax"
          ? new Set([...VALID_CUSTOMS_LABELS].filter(v => v !== "Submit for Tax Review"))
          : VALID_CUSTOMS_LABELS;
        safeSet(reviewedByTaxAction ?? caseData.aiSuggestedAction, allowed);
      }

      const now = nowTimestamp();
      // Activity log: prefer the persisted snapshot (officer edits),
      // otherwise synthesise the two canonical "case created / risk
      // evaluated" entries. The mockActivities table was tied to
      // hardcoded case IDs (C-26-*) and silently no-op'd for
      // backend-sourced cases, so it's been removed.
      const initialActivities: ActivityEntry[] = storedSnapshot?.activities?.length
        ? [...storedSnapshot.activities]
        : getInitialActivitiesForCase(caseData);

      // First time a customs officer opens a "New" case → status auto-changes to "Under Review by Customs"
      if (!isTaxView && effectiveStatus === "New") {
        setCaseStatus("Under Review by Customs");
        persistCaseStatus(caseData.id, "Under Review by Customs");
        initialActivities.push({
          id: `act-status-${Date.now()}`,
          timestamp: now,
          type: "status_update",
          description: "Status changed to Under Review by Customs.",
          by: "Customs Authority Officer",
        });
        // Persist snapshot so the activity log survives a reload
        setCaseSnapshot({
          caseData: { ...caseData, status: "Under Review by Customs" },
          activities: initialActivities,
          riskSaved: storedSnapshot?.riskSaved ?? false,
          vatSaved: storedSnapshot?.vatSaved ?? false,
          vatCategory: storedSnapshot?.vatCategory ?? "",
          updatedAt: new Date().toISOString(),
        });
      } else {
        setCaseStatus(effectiveStatus);
      }

      setActivities(initialActivities);
    }
  }, [caseData?.id, isTaxView]);

  if (!caseData) {
    return (
      <main className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <h2 className="text-xl font-semibold text-foreground mb-2">Case not found</h2>
          <Button variant="outline" onClick={() => navigate(isTaxView ? "/tax-authority" : "/customs-authority")}>
            Back to Dashboard
          </Button>
        </div>
      </main>
    );
  }

  const persistSnapshot = (
    nextCaseData: Case,
    nextActivities: ActivityEntry[],
    nextRiskSaved: boolean,
    extras?: { vatSaved?: boolean; vatCategory?: string; riskSaveNote?: string },
  ) => {
    const existing = getCaseSnapshot(nextCaseData.id);
    setCaseSnapshot({
      caseData: nextCaseData,
      activities: nextActivities,
      riskSaved: nextRiskSaved,
      // Preserve a previously-saved risk note unless the caller passes
      // a fresh one (e.g. on Save Risk); undefined means "leave as is".
      riskSaveNote: extras?.riskSaveNote !== undefined ? extras.riskSaveNote : existing?.riskSaveNote,
      vatSaved: extras?.vatSaved ?? vatSaved,
      vatCategory: extras?.vatCategory ?? vatCategory,
      updatedAt: new Date().toISOString(),
    });
  };

  const handleSaveVat = (category: string, note: string, subcategory?: string) => {
    const timestamp = nowTimestamp();
    const subcatSuffix = subcategory ? ` / ${subcategory}` : "";
    const entry: ActivityEntry = {
      id: `act-vat-${Date.now()}`,
      timestamp,
      type: "note",
      description: `VAT assessment updated. Category: ${category || "Not set"}${subcatSuffix}.${note ? ` Note: ${note}` : ""}`,
      by: "Tax Authority Officer",
    };
    const nextActivities = [...activities, entry];
    setActivities(nextActivities);
    setVatSaved(true);
    setVatCategory(category);
    persistSnapshot(caseData, nextActivities, riskSaved, { vatSaved: true, vatCategory: category });

    // Re-evaluate the suggested action once the officer has locked in
    // their VAT category — the case's total VAT gap now reflects
    // officer-confirmed vs declared rates. Logic mirrors the Tax rule
    // used at case-open (Rules in App.pptx, slide 1):
    //   |sum(per-order gap)| < €1         → No/Limited Risk
    //   retPct > 0.75                     → Confirm Risk
    //   otherwise                         → Request 3rd Party
    if (isTaxView) {
      const officerRate  = vatRatesByCategory()[category] ?? 0;
      const totalVatGap  = caseData.orders.reduce((sum, o) => {
        const officerVat = o.itemValue * (officerRate / 100);
        return sum + (officerVat - o.vatValue);
      }, 0);
      // Use the backend-sourced previous cases (fetched on mount),
      // filtered to the same seller. Falls back to an empty list when
      // the backend hasn't responded yet — retPct is then 0 so the
      // logic routes to "No/Limited Risk" / third-party input, which
      // is the safer default than acting on stale mock data.
      const prevCases = backendPrevCases
        .filter((c) => c.Case_ID !== caseData.id && c.Seller_Name === caseData.seller);
      const total    = prevCases.length;
      const retained = prevCases.filter((c) => c.Proposed_Action_Customs === "retain").length;
      const retPct   = total > 0 ? retained / total : 0;

      if (Math.abs(totalVatGap) < 1) {
        setSelectedAction("No/Limited Risk");
      } else if (retPct > 0.75) {
        setSelectedAction("Confirm Risk");
      } else {
        // Tax can't actually pick this action (Customs-only), but the
        // downstream branch treats it as "no firm verdict" — same
        // behaviour as before the mock removal.
        setSelectedAction("No/Limited Risk");
      }
    }

    toast({ title: "VAT Assessment saved", description: `Category: ${category || "Not set"}.` });
  };

  // Officer edits only change the LEVEL — the score remains the AI's
  // ground truth in every persisted copy of the case.
  const persistedRiskScore = caseData.riskScore;
  const persistedRiskLevel = riskSaved && adjustedRiskLevel ? adjustedRiskLevel : caseData.riskLevel;

  const isClosed = caseStatus === "Closed" || caseData.status === "Closed";
  const isAiInvestigating = caseData.status === "AI Investigation in Progress" || caseStatus === "AI Investigation in Progress";
  const orders = caseData.orders;
  const valueRange =
    orders.length > 0
      ? `€${Math.min(...orders.map((o) => o.itemValue)).toFixed(2)} – €${Math.max(...orders.map((o) => o.itemValue)).toFixed(2)}`
      : "—";
  const vatRange =
    orders.length > 0
      ? `€${Math.min(...orders.map((o) => o.vatValue)).toFixed(2)} – €${Math.max(...orders.map((o) => o.vatValue)).toFixed(2)}`
      : "—";
  const vatPercents = [...new Set(orders.map((o) => `${o.vatPercent}%`))].join(", ");

  const orderDescriptions = [...new Set(orders.map((o) => o.productDescription.split("—")[0].trim()))];
  const totalValue = orders.reduce((s, o) => s + o.itemValue, 0);
  const minValue = orders.length > 0 ? Math.min(...orders.map((o) => o.itemValue)) : 0;
  const maxValue = orders.length > 0 ? Math.max(...orders.map((o) => o.itemValue)) : 0;
  const vatPct = (v: number | undefined) => `${Math.round((v ?? 0) * 100)}%`;

  // ── Engine weights (mirror ENGINE_WEIGHTS in the EU Custom Data Hub
  // backend, api.py:_compute_score). Used to convert per-engine averages
  // into shares of the overall case score so the Risk Signals readout
  // sums to ~100 % instead of four independent severity numbers.
  const ENGINE_WEIGHTS = {
    vatRatio:  0.5,
    ml:        0.9,
    ieSeller:  1.0,
    vagueness: 0.8,
  } as const;

  const engVal = {
    vatRatio:  caseData.engineVatRatio               ?? 0,
    ml:        caseData.engineMlWatchlist            ?? 0,
    ieSeller:  caseData.engineIeSellerWatchlist      ?? 0,
    vagueness: caseData.engineDescriptionVagueness   ?? 0,
  };
  const weighted = {
    vatRatio:  engVal.vatRatio  * ENGINE_WEIGHTS.vatRatio,
    ml:        engVal.ml        * ENGINE_WEIGHTS.ml,
    ieSeller:  engVal.ieSeller  * ENGINE_WEIGHTS.ieSeller,
    vagueness: engVal.vagueness * ENGINE_WEIGHTS.vagueness,
  };
  const totalWeighted =
    weighted.vatRatio + weighted.ml + weighted.ieSeller + weighted.vagueness;
  // Absolute contribution of each engine in "points out of 100" on the
  // same scale as the overall case risk score. The four contribPts
  // values sum approximately to caseData.riskScore; any small residual
  // between Σ contribPts and riskScore comes from the per-order
  // vat_ratio floor and min(1.0, …) cap applied before orders are
  // averaged into the case, so it's not a simple linear reconstruction.
  const contribPts = (w: number): number => Math.round(w * 100);
  const shareOf = (w: number): number =>
    totalWeighted > 0 ? Math.round((w / totalWeighted) * 100) : 0;

  // Build engine signal summaries aligned with the Risk Signals panel
  // below. Each signal is reported as its share of the case risk.
  const signalParts: string[] = [];
  if (engVal.vatRatio > 0)
    signalParts.push(`${signalLabel("vat_ratio")} contributes ${shareOf(weighted.vatRatio)}%`);
  if (engVal.ml > 0)
    signalParts.push(`${signalLabel("watchlist")} contributes ${shareOf(weighted.ml)}%`);
  if (engVal.ieSeller > 0)
    signalParts.push(`${signalLabel("ireland_watchlist")} contributes ${shareOf(weighted.ieSeller)}%`);
  if (engVal.vagueness > 0)
    signalParts.push(`${signalLabel("description_vagueness")} contributes ${shareOf(weighted.vagueness)}%`);

  // Officer-override attribution. `getCaseWithSnapshot` now preserves
  // the AI score on `caseData.riskScore`, so base and caseData agree
  // on the score — only the level can diverge (level-only override).
  const aiRiskScore = caseData.riskScore;
  const aiRiskLevel = baseCaseData.riskLevel;
  const overrideSignificant = riskSaved && aiRiskLevel !== caseData.riskLevel;

  const aiSummary = cleanupText([
    `Case contains ${orders.length} order${orders.length !== 1 ? "s" : ""} from ${caseData.seller} (${caseData.countryOfOrigin} → ${caseData.countryOfDestination})`,
    orders.length > 0 ? `, totalling €${totalValue.toFixed(2)}` : "",
    `. Products: ${orderDescriptions.slice(0, 3).join(", ")}${orderDescriptions.length > 3 ? ` (+${orderDescriptions.length - 3} more)` : ""}`,
    `. Declared category: "${caseData.declaredCategory}"`,
    orders.length > 1 ? ` with values €${minValue.toFixed(2)}–€${maxValue.toFixed(2)}` : ` valued at €${minValue.toFixed(2)}`,
    `. `,
    signalParts.length > 0
      ? `Risk signals: ${signalParts.join("; ")}.`
      : `No significant risk signals detected.`,
    ` Overall case risk: ${caseData.riskScore}/100 (${caseData.riskLevel}).`,
    overrideSignificant
      ? ` Officer adjusted the overall risk to ${caseData.riskLevel} (${caseData.riskScore}/100), superseding the AI's initial assessment of ${aiRiskLevel} (${aiRiskScore}/100).`
      : "",
  ].join(""));

  // Detail strings swap wording depending on whether the engine is
  // actually firing, so a 0 % row doesn't read like it found something.
  // Threshold mirrors the backend's 0.5 per-engine flag cut-off.
  const fires = {
    vatRatio:  engVal.vatRatio  >= 0.5,
    ml:        engVal.ml        >= 0.5,
    ieSeller:  engVal.ieSeller  >= 0.5,
    vagueness: engVal.vagueness >= 0.5,
  };
  // Intermediate severity (0 < raw < 0.5): worth mentioning but not a
  // primary driver on its own.
  const mild = {
    vatRatio:  engVal.vatRatio  > 0 && !fires.vatRatio,
    ml:        engVal.ml        > 0 && !fires.ml,
    ieSeller:  engVal.ieSeller  > 0 && !fires.ieSeller,
    vagueness: engVal.vagueness > 0 && !fires.vagueness,
  };

  const mkFeature = (
    feature: string,
    weightedValue: number,
    detail: string,
  ) => ({
    feature,
    // Absolute contribution in points (sums ≈ riskScore).
    contribution: contribPts(weightedValue),
    // Share of the four engines' total weighted sum (sums to 100 %).
    share:        shareOf(weightedValue),
    detail,
  });

  const mlFeatures = [
    mkFeature(
      signalLabel("vat_ratio"),
      weighted.vatRatio,
      (
        fires.vatRatio
          ? `Declared VAT rate diverges materially from the expected rate for the declared subcategory in ${caseData.countryOfDestination}.`
        : mild.vatRatio
          ? `Declared VAT rate shows a minor deviation from the expected rate in ${caseData.countryOfDestination} — a soft signal on its own.`
        : `Declared VAT rate matches the expected rate for the declared subcategory in ${caseData.countryOfDestination}.`
      ),
    ),
    mkFeature(
      signalLabel("watchlist"),
      weighted.ml,
      (
        fires.ml
          ? `ML model flags seller "${caseData.seller}" shipping "${caseData.declaredCategory}" to ${caseData.countryOfDestination} as a known compliance-risk pattern.`
        : mild.ml
          ? `ML model notes some compliance-risk characteristics for "${caseData.seller}" on this route, below the flag threshold.`
        : `ML model shows no compliance-risk history for "${caseData.seller}" shipping "${caseData.declaredCategory}" to ${caseData.countryOfDestination}.`
      ),
    ),
    mkFeature(
      signalLabel("ireland_watchlist"),
      weighted.ieSeller,
      (
        caseData.countryOfDestination !== "IE"
          ? `Engine only applies to IE-destined orders — not applicable for this case.`
        : fires.ieSeller
          ? `Seller × origin pair matches the current Irish authority watchlist.`
        : `Seller × origin pair is not on the current Irish authority watchlist.`
      ),
    ),
    mkFeature(
      signalLabel("description_vagueness"),
      weighted.vagueness,
      (
        fires.vagueness
          ? `Embedding-model analysis of the product descriptions flags ambiguous or generic wording that obscures the true nature of the goods.`
        : mild.vagueness
          ? `Embedding-model sees some genericity in the product descriptions, below the flag threshold.`
        : `Product descriptions across the orders are specific enough to identify the goods — no vagueness signal.`
      ),
    ),
  ];

  const activityIcon = (type: string, _by: string) => {
    switch (type) {
      case "risk_update":
        return <Gauge className="h-3.5 w-3.5 text-warning" />;
      case "status_update":
        return <RefreshCw className="h-3.5 w-3.5 text-primary" />;
      case "action":
        return <CheckCircle2 className="h-3.5 w-3.5 text-success" />;
      case "note":
        return <ClipboardPenLine className="h-3.5 w-3.5 text-muted-foreground" />;
      default:
        return <FolderOpen className="h-3.5 w-3.5 text-muted-foreground" />;
    }
  };

  const extractNote = (description: string) => {
    const noteMatch = description.match(/Note:\s*(.+)$/);
    return noteMatch ? noteMatch[1] : null;
  };

  const descriptionWithoutNote = (description: string) => {
    return description.replace(/\s*Note:.*$/i, "").trim();
  };

  const handleSaveRisk = () => {
    setShowSaveDialog(true);
  };

  const confirmSaveRisk = () => {
    const newLevel = adjustedRiskLevel ?? caseData.riskLevel;
    const entry: ActivityEntry = {
      id: `act-${Date.now()}`,
      timestamp: nowTimestamp(),
      type: "risk_update",
      description: `Risk level updated to ${newLevel}.${saveNoteText ? ` Note: ${saveNoteText}` : ""}`,
      by: isTaxView ? "Tax Authority Officer" : "Customs Authority Officer",
    };
    const nextActivities = [...activities, entry];
    // AI score remains untouched — the snapshot preserves it exactly
    // so the displayed X/100 never fakes an officer-picked number.
    const nextCaseData: Case = {
      ...caseData,
      riskLevel: newLevel,
    };
    setActivities(nextActivities);
    setRiskSaved(true);
    persistSnapshot(nextCaseData, nextActivities, true, { riskSaveNote: saveNoteText.trim() || undefined });
    setSaveNoteText("");
    setShowSaveDialog(false);
    toast({ title: "Risk assessment saved", description: `Risk level updated to ${newLevel}.` });
  };

  const handleApplyAction = () => {
    setShowApplyDialog(true);
  };

  // ── Agentic AI Assistant helpers ────────────────────────────────────────
  // The chat endpoint can return an optional "proposal" telling the UI
  // the agent wants to take an action. There is no longer any Apply /
  // Cancel button — the officer confirms the proposal by typing "yes"
  // (or similar) in their next message, and cancels by typing "no".
  // `pendingProposal` above is the single source of truth for the
  // unresolved proposal.

  const classifyConfirmation = (text: string): "yes" | "no" | "other" => {
    const t = text.trim().toLowerCase();
    if (!t) return "other";
    const yes = [
      "yes", "y", "yeah", "yep", "yup", "ok", "okay", "sure",
      "confirm", "confirmed", "confirming", "proceed", "go ahead",
      "do it", "please do", "apply", "apply it", "execute",
      "correct", "affirmative", "do so",
    ];
    const no = [
      "no", "n", "nope", "nah", "cancel", "stop", "don't",
      "do not", "abort", "negative", "forget it", "never mind",
      "nevermind",
    ];
    if (yes.includes(t) || yes.some((kw) => t === kw || t.startsWith(kw + " ") || t.startsWith(kw + ",") || t.startsWith(kw + "."))) {
      return "yes";
    }
    if (no.includes(t) || no.some((kw) => t === kw || t.startsWith(kw + " ") || t.startsWith(kw + ",") || t.startsWith(kw + "."))) {
      return "no";
    }
    return "other";
  };

  // Core action executor — mirrors the manual Action-dropdown flow so
  // the case-state transition is identical, then navigates back to the
  // dashboard and closes the case tab.
  const executeProposal = async (action: string, comment: string) => {
    if (!caseData) return { ok: false as const, label: action, error: "No case loaded" };
    const officer = isTaxView ? "Tax Authority Officer" : "Customs Authority Officer";
    const now = nowTimestamp();
    const label = actionLabelOf(action);
    try {
      if (isTaxView) {
        if (action !== "risk_confirmed" && action !== "no_limited_risk") {
          throw new Error(`Unsupported tax action: ${action}`);
        }
        const actionTaken: ActionTaken =
          action === "risk_confirmed" ? "Recommend Control" : "Recommend Release";
        returnToCustomsFromTax(caseData.id);
        setCaseAction(caseData.id, actionTaken);
        setCaseStatus("Reviewed by Tax");
        appendActivities(caseData, [
          { id: `agentic-${Date.now()}`, timestamp: now, type: "action",
            description: `${label} applied via AI Assistant. ${comment}`, by: officer },
          { id: `agentic-status-${Date.now()}`, timestamp: now, type: "status_update",
            description: `Status changed to Reviewed by Tax.`, by: officer },
        ], { status: "Reviewed by Tax", actionTaken });
        taxAction(caseData.id, { action, comment, officer }).catch(() => {});
      } else {
        if (action !== "retainment" && action !== "release"
         && action !== "tax_review" && action !== "input_requested") {
          throw new Error(`Unsupported customs action: ${action}`);
        }
        if (action === "retainment" || action === "release") {
          const actionTaken: ActionTaken =
            action === "retainment" ? "Recommend Control" : "Recommend Release";
          closeCase(caseData.id, actionTaken);
          setCaseStatus("Closed");
          appendActivities(caseData, [
            { id: `agentic-${Date.now()}`, timestamp: now, type: "action",
              description: `${label} applied via AI Assistant. ${comment}`, by: officer },
            { id: `agentic-status-${Date.now()}`, timestamp: now, type: "status_update",
              description: `Status changed to Closed.`, by: officer },
          ], {
            status: "Closed",
            actionTaken,
            closedDate: new Date().toISOString().split("T")[0],
          });
        } else if (action === "tax_review") {
          submitCaseForTaxReview(caseData.id);
          setCaseStatus("Under Review by Tax");
          appendActivities(caseData, [
            { id: `agentic-${Date.now()}`, timestamp: now, type: "action",
              description: `${label} applied via AI Assistant. ${comment}`, by: officer },
            { id: `agentic-status-${Date.now()}`, timestamp: now, type: "status_update",
              description: `Status changed to Under Review by Tax.`, by: officer },
          ], { status: "Under Review by Tax" });
        } else {
          requestThirdPartyInput(caseData.id);
          setCaseStatus("Requested Input by Deemed Importer");
          appendActivities(caseData, [
            { id: `agentic-${Date.now()}`, timestamp: now, type: "action",
              description: `${label} applied via AI Assistant. ${comment}`, by: officer },
            { id: `agentic-status-${Date.now()}`, timestamp: now, type: "status_update",
              description: `Status changed to Requested Input by Deemed Importer.`, by: officer },
          ], { status: "Requested Input by Deemed Importer" });
        }
        customsAction(caseData.id, { action, comment, officer }).catch(() => {});
      }
      setActionApplied(true);
      return { ok: true as const, label };
    } catch (err) {
      return { ok: false as const, label, error: String(err) };
    }
  };

  const sendChat = async (q: string) => {
    if (!caseData) return;
    setChatInput("");
    setChatMessages(prev => [...prev, { role: "user", text: q }]);

    // If a Tax proposal is pending, interpret the next reply as a
    // confirmation/cancellation first. Anything other than an obvious
    // yes/no implicitly cancels and falls through to a fresh Q&A turn.
    if (pendingProposal && isTaxView) {
      const intent = classifyConfirmation(q);
      if (intent === "yes") {
        const { action, comment } = pendingProposal;
        const label = actionLabelOf(action);
        setPendingProposal(null);
        setChatLoading(true);
        const res = await executeProposal(action, comment);
        setChatLoading(false);
        if (res.ok) {
          toast({ title: "Action applied", description: `${label} via AI Assistant.` });
          setChatMessages(prev => [...prev, {
            role: "assistant",
            text: `Done — ${label} has been applied on case ${caseData.id}. Returning to the dashboard…`,
          }]);
          setTimeout(() => {
            closeTab(caseData.id);
            navigate(isTaxView ? "/tax-authority" : "/customs-authority");
          }, 600);
        } else {
          toast({ variant: "destructive", title: "Action failed", description: res.error ?? "Unknown error" });
          setChatMessages(prev => [...prev, {
            role: "assistant",
            text: `I couldn't apply ${label}: ${res.error ?? "unknown error"}.`,
          }]);
        }
        setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
        return;
      }
      if (intent === "no") {
        setPendingProposal(null);
        setChatMessages(prev => [...prev, {
          role: "assistant",
          text: "Okay — cancelled. No action was taken.",
        }]);
        setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
        return;
      }
      // "other" — user drifted into a new question while a proposal was
      // pending. Park the proposal quietly and hand the message to the
      // advisor instead of making the user feel stuck on yes/no. The
      // action assistant can be re-invoked on a future turn.
      setPendingProposal(null);
      setChatMessages(prev => [...prev, {
        role: "assistant",
        text: "No problem — parking that action for now. Let me answer your question.",
      }]);
      setChatLoading(true);
      askCaseAgent(caseData.id, q, isTaxView ? "tax" : "customs", "advisor").then(res => {
        setChatMessages(prev => [...prev, { role: "assistant", text: res.answer }]);
        setChatLoading(false);
        setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
      });
      return;
    }

    setChatLoading(true);
    askCaseAgent(caseData.id, q, isTaxView ? "tax" : "customs").then(res => {
      // Customs agent is Q&A-only — discard any proposal the backend
      // might still surface. Tax keeps propose + chat-confirm flow.
      const proposal = isTaxView && res.proposal
        ? { action: res.proposal.action, comment: res.proposal.comment }
        : null;
      setChatMessages(prev => [
        ...prev,
        {
          role: "assistant",
          text: res.answer,
          proposal: proposal ? { ...proposal, applied: "pending" as const } : undefined,
        },
      ]);
      if (proposal) setPendingProposal(proposal);
      setChatLoading(false);
      setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    });
  };

  const confirmApplyAction = () => {
    // Guard: if no valid action is selected (e.g. prefill fell back to
    // empty, or the officer opened the dropdown without choosing), do
    // nothing but prompt them. This prevents the earlier bug where
    // clicking Apply on a "seemingly empty" list still fired
    // setActionApplied / setActivities and appended a bogus log entry
    // while leaving the status untouched.
    const validSet = isTaxView ? VALID_TAX_LABELS : VALID_CUSTOMS_LABELS;
    if (!selectedAction || !validSet.has(selectedAction)) {
      toast({
        variant: "destructive",
        title: "No action selected",
        description: "Pick an action from the dropdown before confirming.",
      });
      setShowApplyDialog(false);
      return;
    }

    const now = nowTimestamp();
    const officer = isTaxView ? "Tax Authority Officer" : "Customs Authority Officer";
    const noteForCase = applyNoteText.trim();

    const entry: ActivityEntry = {
      id: `act-${Date.now()}`,
      timestamp: now,
      type: "action",
      description: `Action taken: ${selectedAction}.${applyNoteText ? ` Note: ${applyNoteText}` : ""}`,
      by: officer,
    };
    const nextActivitiesWithAction = [...activities, entry];
    const baseSnapshotCase: Case = {
      ...caseData,
      riskScore: persistedRiskScore,
      riskLevel: persistedRiskLevel,
    };
    setActivities(nextActivitiesWithAction);
    setApplyNoteText("");
    setShowApplyDialog(false);
    setActionApplied(true);

    // Helper to append a status_update activity and persist snapshot
    const appendStatusAndPersist = (newStatus: Case["status"], nextCaseDataPatch: Partial<Case> = {}) => {
      const statusEntry: ActivityEntry = {
        id: `act-status-${Date.now()}`,
        timestamp: now,
        type: "status_update",
        description: `Status changed to ${newStatus}.`,
        by: officer,
      };
      const nextActivities = [...nextActivitiesWithAction, statusEntry];
      const nextCaseData: Case = {
        ...baseSnapshotCase,
        ...nextCaseDataPatch,
        status: newStatus,
        notes: noteForCase || baseSnapshotCase.notes,
      };
      setActivities(nextActivities);
      persistSnapshot(nextCaseData, nextActivities, riskSaved);
    };

    // Handle case flow based on action
    if (isTaxView) {
      // Tax officer actions
      if (selectedAction === "Confirm Risk" || selectedAction === "No/Limited Risk") {
        // Tax confirms — case is marked "Reviewed by Tax" and returns to Customs (NOT closed)
        returnToCustomsFromTax(caseData.id);
        persistCaseAction(
          caseData.id,
          selectedAction === "Confirm Risk" ? "Recommend Control" : "Recommend Release",
        );
        setCaseStatus("Reviewed by Tax");
        appendStatusAndPersist("Reviewed by Tax");
        const backendAction = selectedAction === "Confirm Risk" ? "risk_confirmed" : "no_limited_risk";
        taxAction(caseData.id, { action: backendAction as any, comment: noteText, officer: "Tax Officer" }).catch(() => {});
        toast({
          title: "Action applied",
          description: `${selectedAction} — case returned to Customs Authority for final action.`,
        });
        return;
      }
      // No other Tax-side actions: Request Input is Customs-only.
    } else {
      // Customs officer actions
      if (selectedAction === "Recommend Control" || selectedAction === "Recommend Release") {
        closeCase(caseData.id, selectedAction as "Recommend Control" | "Recommend Release");
        setCaseStatus("Closed");
        appendStatusAndPersist("Closed", {
          actionTaken: selectedAction as "Recommend Control" | "Recommend Release",
          closedDate: new Date().toISOString().split("T")[0],
        });
        const backendAction = selectedAction === "Recommend Control" ? "retainment" : "release";
        customsAction(caseData.id, { action: backendAction as any, comment: noteText, officer: "Customs Officer" }).catch(() => {});
        toast({ title: "Action applied", description: `${selectedAction} — case moved to closed.` });

        if (createRule) {
          setShowRuleDialog(true);
        }
        return;
      } else if (selectedAction === "Submit for Tax Review") {
        submitCaseForTaxReview(caseData.id);
        setCaseStatus("Under Review by Tax");
        appendStatusAndPersist("Under Review by Tax");
        customsAction(caseData.id, { action: "tax_review", comment: noteText, officer: "Customs Officer" }).catch(() => {});
        toast({ title: "Submitted for Tax Review", description: "Case sent to Tax Authority." });
        return;
      } else if (selectedAction === "Request Input from Deemed Importer") {
        requestThirdPartyInput(caseData.id);
        setCaseStatus("Requested Input by Deemed Importer");
        appendStatusAndPersist("Requested Input by Deemed Importer");
        customsAction(caseData.id, { action: "input_requested", comment: noteText, officer: "Customs Officer" }).catch(() => {});
        toast({ title: "Action applied", description: "Request sent to deemed importer." });
        return;
      }
    }

    if (createRule) {
      setShowRuleDialog(true);
    }
  };

  const confirmCreateRule = () => {
    toast({
      title: "Business rule created",
      description: `Rule will be applied to all future cases with similar pattern: ${caseData.declaredCategory} → ${caseData.aiSuggestedCategory}.`,
    });
    setCreateRule(false);
    setShowRuleDialog(false);
  };

  const handleAddNote = () => {
    if (!noteText.trim()) return;
    const entry: ActivityEntry = {
      id: `act-${Date.now()}`,
      timestamp: nowTimestamp(),
      type: "note",
      description: `Note added. Note: ${noteText}`,
      by: isTaxView ? "Tax Authority Officer" : "Customs Authority Officer",
    };
    const nextActivities = [...activities, entry];
    setActivities(nextActivities);
    persistSnapshot(
      {
        ...caseData,
        riskScore: persistedRiskScore,
        riskLevel: persistedRiskLevel,
      },
      nextActivities,
      riskSaved,
    );
    const officer = isTaxView ? "Tax Authority" : "Customs Authority";
    addCommunication(caseData.id, { from: officer, action: "note", message: noteText }).catch(() => {});
    setNoteText("");
    setShowAddNoteDialog(false);
    toast({ title: "Note added" });
  };

  const toggleCorrelation = (caseId: string) => {
    setSelectedCorrelations((prev) => (prev.includes(caseId) ? prev.filter((c) => c !== caseId) : [...prev, caseId]));
  };

  const handleCorrelate = () => {
    toast({ title: "Cases correlated", description: `${selectedCorrelations.length} case(s) linked as a major case.` });
    setSelectedCorrelations([]);
  };

  // Previous cases must always be from the same seller as the current case
  const filteredPrevious = backendPrevCases.map(pc => ({
    caseId: pc.Case_ID,
    caseName: pc.Product_Description ?? pc.Case_ID,
    actionTaken: pc.Proposed_Action_Customs === "retain" ? "Recommend Control" as const
               : pc.Proposed_Action_Customs === "release" ? "Recommend Release" as const
               : "Submitted for Tax Review" as any,
    riskScore: Math.round((pc.Overall_Case_Risk_Score ?? 0) * 100),
    riskLevel: (pc.Overall_Case_Risk_Level ?? "Medium") as "High" | "Medium" | "Low",
    seller: pc.Seller_Name ?? "",
    countryOfOrigin: pc.Country_Origin ?? "",
    countryOfDestination: pc.Country_Destination ?? "",
    productDescription: pc.Product_Description ?? "",
    declaredCategory: pc.HS_Product_Category ?? "",
    aiCategory: pc.HS_Product_Category ?? "",
  }));
  const filteredCorrelations = backendCorrelatedCases.map(cc => ({
    caseId: cc.Case_ID,
    caseName: cc.Product_Description ?? cc.Case_ID,
    riskScore: Math.round((cc.Overall_Case_Risk_Score ?? 0) * 100),
    riskLevel: (cc.Overall_Case_Risk_Level ?? "Medium") as "High" | "Medium" | "Low",
    seller: cc.Seller_Name ?? "",
    countryOfOrigin: cc.Country_Origin ?? "",
    countryOfDestination: cc.Country_Destination ?? "",
    productDescription: cc.Product_Description ?? "",
    declaredCategory: cc.HS_Product_Category ?? "",
    detected: true,
    order_count: cc.order_count ?? 0,
  }));
  // Available actions based on authority
  const availableActions = isTaxView ? taxActions : customsActions;

  return (
    <main className="flex-1 overflow-auto p-6 space-y-5">
      {/* Header with back button and action bar */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() =>
              navigate(isTaxView ? "/tax-authority" : isClosed ? "/customs-authority/closed" : "/customs-authority")
            }
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h2 className="text-xl font-bold text-foreground">Review Case {caseData.id}</h2>
        </div>

        {/* AI investigation banner */}
        {isAiInvestigating && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-purple-500/10 border border-purple-500/30">
            <span className="text-sm">⚙️</span>
            <span className="text-xs font-medium text-purple-600">AI Agent is analysing this case — actions are locked until analysis completes.</span>
          </div>
        )}

        {/* Action bar */}
        {!isClosed && !actionApplied && !isAiInvestigating && (
          <div className="flex items-center gap-2">
            <Select value={selectedAction} onValueChange={setSelectedAction}>
              <SelectTrigger className="w-[260px] text-sm">
                <SelectValue placeholder="Select Action" />
              </SelectTrigger>
              <SelectContent>
                {isTaxView ? (
                  <>
                    <SelectItem value="Confirm Risk">
                      <span className="flex items-center gap-2">
                        <AlertTriangle className="h-4 w-4 text-destructive" /> Confirm Risk
                      </span>
                    </SelectItem>
                    <SelectItem value="No/Limited Risk">
                      <span className="flex items-center gap-2">
                        <CheckCircle2 className="h-4 w-4 text-success" /> No/Limited Risk
                      </span>
                    </SelectItem>
                  </>
                ) : (
                  <>
                    <SelectItem value="Recommend Control">
                      <span className="flex items-center gap-2">
                        <XCircle className="h-4 w-4 text-destructive" /> Recommend Control
                      </span>
                    </SelectItem>
                    <SelectItem value="Recommend Release">
                      <span className="flex items-center gap-2">
                        <CheckCircle2 className="h-4 w-4 text-success" /> Recommend Release
                      </span>
                    </SelectItem>
                    {caseStatus !== "Reviewed by Tax" && (
                      <SelectItem value="Submit for Tax Review">
                        <span className="flex items-center gap-2">
                          <FileSearch className="h-4 w-4 text-primary" /> Submit for Tax Review
                        </span>
                      </SelectItem>
                    )}
                    <SelectItem value="Request Input from Deemed Importer">
                      <span className="flex items-center gap-2">
                        <UserRound className="h-4 w-4 text-warning" /> Request Input from Deemed Importer
                      </span>
                    </SelectItem>
                  </>
                )}
              </SelectContent>
            </Select>
            <Button size="sm" onClick={handleApplyAction}>
              Apply
            </Button>
          </div>
        )}
      </div>

      {/* Main two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* LEFT column */}
        <div className="space-y-4">
          {/* Case Information */}
          <div className="bg-card rounded-lg border border-border p-4">
            <h3 className="text-sm font-semibold text-card-foreground mb-3 uppercase tracking-wider">
              Case Information
            </h3>
            {(() => {
              const shortDesc = (orders[0]?.productDescription ?? "").split("—")[0].trim() || "—";
              const caseName = `${caseData.seller} - ${shortDesc} - ${caseData.countryOfDestination}`;
              return (
                <div className="mb-3 pb-3 border-b border-border">
                  <p className="text-xs text-muted-foreground mb-1">Case Name</p>
                  <p className="text-sm font-medium text-card-foreground">{caseName}</p>
                </div>
              );
            })()}
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Case ID</dt>
                <dd className="text-card-foreground font-normal">{caseData.id}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Status</dt>
                <dd>
                  <Badge className={cn("text-xs", statusStyles[caseStatus])}>{caseStatus}</Badge>
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Creation Date</dt>
                <dd className="text-card-foreground">{orders[0]?.date ?? "—"}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Risk Level</dt>
                <dd>
                  <Badge className={cn("text-xs", riskLevelStyles[persistedRiskLevel])}>
                    {persistedRiskLevel}
                  </Badge>
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground"># Orders in Case</dt>
                <dd className="text-card-foreground font-normal">{orders.length}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Risk Score</dt>
                <dd className="text-card-foreground font-normal">
                  {caseData.riskScore}/100
                </dd>
              </div>
            </div>
            <div className="mt-3 pt-3 border-t border-border">
              <div className="bg-muted/50 rounded-md p-3">
                <div className="flex items-center gap-1.5 mb-1">
                  <p className="text-xs font-medium text-primary">AI Case Summary</p>
                  <Sparkles className="h-3.5 w-3.5 text-primary" />
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">{aiSummary}</p>
              </div>
            </div>
          </div>

          {/* Order Information */}
          <div className="bg-card rounded-lg border border-border p-4">
            <h3 className="text-sm font-semibold text-card-foreground mb-3 uppercase tracking-wider">
              Order Information
            </h3>
            <div className="space-y-4 text-sm">
              {/* Seller */}
              <div>
                <p className="font-semibold text-card-foreground mb-1">Seller</p>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                  <div className="flex justify-between">
                    <dt className="text-muted-foreground">Seller name</dt>
                    <dd className="text-card-foreground">{caseData.seller}</dd>
                  </div>
                </div>
              </div>

              {/* Buyer */}
              <div>
                <p className="font-semibold text-card-foreground mb-1">Buyer</p>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                  <div className="flex justify-between">
                    <dt className="text-muted-foreground">Buyer name</dt>
                    <dd className="text-card-foreground">{(caseData as any).buyerName ?? "John O'Sullivan"}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-muted-foreground">IOSS number</dt>
                    <dd className="text-card-foreground font-mono">{(caseData as any).iossNumber ?? "IM2501234567"}</dd>
                  </div>
                </div>
              </div>

              {/* Route */}
              <div>
                <p className="font-semibold text-card-foreground mb-1">Route</p>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                  <div className="flex justify-between">
                    <dt className="text-muted-foreground">Country of origin</dt>
                    <dd className="text-card-foreground">{caseData.countryOfOrigin}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-muted-foreground">Country of release</dt>
                    <dd className="text-card-foreground">IE</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-muted-foreground">Country of destination</dt>
                    <dd className="text-card-foreground">{caseData.countryOfDestination}</dd>
                  </div>
                </div>
              </div>

              {/* Product */}
              <div>
                <p className="font-semibold text-card-foreground mb-1">Product</p>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                  <div className="flex justify-between">
                    <dt className="text-muted-foreground">Declared product category</dt>
                    <dd className="text-card-foreground">{caseData.declaredCategory}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-muted-foreground">Product description</dt>
                    <dd className="text-card-foreground">{getBaseProductFromOrders(orders)}</dd>
                  </div>
                </div>
              </div>

              {/* Item Value */}
              <div>
                <p className="font-semibold text-card-foreground mb-1">Declared Item value</p>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                  <div className="flex justify-between">
                    <dt className="text-muted-foreground">Declared Item value range</dt>
                    <dd className="text-card-foreground">{valueRange}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-muted-foreground">Total declared item value</dt>
                    <dd className="text-card-foreground">
                      €{orders.reduce((sum, o) => sum + o.itemValue, 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </dd>
                  </div>
                </div>
              </div>

              {/* VAT Value */}
              <div>
                <p className="font-semibold text-card-foreground mb-1">VAT value</p>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                  <div className="flex justify-between">
                    <dt className="text-muted-foreground">Declared VAT value range</dt>
                    <dd className="text-card-foreground">{vatRange}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-muted-foreground">Total declared VAT value</dt>
                    <dd className="text-card-foreground">
                      €{orders.reduce((sum, o) => sum + o.vatValue, 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </dd>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Risk Analysis */}
          <div className="bg-card rounded-lg border border-border p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-card-foreground uppercase tracking-wider">
                {isTaxView || isClosed || riskSaved ? "Risk Analysis Summary" : "Risk Analysis"}
              </h3>
              {!isClosed && !riskSaved && !isTaxView && (
                <Button size="sm" variant="outline" className="h-7 px-2.5 text-xs" onClick={handleSaveRisk}>
                  <Save className="h-3 w-3 mr-1" />
                  Save
                </Button>
              )}
              {riskSaved && <Badge className="text-[10px] bg-success/15 text-success">Saved</Badge>}
            </div>

            <div
              className={cn(
                "grid gap-4",
                !isClosed ? "grid-cols-2" : "grid-cols-1",
                !isTaxView && "mb-4 pb-4 border-b border-border",
              )}
            >
              {/* ML Risk Prediction — always show original AI score, never overwritten by officer adjustment */}
              <div>
                <p className="text-xs text-muted-foreground mb-2">AI Risk Prediction</p>
                <div className="flex items-center gap-2">
                  <p className="text-2xl font-bold text-card-foreground">{baseCaseData.riskScore}</p>
                  <Badge className={cn("text-xs", riskLevelStyles[baseCaseData.riskLevel])}>
                    {baseCaseData.riskLevel}
                  </Badge>
                </div>
              </div>

              {/* Officer Risk Adjustment — LEVEL only. The officer's
                  edit never overwrites the AI score; the tile on the
                  left keeps showing the AI computation as the ground
                  truth, and this tile shows the officer's chosen level. */}
              {!isClosed && (
                <div>
                  <p className="text-xs text-muted-foreground mb-2">Current Customs Officer Risk Level</p>
                  {isTaxView ? (
                    // Tax view is read-only. Show the officer's adjusted
                    // level only when one was actually saved; otherwise
                    // render "—" so the field reads as empty instead of
                    // falsely advertising a default level the officer
                    // never picked.
                    riskSaved && adjustedRiskLevel ? (
                      <div className="flex items-center gap-2">
                        <Badge className={cn("text-xs", riskLevelStyles[adjustedRiskLevel])}>
                          {adjustedRiskLevel}
                        </Badge>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground italic">— not adjusted</p>
                    )
                  ) : riskSaved && adjustedRiskLevel ? (
                    <div className="flex items-center gap-2">
                      <Badge className={cn("text-xs", riskLevelStyles[adjustedRiskLevel])}>
                        {adjustedRiskLevel}
                      </Badge>
                    </div>
                  ) : (
                    <Select
                      value={adjustedRiskLevel ?? "Unchanged"}
                      onValueChange={(level) => {
                        // Officer picks the level directly; no numeric
                        // round-trip. AI classifier (backend) emits only
                        // Medium/High; officer can additionally override
                        // to Low.
                        setAdjustedRiskLevel(
                          level === "Unchanged" ? null : (level as OfficerRiskLevel),
                        );
                      }}
                    >
                      <SelectTrigger className="h-9 w-36 text-sm font-semibold">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="Unchanged">Unchanged</SelectItem>
                        <SelectItem value="High">High</SelectItem>
                        <SelectItem value="Medium">Medium</SelectItem>
                        <SelectItem value="Low">Low</SelectItem>
                      </SelectContent>
                    </Select>
                  )}
                </div>
              )}
            </div>

            {/* AI Risk Summary — sits between the risk-level tiles
                above and the Risk Signals breakdown below, so the
                officer reads: score + adjustment → natural-language
                rationale → per-engine contributions. */}
            <div className={cn("mb-3", !isTaxView && "pb-3 border-b border-border")}>
              <div className="bg-muted/50 rounded-md p-3">
                <div className="flex items-center gap-1.5 mb-1">
                  <p className="text-xs font-medium text-primary">AI Risk Summary</p>
                  <Sparkles className="h-3.5 w-3.5 text-primary" />
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {(() => {
                    const drivers: string[] = [];
                    if (engVal.vatRatio   >= 0.3) drivers.push(`${signalLabel("vat_ratio")} (${shareOf(weighted.vatRatio)}% of case risk)`);
                    if (engVal.ml         >= 0.3) drivers.push(`${signalLabel("watchlist")} — ${caseData.seller} / ${caseData.declaredCategory} (${shareOf(weighted.ml)}% of case risk)`);
                    if (engVal.ieSeller   >= 0.3) drivers.push(`${signalLabel("ireland_watchlist")} (${shareOf(weighted.ieSeller)}% of case risk)`);
                    if (engVal.vagueness  >= 0.3) drivers.push(`${signalLabel("description_vagueness")} (${shareOf(weighted.vagueness)}% of case risk)`);
                    const driverPart = drivers.length > 0
                      ? `Primary drivers: ${drivers.join("; ")}.`
                      : `No single engine dominates — risk is distributed across multiple low-level signals.`;
                    return cleanupText(
                      `Risk engines assigned a consolidated score of ${aiRiskScore}/100 (${aiRiskLevel} risk). ` +
                      `${driverPart} ` +
                      `Origin: ${caseData.countryOfOrigin}, destination: ${caseData.countryOfDestination}, seller: "${caseData.seller}".`
                    );
                  })()}
                </p>
                {/* Officer-adjustment appendix — a SEPARATE paragraph
                    so the AI's rationale stays untouched. Fires whenever
                    the officer has saved a risk edit and the resulting
                    score or level differs from the AI's. Includes the
                    officer's free-text note when present; otherwise a
                    factual one-liner covers the audit trail. */}
                {riskSaved && aiRiskLevel !== caseData.riskLevel && (() => {
                  const officerLabel = isTaxView ? "Tax Authority Officer" : "Customs Authority Officer";
                  const note = storedSnapshot?.riskSaveNote?.trim();
                  const factual = `${officerLabel} adjusted the risk level from ${aiRiskLevel} to ${caseData.riskLevel}. The AI-computed risk score (${aiRiskScore}/100) remains the reference figure.`;
                  const withComment = note
                    ? `${factual} Officer comment: "${note}"`
                    : `${factual} No justification was provided with the adjustment.`;
                  return (
                    <p className="text-xs text-muted-foreground leading-relaxed mt-2 pt-2 border-t border-border/40">
                      {cleanupText(withComment)}
                    </p>
                  );
                })()}
              </div>
            </div>

            {/* Explainability - only for customs view */}
            {!isTaxView && (
              <div>
                <p className="text-xs text-muted-foreground mb-1">Risk Signals</p>
                <p className="text-[11px] text-muted-foreground mb-3 italic">
                  Each bar is the signal&apos;s contribution to the overall case risk score.
                  The four contributions sum to approximately the overall score.
                </p>
                <div className="space-y-3">
                  {mlFeatures.map((f) => (
                    <div key={f.feature} className="space-y-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-medium text-card-foreground">
                          {f.feature}
                        </span>
                        <span className="text-muted-foreground font-medium">
                          {f.contribution} pts
                        </span>
                      </div>
                      <div className="w-full bg-muted rounded-full h-1.5">
                        <div
                          className="bg-primary rounded-full h-1.5 transition-all"
                          style={{ width: `${Math.min(f.contribution, 100)}%` }}
                        />
                      </div>
                      <div className="flex justify-end text-[11px] text-muted-foreground">
                        <span>{f.share}% of case risk</span>
                      </div>
                      <p className="text-[11px] text-muted-foreground leading-relaxed">{f.detail}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* VAT Assessment - Tax Authority full editor, Customs sees compact read-only summary */}
          {isTaxView && (
            <VATAssessmentSection
              caseData={caseData}
              orders={orders}
              isClosed={isClosed}
              vatSaved={vatSaved}
              initialCategory={vatCategory}
              onSave={handleSaveVat}
            />
          )}
          {!isTaxView &&
            vatSaved &&
            (() => {
              const totalItemValue = orders.reduce((sum, o) => sum + o.itemValue, 0);
              // Ground-truth declared VAT totals (same logic as the Tax
              // full editor). Effective rate inferred from the actual
              // per-order sums so the Customs compact summary matches
              // what the officer sees in the Linked Orders tab.
              const declaredVatValue = orders.reduce((sum, o) => sum + o.vatValue, 0);
              const declaredVatRate = totalItemValue > 0
                ? (declaredVatValue / totalItemValue) * 100
                : 0;
              const officerVatRate = vatCategory ? (vatRatesByCategory()[vatCategory] ?? 23) : 0;
              const officerVatValue = totalItemValue * (officerVatRate / 100);
              const vatGap = officerVatValue - declaredVatValue;
              return (
                <div className="bg-card rounded-lg border border-border p-4">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <AlertTriangle className="h-4 w-4 text-primary" />
                      <h3 className="text-sm font-semibold text-card-foreground uppercase tracking-wider">
                        VAT Assessment Summary
                      </h3>
                    </div>
                    <Badge className="text-[10px] bg-success/15 text-success">Saved by Tax Authority</Badge>
                  </div>
                  <div className="grid grid-cols-3 gap-3 mb-4">
                    <div className="rounded-md border border-border p-3">
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Declared VAT</p>
                      <p className="text-base font-semibold text-card-foreground mt-1">
                        €{declaredVatValue.toFixed(2)}
                      </p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        {declaredVatRate.toFixed(2)}% — {caseData.declaredCategory}
                      </p>
                    </div>
                    <div className="rounded-md border border-border p-3">
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Officer Confirmed VAT</p>
                      <p className="text-base font-semibold text-card-foreground mt-1">€{officerVatValue.toFixed(2)}</p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        {officerVatRate}% — {vatCategory || "—"}
                      </p>
                    </div>
                    <div className="rounded-md border border-border p-3">
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">VAT Gap</p>
                      <p
                        className={cn(
                          "text-base font-semibold mt-1",
                          vatGap > 0 ? "text-destructive" : vatGap < 0 ? "text-success" : "text-card-foreground",
                        )}
                      >
                        €{Math.abs(vatGap).toFixed(2)}
                      </p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        {vatGap > 0 ? "Underpaid" : vatGap < 0 ? "Overpaid" : "No gap"}
                      </p>
                    </div>
                  </div>
                  <div className="bg-muted/50 rounded-md p-3">
                    <div className="flex items-center gap-1.5 mb-1">
                      <p className="text-xs font-medium text-primary">AI VAT Assessment Summary</p>
                      <Sparkles className="h-3.5 w-3.5 text-primary" />
                    </div>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      {(() => {
                        // Same reasoning as the earlier AI summary: let the
                        // VAT gap drive the wording so the sentence agrees
                        // with the € number in the VAT Gap tile on the left.
                        const sameCategory = caseData.declaredCategory === vatCategory;
                        if (Math.abs(vatGap) < 0.005) {
                          return (
                            <>
                              Declared VAT category "{caseData.declaredCategory}" was confirmed by Tax Authority. No
                              deviation detected.
                            </>
                          );
                        }
                        return (
                          <>
                            {sameCategory
                              ? `VAT rate mismatch within category "${caseData.declaredCategory}". `
                              : `Wrong VAT product category declared. Tax Authority reassessed the case under category "${vatCategory}" instead of declared "${caseData.declaredCategory}". `}
                            Resulting VAT gap: €{Math.abs(vatGap).toFixed(2)}.
                          </>
                        );
                      })()}
                    </p>
                  </div>
                </div>
              );
            })()}
        </div>

        {/* RIGHT column */}
        <div className="space-y-4">
          {/* AI Suggested Action */}
          <div className="bg-card rounded-lg border border-border p-4">
            <h3 className="text-sm font-semibold text-card-foreground mb-3 uppercase tracking-wider flex items-center gap-2">
              {isClosed ? "Action Taken" : "AI Suggested Action"}
              <Sparkles className="h-4 w-4 text-primary" />
            </h3>
            {(() => {
              // Canonical AI recommendations come from the backend
              // (_compute_customs_recommendation / _compute_tax_recommendation).
              // List and detail views are guaranteed to agree.
              let dynamicAction: string;
              let dynamicDescription: string;

              // After Tax Authority has reviewed, the pre-review "Submit
              // for Tax Review" suggestion is stale — swap it for the
              // post-review customs action. Prefer the localStorage
              // override (set by the Tax officer in this browser session)
              // and fall back to the backend's aiSuggestedAction, which
              // now honours Proposed_Action_Tax at compute-time. Belt-
              // and-suspenders against a cold localStorage (e.g. after a
              // simulation reset, or another browser opening the case).
              const postTaxReviewAction = caseStatus === "Reviewed by Tax"
                ? (getEffectiveCaseAction(caseData.id, undefined)
                   ?? caseData.aiSuggestedAction
                   ?? null)
                : null;
              if (isClosed) {
                dynamicAction = caseData.actionTaken ?? "";
                dynamicDescription = caseData.notes ?? "";
              } else if (isTaxView) {
                dynamicAction      = caseData.aiSuggestedTaxAction ?? "AI Uncertain";
                dynamicDescription = caseData.aiTaxAnalysis
                  ?? "AI recommendation unavailable — backend did not attach a tax analysis for this case.";
              } else if (postTaxReviewAction) {
                dynamicAction      = postTaxReviewAction;
                dynamicDescription = `Tax Authority has reviewed this case and recommends ${postTaxReviewAction}. Apply this action to close the case.`;
              } else {
                dynamicAction      = caseData.aiSuggestedAction;
                dynamicDescription = caseData.aiCustomsAnalysis
                  ?? "AI recommendation unavailable — backend did not attach a customs analysis for this case.";
              }

              // Override note — when the officer picks a different
              // action from the AI recommendation, the rationale panel
              // surfaces it immediately so the comment stays consistent
              // with what the officer is about to apply.
              const aiRecommendation = isTaxView
                ? (caseData.aiSuggestedTaxAction ?? "AI Uncertain")
                : caseData.aiSuggestedAction;
              const showOverride =
                !isClosed
                && selectedAction
                && selectedAction !== aiRecommendation;
              const overrideNote = showOverride
                ? ` Officer override — ${selectedAction} selected instead of the AI-recommended ${aiRecommendation}.`
                : "";
              // Also surface the officer's risk-level adjustment when
              // it materially differs from the engine's — keeps this
              // backend-sourced rationale in sync with the edits the
              // officer just made (and updates immediately, without a
              // page refresh, because overrideSignificant is derived
              // from live caseData / snapshot state).
              const riskOverrideNote = overrideSignificant
                ? ` Officer adjusted the overall risk to ${caseData.riskLevel} (${caseData.riskScore}/100), superseding the AI's initial assessment of ${aiRiskLevel} (${aiRiskScore}/100).`
                : "";

              const iconMap: Record<string, { icon: typeof XCircle; color: string }> = {
                "Recommend Control": { icon: XCircle, color: "text-destructive" },
                "Recommend Release": { icon: CheckCircle2, color: "text-success" },
                "Submit for Tax Review": { icon: FileSearch, color: "text-primary" },
                "Request Input from Deemed Importer": { icon: UserRound, color: "text-warning" },
                "Confirm Risk": { icon: AlertTriangle, color: "text-destructive" },
                "No/Limited Risk": { icon: CheckCircle2, color: "text-success" },
                "AI Uncertain": { icon: HelpCircle, color: "text-warning" },
              };
              const match = iconMap[dynamicAction];
              const Icon = match?.icon;
              return (
                <div>
                  <p
                    className={cn(
                      "text-sm font-semibold flex items-center gap-2",
                      dynamicAction === "Recommend Control" || dynamicAction === "Confirm Risk"
                        ? "text-destructive"
                        : dynamicAction === "Recommend Release" || dynamicAction === "No/Limited Risk"
                          ? "text-success"
                          : "text-card-foreground",
                    )}
                  >
                    {Icon && <Icon className={cn("h-4 w-4", match.color)} />}
                    {dynamicAction}
                  </p>
                  <p className="text-xs text-muted-foreground mt-2 leading-relaxed">
                    {cleanupText(dynamicDescription + riskOverrideNote)}
                    {overrideNote && <span className="text-warning">{cleanupText(overrideNote)}</span>}
                  </p>
                </div>
              );
            })()}
          </div>

          {/* Bottom tabs: Previous Cases, Correlate, Linked Orders, AI Agent */}
          <div className="bg-card rounded-lg border border-border">
            <Tabs defaultValue="previous-cases">
              <TabsList className="w-full justify-start border-b border-border rounded-none bg-transparent px-2 pt-1">
                <TabsTrigger value="previous-cases" className="text-xs">
                  Previous Cases
                </TabsTrigger>
                {!isTaxView && (
                  <TabsTrigger value="correlate" className="text-xs">
                    Correlate
                  </TabsTrigger>
                )}
                <TabsTrigger value="linked-orders" className="text-xs">
                  Linked Orders
                </TabsTrigger>
                <TabsTrigger value="ai-agent" className="text-xs">
                  AI Agent
                </TabsTrigger>
              </TabsList>

              {/* Linked Orders */}
              <TabsContent value="linked-orders" className="p-0 m-0">
                <p className="text-xs text-muted-foreground px-3 pt-3 pb-1">
                  {orders.length} order{orders.length !== 1 ? "s" : ""} linked to this case.
                </p>
                <div className="overflow-x-auto max-h-[400px] overflow-y-auto border-t border-border">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-muted/80 z-10">
                      <tr className="border-b border-border">
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                          Order ID
                        </th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                          Seller
                        </th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                          Declared Product Category
                        </th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                          Product Subcategory
                        </th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                          Product Description
                        </th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                          Country of Origin
                        </th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                          Country of Destination
                        </th>
                        <th className="px-3 py-2 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                          Item Value
                        </th>
                        <th className="px-3 py-2 text-right font-semibold text-muted-foreground uppercase tracking-wider">
                          VAT Value
                        </th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                          Status
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {orders.map((order) => (
                        <tr
                          key={order.id}
                          className="border-b border-border last:border-0 hover:bg-muted/30 transition-colors"
                        >
                          <td className="px-3 py-2 font-mono text-card-foreground">{order.id}</td>
                          <td className="px-3 py-2 text-card-foreground truncate max-w-[120px]">{caseData.seller}</td>
                          <td className="px-3 py-2 text-card-foreground">{caseData.declaredCategory}</td>
                          <td className="px-3 py-2 font-mono text-card-foreground">{order.vatSubcategoryCode ?? "—"}</td>
                          <td className="px-3 py-2 text-card-foreground">{order.productDescription}</td>
                          <td className="px-3 py-2 text-card-foreground">{caseData.countryOfOrigin}</td>
                          <td className="px-3 py-2 text-card-foreground">{caseData.countryOfDestination}</td>
                          <td className="px-3 py-2 text-right text-card-foreground">€{order.itemValue}</td>
                          <td className="px-3 py-2 text-right text-card-foreground">
                            €{order.vatValue} ({order.vatPercent}%)
                          </td>
                          <td className="px-3 py-2">
                            {(() => {
                              const orderStatus = isClosed
                                ? caseData.actionTaken === "Recommend Control"
                                  ? "Held for Inspection"
                                  : caseData.actionTaken === "Recommend Release"
                                    ? "To Be Released"
                                    : "Under Investigation"
                                : "Under Investigation";
                              const styles =
                                orderStatus === "Held for Inspection"
                                  ? "bg-destructive/15 text-destructive"
                                  : orderStatus === "To Be Released"
                                    ? "bg-success/15 text-success"
                                    : "bg-warning/15 text-warning";
                              return <Badge className={cn("text-[10px] font-medium", styles)}>{orderStatus}</Badge>;
                            })()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </TabsContent>

              {/* Previous Cases */}
              <TabsContent value="previous-cases" className="p-4 m-0">
                {(() => {
                  const retainCount = filteredPrevious.filter((pc) => pc.actionTaken === "Recommend Control").length;
                  const releaseCount = filteredPrevious.filter((pc) => pc.actionTaken === "Recommend Release").length;
                  const total = filteredPrevious.length;
                  const retainPct = total > 0 ? Math.round((retainCount / total) * 100) : 0;
                  const releasePct = total > 0 ? Math.round((releaseCount / total) * 100) : 0;
                  return (
                    <>
                      <p className="text-xs text-muted-foreground mb-3">
                        The following similar previous cases were identified, based on seller, declared product
                        category, product description, country of origin, and the corresponding action taken in the
                        past.
                      </p>
                      <div className="flex items-center gap-4 mb-3 flex-wrap">
                        <p className="text-xs text-muted-foreground">Action distribution:</p>
                        <Badge className="text-xs bg-destructive/15 text-destructive">
                          {retainPct}% Recommend Control
                        </Badge>
                        <Badge className="text-xs bg-success/15 text-success">{releasePct}% Recommend Release</Badge>
                      </div>
                      <div className="overflow-x-auto max-h-[300px] overflow-y-auto">
                        <table className="w-full text-xs">
                          <thead className="sticky top-0 bg-muted/80 z-10">
                            <tr className="border-b border-border">
                              <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                                Case ID
                              </th>
                              <th className="px-3 py-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                                # Orders in Case
                              </th>
                              <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                                Seller
                              </th>
                              <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                                Declared Product Category
                              </th>
                              <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                                Product Description
                              </th>
                              <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                                Country of Origin
                              </th>
                              <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                                Country of Destination
                              </th>
                              <th className="px-3 py-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                                Risk Level
                              </th>
                              <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                                Action
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            {filteredPrevious.map((pc) => (
                              <tr
                                key={pc.caseId}
                                className="border-b border-border last:border-0 hover:bg-muted/30 transition-colors"
                              >
                                <td className="px-3 py-2 font-mono text-card-foreground">{pc.caseId}</td>
                                <td className="px-3 py-2 text-center text-card-foreground">
                                  {(pc.caseId.charCodeAt(pc.caseId.length - 1) % 8) + 2}
                                </td>
                                <td className="px-3 py-2 text-card-foreground truncate max-w-[120px]">{pc.seller}</td>
                                <td className="px-3 py-2 text-card-foreground">{pc.declaredCategory}</td>
                                <td className="px-3 py-2 text-card-foreground">{getBaseProductFromOrders(orders)}</td>
                                <td className="px-3 py-2 text-card-foreground">{pc.countryOfOrigin}</td>
                                <td className="px-3 py-2 text-card-foreground">{pc.countryOfDestination}</td>
                                <td className="px-3 py-2 text-center">
                                  <Badge className={cn("text-xs", riskLevelStyles[pc.riskLevel])}>{pc.riskLevel}</Badge>
                                </td>
                                <td className="px-3 py-2">
                                  <span
                                    className={cn(
                                      "font-medium",
                                      pc.actionTaken === "Recommend Control"
                                        ? "text-destructive"
                                        : pc.actionTaken === "Recommend Release"
                                          ? "text-success"
                                          : "text-card-foreground",
                                    )}
                                  >
                                    {pc.actionTaken}
                                  </span>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      {filteredPrevious.length === 0 && (
                        <p className="text-xs text-muted-foreground">No similar previous cases found.</p>
                      )}
                    </>
                  );
                })()}
              </TabsContent>

              {/* Correlate */}
              <TabsContent value="correlate" className="p-4 m-0">
                <p className="text-xs text-muted-foreground mb-3 whitespace-pre-line">
                  The following similar cases were identified, based on seller, declared product category, product
                  description flagged by AI as closely related to the current product description, and country of
                  destination. {"\n\n"}
                  Select cases to correlate them to this parent case.
                </p>
                <div className="overflow-x-auto max-h-[300px] overflow-y-auto">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-muted/80 z-10">
                      <tr className="border-b border-border">
                        <th className="px-3 py-2 text-left">
                          <Checkbox
                            checked={
                              filteredCorrelations.length > 0 &&
                              selectedCorrelations.length === filteredCorrelations.length
                            }
                            onCheckedChange={(checked) => {
                              if (checked) {
                                setSelectedCorrelations(filteredCorrelations.map((c) => c.caseId));
                              } else {
                                setSelectedCorrelations([]);
                              }
                            }}
                          />
                        </th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                          Case ID
                        </th>
                        <th className="px-3 py-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                          # Orders in Case
                        </th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                          Seller
                        </th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                          Declared Product Category
                        </th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                          Product Description
                        </th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                          Country of Origin
                        </th>
                        <th className="px-3 py-2 text-left font-semibold text-muted-foreground uppercase tracking-wider">
                          Country of Destination
                        </th>
                        <th className="px-3 py-2 text-center font-semibold text-muted-foreground uppercase tracking-wider">
                          Risk Level
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredCorrelations.map((cc) => (
                        <tr
                          key={cc.caseId}
                          className="border-b border-border last:border-0 hover:bg-muted/30 transition-colors"
                        >
                          <td className="px-3 py-2">
                            <Checkbox
                              checked={selectedCorrelations.includes(cc.caseId)}
                              onCheckedChange={() => toggleCorrelation(cc.caseId)}
                            />
                          </td>
                          <td className="px-3 py-2 font-mono text-card-foreground">{cc.caseId}</td>
                          <td className="px-3 py-2 text-center text-card-foreground">
                            {(cc as any).order_count ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-card-foreground truncate max-w-[120px]">{cc.seller}</td>
                          <td className="px-3 py-2 text-card-foreground">{cc.declaredCategory}</td>
                          <td className="px-3 py-2 text-card-foreground truncate max-w-[160px]" title={cc.productDescription}>{cc.productDescription}</td>
                          <td className="px-3 py-2 text-card-foreground">{cc.countryOfOrigin}</td>
                          <td className="px-3 py-2 text-card-foreground">{cc.countryOfDestination}</td>
                          <td className="px-3 py-2 text-center">
                            <Badge className={cn("text-xs", riskLevelStyles[cc.riskLevel])}>{cc.riskLevel}</Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {filteredCorrelations.length === 0 && (
                  <p className="text-xs text-muted-foreground">No similar cases to correlate.</p>
                )}
                {selectedCorrelations.length > 0 && (
                  <Button size="sm" className="mt-3" onClick={handleCorrelate}>
                    Correlate {selectedCorrelations.length} Case(s) into Major Case
                  </Button>
                )}
              </TabsContent>

              {/* AI Agent */}
              <TabsContent value="ai-agent" className="p-4 m-0">
                <div className="flex flex-col h-[320px]">
                  <div className="flex-1 bg-muted/30 rounded-md p-3 mb-3 overflow-y-auto">
                    {chatMessages.length === 0 ? (
                      <div className="flex items-center justify-center h-full">
                        <div className="text-center">
                          <Bot className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
                          <p className="text-sm text-muted-foreground">
                            {isTaxView ? "Tax Authority AI Assistant" : "Customs Authority AI Assistant"}
                          </p>
                          <p className="text-xs text-muted-foreground mt-1">
                            {isTaxView
                              ? "Ask about VAT rates, tax compliance, fraud patterns, or revenue implications."
                              : "Ask about risk profiles, product classification, seller history, or enforcement actions."}
                          </p>
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {chatMessages.map((msg, i) => (
                          <div key={i} className={cn("flex flex-col", msg.role === "user" ? "items-end" : "items-start")}>
                            <div className={cn(
                              "max-w-[80%] rounded-lg px-3 py-2 text-xs leading-relaxed whitespace-pre-wrap",
                              msg.role === "user"
                                ? "bg-primary text-primary-foreground"
                                : "bg-card border border-border text-card-foreground"
                            )}>
                              {msg.role === "assistant" && (
                                <span className={cn(
                                  "inline-flex items-center gap-1 mr-1 text-[10px] font-semibold uppercase tracking-wider",
                                  isTaxView ? "text-yellow-600" : "text-primary",
                                )}>
                                  <Bot className="h-3 w-3" />
                                  {isTaxView ? "Tax AI" : "Customs AI"}
                                </span>
                              )}
                              {msg.text}
                            </div>
                            {msg.role === "assistant" && msg.proposal && (() => {
                              const p = msg.proposal;
                              const label = actionLabelOf(p.action);
                              const isLive =
                                !!pendingProposal
                                && pendingProposal.action === p.action
                                && pendingProposal.comment === p.comment;
                              return (
                                <div className={cn(
                                  "mt-2 max-w-[80%] border rounded-lg p-3 text-xs",
                                  isLive ? "bg-muted/60 border-primary/40" : "bg-muted/20 border-border/60 opacity-70",
                                )}>
                                  <div className="flex items-center gap-1.5 mb-1">
                                    <Sparkles className="h-3 w-3 text-primary" />
                                    <span className="font-semibold text-card-foreground">
                                      Proposed action: {label}
                                    </span>
                                  </div>
                                  <p className="text-muted-foreground mb-1">
                                    <span className="font-medium">Comment to attach:</span> {p.comment || <em>(empty)</em>}
                                  </p>
                                  {isLive ? (
                                    <p className="text-[11px] text-muted-foreground italic">
                                      Reply <span className="font-semibold text-card-foreground">yes</span> to confirm,
                                      or <span className="font-semibold text-card-foreground">no</span> to cancel.
                                    </p>
                                  ) : (
                                    <p className="text-[11px] text-muted-foreground italic">Resolved.</p>
                                  )}
                                </div>
                              );
                            })()}
                          </div>
                        ))}
                        {chatLoading && (
                          <div className="flex justify-start">
                            <div className="bg-card border border-border rounded-lg px-3 py-2 text-xs text-muted-foreground">
                              <Bot className="h-3 w-3 inline mr-1 opacity-60" />Thinking...
                            </div>
                          </div>
                        )}
                        <div ref={chatEndRef} />
                      </div>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Textarea
                      placeholder={isTaxView
                        ? "Ask the Tax Authority assistant about VAT rates, compliance, or fraud patterns…"
                        : "Ask the Customs Authority assistant about risk profiles, classification, or seller history…"}
                      className="text-sm resize-none"
                      rows={2}
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          if (chatInput.trim() && !chatLoading) {
                            sendChat(chatInput.trim());
                          }
                        }
                      }}
                      disabled={chatLoading}
                    />
                    <Button size="sm" className="self-end" disabled={chatLoading || !chatInput.trim()}
                      onClick={() => sendChat(chatInput.trim())}>
                      Send
                    </Button>
                  </div>
                </div>
              </TabsContent>
            </Tabs>
          </div>

          {/* Activities */}
          <div className="bg-card rounded-lg border border-border p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-card-foreground uppercase tracking-wider">Activities</h3>
              {!isClosed && (
                <Button size="sm" variant="outline" onClick={() => setShowAddNoteDialog(true)}>
                  <MessageSquarePlus className="h-3.5 w-3.5 mr-1" />
                  Add Note
                </Button>
              )}
            </div>

            {/* Activity log */}
            <div className="space-y-0 max-h-[340px] overflow-y-auto pr-1">
              {[...activities].reverse().map((act) => {
                const note = extractNote(act.description);
                const mainDesc = descriptionWithoutNote(act.description);
                return (
                  <div key={act.id} className="flex items-start gap-3 py-3 border-b border-border last:border-0">
                    <div className="mt-0.5">{activityIcon(act.type, act.by)}</div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-card-foreground">{mainDesc}</p>
                      <p className="text-[11px] text-muted-foreground mt-0.5">
                        {act.by} · {act.timestamp}
                      </p>
                      {note && <p className="text-[11px] text-card-foreground/70 mt-1 italic">Note: "{note}"</p>}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* AI Activity Summary */}
            <div className="mt-3 pt-3 border-t border-border">
              <div className="bg-muted/50 rounded-md p-3">
                <div className="flex items-center gap-1.5 mb-1">
                  <p className="text-xs font-medium text-primary">AI Activity Summary</p>
                  <Sparkles className="h-3.5 w-3.5 text-primary" />
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {activities.length === 0
                    ? "No activities recorded yet."
                    : (() => {
                        const statusUpdates = activities.filter((a) => a.type === "status_update");
                        const notes = activities.filter((a) => a.type === "note");
                        const actions = activities.filter((a) => a.type === "action");
                        const riskUpdates = activities.filter((a) => a.type === "risk_update");
                        const lines: string[] = [];

                        if (statusUpdates.length > 0) {
                          const latestStatus = statusUpdates[statusUpdates.length - 1];
                          const statusDesc = latestStatus.description
                            .replace("Status changed from ", "")
                            .replace(" to ", " → ");
                          lines.push(
                            `Case progressed through ${statusUpdates.length} status change${statusUpdates.length > 1 ? "s" : ""}, currently "${statusDesc.split(" → ").pop()}".`,
                          );
                        }

                        if (riskUpdates.length > 0) {
                          const latestRisk = riskUpdates[riskUpdates.length - 1];
                          const scoreMatch = latestRisk.description.match(/\d+/);
                          const score = scoreMatch ? parseInt(scoreMatch[0]) : null;
                          if (score !== null) {
                            const level = score >= 65 ? "high" : score >= 40 ? "medium" : "low";
                            lines.push(
                              `Risk engine flagged this case at score ${score} (${level} risk), warranting ${level === "high" ? "immediate attention" : level === "medium" ? "closer review" : "standard processing"}.`,
                            );
                          }
                        }

                        if (actions.length > 0) {
                          const latestAction = actions[actions.length - 1];
                          lines.push(`Most recent action: ${latestAction.description}.`);
                        }

                        if (notes.length > 0) {
                          const latestNote = notes[notes.length - 1];
                          const noteText = latestNote.description.includes("Note: ")
                            ? latestNote.description.split("Note: ")[1]
                            : latestNote.description;
                          lines.push(`Officer noted: "${noteText}"`);
                        }

                        if (lines.length === 0) {
                          lines.push("Case was created with initial system entries. No officer actions taken yet.");
                        }

                        return lines.join(" ");
                      })()}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Save Risk Dialog */}
      <Dialog open={showSaveDialog} onOpenChange={setShowSaveDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Save Risk Assessment</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Risk level adjusted to <strong>{adjustedRiskLevel ?? "(unchanged)"}</strong>. Add a note to explain the change.
          </p>
          <Textarea
            placeholder="Add a note..."
            value={saveNoteText}
            onChange={(e) => setSaveNoteText(e.target.value)}
            rows={3}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowSaveDialog(false)}>
              Cancel
            </Button>
            <Button onClick={confirmSaveRisk}>Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Apply Action Dialog */}
      <Dialog open={showApplyDialog} onOpenChange={setShowApplyDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Apply Action: {selectedAction}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">Add a note for this action.</p>
          <Textarea
            placeholder="Add a note..."
            value={applyNoteText}
            onChange={(e) => setApplyNoteText(e.target.value)}
            rows={3}
          />
          {(selectedAction === "Recommend Control" || selectedAction === "Recommend Release") && (
            <>
              <div className="flex items-center gap-2 mt-2">
                <Checkbox checked={createRule} onCheckedChange={(c) => setCreateRule(!!c)} id="create-rule" />
                <label htmlFor="create-rule" className="text-sm text-card-foreground cursor-pointer">
                  Create a business rule to apply this to all similar future cases
                </label>
              </div>
              <div className="flex items-center gap-2 mt-1">
                <Checkbox
                  checked={informMemberStates}
                  onCheckedChange={(c) => setInformMemberStates(!!c)}
                  id="inform-member-states"
                />
                <label htmlFor="inform-member-states" className="text-sm text-card-foreground cursor-pointer">
                  Inform member states about this case
                </label>
              </div>
            </>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowApplyDialog(false)}>
              Cancel
            </Button>
            <Button onClick={confirmApplyAction}>Apply</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Business Rule Dialog */}
      <Dialog open={showRuleDialog} onOpenChange={setShowRuleDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Business Rule</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <p className="text-muted-foreground">
              A business rule will automatically apply the action <strong>"{selectedAction}"</strong> to all future
              cases matching this pattern:
            </p>
            <div className="bg-muted/50 rounded-md p-3 space-y-1 text-xs">
              <p>
                <span className="text-muted-foreground">Declared Product Category:</span>{" "}
                <span className="font-medium text-card-foreground">{caseData.declaredCategory}</span>
              </p>
              <p>
                <span className="text-muted-foreground">Product Description:</span>{" "}
                <span className="font-medium text-card-foreground">
                  {orders[0]?.productDescription ?? "—"}{" "}
                  <span className="text-muted-foreground font-normal">(AI summary of core meaning)</span>
                </span>
              </p>
              <p>
                <span className="text-muted-foreground">Seller:</span>{" "}
                <span className="font-medium text-card-foreground">{caseData.seller}</span>
              </p>
              <p>
                <span className="text-muted-foreground">Country of Destination:</span>{" "}
                <span className="font-medium text-card-foreground">{caseData.countryOfDestination}</span>
              </p>
              <p className="pt-1 mt-1 border-t border-border/60">
                <span className="text-muted-foreground">Action:</span>{" "}
                <span className="font-medium text-card-foreground">{selectedAction}</span>
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowRuleDialog(false)}>
              Cancel
            </Button>
            <Button onClick={confirmCreateRule}>Create Rule</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add Note Dialog */}
      <Dialog open={showAddNoteDialog} onOpenChange={setShowAddNoteDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Note</DialogTitle>
          </DialogHeader>
          <Textarea
            placeholder="Enter your note..."
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            rows={4}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAddNoteDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleAddNote} disabled={!noteText.trim()}>
              Add Note
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}
