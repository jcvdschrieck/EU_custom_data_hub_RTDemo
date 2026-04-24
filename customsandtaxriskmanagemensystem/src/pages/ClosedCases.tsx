import { useState, useMemo, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getLiveCases, getLiveClosedCases, type Case } from "@/lib/caseData";
import { useCaseTab } from "@/pages/CustomsLayout";
import { StatCard } from "@/components/StatCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CheckCircle2, Search, Eye, XCircle, ArrowRightLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import { TransactionPieCharts } from "@/components/TransactionPieCharts";
import {
  getEffectiveCaseStatus,
  getCaseSnapshots,
  getCaseWithSnapshot,
  getCaseClosedDates,
  getEffectiveCaseAction,
} from "@/lib/caseStore";
import { riskLevelStyles } from "@/lib/styles";

const riskScoreColor = (score: number) => {
  if (score >= 85) return "text-destructive font-bold";
  if (score >= 70) return "text-risk-high font-semibold";
  if (score >= 50) return "text-warning font-semibold";
  return "text-success font-medium";
};

const actionStyles: Record<string, { style: string; icon: typeof CheckCircle2 }> = {
  "Recommend Control": { style: "bg-destructive/10 text-destructive", icon: XCircle },
  "Recommend Release": { style: "bg-success/10 text-success", icon: CheckCircle2 },
  "Submitted for Tax Review": { style: "bg-primary/10 text-primary", icon: ArrowRightLeft },
  "Input Requested": { style: "bg-warning/10 text-warning", icon: ArrowRightLeft },
};

export default function ClosedCases() {
  const [searchQuery, setSearchQuery] = useState("");
  const navigate = useNavigate();
  const { openTab } = useCaseTab();

  const [activeSeller, setActiveSeller] = useState("all");
  const [activeOrigin, setActiveOrigin] = useState("all");
  const [activeCategory, setActiveCategory] = useState("all");

  // Force re-render when case store changes
  const [, forceUpdate] = useState(0);
  useEffect(() => {
    const handler = () => forceUpdate((v) => v + 1);
    window.addEventListener("case-store-updated", handler);
    return () => window.removeEventListener("case-store-updated", handler);
  }, []);

  // Combine static closed cases with cases that became closed via the live flow.
  // getCaseWithSnapshot is now score-safe by design (it only overlays
  // the officer's level override, never the score), so the closed-list
  // risk column shows the AI's ground truth automatically.
  const closedCases = useMemo<Case[]>(() => {
    const closedDates = getCaseClosedDates();
    const dynamicallyClosed = getLiveCases()
      .filter((c) => getEffectiveCaseStatus(c.id, c.status) === "Closed")
      .map((c) => {
        const snap = getCaseWithSnapshot(c);
        return {
          ...snap,
          status: "Closed" as const,
          actionTaken: getEffectiveCaseAction(c.id, snap.actionTaken),
          closedDate: closedDates[c.id] ?? snap.closedDate,
        };
      });
    const backendClosed = getLiveClosedCases().map(getCaseWithSnapshot);
    const backendIds = new Set(backendClosed.map(c => c.id));
    const uniqueDynamic = dynamicallyClosed.filter(c => !backendIds.has(c.id));
    return [...backendClosed, ...uniqueDynamic].filter(c => c.countryOfDestination === "IE");
  }, [getCaseSnapshots()]);

  const filteredCases = useMemo(() => {
    return closedCases.filter((c) => {
      const q = searchQuery.toLowerCase();
      const matchesSearch =
        !q ||
        c.id.toLowerCase().includes(q) ||
        c.caseName.toLowerCase().includes(q) ||
        c.seller.toLowerCase().includes(q) ||
        c.countryOfOrigin.toLowerCase().includes(q);
      const matchesSeller = activeSeller === "all" || c.seller === activeSeller;
      const matchesOrigin = activeOrigin === "all" || c.countryOfOrigin === activeOrigin;
      const matchesCategory = activeCategory === "all" || c.declaredCategory === activeCategory;
      return matchesSearch && matchesSeller && matchesOrigin && matchesCategory;
    });
  }, [closedCases, searchQuery, activeSeller, activeOrigin, activeCategory]);

  const pieData = closedCases.map((c) => ({
    seller: c.seller,
    originCountry: c.countryOfOrigin,
    productCategory: c.declaredCategory,
  }));

  return (
    <main className="flex-1 p-6 space-y-6 overflow-auto">
      {/* Stats - only closed cases count */}
      <div className="grid grid-cols-1 max-w-xs">
        <StatCard
          title="Closed Cases"
          value={closedCases.length}
          subtitle="All resolved"
          icon={CheckCircle2}
          variant="success"
        />
      </div>

      {/* Pie Charts */}
      <TransactionPieCharts
        transactions={pieData}
        onFilterSeller={(v) => setActiveSeller(v)}
        onFilterOrigin={(v) => setActiveOrigin(v)}
        onFilterProductCategory={(v) => setActiveCategory(v)}
        activeSeller={activeSeller}
        activeOrigin={activeOrigin}
        activeProductCategory={activeCategory}
      />

      {/* Table */}
      <div className="bg-card rounded-lg border border-border shadow-sm">
        <div className="border-b border-border p-5">
          <h2 className="text-lg font-semibold text-card-foreground">Closed Cases</h2>
          <p className="text-xs text-muted-foreground mt-0.5">Resolved cases with action taken</p>
        </div>

        <div className="px-5 py-3 border-b border-border">
          <div className="relative max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search by case ID, seller, country..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 bg-muted/50"
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border bg-muted/50">
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">Case ID</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">Case Name</th>
                <th className="px-5 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground"># Orders in Case</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">Seller</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">Declared Product Category</th>
                <th className="px-5 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">Country of Origin</th>
                <th className="px-5 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">Country of Destination</th>
                <th className="px-5 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">Risk Score</th>
                <th className="px-5 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">Risk Level</th>
                <th className="px-5 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">Action Taken</th>
                <th className="px-5 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">Review</th>
              </tr>
            </thead>
            <tbody>
              {filteredCases.length === 0 ? (
                <tr>
                  <td colSpan={11} className="px-5 py-12 text-center text-muted-foreground text-sm">
                    No closed cases yet.
                  </td>
                </tr>
              ) : (
                filteredCases.map((c) => {
                  const actionInfo = actionStyles[c.actionTaken || "Recommend Release"];
                  return (
                    <tr key={c.id} className="border-b border-border last:border-0 hover:bg-muted/30 transition-colors">
                      <td className="px-5 py-3.5 text-sm font-mono text-card-foreground">{c.id}</td>
                      <td className="px-5 py-3.5 text-sm text-card-foreground max-w-[200px] truncate">{c.caseName}</td>
                      <td className="px-5 py-3.5 text-sm text-center text-card-foreground">{c.orders.length}</td>
                      <td className="px-5 py-3.5 text-sm text-card-foreground">{c.seller}</td>
                      <td className="px-5 py-3.5 text-sm text-card-foreground">{c.declaredCategory}</td>
                      <td className="px-5 py-3.5 text-center"><Badge variant="outline" className="text-xs">{c.countryOfOrigin}</Badge></td>
                      <td className="px-5 py-3.5 text-center"><Badge variant="outline" className="text-xs">{c.countryOfDestination}</Badge></td>
                      <td className="px-5 py-3.5 text-center"><span className={cn("text-sm", riskScoreColor(c.riskScore))}>{c.riskScore}</span></td>
                      <td className="px-5 py-3.5 text-center"><Badge className={cn("text-xs", riskLevelStyles[c.riskLevel])}>{c.riskLevel}</Badge></td>
                      <td className="px-5 py-3.5 text-center">
                        <Badge className={cn("text-xs", actionInfo?.style)}>
                          {/* Drop the "Recommend " prefix — the action is
                              taken, not recommended, so "Control" / "Release"
                              reads cleaner in the closed-cases list. */}
                          {(c.actionTaken ?? "").replace(/^Recommend(ed)?\s+/, "")}
                        </Badge>
                      </td>
                      <td className="px-5 py-3.5 text-center">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => {
                            openTab(c.id, c.id, true);
                            navigate(`/customs-authority/case/${c.id}`);
                          }}
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  );
}
