import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { X, ChevronLeft, ChevronRight, LayoutDashboard, FolderOpen, FolderClosed } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export interface OpenCaseTab {
  id: string;
  label: string;
  isClosed?: boolean;
}

interface CaseTabSidebarProps {
  openTabs: OpenCaseTab[];
  onCloseTab: (id: string) => void;
  basePath?: string;
  hideClosedSection?: boolean;
}

export function CaseTabSidebar({ openTabs, onCloseTab, basePath = "/customs-authority", hideClosedSection = false }: CaseTabSidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const ongoingTabs = openTabs.filter((t) => !t.isClosed);
  const closedTabs = openTabs.filter((t) => t.isClosed);

  const isActive = (path: string) => location.pathname === path;

  if (openTabs.length === 0) {
    return null;
  }

  const renderTab = (tab: OpenCaseTab, fallbackPath: string) => (
    <div
      key={tab.id}
      className={cn(
        "flex items-center gap-1 group",
        collapsed ? "justify-center px-1" : "px-3"
      )}
    >
      <button
        onClick={() => navigate(`${basePath}/case/${tab.id}`)}
        className={cn(
          "flex-1 text-left text-xs py-1.5 px-2 rounded transition-colors hover:bg-muted/50 truncate",
          isActive(`${basePath}/case/${tab.id}`) && "bg-primary/10 text-primary font-medium"
        )}
        title={tab.label}
      >
        {collapsed ? <LayoutDashboard className="h-3 w-3" /> : tab.label}
      </button>
      {!collapsed && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onCloseTab(tab.id);
            if (isActive(`${basePath}/case/${tab.id}`)) {
              navigate(fallbackPath);
            }
          }}
          className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-muted transition-opacity"
        >
          <X className="h-3 w-3 text-muted-foreground" />
        </button>
      )}
    </div>
  );

  return (
    <div
      className={cn(
        "h-full border-r border-border bg-card flex flex-col transition-all duration-200",
        collapsed ? "w-12" : "w-56"
      )}
    >
      <div className="flex items-center justify-end p-1 border-b border-border">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-foreground hover:bg-muted"
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto py-2">
        {ongoingTabs.length > 0 && (
          <div className="mb-3">
            {!collapsed && (
              <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                <FolderOpen className="h-3 w-3" />
                Open
              </div>
            )}
            {ongoingTabs.map((tab) => renderTab(tab, basePath))}
          </div>
        )}

        {!hideClosedSection && closedTabs.length > 0 && (
          <div>
            {!collapsed && (
              <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                <FolderClosed className="h-3 w-3" />
                Closed
              </div>
            )}
            {closedTabs.map((tab) => renderTab(tab, `${basePath}/closed`))}
          </div>
        )}
      </div>
    </div>
  );
}
