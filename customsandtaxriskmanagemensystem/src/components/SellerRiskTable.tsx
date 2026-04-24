import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Eye } from "lucide-react";
import { Link } from "react-router-dom";

interface Seller {
  id: string;
  name: string;
  iossNumber: string;
  region: string;
  totalTransactions: number;
  suspiciousTransactions: number;
  riskScore: number;
  riskLevel: "Critical" | "High" | "Medium" | "Low";
  lastActivity: string;
}

const mockSellers: Seller[] = [
  {
    id: "S-4201",
    name: "ShenZhen TechGoods Ltd",
    iossNumber: "IM3560000012",
    region: "Dublin",
    totalTransactions: 14520,
    suspiciousTransactions: 1893,
    riskScore: 94,
    riskLevel: "Critical",
    lastActivity: "2026-04-01",
  },
  {
    id: "S-3887",
    name: "GlobalMart Express",
    iossNumber: "IM3560000034",
    region: "Cork",
    totalTransactions: 9870,
    suspiciousTransactions: 1104,
    riskScore: 87,
    riskLevel: "Critical",
    lastActivity: "2026-04-02",
  },
  {
    id: "S-2910",
    name: "HK ValueShip Trading",
    iossNumber: "IM3560000056",
    region: "Galway",
    totalTransactions: 7340,
    suspiciousTransactions: 612,
    riskScore: 72,
    riskLevel: "High",
    lastActivity: "2026-03-30",
  },
  {
    id: "S-2544",
    name: "EuroDropShip GmbH x",
    iossNumber: "IM2760000078",
    region: "Limerick",
    totalTransactions: 5200,
    suspiciousTransactions: 389,
    riskScore: 61,
    riskLevel: "High",
    lastActivity: "2026-03-29",
  },
  {
    id: "S-1998",
    name: "NordBazaar AB",
    iossNumber: "IM7520000091",
    region: "Waterford",
    totalTransactions: 3100,
    suspiciousTransactions: 187,
    riskScore: 48,
    riskLevel: "Medium",
    lastActivity: "2026-03-28",
  },
  {
    id: "S-1450",
    name: "MediterraneanGoods SRL",
    iossNumber: "IM3800000045",
    region: "Kerry",
    totalTransactions: 2800,
    suspiciousTransactions: 98,
    riskScore: 31,
    riskLevel: "Medium",
    lastActivity: "2026-03-27",
  },
  {
    id: "S-0812",
    name: "BalticTrade OÜ",
    iossNumber: "IM2330000023",
    region: "Donegal",
    totalTransactions: 1450,
    suspiciousTransactions: 23,
    riskScore: 42,
    riskLevel: "Medium",
    lastActivity: "2026-03-25",
  },
];

const riskBadgeStyles: Record<string, string> = {
  Critical: "bg-risk-critical text-destructive-foreground",
  High: "bg-risk-high text-warning-foreground",
  Medium: "bg-risk-medium text-warning-foreground",
  Low: "bg-risk-low text-success-foreground",
};

export function SellerRiskTable() {
  return (
    <div className="bg-card rounded-lg border border-border shadow-sm">
      <div className="flex items-center justify-between border-b border-border p-5">
        <div>
          <h2 className="text-lg font-semibold text-card-foreground">Seller Risk Profiles</h2>
          <p className="text-sm text-muted-foreground">Ranked by suspicious VAT transaction volume</p>
        </div>
        <Button variant="outline" size="sm">
          Export
        </Button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border bg-muted/50">
              <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Seller
              </th>
              <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                IOSS Number
              </th>
              <th className="px-5 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Region
              </th>
              <th className="px-5 py-3 text-right text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Transactions
              </th>
              <th className="px-5 py-3 text-right text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Suspicious
              </th>
              <th className="px-5 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Risk Score
              </th>
              <th className="px-5 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Risk Level
              </th>
              <th className="px-5 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                View
              </th>
            </tr>
          </thead>
          <tbody>
            {mockSellers.map((seller) => (
              <tr key={seller.id} className="border-b border-border last:border-0 hover:bg-muted/30 transition-colors">
                <td className="px-5 py-4">
                  <div>
                    <p className="font-medium text-card-foreground text-sm">{seller.name}</p>
                    <p className="text-xs text-muted-foreground">{seller.id}</p>
                  </div>
                </td>
                <td className="px-5 py-4 text-sm font-mono text-muted-foreground">{seller.iossNumber}</td>
                <td className="px-5 py-4 text-center text-sm text-muted-foreground">{seller.region}</td>
                <td className="px-5 py-4 text-right text-sm text-card-foreground">
                  {seller.totalTransactions.toLocaleString()}
                </td>
                <td className="px-5 py-4 text-right text-sm font-semibold text-destructive">
                  {seller.suspiciousTransactions.toLocaleString()}
                </td>
                <td className="px-5 py-4 text-center">
                  <RiskScoreBar score={seller.riskScore} />
                </td>
                <td className="px-5 py-4 text-center">
                  <Badge className={cn("text-xs", riskBadgeStyles[seller.riskLevel])}>{seller.riskLevel}</Badge>
                </td>
                <td className="px-5 py-4 text-center">
                  <Link to={`/investigation/${seller.id}`}>
                    <Button variant="ghost" size="icon" className="h-8 w-8">
                      <Eye className="h-4 w-4" />
                    </Button>
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RiskScoreBar({ score }: { score: number }) {
  const color =
    score >= 80 ? "bg-risk-critical" : score >= 60 ? "bg-risk-high" : score >= 40 ? "bg-risk-medium" : "bg-risk-low";

  return (
    <div className="flex items-center justify-center gap-2">
      <div className="w-16 h-2 rounded-full bg-muted">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${score}%` }} />
      </div>
      <span className="text-xs font-semibold text-card-foreground w-6">{score}</span>
    </div>
  );
}
