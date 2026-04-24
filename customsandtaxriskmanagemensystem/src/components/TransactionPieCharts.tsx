import { useMemo } from "react";
import { PieChart, Pie, Cell, Tooltip } from "recharts";

interface Transaction {
  seller: string;
  originCountry: string;
  productCategory: string;
}

interface TransactionPieChartsProps {
  transactions: Transaction[];
  onFilterSeller: (value: string) => void;
  onFilterOrigin: (value: string) => void;
  onFilterProductCategory: (value: string) => void;
  activeSeller: string;
  activeOrigin: string;
  activeProductCategory: string;
}

const COLORS = [
  "hsl(var(--primary))",
  "hsl(var(--destructive))",
  "hsl(38 92% 50%)",
  "hsl(210 70% 55%)",
  "hsl(280 60% 55%)",
  "hsl(160 60% 45%)",
  "hsl(25 80% 55%)",
  "hsl(340 65% 50%)",
  "hsl(190 70% 45%)",
  "hsl(120 50% 40%)",
];

function aggregate(items: string[]) {
  const counts: Record<string, number> = {};
  items.forEach((item) => {
    counts[item] = (counts[item] || 0) + 1;
  });
  return Object.entries(counts)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
}


interface ChartCardProps {
  title: string;
  data: { name: string; value: number }[];
  activeValue: string;
  onSliceClick: (value: string) => void;
}

function ChartCard({ title, data, activeValue, onSliceClick }: ChartCardProps) {
  const total = data.reduce((s, d) => s + d.value, 0);

  const handleClick = (entry: { name: string }) => {
    onSliceClick(activeValue === entry.name ? "all" : entry.name);
  };

  return (
    <div className="bg-card rounded-lg border border-border shadow-sm p-4">
      <h3 className="text-sm font-semibold text-card-foreground mb-1">{title}</h3>
      <p className="text-xs text-muted-foreground mb-3">
        {data.length} unique · {total} parcels
      </p>
      <div className="flex items-center gap-4">
        <div className="w-[140px] h-[140px] flex-shrink-0">
          <PieChart width={140} height={140}>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={30}
              outerRadius={60}
              paddingAngle={2}
              dataKey="value"
              cursor="pointer"
              onClick={(_, index) => handleClick(data[index])}
              stroke="none"
            >
              {data.map((entry, index) => (
                <Cell
                  key={entry.name}
                  fill={COLORS[index % COLORS.length]}
                  opacity={activeValue !== "all" && activeValue !== entry.name ? 0.3 : 1}
                />
              ))}
            </Pie>
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0].payload;
                const pct = ((d.value / total) * 100).toFixed(1);
                return (
                  <div className="bg-popover border border-border rounded-md px-3 py-2 shadow-lg text-xs">
                    <p className="font-medium text-popover-foreground">{d.name}</p>
                    <p className="text-muted-foreground">
                      {d.value} parcels ({pct}%)
                    </p>
                  </div>
                );
              }}
            />
          </PieChart>
        </div>
        <div className="flex-1 min-w-0 space-y-1.5 max-h-[140px] overflow-y-auto pr-1">
          {data.map((entry, index) => {
            const pct = ((entry.value / total) * 100).toFixed(0);
            const isActive = activeValue === entry.name;
            return (
              <button
                key={entry.name}
                onClick={() => handleClick(entry)}
                className={`w-full flex items-center gap-2 text-left text-xs rounded px-1.5 py-1 transition-colors hover:bg-muted/50 ${
                  isActive ? "bg-muted" : ""
                } ${activeValue !== "all" && !isActive ? "opacity-40" : ""}`}
              >
                <span
                  className="w-2.5 h-2.5 rounded-sm flex-shrink-0"
                  style={{ backgroundColor: COLORS[index % COLORS.length] }}
                />
                <span className="truncate text-card-foreground flex-1">{entry.name}</span>
                <span className="text-muted-foreground flex-shrink-0">{pct}%</span>
              </button>
            );
          })}
        </div>
      </div>
      {activeValue !== "all" && (
        <button
          onClick={() => onSliceClick("all")}
          className="mt-2 text-xs text-primary hover:underline"
        >
          Clear filter
        </button>
      )}
    </div>
  );
}

export function TransactionPieCharts({
  transactions,
  onFilterSeller,
  onFilterOrigin,
  onFilterProductCategory,
  activeSeller,
  activeOrigin,
  activeProductCategory,
}: TransactionPieChartsProps) {
  const filteredForSeller = useMemo(() => {
    let filtered = transactions;
    if (activeOrigin !== "all") filtered = filtered.filter(t => t.originCountry === activeOrigin);
    if (activeProductCategory !== "all") filtered = filtered.filter(t => t.productCategory === activeProductCategory);
    return filtered;
  }, [transactions, activeOrigin, activeProductCategory]);

  const filteredForOrigin = useMemo(() => {
    let filtered = transactions;
    if (activeSeller !== "all") filtered = filtered.filter(t => t.seller === activeSeller);
    if (activeProductCategory !== "all") filtered = filtered.filter(t => t.productCategory === activeProductCategory);
    return filtered;
  }, [transactions, activeSeller, activeProductCategory]);

  const filteredForCategory = useMemo(() => {
    let filtered = transactions;
    if (activeSeller !== "all") filtered = filtered.filter(t => t.seller === activeSeller);
    if (activeOrigin !== "all") filtered = filtered.filter(t => t.originCountry === activeOrigin);
    return filtered;
  }, [transactions, activeSeller, activeOrigin]);

  const sellerData = useMemo(() => aggregate(filteredForSeller.map((t) => t.seller)), [filteredForSeller]);
  const originData = useMemo(() => aggregate(filteredForOrigin.map((t) => t.originCountry)), [filteredForOrigin]);
  const categoryData = useMemo(() => aggregate(filteredForCategory.map((t) => t.productCategory)), [filteredForCategory]);

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <ChartCard title="By Seller Name" data={sellerData} activeValue={activeSeller} onSliceClick={onFilterSeller} />
      <ChartCard title="By Origin Country" data={originData} activeValue={activeOrigin} onSliceClick={onFilterOrigin} />
      <ChartCard title="By Product Category" data={categoryData} activeValue={activeProductCategory} onSliceClick={onFilterProductCategory} />
    </div>
  );
}
