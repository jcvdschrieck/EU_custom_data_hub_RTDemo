import { useState, useRef, useEffect } from "react";
import { Filter } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface ColumnFilterDropdownProps {
  options: string[];
  selected: Set<string>;
  onSelectionChange: (selected: Set<string>) => void;
}

export function ColumnFilterDropdown({ options, selected, onSelectionChange }: ColumnFilterDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const isFiltered = selected.size > 0 && selected.size < options.length;

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const toggleOption = (opt: string) => {
    const next = new Set(selected);
    if (next.has(opt)) next.delete(opt);
    else next.add(opt);
    onSelectionChange(next);
  };

  const selectAll = () => onSelectionChange(new Set());

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        className={cn(
          "ml-1 inline-flex items-center justify-center rounded p-0.5 hover:bg-accent/50 transition-colors",
          isFiltered && "text-primary"
        )}
      >
        <Filter className={cn("h-3 w-3", isFiltered ? "fill-primary/30" : "")} />
      </button>
      {open && (
        <div className="absolute top-full left-0 z-50 mt-1 w-52 rounded-md border bg-popover p-2 shadow-md text-popover-foreground">
          <button
            onClick={selectAll}
            className="w-full text-left text-xs text-muted-foreground hover:text-foreground px-2 py-1 rounded hover:bg-accent/50 mb-1"
          >
            {selected.size === 0 ? "✓ All selected" : "Select All"}
          </button>
          <div className="max-h-48 overflow-y-auto space-y-0.5">
            {options.map((opt) => {
              const isChecked = selected.size === 0 || selected.has(opt);
              return (
                <label
                  key={opt}
                  className="flex items-center gap-2 px-2 py-1 rounded hover:bg-accent/50 cursor-pointer text-xs"
                >
                  <Checkbox
                    checked={isChecked}
                    onCheckedChange={() => {
                      if (selected.size === 0) {
                        const next = new Set(options.filter(o => o !== opt));
                        onSelectionChange(next);
                      } else {
                        toggleOption(opt);
                      }
                    }}
                  />
                  <span className="truncate">{opt}</span>
                </label>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// Numeric range filter (min/max)
export interface NumericRange {
  min: number | null;
  max: number | null;
}

interface NumericFilterDropdownProps {
  range: NumericRange;
  onRangeChange: (range: NumericRange) => void;
  prefix?: string;
}

export function NumericFilterDropdown({ range, onRangeChange, prefix = "" }: NumericFilterDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const isFiltered = range.min !== null || range.max !== null;

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        className={cn(
          "ml-1 inline-flex items-center justify-center rounded p-0.5 hover:bg-accent/50 transition-colors",
          isFiltered && "text-primary"
        )}
      >
        <Filter className={cn("h-3 w-3", isFiltered ? "fill-primary/30" : "")} />
      </button>
      {open && (
        <div className="absolute top-full right-0 z-50 mt-1 w-48 rounded-md border bg-popover p-3 shadow-md text-popover-foreground space-y-2">
          <p className="text-[10px] font-semibold uppercase text-muted-foreground tracking-wider">Filter range</p>
          <div className="space-y-1.5">
            <label className="text-xs text-muted-foreground">Min {prefix}</label>
            <Input
              type="number"
              placeholder="No min"
              className="h-7 text-xs"
              value={range.min ?? ""}
              onChange={(e) => onRangeChange({ ...range, min: e.target.value ? Number(e.target.value) : null })}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs text-muted-foreground">Max {prefix}</label>
            <Input
              type="number"
              placeholder="No max"
              className="h-7 text-xs"
              value={range.max ?? ""}
              onChange={(e) => onRangeChange({ ...range, max: e.target.value ? Number(e.target.value) : null })}
            />
          </div>
          {isFiltered && (
            <button
              onClick={() => onRangeChange({ min: null, max: null })}
              className="w-full text-xs text-muted-foreground hover:text-foreground text-center py-1 rounded hover:bg-accent/50"
            >
              Clear
            </button>
          )}
        </div>
      )}
    </div>
  );
}
