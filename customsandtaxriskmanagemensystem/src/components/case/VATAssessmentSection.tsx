import { useState, useEffect } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { AlertTriangle, Save, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { getVatSubcategories, expectedVatRateFor, getCountryStandardRate } from "@/lib/referenceStore";
import { vatRatesByCategory, vatCategoryOptions } from "@/lib/vatRates";
import type { Case, Order } from "@/lib/caseData";

export interface VATAssessmentSectionProps {
  caseData: Case;
  orders: Order[];
  isClosed: boolean;
  vatSaved: boolean;
  initialCategory?: string;
  onSave: (category: string, note: string, subcategory?: string) => void;
}

export function VATAssessmentSection({
  caseData,
  orders,
  isClosed,
  vatSaved,
  initialCategory,
  onSave,
}: VATAssessmentSectionProps) {
  const [officerCategory, setOfficerCategory] = useState<string>(initialCategory ?? "");
  const [officerSubcategory, setOfficerSubcategory] = useState<string>("");
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [saveNote, setSaveNote] = useState("");

  useEffect(() => {
    if (initialCategory) setOfficerCategory(initialCategory);
  }, [initialCategory]);

  // Reset subcategory whenever the parent category changes so the
  // second dropdown never shows an option that doesn't belong to the
  // newly-picked category.
  useEffect(() => {
    setOfficerSubcategory("");
  }, [officerCategory]);

  const officerSubcategories = officerCategory
    ? getVatSubcategories(officerCategory)
    : [];
  // Friendly name for the currently-selected subcategory, used in the
  // locked view and the (closed) select trigger so the officer reads
  // "Medical device / diagnostic equipment" rather than "EL-09".
  const officerSubcategoryName = officerSubcategory
    ? officerSubcategories.find((s) => s.code === officerSubcategory)?.name ?? officerSubcategory
    : "";

  const totalItemValue = orders.reduce((sum, o) => sum + o.itemValue, 0);
  // Declared VAT = ground-truth sum of each order's actual vat_fee
  // (per-destination / per-subcategory, so it can't be recomputed from
  // a single category rate). Effective rate inferred from the actual
  // totals — stays in sync with the Linked Orders tab automatically.
  const declaredVatValue = orders.reduce((sum, o) => sum + o.vatValue, 0);
  const declaredVatRate = totalItemValue > 0
    ? (declaredVatValue / totalItemValue) * 100
    : 0;
  // Rate lookup strategy, priority order:
  //   1. expectedVatRateFor(destination, subcategory) — the canonical
  //      (country, subcategory) entry from vat_dataset, or the country
  //      standard rate if no exception applies. Returns a fraction.
  //   2. vatRatesByCategory()[parent] — backend vat_categories rate
  //      (Irish standard), used as last-resort when destination is
  //      outside the 4 countries we track in vat_dataset.
  //   3. Historical fallback of 23 (Irish standard) if even that is
  //      missing.
  // We emit rates as PERCENTAGES (e.g. 23 not 0.23) to stay consistent
  // with the rest of this component.
  const fractionToPercent = (f: number | undefined): number | undefined =>
    f === undefined ? undefined : f * 100;
  const destination = caseData.countryOfDestination;
  const aiSuggestedCategory = caseData.aiSuggestedCategory;

  // AI-suggested: no subcategory is available (AI only proposes a
  // parent category). Use country standard rate for the destination,
  // fall back to the backend vat_categories rate for the suggested
  // parent, then to 23.
  const aiVatRate =
    fractionToPercent(getCountryStandardRate(destination))
    ?? vatRatesByCategory()[aiSuggestedCategory]
    ?? 23;
  const aiVatValue = totalItemValue * (aiVatRate / 100);

  // Officer-suggested: the officer picks a subcategory when available,
  // which unlocks the precise (country, subcategory) rate. Absent a
  // subcategory, fall back to country standard rate, then to the
  // parent-category rate, then to 23.
  const officerVatRate = officerCategory
    ? (
        fractionToPercent(expectedVatRateFor(destination, officerSubcategory))
        ?? vatRatesByCategory()[officerCategory]
        ?? 23
      )
    : null;
  const officerVatValue = officerVatRate !== null ? totalItemValue * (officerVatRate / 100) : null;
  const vatDifference = officerVatValue !== null ? officerVatValue - declaredVatValue : null;

  const confidencePct = caseData.declaredCategory !== caseData.aiSuggestedCategory ? 90 : 30;
  const locked = vatSaved || isClosed;

  const handleConfirmSave = () => {
    onSave(officerCategory, saveNote, officerSubcategory || undefined);
    setSaveNote("");
    setShowSaveDialog(false);
  };

  return (
    <div className="bg-card rounded-lg border border-border p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold text-card-foreground uppercase tracking-wider">VAT Assessment</h3>
        </div>
        {!isClosed && !vatSaved && (
          <Button
            size="sm"
            variant="outline"
            className="h-7 px-2.5 text-xs"
            disabled={!officerCategory}
            onClick={() => setShowSaveDialog(true)}
          >
            <Save className="h-3 w-3 mr-1" />
            Save
          </Button>
        )}
        {vatSaved && <Badge className="text-[10px] bg-success/15 text-success">Saved</Badge>}
      </div>

      {/* Declared VAT */}
      <div className="mb-4">
        <p className="text-xs font-semibold text-card-foreground mb-2">Declared VAT</p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="px-3 py-2 text-left text-muted-foreground font-medium">Declared VAT Product Category</th>
                <th className="px-3 py-2 text-right text-muted-foreground font-medium">Declared VAT %</th>
                <th className="px-3 py-2 text-right text-muted-foreground font-medium">Total Value</th>
                <th className="px-3 py-2 text-right text-muted-foreground font-medium">Declared VAT Value</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-border">
                <td className="px-3 py-2 text-card-foreground">{caseData.declaredCategory}</td>
                <td className="px-3 py-2 text-right text-card-foreground">{declaredVatRate.toFixed(2)}%</td>
                <td className="px-3 py-2 text-right text-card-foreground">€{totalItemValue.toFixed(2)}</td>
                <td className="px-3 py-2 text-right text-card-foreground">€{declaredVatValue.toFixed(2)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* AI-Suggested VAT */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-semibold text-card-foreground">AI-Suggested VAT</p>
          {!caseData.aiAnalysis && (
            <Badge className="text-[10px] text-muted-foreground" variant="outline">
              AI Agent: Not yet analysed
            </Badge>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="px-3 py-2 text-left text-muted-foreground font-medium">
                  AI Suggested VAT Product Category
                </th>
                <th className="px-3 py-2 text-right text-muted-foreground font-medium">AI Suggested VAT %</th>
                <th className="px-3 py-2 text-right text-muted-foreground font-medium">Total Value</th>
                <th className="px-3 py-2 text-right text-muted-foreground font-medium">AI Suggested VAT Value</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-border">
                <td className="px-3 py-2 text-card-foreground">{aiSuggestedCategory}</td>
                <td className="px-3 py-2 text-right text-card-foreground">{aiVatRate.toFixed(2)}%</td>
                <td className="px-3 py-2 text-right text-card-foreground">€{totalItemValue.toFixed(2)}</td>
                <td className="px-3 py-2 text-right text-card-foreground">€{aiVatValue.toFixed(2)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Officer-Suggested VAT */}
      <div className="mb-4">
        <p className="text-xs font-semibold text-card-foreground mb-2">Officer-Suggested VAT</p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="px-3 py-2 text-left text-muted-foreground font-medium">VAT Product Category</th>
                <th className="px-3 py-2 text-right text-muted-foreground font-medium">Officer-Suggested VAT %</th>
                <th className="px-3 py-2 text-right text-muted-foreground font-medium">Total Value</th>
                <th className="px-3 py-2 text-right text-muted-foreground font-medium">Officer-Suggested VAT Value</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-border">
                <td className="px-3 py-2">
                  {locked ? (
                    <span className="text-card-foreground">
                      {officerCategory || "—"}
                      {officerSubcategory && officerSubcategoryName && (
                        <span className="text-muted-foreground">
                          {" "}· {officerSubcategoryName}
                          <span className="font-mono"> ({officerSubcategory})</span>
                        </span>
                      )}
                    </span>
                  ) : (
                    <div className="flex items-center gap-2 flex-wrap">
                      <Select value={officerCategory} onValueChange={setOfficerCategory}>
                        <SelectTrigger className="h-8 w-[200px] text-xs">
                          <SelectValue placeholder="Select category..." />
                        </SelectTrigger>
                        <SelectContent>
                          {vatCategoryOptions().map((opt) => (
                            <SelectItem key={opt.value} value={opt.value}>
                              {opt.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {officerCategory && officerSubcategories.length > 0 && (
                        <Select value={officerSubcategory} onValueChange={setOfficerSubcategory}>
                          <SelectTrigger className="h-8 w-[300px] text-xs">
                            {/* Explicit text in the trigger: show the
                                friendly name (not the EL-09 code) once
                                an option is picked. */}
                            {officerSubcategory
                              ? <span className="truncate">{officerSubcategoryName}</span>
                              : <SelectValue placeholder="Select subcategory..." />}
                          </SelectTrigger>
                          <SelectContent>
                            {officerSubcategories.map((sub) => (
                              <SelectItem key={sub.code} value={sub.code}>
                                <span className="text-card-foreground">{sub.name}</span>
                                <span className="font-mono ml-2 text-muted-foreground">({sub.code})</span>
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      )}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 text-right text-card-foreground">
                  {officerVatRate !== null ? `${officerVatRate.toFixed(2)}%` : "—"}
                </td>
                <td className="px-3 py-2 text-right text-card-foreground">€{totalItemValue.toFixed(2)}</td>
                <td className="px-3 py-2 text-right text-card-foreground">
                  {officerVatValue !== null ? `€${officerVatValue.toFixed(2)}` : "—"}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Estimated VAT Difference - only when officer selected a category */}
      {officerCategory && vatDifference !== null && (
        <div className="mb-4 space-y-2">
          <div className="flex justify-between text-xs">
            <span className="text-muted-foreground">Officer-Suggested VAT Value</span>
            <span className="text-card-foreground">€{officerVatValue!.toFixed(2)}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-muted-foreground">- Declared VAT Value</span>
            <span className="text-card-foreground">-€{declaredVatValue.toFixed(2)}</span>
          </div>
          <div className="flex justify-between items-center pt-2 border-t border-border">
            <span className="text-xs font-bold text-card-foreground">Estimated VAT Difference</span>
            <span className="flex items-center gap-2">
              <span
                className={cn(
                  "text-base font-bold",
                  vatDifference > 0 ? "text-destructive" : vatDifference < 0 ? "text-success" : "text-card-foreground",
                )}
              >
                € {Math.abs(vatDifference).toFixed(2)}
              </span>
              {vatDifference > 0 && (
                <span className="text-[10px] font-bold uppercase tracking-wider text-destructive">Underpaid</span>
              )}
              {vatDifference < 0 && (
                <span className="text-[10px] font-bold uppercase tracking-wider text-success">Overpaid</span>
              )}
            </span>
          </div>
        </div>
      )}

      {/* AI VAT Assessment Summary — category deviation (always shown)
          plus the VAT Fraud Detection agent's verdict, rationale and
          legislation references once the agent has run. */}
      <div className="mt-3 pt-3 border-t border-border">
        <div className="bg-muted/50 rounded-md p-3">
          <div className="flex items-center gap-1.5 mb-1">
            <p className="text-xs font-medium text-primary">AI VAT Assessment Summary</p>
            <Sparkles className="h-3.5 w-3.5 text-primary" />
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed">
            {(() => {
              const aiVatGap = aiVatValue - declaredVatValue;
              const sameCategory = caseData.declaredCategory === caseData.aiSuggestedCategory;
              if (Math.abs(aiVatGap) < 0.005) {
                return (
                  <>
                    Declared VAT category "{caseData.declaredCategory}" appears consistent with the product description "
                    {orders[0]?.productDescription}". No deviation detected.
                  </>
                );
              }
              return (
                <>
                  {sameCategory ? "VAT rate mismatch within the declared category. " : "Wrong VAT product category declared. "}
                  The product description "{orders[0]?.productDescription}" suggests a VAT rate of {aiVatRate.toFixed(2)}%, while the invoice applied {declaredVatRate.toFixed(2)}% under "{caseData.declaredCategory}". Estimated gap: €{Math.abs(aiVatGap).toFixed(2)}.
                </>
              );
            })()}
          </p>
          <p className="text-xs mt-2">
            <span className="text-muted-foreground">Confidence: </span>
            <span
              className={cn(
                "font-semibold",
                confidencePct >= 80 ? "text-success" : confidencePct >= 50 ? "text-warning" : "text-muted-foreground",
              )}
            >
              {confidencePct}%
            </span>{" "}
            <span
              className={cn(
                confidencePct >= 80 ? "text-success" : confidencePct >= 50 ? "text-warning" : "text-muted-foreground",
              )}
            >
              ({confidencePct >= 80 ? "High Confidence" : confidencePct >= 50 ? "Medium Confidence" : "Low Confidence"})
            </span>
          </p>

          {/* Agent verdict + rationale, shown once the VAT Fraud Detection
              agent has completed. The string is stored as "[verdict] reasoning"
              by _agent_worker in api.py; we split them so the verdict renders
              as a coloured badge and the reasoning as free text. */}
          {caseData.aiAnalysis && (() => {
            const raw = caseData.aiAnalysis;
            const m = raw.match(/^\[(\w+)\]\s*/);
            const verdict = m ? m[1] : "unknown";
            const reasoning = m ? raw.slice(m[0].length) : raw;
            const verdictColor =
              verdict === "suspicious" || verdict === "incorrect" ? "text-destructive" :
              verdict === "correct" || verdict === "legitimate"    ? "text-success" :
              "text-warning";
            return (
              <div className="mt-3 pt-2 border-t border-border/60">
                <div className="flex items-center gap-1.5 mb-1">
                  <Sparkles className="h-3 w-3 text-primary" />
                  <span className="text-[11px] font-semibold text-card-foreground">
                    VAT Fraud Detection Agent — verdict:
                  </span>
                  <Badge className={cn("text-[10px] capitalize", verdictColor)} variant="outline">
                    {verdict}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap">
                  {reasoning || "No rationale returned."}
                </p>
                {caseData.aiLegislationRefs && caseData.aiLegislationRefs.length > 0 && (
                  <div className="mt-2">
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                      Legislation sources
                    </p>
                    <ul className="space-y-1">
                      {caseData.aiLegislationRefs.map((ref, i) => {
                        const label = ref.source
                          ? `${ref.source}${ref.section ? ` — ${ref.section}` : ""}`
                          : ref.ref ?? `Reference ${i + 1}`;
                        const detail = [
                          ref.paragraph ? `¶ ${ref.paragraph}` : null,
                          ref.page != null && ref.page !== "" ? `p. ${ref.page}` : null,
                        ].filter(Boolean).join(" · ");
                        return (
                          <li key={i} className="text-[11px] leading-snug">
                            {ref.url ? (
                              <a
                                href={ref.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-primary hover:underline"
                              >
                                {label}
                              </a>
                            ) : (
                              <span className="text-card-foreground">{label}</span>
                            )}
                            {detail && <span className="text-muted-foreground"> ({detail})</span>}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}
                <p className="text-[10px] text-muted-foreground mt-2">
                  Source: VAT Fraud Detection Agent · LM Studio (local LLM) · Case {caseData.id}
                </p>
              </div>
            );
          })()}
        </div>
      </div>

      {/* Save VAT Assessment Dialog */}
      <Dialog open={showSaveDialog} onOpenChange={setShowSaveDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Save VAT Assessment</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Officer-suggested VAT category: <strong>{officerCategory || "Not set"}</strong>. Add a note to explain the
            assessment.
          </p>
          <Textarea
            placeholder="Add a note..."
            value={saveNote}
            onChange={(e) => setSaveNote(e.target.value)}
            rows={3}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowSaveDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleConfirmSave}>Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
