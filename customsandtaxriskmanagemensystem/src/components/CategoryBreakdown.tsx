import { cn } from "@/lib/utils";
import { AlertTriangle, FileWarning, Package, DollarSign } from "lucide-react";
import { type LucideIcon } from "lucide-react";

interface Category {
  name: string;
  count: number;
  percentage: number;
  icon: LucideIcon;
  color: string;
  description: string;
}

const categories: Category[] = [
  {
    name: "VAT Rate Deviation",
    count: 612,
    percentage: 32.3,
    icon: AlertTriangle,
    color: "bg-risk-critical",
    description:
      "Goods in the same product category reported at differing VAT rates across shipments, sellers, or periods — pointing to rate misclassification or selective underreporting.",
  },
  {
    name: "Customs Duty Gap",
    count: 498,
    percentage: 26.3,
    icon: FileWarning,
    color: "bg-risk-high",
    description:
      "Customs duties declared differ from the expected tariff for the declared commodity code, or duties are omitted from the taxable base used to calculate VAT.",
  },
  {
    name: "Product Type Mismatch",
    count: 445,
    percentage: 23.5,
    icon: Package,
    color: "bg-risk-medium",
    description:
      "The commodity description in the customs declaration conflicts with the product category used in the IOSS VAT filing, suggesting misclassification to obtain a reduced rate or lower dutiable value.",
  },
  {
    name: "Taxable Value Understatement",
    count: 338,
    percentage: 17.9,
    icon: DollarSign,
    color: "bg-risk-low",
    description:
      "The VAT taxable value excludes customs duties, excise duties, or transport costs that should legally form part of the import VAT base under Article 85 VAT Directive.",
  },
];

export function CategoryBreakdown() {
  const total = categories.reduce((sum, c) => sum + c.count, 0);

  return (
    <div className="bg-card rounded-lg border border-border shadow-sm">
      <div className="border-b border-border p-5">
        <h2 className="text-lg font-semibold text-card-foreground">Suspicion Categories</h2>
        <p className="text-sm text-muted-foreground">
          {total.toLocaleString()} parcels with identified risk classified into 4 categories
        </p>
      </div>

      {/* Stacked bar */}
      <div className="px-5 pt-5">
        <div className="flex h-3 w-full rounded-full overflow-hidden">
          {categories.map((cat) => (
            <div key={cat.name} className={cn("h-full", cat.color)} style={{ width: `${cat.percentage}%` }} />
          ))}
        </div>
      </div>

      {/* Category cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-5">
        {categories.map((cat) => (
          <div key={cat.name} className="rounded-lg border border-border p-4 hover:bg-muted/30 transition-colors">
            <div className="flex items-start gap-3">
              <div className={cn("rounded-lg p-2", cat.color + "/10")}>
                <cat.icon className={cn("h-5 w-5", cat.color.replace("bg-", "text-"))} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-1">
                  <h3 className="font-semibold text-sm text-card-foreground">{cat.name}</h3>
                  <span className="text-sm font-bold text-card-foreground">{cat.count.toLocaleString()}</span>
                </div>
                <div className="flex items-center gap-2 mb-2">
                  <div className="flex-1 h-1.5 rounded-full bg-muted">
                    <div className={cn("h-full rounded-full", cat.color)} style={{ width: `${cat.percentage}%` }} />
                  </div>
                  <span className="text-xs text-muted-foreground w-10 text-right">{cat.percentage}%</span>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">{cat.description}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
