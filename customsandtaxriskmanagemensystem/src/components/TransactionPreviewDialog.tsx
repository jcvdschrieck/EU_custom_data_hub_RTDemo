import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import {
  AlertTriangle,
  FileText,
  Package,
  Receipt,
  Tag,
  TrendingDown,
  ArrowRight,
} from "lucide-react";

interface Transaction {
  id: string;
  date: string;
  declaredValue: number;
  estimatedValue: number;
  vatDeclared: number;
  vatExpected: number;
  category: string;
  commodity: string;
  status: "Flagged" | "Under Review" | "Confirmed";
}

interface TransactionPreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  transaction: Transaction | null;
}

const categoryDescriptions: Record<string, string> = {
  "VAT Rate Deviation":
    "The VAT rate applied does not match the expected rate for the declared product category.",
  "Customs Duty Gap":
    "A discrepancy exists between declared customs value and the estimated market value.",
  "Product Type Mismatch":
    "The product has been classified under a different category than expected based on its description.",
  "Taxable Value Understatement":
    "The declared taxable value is significantly lower than the estimated market value.",
};

const categoryBadgeStyles: Record<string, string> = {
  "VAT Rate Deviation": "bg-risk-critical/15 text-destructive border-risk-critical/30",
  "Customs Duty Gap": "bg-risk-high/15 text-warning border-risk-high/30",
  "Product Type Mismatch": "bg-risk-medium/15 text-warning border-risk-medium/30",
  "Taxable Value Understatement": "bg-risk-low/15 text-success border-risk-low/30",
};

const invoiceData: Record<string, {
  invoiceNumber: string;
  invoiceDate: string;
  seller: string;
  buyer: string;
  buyerCountry: string;
  shippingMethod: string;
  hsCode: string;
  declaredCategory: string;
  expectedCategory: string;
  declaredVatRate: string;
  expectedVatRate: string;
  weight: string;
  quantity: number;
}> = {
  "TXN-84201": {
    invoiceNumber: "INV-2026-SZ-04201",
    invoiceDate: "2026-03-30",
    seller: "ShenZhen TechGoods Ltd",
    buyer: "John Murphy",
    buyerCountry: "Ireland",
    shippingMethod: "Standard Post (CN)",
    hsCode: "8518.30.00",
    declaredCategory: "Accessories",
    expectedCategory: "Educational Material",
    declaredVatRate: "13.5%",
    expectedVatRate: "23%",
    weight: "0.12 kg",
    quantity: 2,
  },
  "TXN-84195": {
    invoiceNumber: "INV-2026-SZ-04195",
    invoiceDate: "2026-03-30",
    seller: "ShenZhen TechGoods Ltd",
    buyer: "Sarah O'Connor",
    buyerCountry: "Ireland",
    shippingMethod: "Express (DHL)",
    hsCode: "8517.62.00",
    declaredCategory: "Educational Material",
    expectedCategory: "Educational Material",
    declaredVatRate: "10%",
    expectedVatRate: "23%",
    weight: "0.25 kg",
    quantity: 1,
  },
  "TXN-84130": {
    invoiceNumber: "INV-2026-SZ-04130",
    invoiceDate: "2026-03-29",
    seller: "ShenZhen TechGoods Ltd",
    buyer: "Declan Walsh",
    buyerCountry: "Ireland",
    shippingMethod: "Standard Post (CN)",
    hsCode: "3926.90.97",
    declaredCategory: "Accessory",
    expectedCategory: "Phone Case / Protective Equipment",
    declaredVatRate: "13%",
    expectedVatRate: "23%",
    weight: "0.05 kg",
    quantity: 3,
  },
  "TXN-84098": {
    invoiceNumber: "INV-2026-SZ-04098",
    invoiceDate: "2026-03-29",
    seller: "ShenZhen TechGoods Ltd",
    buyer: "Emma Byrne",
    buyerCountry: "Ireland",
    shippingMethod: "Standard Post (CN)",
    hsCode: "8518.22.00",
    declaredCategory: "Educational Material",
    expectedCategory: "Educational Material",
    declaredVatRate: "23%",
    expectedVatRate: "23%",
    weight: "0.45 kg",
    quantity: 1,
  },
  "TXN-83945": {
    invoiceNumber: "INV-2026-SZ-03945",
    invoiceDate: "2026-03-28",
    seller: "ShenZhen TechGoods Ltd",
    buyer: "Cian Kelly",
    buyerCountry: "Ireland",
    shippingMethod: "Standard Post (CN)",
    hsCode: "9405.42.00",
    declaredCategory: "Lighting",
    expectedCategory: "LED Electronics",
    declaredVatRate: "23%",
    expectedVatRate: "23%",
    weight: "0.30 kg",
    quantity: 5,
  },
  "TXN-83901": {
    invoiceNumber: "INV-2026-SZ-03901",
    invoiceDate: "2026-03-28",
    seller: "ShenZhen TechGoods Ltd",
    buyer: "Aoife Doyle",
    buyerCountry: "Ireland",
    shippingMethod: "Express (DHL)",
    hsCode: "8525.80.19",
    declaredCategory: "Educational Material",
    expectedCategory: "Educational Material",
    declaredVatRate: "10%",
    expectedVatRate: "23%",
    weight: "0.68 kg",
    quantity: 1,
  },
  "TXN-83856": {
    invoiceNumber: "INV-2026-SZ-03856",
    invoiceDate: "2026-03-27",
    seller: "ShenZhen TechGoods Ltd",
    buyer: "Liam Fitzgerald",
    buyerCountry: "Ireland",
    shippingMethod: "Standard Post (CN)",
    hsCode: "8473.30.80",
    declaredCategory: "Cable",
    expectedCategory: "Computer Peripheral / USB Hub",
    declaredVatRate: "10%",
    expectedVatRate: "23%",
    weight: "0.08 kg",
    quantity: 1,
  },
};

function InfoRow({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex justify-between items-center py-1.5">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={cn("text-sm font-medium", highlight ? "text-destructive" : "text-card-foreground")}>{value}</span>
    </div>
  );
}

export function TransactionPreviewDialog({ open, onOpenChange, transaction }: TransactionPreviewDialogProps) {
  if (!transaction) return null;

  const invoice = invoiceData[transaction.id] || invoiceData["TXN-84201"];
  const vatGap = transaction.vatExpected - transaction.vatDeclared;
  const valueGap = transaction.estimatedValue - transaction.declaredValue;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <DialogTitle className="text-lg">Transaction {transaction.id}</DialogTitle>
            <Badge
              variant="outline"
              className={cn("text-[10px]", categoryBadgeStyles[transaction.category])}
            >
              {transaction.category}
            </Badge>
          </div>
        </DialogHeader>

        {/* Suspicion Category */}
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-destructive mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-semibold text-destructive">Suspicion: {transaction.category}</p>
              <p className="text-sm text-muted-foreground mt-1">
                {categoryDescriptions[transaction.category]}
              </p>
            </div>
          </div>
        </div>

        <Separator />

        {/* Invoice Information */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Receipt className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold text-card-foreground">Invoice Information</h3>
          </div>
          <div className="bg-muted/30 rounded-lg p-4 space-y-0.5">
            <InfoRow label="Invoice Number" value={invoice.invoiceNumber} />
            <InfoRow label="Invoice Date" value={invoice.invoiceDate} />
            <InfoRow label="Seller" value={invoice.seller} />
            <InfoRow label="Buyer" value={invoice.buyer} />
            <InfoRow label="Buyer Country" value={invoice.buyerCountry} />
            <InfoRow label="Shipping Method" value={invoice.shippingMethod} />
            <InfoRow label="HS Code" value={invoice.hsCode} />
            <InfoRow label="Quantity" value={String(invoice.quantity)} />
            <InfoRow label="Weight" value={invoice.weight} />
          </div>
        </div>

        <Separator />

        {/* Product Classification */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Tag className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold text-card-foreground">Product Classification</h3>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-border bg-muted/30 p-3">
              <p className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1">Declared Category</p>
              <p className="text-sm font-medium text-card-foreground">{invoice.declaredCategory}</p>
            </div>
            <div className="rounded-lg border border-primary/30 bg-primary/5 p-3">
              <p className="text-[11px] uppercase tracking-wider text-primary mb-1">Expected Category</p>
              <p className="text-sm font-medium text-primary">{invoice.expectedCategory}</p>
            </div>
          </div>
        </div>

        <Separator />

        {/* VAT Comparison */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <TrendingDown className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold text-card-foreground">VAT Comparison</h3>
          </div>
          <div className="grid grid-cols-2 gap-3 mb-3">
            <div className="rounded-lg border border-border bg-muted/30 p-3">
              <p className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1">Declared VAT Rate</p>
              <p className="text-lg font-bold text-card-foreground">{invoice.declaredVatRate}</p>
            </div>
            <div className="rounded-lg border border-primary/30 bg-primary/5 p-3">
              <p className="text-[11px] uppercase tracking-wider text-primary mb-1">Expected VAT Rate</p>
              <p className="text-lg font-bold text-primary">{invoice.expectedVatRate}</p>
            </div>
          </div>
        </div>

        <Separator />

        {/* Value Comparison */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Package className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold text-card-foreground">Value & VAT Breakdown</h3>
          </div>
          <div className="bg-muted/30 rounded-lg p-4 space-y-0.5">
            <InfoRow label="Declared Value" value={`€${transaction.declaredValue.toFixed(2)}`} />
            <InfoRow label="Estimated Market Value" value={`€${transaction.estimatedValue.toFixed(2)}`} />
            {valueGap > 0 && (
              <InfoRow label="Value Gap" value={`€${valueGap.toFixed(2)}`} highlight />
            )}
            <div className="my-2 border-t border-border" />
            <InfoRow label="VAT Declared" value={`€${transaction.vatDeclared.toFixed(2)}`} />
            <InfoRow label="VAT Expected" value={`€${transaction.vatExpected.toFixed(2)}`} />
            <InfoRow label="VAT Gap" value={`€${vatGap.toFixed(2)}`} highlight />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
