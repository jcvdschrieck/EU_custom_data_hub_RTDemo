import { useState, createContext, useContext, useCallback } from "react";
import { Outlet } from "react-router-dom";
import { SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import type { OpenCaseTab } from "@/components/CaseTabSidebar";

interface CaseTabContextValue {
  openTab: (id: string, label: string, isClosed?: boolean) => void;
  closeTab: (id: string) => void;
  openTabs: OpenCaseTab[];
}

export const TaxCaseTabContext = createContext<CaseTabContextValue>({
  openTab: () => {},
  closeTab: () => {},
  openTabs: [],
});

export function useTaxCaseTab() {
  return useContext(TaxCaseTabContext);
}

export default function TaxLayout() {
  const [openTabs, setOpenTabs] = useState<OpenCaseTab[]>([]);

  const openTab = useCallback((id: string, label: string, isClosed?: boolean) => {
    setOpenTabs((prev) => {
      if (prev.some((t) => t.id === id)) return prev;
      return [...prev, { id, label, isClosed }];
    });
  }, []);

  const closeTab = useCallback((id: string) => {
    setOpenTabs((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <SidebarProvider>
      <TaxCaseTabContext.Provider value={{ openTab, closeTab, openTabs }}>
        <div className="min-h-screen flex w-full">
          <AppSidebar />
          <div className="flex-1 flex flex-col">
            <header className="h-14 flex items-center border-b border-border bg-card px-4 shadow-sm">
              <h1 className="text-2xl font-semibold text-foreground">
                Tax Authority - Customs VAT Monitoring Application
              </h1>
            </header>
            <Outlet />
          </div>
        </div>
      </TaxCaseTabContext.Provider>
    </SidebarProvider>
  );
}
