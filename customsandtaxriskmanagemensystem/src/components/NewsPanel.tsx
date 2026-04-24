import { Badge } from "@/components/ui/badge";

interface NewsItem {
  category: string;
  categoryColor: string;
  date: string;
  title: string;
  summary: string;
  source: string;
}

const news: NewsItem[] = [
  {
    category: "Policy",
    categoryColor: "bg-primary text-primary-foreground",
    date: "Today",
    title: "EU Commission Updates IOSS Reporting Requirements",
    summary:
      "New mandatory fields for transaction-level reporting to improve VAT fraud detection across member states.",
    source: "EU Official Journal",
  },
  {
    category: "Enforcement",
    categoryColor: "bg-destructive text-destructive-foreground",
    date: "Yesterday",
    title: "Cross-Border VAT Fraud Ring Dismantled",
    summary:
      "Joint operation by OLAF and national authorities uncovers €12M in undeclared import VAT.",
    source: "EU Tax Observatory",
  },
  {
    category: "Alert",
    categoryColor: "bg-warning text-warning-foreground",
    date: "2 days ago",
    title: "New Undervaluation Pattern Detected",
    summary:
      "Intelligence reports indicate systematic undervaluation of electronics shipments via IOSS.",
    source: "Risk Analysis Unit",
  },
];

export function NewsPanel() {
  return (
    <div className="bg-card rounded-lg border border-border shadow-sm">
      <div className="border-b border-border p-5">
        <h2 className="text-lg font-semibold text-card-foreground">
          News & Updates
        </h2>
      </div>
      <div className="divide-y divide-border">
        {news.map((item, i) => (
          <div key={i} className="p-4 hover:bg-muted/30 transition-colors">
            <div className="flex items-center gap-2 mb-1.5">
              <Badge className={item.categoryColor + " text-[10px] px-1.5 py-0"}>
                {item.category}
              </Badge>
              <span className="text-[10px] text-muted-foreground">
                {item.date}
              </span>
            </div>
            <p className="text-sm font-medium text-card-foreground leading-snug">
              {item.title}
            </p>
            <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
              {item.summary}
            </p>
            <p className="text-[10px] text-muted-foreground mt-1.5">
              ○ {item.source}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
