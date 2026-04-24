import { useState, useMemo, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTaxCaseTab } from "@/pages/TaxLayout";
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
  UserRound,
  MoreHorizontal,
  Clock,
  X,
  Bot,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/use-toast";
import { getLiveCases, type Case } from "@/lib/caseData";
import { taxAction } from "@/lib/apiClient";
import { getEffectiveCaseStatus, closeCase, returnToCustomsFromTax, requestThirdPartyInput, setCaseAction, getCaseStatuses, getCaseWithSnapshot, appendActivities, nowTimestamp } from "@/lib/caseStore";
import { taxCodeFor } from "@/lib/caseEnum";
import { statusStyles, riskLevelStyles } from "@/lib/styles";

const riskScoreColor = (_score: number) => "text-card-foreground font-medium";

const TaxAuthority = () => {
  const { toast } = useToast();
  const navigate = useNavigate();
  const { openTab } = useTaxCaseTab();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");
  const [filterView, setFilterView] = useState("all");

  // Action dialog state
  const [showActionDialog, setShowActionDialog] = useState(false);
  const [pendingActionType, setPendingActionType] = useState<string>("");
  const [actionNote, setActionNote] = useState("");
  const [createRule, setCreateRule] = useState(false);
  const [informMemberStates, setInformMemberStates] = useState(false);

  // Column filters
  const [colFilterSeller, setColFilterSeller] = useState<Set<string>>(new Set());
  const [colFilterCategory, setColFilterCategory] = useState<Set<string>>(new Set());
  const [colFilterOrigin, setColFilterOrigin] = useState<Set<string>>(new Set());
  const [colFilterRiskLevel, setColFilterRiskLevel] = useState<Set<string>>(new Set());
  const [colFilterRiskScore, setColFilterRiskScore] = useState<NumericRange>({ min: null, max: null });

  // Force re-render when case store changes
  const [, forceUpdate] = useState(0);
  useEffect(() => {
    const handler = () => forceUpdate(v => v + 1);
    window.addEventListener("case-store-updated", handler);
    return () => window.removeEventListener("case-store-updated", handler);
  }, []);

  // Cases under tax review
  const taxCases = useMemo(() => {
    return getLiveCases().filter(c => {
      const effectiveStatus = getEffectiveCaseStatus(c.id, c.status);
      return (effectiveStatus === "Under Review by Tax" || effectiveStatus === "AI Investigation in Progress")
        && c.countryOfDestination === "IE";
    }).map(getCaseWithSnapshot);
  }, [getCaseStatuses()]);

  const uniqueSellers = useMemo(() => [...new Set(taxCases.map(c => c.seller))].sort(), [taxCases]);
  const uniqueCategories = useMemo(() => [...new Set(taxCases.map(c => c.declaredCategory))].sort(), [taxCases]);
  const uniqueOrigins = useMemo(() => [...new Set(taxCases.map(c => c.countryOfOrigin))].sort(), [taxCases]);
  const uniqueRiskLevels = useMemo(() => ["High", "Medium", "Low"], []);

  const passesFilter = (value: string, filterSet: Set<string>) => filterSet.size === 0 || filterSet.has(value);

  const filteredCases = useMemo(() => {
    return taxCases.filter((c) => {
      if (filterView === "selection" && !selectedIds.has(c.id)) return false;
      const q = searchQuery.toLowerCase();
      const matchesSearch = !q ||
        c.id.toLowerCase().includes(q) ||
        c.caseName.toLowerCase().includes(q) ||
        c.seller.toLowerCase().includes(q) ||
        c.countryOfOrigin.toLowerCase().includes(q) ||
        c.declaredCategory.toLowerCase().includes(q);
      const passesRiskScore =
        (colFilterRiskScore.min === null || c.riskScore >= colFilterRiskScore.min) &&
        (colFilterRiskScore.max === null || c.riskScore <= colFilterRiskScore.max);
      return matchesSearch &&
        passesFilter(c.seller, colFilterSeller) &&
        passesFilter(c.declaredCategory, colFilterCategory) &&
        passesFilter(c.countryOfOrigin, colFilterOrigin) &&
        passesFilter(c.riskLevel, colFilterRiskLevel) &&
        passesRiskScore;
    });
  }, [taxCases, searchQuery, colFilterSeller, colFilterCategory, colFilterOrigin, colFilterRiskLevel, colFilterRiskScore, filterView, selectedIds]);

  const hasActiveFilters = searchQuery !== "" ||
    colFilterSeller.size > 0 || colFilterCategory.size > 0 || colFilterOrigin.size > 0 ||
    colFilterRiskLevel.size > 0 ||
    colFilterRiskScore.min !== null || colFilterRiskScore.max !== null ||
    filterView !== "all";

  const clearFilters = () => {
    setSearchQuery("");
    setColFilterSeller(new Set());
    setColFilterCategory(new Set());
    setColFilterOrigin(new Set());
    setColFilterRiskLevel(new Set());
    setColFilterRiskScore({ min: null, max: null });
    setFilterView("all");
  };

  const toggleSelection = (id: string) => {
    setSelectedIds(prev => {
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
      setSelectedIds(new Set(filteredCases.map(c => c.id)));
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
    const officer = "Tax Authority Officer";
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

    ids.forEach((id) => {
      const c = getLiveCases().find((x) => x.id === id);
      if (!c) return;
      if (pendingActionType === "Confirm Risk" || pendingActionType === "No/Limited Risk") {
        returnToCustomsFromTax(id);
        setCaseAction(id, pendingActionType === "Confirm Risk" ? "Recommend Control" : "Recommend Release");
        writeActivities(c, "Reviewed by Tax");
        const action = taxCodeFor(pendingActionType);
        if (action) taxAction(id, { action, comment: actionNote, officer }).catch(() => {});
      }
      // "Request Input from Deemed Importer" is reserved for the Customs
      // officer; Tax can only Confirm Risk or flag No/Limited Risk.
    });

    toast({
      title: pendingActionType,
      description: `${ids.length} case(s) returned to Customs.${actionNote ? " Notes attached." : ""}`,
    });

    setSelectedIds(new Set());
    setShowActionDialog(false);
    setActionNote("");
    setCreateRule(false);
    setInformMemberStates(false);
  };

  const pieData = taxCases.map(c => ({
    seller: c.seller,
    originCountry: c.countryOfOrigin,
    productCategory: c.declaredCategory,
  }));

  return (
    <main className="flex-1 p-6 space-y-6 overflow-auto">
            {/* Stats */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {(() => {
                const underReview = taxCases.filter(c =>
                  getEffectiveCaseStatus(c.id, c.status) === "Under Review by Tax"
                ).length;
                const underAI = taxCases.filter(c =>
                  getEffectiveCaseStatus(c.id, c.status) === "AI Investigation in Progress"
                ).length;
                return (
                  <>
                    <StatCard title="My Cases" value={underReview} subtitle="Awaiting action" icon={AlertTriangle} variant="danger" />
                    <StatCard title="Under Review by AI Agent" value={underAI} subtitle="Sent to AI agent" icon={Bot} variant="default" />
                  </>
                );
              })()}
            </div>

            {/* Pie Charts */}
            {taxCases.length > 0 && (
              <TransactionPieCharts
                transactions={pieData}
                onFilterSeller={(v) => setColFilterSeller(v === "all" ? new Set() : new Set([v]))}
                onFilterOrigin={(v) => setColFilterOrigin(v === "all" ? new Set() : new Set([v]))}
                onFilterProductCategory={(v) => setColFilterCategory(v === "all" ? new Set() : new Set([v]))}
                activeSeller={colFilterSeller.size === 1 ? [...colFilterSeller][0] : "all"}
                activeOrigin={colFilterOrigin.size === 1 ? [...colFilterOrigin][0] : "all"}
                activeProductCategory={colFilterCategory.size === 1 ? [...colFilterCategory][0] : "all"}
              />
            )}

            {/* Table */}
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
                  {filteredCases.length} of {taxCases.length}
                </span>
              </div>

              {/* Bulk action bar */}
              {selectedIds.size > 0 && (
                <div className="flex items-center justify-between border-b border-border p-4 bg-muted/30">
                  <span className="text-sm font-medium text-card-foreground">
                    {selectedIds.size} case{selectedIds.size !== 1 ? "s" : ""} selected
                  </span>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button size="sm" variant="outline" className="gap-1.5">
                        <MoreHorizontal className="h-3.5 w-3.5" />
                        Apply Action to Selection ({selectedIds.size})
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => openActionDialog("Confirm Risk")}>
                        <AlertTriangle className="h-4 w-4 mr-2 text-destructive" /> Confirm Risk
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => openActionDialog("No/Limited Risk")}>
                        <CheckCircle2 className="h-4 w-4 mr-2 text-success" /> No/Limited Risk
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
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
                      <th className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground"># Orders</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        <span className="inline-flex items-center">
                          Seller
                          <ColumnFilterDropdown options={uniqueSellers} selected={colFilterSeller} onSelectionChange={setColFilterSeller} />
                        </span>
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        <span className="inline-flex items-center">
                          Declared Category
                          <ColumnFilterDropdown options={uniqueCategories} selected={colFilterCategory} onSelectionChange={setColFilterCategory} />
                        </span>
                      </th>
                      <th className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        <span className="inline-flex items-center">
                          Origin
                          <ColumnFilterDropdown options={uniqueOrigins} selected={colFilterOrigin} onSelectionChange={setColFilterOrigin} />
                        </span>
                      </th>
                      <th className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">Destination</th>
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
                      <th className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">Status</th>
                      <th className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">Review</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredCases.length === 0 ? (
                      <tr>
                        <td colSpan={11} className="px-5 py-12 text-center text-muted-foreground">
                          <Search className="h-8 w-8 mx-auto mb-2 opacity-40" />
                          <p className="text-sm">No cases under tax review</p>
                          <p className="text-xs mt-1">Cases will appear here when submitted by Customs Authority</p>
                        </td>
                      </tr>
                    ) : (
                      filteredCases.map((c) => (
                        <tr key={c.id} className={cn("border-b border-border last:border-0 hover:bg-muted/30 transition-colors", selectedIds.has(c.id) && "bg-primary/5")}>
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
                          <td className="px-4 py-3.5 text-center">
                            {(() => {
                              const effectiveStatus = getEffectiveCaseStatus(c.id, c.status);
                              const isAI = effectiveStatus === "AI Investigation in Progress";
                              const label = isAI ? "⚙️ AI Processing" : effectiveStatus;
                              return (
                                <Badge className={cn("text-xs", statusStyles[effectiveStatus] ?? "bg-primary/10 text-primary")}>
                                  {label}
                                </Badge>
                              );
                            })()}
                          </td>
                          <td className="px-4 py-3.5 text-center">
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              onClick={() => {
                                openTab(c.id, c.id);
                                navigate(`/tax-authority/case/${c.id}`);
                              }}
                            >
                              <Eye className="h-4 w-4" />
                            </Button>
                          </td>
                        </tr>
                      ))
                    )}
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
                {(pendingActionType === "Confirm Risk" || pendingActionType === "No/Limited Risk") && (
                  <>
                    <div className="flex items-start gap-2 mt-2">
                      <Checkbox checked={createRule} onCheckedChange={(c) => setCreateRule(!!c)} id="tax-create-rule" className="mt-0.5" />
                      <label htmlFor="tax-create-rule" className="text-sm text-card-foreground cursor-pointer">Create a business rule to apply this to all similar future cases</label>
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
                      <Checkbox checked={informMemberStates} onCheckedChange={(c) => setInformMemberStates(!!c)} id="tax-inform-member-states" />
                      <label htmlFor="tax-inform-member-states" className="text-sm text-card-foreground cursor-pointer">Inform member states about this case</label>
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

export default TaxAuthority;
