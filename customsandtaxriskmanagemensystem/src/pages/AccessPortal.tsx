import { Shield, Landmark, ArrowLeft } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { Card } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const EU_COUNTRIES = [
  { code: "AT", name: "Austria", flag: "🇦🇹" },
  { code: "BE", name: "Belgium", flag: "🇧🇪" },
  { code: "BG", name: "Bulgaria", flag: "🇧🇬" },
  { code: "HR", name: "Croatia", flag: "🇭🇷" },
  { code: "CY", name: "Cyprus", flag: "🇨🇾" },
  { code: "CZ", name: "Czechia", flag: "🇨🇿" },
  { code: "DK", name: "Denmark", flag: "🇩🇰" },
  { code: "EE", name: "Estonia", flag: "🇪🇪" },
  { code: "FI", name: "Finland", flag: "🇫🇮" },
  { code: "FR", name: "France", flag: "🇫🇷" },
  { code: "DE", name: "Germany", flag: "🇩🇪" },
  { code: "GR", name: "Greece", flag: "🇬🇷" },
  { code: "HU", name: "Hungary", flag: "🇭🇺" },
  { code: "IE", name: "Ireland", flag: "🇮🇪" },
  { code: "IT", name: "Italy", flag: "🇮🇹" },
  { code: "LV", name: "Latvia", flag: "🇱🇻" },
  { code: "LT", name: "Lithuania", flag: "🇱🇹" },
  { code: "LU", name: "Luxembourg", flag: "🇱🇺" },
  { code: "MT", name: "Malta", flag: "🇲🇹" },
  { code: "NL", name: "Netherlands", flag: "🇳🇱" },
  { code: "PL", name: "Poland", flag: "🇵🇱" },
  { code: "PT", name: "Portugal", flag: "🇵🇹" },
  { code: "RO", name: "Romania", flag: "🇷🇴" },
  { code: "SK", name: "Slovakia", flag: "🇸🇰" },
  { code: "SI", name: "Slovenia", flag: "🇸🇮" },
  { code: "ES", name: "Spain", flag: "🇪🇸" },
  { code: "SE", name: "Sweden", flag: "🇸🇪" },
];

const ENABLED_CODE = "IE";

type Authority = "customs" | "tax";

const AccessPortal = () => {
  const navigate = useNavigate();
  const [authority, setAuthority] = useState<Authority | null>(null);
  const [country, setCountry] = useState<string>(ENABLED_CODE);

  const handleContinue = () => {
    try {
      localStorage.setItem("selected-country", country);
    } catch {
      /* ignore */
    }
    navigate(authority === "customs" ? "/customs-authority" : "/tax-authority");
  };

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center p-8">
      <div className="text-center mb-12">
        <h1 className="text-3xl font-bold text-foreground mb-2">Risk Monitoring Application</h1>
        <p className="text-muted-foreground text-lg">
          {authority ? "Select your country to continue" : "Select your authority to continue"}
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-2xl w-full">
        <Card
          onClick={() => !authority && setAuthority("customs")}
          className={cn(
            "p-8 flex flex-col items-center gap-4 transition-all group",
            !authority && "cursor-pointer hover:border-primary hover:shadow-lg",
            authority === "customs" && "border-primary shadow-lg",
            authority === "tax" && "opacity-40",
          )}
        >
          <div className="h-16 w-16 rounded-full bg-primary/10 flex items-center justify-center group-hover:bg-primary/20 transition-colors">
            <Shield className="h-8 w-8 text-primary" />
          </div>
          <h2 className="text-xl font-semibold text-foreground">Customs Authority</h2>
        </Card>

        <Card
          onClick={() => !authority && setAuthority("tax")}
          className={cn(
            "p-8 flex flex-col items-center gap-4 transition-all group",
            !authority && "cursor-pointer hover:border-primary hover:shadow-lg",
            authority === "tax" && "border-primary shadow-lg",
            authority === "customs" && "opacity-40",
          )}
        >
          <div className="h-16 w-16 rounded-full bg-primary/10 flex items-center justify-center group-hover:bg-primary/20 transition-colors">
            <Landmark className="h-8 w-8 text-primary" />
          </div>
          <h2 className="text-xl font-semibold text-foreground">Tax Authority</h2>
        </Card>
      </div>

      {authority && (
        <div className="mt-10 w-full max-w-md">
          <Card className="p-6 flex flex-col gap-4">
            <label className="text-sm font-medium text-foreground">Country (EU Member State)</label>
            <Select value={country} onValueChange={setCountry}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select a country" />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {EU_COUNTRIES.map((c) => {
                  const enabled = c.code === ENABLED_CODE;
                  return (
                    <SelectItem
                      key={c.code}
                      value={c.code}
                      disabled={!enabled}
                      className={cn(!enabled && "opacity-50")}
                    >
                      <span className="mr-2">{c.flag}</span>
                      {c.name}
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Only Ireland is available in this preview.
            </p>
            <div className="flex items-center justify-between gap-2 pt-2">
              <Button variant="ghost" size="sm" onClick={() => setAuthority(null)}>
                <ArrowLeft className="h-4 w-4 mr-1" />
                Back
              </Button>
              <Button onClick={handleContinue} disabled={country !== ENABLED_CODE}>
                Continue
              </Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
};

export default AccessPortal;
