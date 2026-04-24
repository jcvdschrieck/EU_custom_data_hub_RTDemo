import { useState, useMemo, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { getLiveCases, type Case, type CaseStatus } from "@/lib/caseData";
import { customsAction } from "@/lib/apiClient";
import { useCaseTab } from "@/pages/CustomsLayout";
import { StatCard } from "@/components/StatCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { TransactionPieCharts } from "@/components/TransactionPieCharts";
import { ColumnFilterDropdown, NumericFilterDropdown, type NumericRange } from "@/components/ColumnFilterDropdown";
import {
  AlertTriangle,
  Search,
  Eye,
  CheckCircle2,
  XCircle,
  FileSearch,
  MoreHorizontal,
  Clock,
  UserRound,
  X,
  Bot,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/use-toast";
import { getEffectiveCaseStatus, getEffectiveCaseAction, closeCase, submitForTaxReview, requestThirdPartyInput, returnToCustomsFromTax, getCaseStatuses, getCaseWithSnapshot, appendActivities, nowTimestamp } from "@/lib/caseStore";
import { customsCodeFor } from "@/lib/caseEnum";
import { statusStyles, riskLevelStyles } from "@/lib/styles";

const riskScoreColor = (_score: number) => "text-card-foreground font-medium";

const aiActionStyles: Record<string, { color: string; icon: typeof XCircle }> = {
  "Recommend Control": { color: "text-destructive", icon: XCircle },
  "Recommend Release": { color: "text-success", icon: CheckCircle2 },
  "Submit for Tax Review": { color: "text-primary", icon: FileSearch },
  "Request Input from Deemed Importer": { color: "text-warning", icon: UserRound },
};

const OngoingCases = () => {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");
  const [filterView, setFilterView] = useState<string>("all");
  const { toast } = useToast();
  const navigate = useNavigate();
  const { openTab } = useCaseTab();

  // Action dialog state
  const [showActionDialog, setShowActionDialog] = useState(false);
  const [pendingActionType, setPendingActionType] = useState<string>("");
  const [actionNote, setActionNote] = useState("");
  const [createRule, setCreateRule] = useState(false);
  const [informMemberStates, setInformMemberStates] = useState(false);

  // Force re-render when case store changes
  const [, forceUpdate] = useState(0);
  useEffect(() => {
    const handler = () => forceUpdate(v => v + 1);
    window.addEventListener("case-store-updated", handler);
    return () => window.removeEventListener("case-store-updated", handler);
  }, []);

  // Column filters
  const [colFilterSeller, setColFilterSeller] = useState<Set<string>>(new Set());
  const [colFilterCategory, setColFilterCategory] = useState<Set<string>>(new Set());
  const [colFilterOrigin, setColFilterOrigin] = useState<Set<string>>(new Set());
  const [colFilterRiskLevel, setColFilterRiskLevel] = useState<Set<string>>(new Set());
  const [colFilterStatus, setColFilterStatus] = useState<Set<string>>(new Set());
  const [colFilterRiskScore, setColFilterRiskScore] = useState<NumericRange>({ min: null, max: null });

  // Pie chart active values
  const [activeSeller, setActiveSeller] = useState("all");
  const [activeOrigin, setActiveOrigin] = useState("all");
  const [activeCategory, setActiveCategory] = useState("all");

  const handlePieFilterSeller = (v: string) => {
    setActiveSeller(v);
    setColFilterSeller(v === "all" ? new Set() : new Set([v]));
  };
  const handlePieFilterOrigin = (v: string) => {
    setActiveOrigin(v);
    setColFilterOrigin(v === "all" ? new Set() : new Set([v]));
  };
  const handlePieFilterCategory = (v: string) => {
    setActiveCategory(v);
    setColFilterCategory(v === "all" ? new Set() : new Set([v]));
  };

  // Ongoing dashboard: exclude closed / under-tax-review / AI-investigating
  // cases. getCaseWithSnapshot overlays the officer's level override so
  // the row badge agrees with the case-review screen (the AI score is
  // always preserved by the helper — officer edits are level-only).
  const ongoingCases = useMemo(() => {
    return getLiveCases()
      .filter(c => {
        const effectiveStatus = getEffectiveCaseStatus(c.id, c.status);
        return effectiveStatus !== "Closed" && effectiveStatus !== "Under Review by Tax"
          && effectiveStatus !== "AI Investigation in Progress"
          && c.countryOfDestination === "IE";
      })
      .map(getCaseWithSnapshot);
  }, [getCaseStatuses()]);

  const uniqueSellers = useMemo(() => [...new Set(ongoingCases.map((c) => c.seller))].sort(), [ongoingCases]);
  const uniqueCategories = useMemo(() => [...new Set(ongoingCases.map((c) => c.declaredCategory))].sort(), [ongoingCases]);
  const uniqueOrigins = useMemo(() => [...new Set(ongoingCases.map((c) => c.countryOfOrigin))].sort(), [ongoingCases]);
  const uniqueRiskLevels = useMemo(() => ["High", "Medium", "Low"], []);
  const uniqueStatuses = useMemo(() => {
    const all = new Set<string>();
    ongoingCases.forEach((c) => all.add(getEffectiveCaseStatus(c.id, c.status)));
    return [...all].sort();
  }, [ongoingCases]);

  const passesFilter = (value: string, filterSet: Set<string>) => filterSet.size === 0 || filterSet.has(value);

  const filteredCases = useMemo(() => {
    return ongoingCases.filter((c) => {
      if (filterView === "selection" && !selectedIds.has(c.id)) return false;
      const q = searchQuery.toLowerCase();
      const matchesSearch =
        !q ||
        c.id.toLowerCase().includes(q) ||
        c.caseName.toLowerCase().includes(q) ||
        c.seller.toLowerCase().includes(q) ||
        c.countryOfOrigin.toLowerCase().includes(q) ||
        c.declaredCategory.toLowerCase().includes(q);
      const passesRiskScore =
        (colFilterRiskScore.min === null || c.riskScore >= colFilterRiskScore.min) &&
        (colFilterRiskScore.max === null || c.riskScore <= colFilterRiskScore.max);
      const effectiveStatus = getEffectiveCaseStatus(c.id, c.status);
      return (
        matchesSearch &&
        passesFilter(c.seller, colFilterSeller) &&
        passesFilter(c.declaredCategory, colFilterCategory) &&
        passesFilter(c.countryOfOrigin, colFilterOrigin) &&
        passesFilter(c.riskLevel, colFilterRiskLevel) &&
        passesFilter(effectiveStatus, colFilterStatus) &&
        passesRiskScore
      );
    });
  }, [searchQuery, colFilterSeller, colFilterCategory, colFilterOrigin, colFilterRiskLevel, colFilterStatus, colFilterRiskScore, filterView, selectedIds, ongoingCases]);

  const hasActiveFilters =
    colFilterSeller.size > 0 || colFilterCategory.size > 0 || colFilterOrigin.size > 0 ||
    colFilterRiskLevel.size > 0 || colFilterStatus.size > 0 ||
    colFilterRiskScore.min !== null || colFilterRiskScore.max !== null ||
    filterView !== "all" || searchQuery !== "";

  const clearFilters = () => {
    setSearchQuery("");
    setColFilterSeller(new Set());
    setColFilterCategory(new Set());
    setColFilterOrigin(new Set());
    setColFilterRiskLevel(new Set());
    setColFilterStatus(new Set());
    setColFilterRiskScore({ min: null, max: null });
    setFilterView("all");
    setActiveSeller("all");
    setActiveOrigin("all");
    setActiveCategory("all");
  };

  const toggleSelection = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selectedIds.size === filteredCases.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredCases.map((c) => c.id)));
    }
  };

  const openActionDialog = (actionType: string) => {
    setPendingActionType(actionType);
    setActionNote("");
    setCreateRule(false);
    setInformMemberStates(false);
    setShowActionDialog(true);
  };

  const confirmAction = () => {
    const ids = [...selectedIds];
    const ts = nowTimestamp();
    const officer = "Customs Authority Officer";
    const noteSuffix = actionNote ? ` Note: ${actionNote}` : "";

    const writeActivities = (caseObj: Case, newStatus: Case["status"], extraPatch: Partial<Case> = {}) => {
      appendActivities(
        caseObj,
        [
          {
            id: `bulk-act-${caseObj.id}-${Date.now()}`,
            timestamp: ts,
            type: "action",
            description: `Action taken: ${pendingActionType}.${noteSuffix}`,
            by: officer,
          },
          {
            id: `bulk-status-${caseObj.id}-${Date.now()}`,
            timestamp: ts,
            type: "status_update",
            description: `Status changed to ${newStatus}.`,
            by: officer,
          },
        ],
        { status: newStatus, ...extraPatch },
      );
    };

    // Track backend-call failures so we surface them instead of silently
    // swallowing the error (previously .catch(() => {}) hid real CORS /
    // network / 5xx issues — the UI would show an optimistic toast while
    // the backend never saw the action, so e.g. the VAT Fraud Detection
    // agent never fired).
    const failures: string[] = [];
    const reportFailure = (id: string, err: unknown) => {
      failures.push(`${id}: ${String(err)}`);
      console.error(`[customs-action] ${id} failed`, err);
    };

    const backendCalls: Promise<void>[] = [];

    ids.forEach((id) => {
      const c = getLiveCases().find((x) => x.id === id);
      if (!c) return;
      if (pendingActionType === "Recommend Control" || pendingActionType === "Recommend Release") {
        closeCase(id, pendingActionType as "Recommend Control" | "Recommend Release");
        writeActivities(c, "Closed", {
          actionTaken: pendingActionType as "Recommend Control" | "Recommend Release",
          closedDate: new Date().toISOString().split("T")[0],
        });
        const action = customsCodeFor(pendingActionType);
        if (action) {
          backendCalls.push(
            customsAction(id, { action, comment: actionNote, officer })
              .catch((err) => reportFailure(id, err)),
          );
        }
      } else if (pendingActionType === "Submit for Tax Review") {
        submitForTaxReview(id);
        writeActivities(c, "Under Review by Tax");
        backendCalls.push(
          customsAction(id, { action: "tax_review", comment: actionNote, officer })
            .catch((err) => reportFailure(id, err)),
        );
      } else if (pendingActionType === "Request Input from Deemed Importer") {
        requestThirdPartyInput(id);
        writeActivities(c, "Requested Input by Deemed Importer");
        backendCalls.push(
          customsAction(id, { action: "input_requested", comment: actionNote, officer })
            .catch((err) => reportFailure(id, err)),
        );
      }
    });

    // Fire the optimistic toast, then surface a second destructive toast
    // if any backend call actually failed. Avoids blocking the UI on
    // the backend round-trip while still making silent failures visible.
    toast({
      title: pendingActionType,
      description: `${ids.length} case(s) updated.${actionNote ? " Notes attached." : ""}`,
    });
    void Promise.all(backendCalls).then(() => {
      if (failures.length > 0) {
        toast({
          variant: "destructive",
          title: `Backend rejected ${failures.length} of ${ids.length} action(s)`,
          description: "See browser console for details. Affected cases may not have triggered the AI agent.",
        });
      }
    });

    setSelectedIds(new Set());
    setShowActionDialog(false);
    setActionNote("");
    setCreateRule(false);
    setInformMemberStates(false);
  };

  const pieData = ongoingCases.map((c) => ({
    seller: c.seller,
    originCountry: c.countryOfOrigin,
    productCategory: c.declaredCategory,
  }));

  const allIeCases = getLiveCases().filter(c => c.countryOfDestination === "IE");
  const myCasesCount = ongoingCases.filter((c) => {
    const s = getEffectiveCaseStatus(c.id, c.status);
    return s === "New" || s === "Under Review by Customs" || s === "Reviewed by Tax";
  }).length;
  const aiInvestigating = allIeCases.filter(c => getEffectiveCaseStatus(c.id, c.status) === "AI Investigation in Progress").length;
  const underReviewByOther = allIeCases.filter(c => getEffectiveCaseStatus(c.id, c.status) === "Under Review by Tax").length;
  const pendingThirdParty = allIeCases.filter(c => getEffectiveCaseStatus(c.id, c.status) === "Requested Input by Deemed Importer").length;

  return (
    <main className="flex-1 p-6 space-y-6 overflow-auto">
      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="My Cases" value={myCasesCount} subtitle="Awaiting action" icon={AlertTriangle} variant="danger" />
        <StatCard title="Under Review by AI Agent" value={aiInvestigating} subtitle="Sent to AI agent" icon={Bot} variant="default" />
        <StatCard title="Under Review by Other Authority" value={underReviewByOther} subtitle="Sent to Tax Authority" icon={Clock} variant="warning" />
        <StatCard title="Pending Input from Deemed Importer" value={pendingThirdParty} subtitle="Awaiting input" icon={Clock} variant="warning" />
      </div>

      {/* Pie Charts */}
      <TransactionPieCharts
        transactions={pieData}
        onFilterSeller={handlePieFilterSeller}
        onFilterOrigin={handlePieFilterOrigin}
        onFilterProductCategory={handlePieFilterCategory}
        activeSeller={activeSeller}
        activeOrigin={activeOrigin}
        activeProductCategory={activeCategory}
      />

      {/* Cases table */}
      <div className="bg-card rounded-lg border border-border shadow-sm">
        <div className="border-b border-border p-5">
          <h2 className="text-lg font-semibold text-card-foreground">Cases for Investigation</h2>
          <p className="text-xs text-muted-foreground mt-0.5">Select cases and take action</p>
        </div>

        {/* Search bar */}
        <div className="px-5 py-3 border-b border-border flex items-center gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search by case ID, seller, country..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 bg-muted/50"
            />
          </div>
          <Select value={filterView} onValueChange={setFilterView}>
            <SelectTrigger className="w-[170px] h-9 text-xs">
              <SelectValue placeholder="View" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">View All</SelectItem>
              <SelectItem value="selection">Selection Only ({selectedIds.size})</SelectItem>
            </SelectContent>
          </Select>
          {hasActiveFilters && (
            <Button variant="ghost" size="sm" className="h-9 gap-1 text-xs text-muted-foreground" onClick={clearFilters}>
              <X className="h-3 w-3" /> Clear filters
            </Button>
          )}
          <span className="text-xs text-muted-foreground whitespace-nowrap">
            {filteredCases.length} of {ongoingCases.length}
          </span>
        </div>

        {/* Bulk action bar */}
        {selectedIds.size > 0 && (
          <div className="flex items-center justify-between border-b border-border p-4 bg-muted/30">
            <span className="text-sm font-medium text-card-foreground">
              {selectedIds.size} case{selectedIds.size !== 1 ? "s" : ""} selected
            </span>
            {(() => {
              // A case already "Reviewed by Tax" has had its tax verdict
              // delivered, so resubmitting to Tax is nonsensical. Disable
              // the option whenever any selected case is in that state.
              const anyReviewedByTax = [...selectedIds].some((id) => {
                const c = ongoingCases.find((x) => x.id === id);
                return c && getEffectiveCaseStatus(c.id, c.status) === "Reviewed by Tax";
              });
              return (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button size="sm" variant="outline" className="gap-1.5">
                      <MoreHorizontal className="h-3.5 w-3.5" />
                      Apply Action to Selection ({selectedIds.size})
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => openActionDialog("Recommend Control")}>
                      <XCircle className="h-4 w-4 mr-2 text-destructive" /> Recommend Control
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => openActionDialog("Recommend Release")}>
                      <CheckCircle2 className="h-4 w-4 mr-2 text-success" /> Recommend Release
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      disabled={anyReviewedByTax}
                      onClick={() => { if (!anyReviewedByTax) openActionDialog("Submit for Tax Review"); }}
                      title={anyReviewedByTax ? "At least one selected case has already been reviewed by Tax." : undefined}
                    >
                      <FileSearch className="h-4 w-4 mr-2" /> Submit for Tax Review
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => openActionDialog("Request Input from Deemed Importer")}>
                      <UserRound className="h-4 w-4 mr-2 text-warning" /> Request Input from Deemed Importer
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              );
            })()}
          </div>
        )}

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border bg-muted/50">
                <th className="px-3 py-3 text-center">
                  <Checkbox
                    checked={filteredCases.length > 0 && selectedIds.size === filteredCases.length}
                    onCheckedChange={toggleAll}
                  />
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">Case ID</th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">Case Name</th>
                <th className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground"># Orders in Case</th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <span className="inline-flex items-center">
                    Seller
                    <ColumnFilterDropdown options={uniqueSellers} selected={colFilterSeller} onSelectionChange={setColFilterSeller} />
                  </span>
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <span className="inline-flex items-center">
                    Declared Product Category
                    <ColumnFilterDropdown options={uniqueCategories} selected={colFilterCategory} onSelectionChange={setColFilterCategory} />
                  </span>
                </th>
                <th className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <span className="inline-flex items-center">
                    Country of Origin
                    <ColumnFilterDropdown options={uniqueOrigins} selected={colFilterOrigin} onSelectionChange={setColFilterOrigin} />
                  </span>
                </th>
                <th className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">Country of Destination</th>
                <th className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <span className="inline-flex items-center">
                    Risk Score
                    <NumericFilterDropdown range={colFilterRiskScore} onRangeChange={setColFilterRiskScore} />
                  </span>
                </th>
                <th className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <span className="inline-flex items-center">
                    Risk Level
                    <ColumnFilterDropdown options={uniqueRiskLevels} selected={colFilterRiskLevel} onSelectionChange={setColFilterRiskLevel} />
                  </span>
                </th>
                <th className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <span className="inline-flex items-center">
                    Status
                    <ColumnFilterDropdown options={uniqueStatuses} selected={colFilterStatus} onSelectionChange={setColFilterStatus} />
                  </span>
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">AI Suggested Action</th>
                <th className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">Review</th>
              </tr>
            </thead>
            <tbody>
              {filteredCases.map((c) => {
                const effectiveStatus = getEffectiveCaseStatus(c.id, c.status);
                // Once Tax Authority has reviewed the case, the AI's
                // original "Submit for Tax Review" suggestion is stale.
                // The tax verdict mapped to a customs action (Recommend
                // Control / Release) is persisted as the case action —
                // surface it here so the Customs officer sees the live
                // post-review recommendation, not the pre-review one.
                const effectiveAction = effectiveStatus === "Reviewed by Tax"
                  ? (getEffectiveCaseAction(c.id, undefined) as unknown as string ?? c.aiSuggestedAction)
                  : c.aiSuggestedAction;
                const actionInfo = aiActionStyles[effectiveAction];
                return (
                  <tr key={c.id} className="border-b border-border last:border-0 hover:bg-muted/30 transition-colors">
                    <td className="px-3 py-3.5 text-center">
                      <Checkbox checked={selectedIds.has(c.id)} onCheckedChange={() => toggleSelection(c.id)} />
                    </td>
                    <td className="px-4 py-3.5 text-sm font-mono text-card-foreground">{c.id}</td>
                    <td className="px-4 py-3.5 text-sm text-card-foreground max-w-[200px] truncate" title={c.caseName}>{c.caseName}</td>
                    <td className="px-4 py-3.5 text-sm text-center text-card-foreground">{c.orders.length}</td>
                    <td className="px-4 py-3.5 text-sm text-card-foreground">{c.seller}</td>
                    <td className="px-4 py-3.5 text-sm text-card-foreground">{c.declaredCategory}</td>
                    <td className="px-4 py-3.5 text-center"><Badge variant="outline" className="text-xs">{c.countryOfOrigin}</Badge></td>
                    <td className="px-4 py-3.5 text-center"><Badge variant="outline" className="text-xs">{c.countryOfDestination}</Badge></td>
                    <td className="px-4 py-3.5 text-center"><span className={cn("text-sm", riskScoreColor(c.riskScore))}>{c.riskScore}</span></td>
                    <td className="px-4 py-3.5 text-center"><Badge className={cn("text-xs", riskLevelStyles[c.riskLevel])}>{c.riskLevel}</Badge></td>
                    <td className="px-4 py-3.5 text-center"><Badge className={cn("text-xs", statusStyles[effectiveStatus])}>{effectiveStatus}</Badge></td>
                    <td className="px-4 py-3.5">
                      <span className={cn("text-xs font-medium inline-flex items-center gap-1", actionInfo?.color)}>
                        {actionInfo && <actionInfo.icon className="h-3.5 w-3.5" />}
                        {effectiveAction}
                      </span>
                    </td>
                    <td className="px-4 py-3.5 text-center">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => {
                          openTab(c.id, c.id, false);
                          navigate(`/customs-authority/case/${c.id}`);
                        }}
                      >
                        <Eye className="h-4 w-4" />
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Action Dialog */}
      <Dialog open={showActionDialog} onOpenChange={setShowActionDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Apply Action: {pendingActionType}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">Add a note for this action.</p>
          <Textarea placeholder="Add a note..." value={actionNote} onChange={(e) => setActionNote(e.target.value)} rows={3} />
          {(pendingActionType === "Recommend Control" || pendingActionType === "Recommend Release") && (
            <>
              <div className="flex items-start gap-2 mt-2">
                <Checkbox checked={createRule} onCheckedChange={(c) => setCreateRule(!!c)} id="bulk-create-rule" className="mt-0.5" />
                <label htmlFor="bulk-create-rule" className="text-sm text-card-foreground cursor-pointer">Create a business rule to apply this to all similar future cases</label>
              </div>
              {createRule && (
                <div className="ml-6 -mt-1 rounded-md border border-border bg-muted/40 p-3">
                  <p className="text-xs font-medium text-card-foreground mb-1.5">This rule will be applied to future cases that match:</p>
                  <ul className="text-xs text-muted-foreground space-y-1 list-disc pl-4">
                    <li>Same <span className="text-card-foreground font-medium">declared product category</span></li>
                    <li>Same <span className="text-card-foreground font-medium">product description</span> (AI summary of core meaning)</li>
                    <li>Same <span className="text-card-foreground font-medium">seller</span></li>
                    <li>Same <span className="text-card-foreground font-medium">country of destination</span></li>
                  </ul>
                </div>
              )}
              <div className="flex items-center gap-2 mt-1">
                <Checkbox checked={informMemberStates} onCheckedChange={(c) => setInformMemberStates(!!c)} id="bulk-inform-member-states" />
                <label htmlFor="bulk-inform-member-states" className="text-sm text-card-foreground cursor-pointer">Inform member states about this case</label>
              </div>
            </>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowActionDialog(false)}>Cancel</Button>
            <Button onClick={confirmAction}>Apply</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
};

export default OngoingCases;
