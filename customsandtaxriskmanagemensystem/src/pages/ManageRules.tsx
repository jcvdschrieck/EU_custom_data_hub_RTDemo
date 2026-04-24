import { ListChecks } from "lucide-react";
import { AppSidebar } from "@/components/AppSidebar";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";

export default function ManageRules() {
  return (
    <SidebarProvider>
      <div className="min-h-screen flex w-full bg-background">
        <AppSidebar />
        <div className="flex-1 flex flex-col">
          <header className="h-12 flex items-center border-b border-border px-2">
            <SidebarTrigger />
            <h1 className="ml-3 text-sm font-semibold text-foreground">Manage My Rules</h1>
          </header>
          <main className="flex-1 p-8">
            <div className="max-w-3xl mx-auto text-center py-20">
              <div className="inline-flex items-center justify-center h-14 w-14 rounded-full bg-primary/10 text-primary mb-4">
                <ListChecks className="h-7 w-7" />
              </div>
              <h2 className="text-2xl font-bold text-foreground mb-2">Manage My Rules</h2>
              <p className="text-muted-foreground">
                Define and configure custom risk-scoring rules used by the AI to flag declarations.
                This area will let you create, edit, and prioritise your rule set.
              </p>
            </div>
          </main>
        </div>
      </div>
    </SidebarProvider>
  );
}
