import { FileText, Settings, Shield, Landmark, Home, FlaskConical, ListChecks, FolderOpen, FolderClosed, X } from "lucide-react";
import revenueLogo from "@/assets/revenue-logo.png";
import { NavLink } from "@/components/NavLink";
import { useLocation, useNavigate } from "react-router-dom";
import { useContext } from "react";
import { CaseTabContext } from "@/pages/CustomsLayout";
import { TaxCaseTabContext } from "@/pages/TaxLayout";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarHeader,
  SidebarFooter,
  useSidebar,
} from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

const mainItems = [
  { title: "Access Portal", url: "/", icon: Home },
  { title: "Customs Authority", url: "/customs-authority", icon: Shield },
  { title: "Tax Authority", url: "/tax-authority", icon: Landmark },
  { title: "Reports", url: "/reports", icon: FileText },
  { title: "Data Lab", url: "/data-lab", icon: FlaskConical },
  { title: "Manage My Rules", url: "/manage-rules", icon: ListChecks },
];

const secondaryItems = [
  { title: "Settings", url: "/settings", icon: Settings },
];

export function AppSidebar() {
  const { state } = useSidebar();
  const collapsed = state === "collapsed";
  const location = useLocation();
  const navigate = useNavigate();

  const customsCtx = useContext(CaseTabContext);
  const taxCtx = useContext(TaxCaseTabContext);

  const isTax = location.pathname.startsWith("/tax-authority");
  const isCustoms = location.pathname.startsWith("/customs-authority");
  const folderBase = isTax ? "/tax-authority" : isCustoms ? "/customs-authority" : null;
  const activeCtx = isTax ? taxCtx : isCustoms ? customsCtx : null;
  const openTabs = activeCtx?.openTabs ?? [];
  const ongoingTabs = openTabs.filter((t) => !t.isClosed);
  const closedTabs = openTabs.filter((t) => t.isClosed);

  const folderItems = folderBase
    ? folderBase === "/customs-authority"
      ? [
          { title: "Ongoing Cases", url: folderBase, icon: FolderOpen, end: true, kind: "ongoing" as const },
          { title: "Closed Cases", url: `${folderBase}/closed`, icon: FolderClosed, end: false, kind: "closed" as const },
        ]
      : [
          { title: "Ongoing Cases", url: folderBase, icon: FolderOpen, end: true, kind: "ongoing" as const },
        ]
    : [];

  const renderTab = (tab: { id: string; label: string }, fallbackPath: string) => {
    const tabPath = `${folderBase}/case/${tab.id}`;
    const active = location.pathname === tabPath;
    return (
      <div
        key={tab.id}
        className={cn(
          "group flex items-center gap-1 ml-7 mr-2 rounded-md transition-colors",
          active
            ? "bg-sidebar-primary text-sidebar-primary-foreground"
            : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
        )}
      >
        <button
          onClick={() => navigate(tabPath)}
          className="flex-1 text-left text-xs py-1 px-2 truncate"
          title={tab.label}
        >
          {tab.label}
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            activeCtx?.closeTab(tab.id);
            if (active) navigate(fallbackPath);
          }}
          className="opacity-0 group-hover:opacity-100 p-0.5 mr-1 rounded hover:bg-sidebar-accent/40 transition-opacity"
          aria-label={`Close ${tab.label}`}
        >
          <X className="h-3 w-3" />
        </button>
      </div>
    );
  };

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="p-4 border-b border-sidebar-border">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src={revenueLogo} alt="Irish Revenue" className="w-8 h-8 object-contain" />
            {!collapsed && (
              <div>
                <p className="font-bold text-sidebar-primary text-xl tracking-tight">DG TAXUD</p>
                <p className="text-[10px] text-sidebar-muted uppercase tracking-wider">European Commission</p>
                <p className="text-[10px] text-sidebar-foreground/80 mt-0.5 flex items-center gap-1">
                  <span aria-hidden>🇮🇪</span>
                  <span>Ireland</span>
                </p>
              </div>
            )}
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel className="text-sidebar-muted text-xs uppercase tracking-wider">Main</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {mainItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton asChild>
                    <NavLink
                      to={item.url}
                      end={item.url === "/"}
                      className="text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                      activeClassName="bg-sidebar-primary text-sidebar-primary-foreground font-medium"
                    >
                      <item.icon className="mr-2 h-4 w-4" />
                      {!collapsed && <span>{item.title}</span>}
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {folderItems.length > 0 && (
          <SidebarGroup>
            <SidebarGroupLabel className="text-sidebar-muted text-xs uppercase tracking-wider">Folders</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {folderItems.map((item) => (
                  <div key={item.title}>
                    <SidebarMenuItem>
                      <SidebarMenuButton asChild>
                        <NavLink
                          to={item.url}
                          end={item.end}
                          className="text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                          activeClassName="bg-sidebar-primary text-sidebar-primary-foreground font-medium"
                        >
                          <item.icon className="mr-2 h-4 w-4" />
                          {!collapsed && <span>{item.title}</span>}
                        </NavLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                    {!collapsed && item.kind === "ongoing" && ongoingTabs.length > 0 && (
                      <div className="mt-1 mb-1 space-y-0.5">
                        {ongoingTabs.map((tab) => renderTab(tab, folderBase!))}
                      </div>
                    )}
                    {!collapsed && item.kind === "closed" && closedTabs.length > 0 && (
                      <div className="mt-1 mb-1 space-y-0.5">
                        {closedTabs.map((tab) => renderTab(tab, `${folderBase}/closed`))}
                      </div>
                    )}
                  </div>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}

        <SidebarGroup>
          <SidebarGroupLabel className="text-sidebar-muted text-xs uppercase tracking-wider">System</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {secondaryItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton asChild>
                    <NavLink
                      to={item.url}
                      className="text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                      activeClassName="bg-sidebar-primary text-sidebar-primary-foreground font-medium"
                    >
                      <item.icon className="mr-2 h-4 w-4" />
                      {!collapsed && <span>{item.title}</span>}
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="border-t border-sidebar-border p-2" />
    </Sidebar>
  );
}
