import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import AccessPortal from "./pages/AccessPortal.tsx";
import CustomsLayout from "./pages/CustomsLayout.tsx";
import TaxLayout from "./pages/TaxLayout.tsx";
import OngoingCases from "./pages/CustomsAuthority.tsx";
import ClosedCases from "./pages/ClosedCases.tsx";
import CaseReview from "./pages/CaseReview.tsx";
import TaxAuthority from "./pages/TaxAuthority.tsx";
import TaxCaseReview from "./pages/TaxCaseReview.tsx";
import NotFound from "./pages/NotFound.tsx";
import ManageRules from "./pages/ManageRules.tsx";
import { startReferenceStore } from "./lib/referenceStore";
import { startBackendCaseStore } from "./lib/backendCaseStore";

const queryClient = new QueryClient();

// Bootstrap backend stores. Idempotent — safe under React StrictMode.
startReferenceStore();
startBackendCaseStore();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<AccessPortal />} />
          <Route path="/customs-authority" element={<CustomsLayout />}>
            <Route index element={<OngoingCases />} />
            <Route path="closed" element={<ClosedCases />} />
            <Route path="case/:id" element={<CaseReview />} />
          </Route>
          <Route path="/tax-authority" element={<TaxLayout />}>
            <Route index element={<TaxAuthority />} />
            <Route path="case/:id" element={<TaxCaseReview />} />
          </Route>
          <Route path="/manage-rules" element={<ManageRules />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
